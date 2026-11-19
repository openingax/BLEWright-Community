import { EventEmitter } from "node:events";
import { AdvertisementCache } from "../esp32-scan/advertisement.js";
import { IdentityGate } from "./identity.js";

const validID = (value) =>
  typeof value === "string" && value.length > 0 && value.length <= 128;
const validBytes = (value) =>
  Array.isArray(value) &&
  value.length <= 512 &&
  value.every((v) => Number.isInteger(v) && v >= 0 && v <= 255);
export function canonicalUUID(value) {
  const text = String(value).replace(/^0x/i, "").toUpperCase();
  if (/^[0-9A-F]{4}$/.test(text))
    return `0000${text}-0000-1000-8000-00805F9B34FB`;
  if (/^[0-9A-F]{8}$/.test(text)) return `${text}-0000-1000-8000-00805F9B34FB`;
  if (/^[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}$/.test(text)) return text;
  throw Error("INVALID_BOARD_UUID");
}
function check(result) {
  if (!result || !Number.isInteger(result.status))
    throw Error("INVALID_BOARD_RESULT");
  if (result.status !== 0) {
    const error = Error(result.error ?? "GATT_ERROR");
    error.boardResult = result;
    throw error;
  }
  return result;
}
function publicFailure(error) {
  return error.boardResult
    ? {
        status:
          error.boardResult.status > 0x100 && error.boardResult.status < 0x200
            ? error.boardResult.status - 0x100
            : 133,
        nimbleStatus: error.boardResult.status,
        reason: error.boardResult.error ?? error.message,
      }
    : { status: 133, reason: error.message };
}

export class ControlledCoordinator extends EventEmitter {
  constructor(worker, { allow, targetPolicy, log = () => {} }) {
    super();
    this.worker = worker;
    this.identity = targetPolicy ?? new IdentityGate(allow);
    this.log = log;
    this.owner = null;
    this.record = null;
    this.scan = null;
    this.cache = new AdvertisementCache();
    this.scanChain = Promise.resolve();
    this.frames = 0;
    this.connectAttempts = 0;
    this.deniedConnects = 0;
    worker.on("boardEvent", (e) => this.event(e));
  }
  claim(session) {
    if (this.owner && this.owner !== session) throw Error("BUSY");
    this.owner = session;
  }
  enqueueScan(work) {
    const promise = this.scanChain.then(work);
    this.scanChain = promise.catch(() => {});
    return promise;
  }
  async startScan(session, scanId, params = {}) {
    const options = session.scanOnly ? { passive: true } : this.identity.scanOptions(params);
    this.claim(session);
    if (this.record && this.record.phase !== "connected") throw Error("BUSY");
    if (this.scan) throw Error("ALREADY_STARTED");
    const token = { session, scanId, boardScanId: null, options };
    this.scan = token;
    try {
      await this.enqueueScan(async () => {
        if (this.scan !== token) return;
        const r = check(await this.worker.command("scan.start", options));
        token.boardScanId = r.scanId;
      });
    } catch (error) {
      if (this.scan === token) this.scan = null;
      throw error;
    }
    return {};
  }
  async stopScan(session, scanId) {
    if (
      !this.scan ||
      this.scan.session !== session ||
      (scanId && this.scan.scanId !== scanId)
    )
      return {};
    this.scan = null;
    await this.enqueueScan(async () =>
      check(await this.worker.command("scan.stop")),
    );
    return {};
  }
  async connect(session, p) {
    const target = this.identity.resolve(p.address, p.addressType);
    try {
      this.identity.assertConnect(
        target.address,
        target.addressType,
      );
    } catch (e) {
      if (e.message !== "C6_ADVERTISEMENT_PROOF_REQUIRED") {
        this.deniedConnects++;
        throw e;
      }
    }
    this.claim(session);
    if (this.record) throw Error("BUSY");
    const record = {
      session,
      id: p.connectionId,
      phase: "connecting",
      generation: null,
      busy: false,
      canceled: false,
      attributes: new Map(),
      notifications: new Set(),
      target,
      mtu: 23,
    };
    this.record = record;
    record.connectPromise = (async () => {
      await this.stopScan(session);
      if (record.canceled || session.closed)
        return { status: 133, reason: "CANCELED" };
      await this.ensureProof(record);
      if (record.canceled || session.closed)
        return { status: 133, reason: "CANCELED" };
      this.connectAttempts++;
      return this.worker.command("connect", target);
    })();
    try {
      const result = await record.connectPromise;
      if (result.status !== 0) {
        if (this.record === record) this.record = null;
        return publicFailure({
          boardResult: result,
          message: "connect failed",
        });
      }
      if (
        !Number.isInteger(result.generation) ||
        !Number.isInteger(result.mtu) ||
        result.mtu < 23
      ) {
        this.emit("unavailable", "INVALID_CONNECT_RESULT");
        throw Error("INVALID_CONNECT_RESULT");
      }
      record.generation = result.generation;
      record.mtu = result.mtu;
      record.phase = "connected";
      if (record.canceled || session.closed) {
        await this.disconnect(session, record.id);
        return { status: 133, reason: "CANCELED" };
      }
      return { status: 0, mtu: record.mtu };
    } catch (error) {
      if (this.record === record) this.record = null;
      throw error;
    }
  }
  async ensureProof(record) {
    const allowed = record.target;
    try {
      this.identity.assertConnect(allowed.address, allowed.addressType);
      return;
    } catch {}
    // A cached CoreBluetooth peripheral may reconnect without an app-level scan.
    // Refresh proof passively, never issue connect until the exact nonce is heard.
    check(await this.worker.command("scan.start"));
    try {
      const deadline = Date.now() + 2000;
      while (
        Date.now() < deadline &&
        !record.canceled &&
        !record.session.closed
      ) {
        try {
          this.identity.assertConnect(allowed.address, allowed.addressType);
          return;
        } catch {}
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      if (!record.canceled && !record.session.closed)
        throw Error("C6_ADVERTISEMENT_PROOF_REQUIRED");
    } finally {
      check(await this.worker.command("scan.stop"));
    }
  }
  async disconnect(session, id) {
    const r = this.record;
    if (!r || r.session !== session || r.id !== id) return { status: 0 };
    if (r.disconnectPromise) return r.disconnectPromise;
    r.canceled = true;
    r.notifications.clear();
    r.disconnectPromise = (async () => {
      if (r.phase === "connecting") {
        check(await this.worker.command("cancel"));
        const connection = await r.connectPromise;
        if (connection.status !== 0) {
          if (this.record === r) this.record = null;
          return { status: 0 };
        }
        r.generation = connection.generation;
        r.phase = "connected";
      }
      if (this.record !== r) return { status: 0 };
      r.phase = "disconnecting";
      try {
        check(
          await this.worker.command("disconnect", { generation: r.generation }),
        );
        return { status: 0 };
      } catch (error) {
        this.emit("unavailable", error.message);
        return publicFailure(error);
      } finally {
        if (this.record === r) this.record = null;
      }
    })();
    return r.disconnectPromise;
  }
  connection(session, id) {
    const r = this.record;
    if (
      !r ||
      r.session !== session ||
      r.id !== id ||
      r.phase !== "connected" ||
      r.canceled
    )
      throw Error("NOT_CONNECTED");
    return r;
  }
  async operation(session, p, work) {
    const r = this.connection(session, p.connectionId);
    if (r.busy) throw Error("BUSY");
    r.busy = true;
    try {
      const result = await work(r);
      if (this.record !== r || r.phase !== "connected" || r.canceled)
        throw Error("STALE_CONNECTION");
      return result;
    } catch (error) {
      if (error.boardResult) return publicFailure(error);
      throw error;
    } finally {
      r.busy = false;
    }
  }
  async command(r, method, params = {}) {
    const result = check(
      await this.worker.command(method, {
        ...params,
        generation: r.generation,
      }),
    );
    if (result.generation !== r.generation) throw Error("STALE_GENERATION");
    return result;
  }
  async discover(session, p) {
    return this.operation(session, p, async (r) => {
      const attributes = new Map(),
        services = [];
      const raw = await this.command(r, "services");
      for (const svc of raw.events ?? []) {
        if (svc.event !== "service") continue;
        const service = {
          id: `g${r.generation}:s${svc.start}`,
          uuid: canonicalUUID(svc.uuid),
          type: 0,
          characteristics: [],
        };
        const chars = (
          await this.command(r, "characteristics", {
            start: svc.start,
            end: svc.end,
          })
        ).events
          .filter((e) => e.event === "characteristic")
          .sort((a, b) => a.definitionHandle - b.definitionHandle);
        for (let i = 0; i < chars.length; i++) {
          const c = chars[i],
            id = `g${r.generation}:c${c.handle}`;
          const characteristic = {
            id,
            uuid: canonicalUUID(c.uuid),
            properties: c.properties,
            permissions: 0,
            descriptors: [],
          };
          attributes.set(id, {
            handle: c.handle,
            kind: "characteristic",
            generation: r.generation,
          });
          const end =
            i + 1 < chars.length ? chars[i + 1].definitionHandle - 1 : svc.end;
          if (end > c.handle) {
            const ds =
              (await this.command(r, "descriptors", { start: c.handle, end }))
                .events ?? [];
            for (const d of ds) {
              if (
                d.event !== "descriptor" ||
                d.characteristicHandle !== c.handle
              )
                continue;
              const did = `g${r.generation}:d${d.handle}`;
              characteristic.descriptors.push({
                id: did,
                uuid: canonicalUUID(d.uuid),
                permissions: 0,
              });
              attributes.set(did, {
                handle: d.handle,
                kind: "descriptor",
                generation: r.generation,
              });
            }
          }
          service.characteristics.push(characteristic);
        }
        services.push(service);
      }
      r.attributes = attributes;
      return { status: 0, services };
    });
  }
  attribute(r, id, kind) {
    const a = r.attributes.get(id);
    if (!a || a.generation !== r.generation || a.kind !== kind)
      throw Error("INVALID_ATTRIBUTE");
    return a;
  }
  async handle(session, method, p) {
    if (method === "ping") return {};
    if (session.scanOnly && !["scan.start", "scan.stop"].includes(method)) throw Error("SCAN_ONLY");
    if (method === "scan.start" || method === "scan.stop") {
      if (!validID(p.scanId)) throw Error("INVALID_ARGUMENT");
      return method === "scan.start"
        ? this.startScan(session, p.scanId, p)
        : this.stopScan(session, p.scanId);
    }
    if (!validID(p.connectionId)) throw Error("INVALID_ARGUMENT");
    if (method === "connect") return this.connect(session, p);
    if (method === "disconnect")
      return this.disconnect(session, p.connectionId);
    if (method === "close") {
      await this.disconnect(session, p.connectionId);
      return {};
    }
    if (method === "discover") return this.discover(session, p);
    if (method === "notification.set") {
      const r = this.connection(session, p.connectionId);
      this.attribute(r, p.attributeId, "characteristic");
      if (typeof p.enabled !== "boolean") throw Error("INVALID_ARGUMENT");
      if (p.enabled) r.notifications.add(p.attributeId);
      else r.notifications.delete(p.attributeId);
      return { status: 0 };
    }
    if (
      ![
        "read",
        "write",
        "descriptor.read",
        "descriptor.write",
        "mtu",
        "rssi",
      ].includes(method)
    )
      throw Error("UNSUPPORTED");
    return this.operation(session, p, async (r) => {
      if (method === "mtu") {
        const reply = await this.command(r, "mtu");
        if (!Number.isInteger(reply.data?.mtu))
          throw Error("INVALID_BOARD_RESULT");
        r.mtu = reply.data.mtu;
        return { status: 0, mtu: r.mtu };
      }
      if (method === "rssi") {
        const reply = await this.command(r, "rssi");
        if (!Number.isFinite(reply.rssi)) throw Error("INVALID_BOARD_RESULT");
        return { status: 0, rssi: reply.rssi };
      }
      const attribute = this.attribute(
        r,
        p.attributeId,
        method.startsWith("descriptor.") ? "descriptor" : "characteristic",
      );
      if (method.endsWith("write")) {
        if (!validBytes(p.value)) throw Error("INVALID_ARGUMENT");
        if (method === "write" && ![1, 2].includes(p.writeType ?? 2))
          throw Error("UNSUPPORTED_WRITE_TYPE");
        await this.command(r, "write", {
          handle: attribute.handle,
          value: p.value,
          withoutResponse: method === "write" && p.writeType === 1,
        });
        return { status: 0 };
      }
      const reply = await this.command(r, "read", { handle: attribute.handle });
      if (!validBytes(reply.data?.value)) throw Error("INVALID_BOARD_RESULT");
      return { status: 0, value: reply.data.value };
    });
  }
  event(e) {
    try {
      this.identity.observe(e);
    } catch {}
    if (e.event === "advertisement") {
      const s = this.scan;
      if (!s || e.scanId !== s.boardScanId) return;
      if (!s.session.scanOnly && !this.identity.accepts(e)) return;
      const device = this.cache.update(e);
      this.frames++;
      s.session.send({
        type: "event",
        event: "advertisement",
        scanId: s.scanId,
        device,
      });
    } else if (e.event === "scanStopped") {
      const s = this.scan;
      if (!s || s.boardScanId !== e.scanId) return;
      s.boardScanId = null;
      this.enqueueScan(async () => {
        if (this.scan !== s) return;
        const result = check(await this.worker.command("scan.start", s.options));
        s.boardScanId = result.scanId;
      }).catch((error) => this.emit("unavailable", error.message));
    } else if (e.event === "notification") {
      const r = this.record;
      if (
        !r ||
        r.phase !== "connected" ||
        r.canceled ||
        r.generation !== e.generation
      )
        return;
      const entry = [...r.attributes].find(
        ([, a]) =>
          a.kind === "characteristic" &&
          a.handle === e.handle &&
          a.generation === e.generation,
      );
      if (entry && r.notifications.has(entry[0]))
        r.session.send({
          type: "event",
          event: "notification",
          connectionId: r.id,
          attributeId: entry[0],
          value: e.value,
        });
    } else if (e.event === "disconnected") {
      const r = this.record;
      if (!r || r.generation === null || e.generation <= r.generation) return;
      r.attributes.clear();
      r.notifications.clear();
      if (r.phase === "disconnecting" || r.canceled) return; // Requested disconnect finishes through its single RPC result.
      this.record = null;
      r.session.send({
        type: "event",
        event: "disconnected",
        connectionId: r.id,
        reason: e.reason,
        generation: e.generation,
      });
    }
  }
  async release(session) {
    if (this.owner !== session) return;
    try {
      await this.stopScan(session);
      if (this.record?.session === session)
        await this.disconnect(session, this.record.id);
    } catch (error) {
      this.emit("unavailable", error.message);
      throw error;
    } finally {
      if (this.owner === session) this.owner = null;
    }
  }
  summary() {
    return {
      event: "controlledC6Summary",
      advertisementsForwarded: this.frames,
      allowedConnectionAttempts: this.connectAttempts,
      deniedConnectionRequests: this.deniedConnects,
    };
  }
}
export class ControlledSession {
  constructor({ send, coordinator, scanOnly = false }) {
    this.scanOnly = scanOnly;
    this.send = send;
    this.coordinator = coordinator;
    this.closed = false;
  }
  request(q) {
    this.coordinator
      .handle(this, q.method, q.params ?? {})
      .then((result) => {
        if (!this.closed) this.send({ type: "result", id: q.id, result });
      })
      .catch((error) => {
        if (!this.closed)
          this.send({
            type: "result",
            id: q.id,
            error: { code: error.message },
          });
      });
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    return this.coordinator.release(this);
  }
}
