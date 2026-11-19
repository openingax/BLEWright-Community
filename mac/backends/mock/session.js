import { Link, fixture as F } from "./model.js";
export const database = [
  {
    id: "service-1",
    uuid: F.service,
    type: 0,
    characteristics: [
      {
        id: "char-1",
        uuid: F.characteristic,
        properties: 30,
        permissions: 17,
        descriptors: [{ id: "desc-1", uuid: F.cccd, permissions: 17 }],
      },
    ],
  },
];
const advertisement = {
  address: F.address,
  name: F.name,
  type: 2,
  rssi: -48,
  advertising: [2, 1, 6, 3, 3, 0xf0, 0xff, 10, 9, ...Buffer.from(F.name)],
};
function binary(value) {
  return (
    Array.isArray(value) &&
    value.length <= 512 &&
    value.every((x) => Number.isInteger(x) && x >= 0 && x <= 255)
  );
}
function identifier(value) {
  return typeof value === "string" && value.length > 0 && value.length <= 128;
}

export class MockSession {
  constructor({ send, delay = 25 }) {
    this.send = send;
    this.delay = delay;
    this.links = new Map();
    this.scans = new Map();
    this.timers = new Set();
    this.closed = false;
  }
  after(fn, delay = this.delay) {
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      if (!this.closed) fn();
    }, delay);
    this.timers.add(timer);
  }
  request(q) {
    const reply = (result) => this.send({ type: "result", id: q.id, result });
    const error = (code) =>
      this.send({ type: "result", id: q.id, error: { code } });
    const p = q.params ?? {};
    if (q.method === "ping") {
      reply({});
      return;
    }
    if (q.method === "scan.start") {
      if (!identifier(p.scanId)) return error("INVALID_ARGUMENT");
      if (this.scans.has(p.scanId)) return error("ALREADY_STARTED");
      if (this.scans.size >= 64) return error("LIMIT");
      const token = {};
      this.scans.set(p.scanId, token);
      reply({});
      this.after(() => {
        if (this.scans.get(p.scanId) === token)
          this.send({
            type: "event",
            event: "advertisement",
            scanId: p.scanId,
            device: advertisement,
          });
      }, 80);
      return;
    }
    if (q.method === "scan.stop") {
      this.scans.delete(p.scanId);
      reply({});
      return;
    }
    if (!identifier(p.connectionId)) return error("INVALID_ARGUMENT");
    if (q.method === "connect") {
      if (this.links.has(p.connectionId)) return error("ALREADY_CONNECTED");
      if (this.links.size >= 64) return error("LIMIT");
      if (p.address !== F.address) {
        reply({ status: 133 });
        return;
      }
      const link = new Link();
      this.links.set(p.connectionId, link);
      this.after(() => {
        if (link.state !== "connecting") {
          reply({ status: 133 });
          return;
        }
        link.connected();
        reply({ status: 0 });
      });
      return;
    }
    const link = this.links.get(p.connectionId);
    if (q.method === "close") {
      if (link) link.close();
      this.links.delete(p.connectionId);
      reply({});
      return;
    }
    if (!link) return error("NOT_CONNECTED");
    if (q.method === "disconnect") {
      link.disconnect();
      reply({ status: 0 });
      return;
    }
    if (q.method === "notification.set") {
      if (link.state !== "connected") return error("NOT_CONNECTED");
      if (p.attributeId !== "char-1" || typeof p.enabled !== "boolean")
        return error("INVALID_ARGUMENT");
      link.localNotify = p.enabled;
      reply({ status: 0 });
      return;
    }
    if (
      ![
        "discover",
        "read",
        "write",
        "descriptor.read",
        "descriptor.write",
        "mtu",
        "rssi",
      ].includes(q.method)
    )
      return error("UNSUPPORTED");
    if (["read", "write"].includes(q.method) && p.attributeId !== "char-1")
      return error("INVALID_ATTRIBUTE");
    if (q.method.startsWith("descriptor.") && p.attributeId !== "desc-1")
      return error("INVALID_ATTRIBUTE");
    if (["write", "descriptor.write"].includes(q.method) && !binary(p.value))
      return error("INVALID_ARGUMENT");
    if (
      q.method === "mtu" &&
      (!Number.isInteger(p.mtu) || p.mtu < 23 || p.mtu > 517)
    )
      return error("INVALID_ARGUMENT");
    const epoch = link.begin();
    if (epoch === null)
      return error(link.state === "connected" ? "BUSY" : "NOT_CONNECTED");
    this.after(() => {
      if (!link.complete(epoch)) {
        reply({ status: 133 });
        return;
      }
      let result = { status: 0 },
        emit = false;
      switch (q.method) {
        case "discover":
          result.services = database;
          break;
        case "read":
          result.value = [...link.value];
          break;
        case "write":
          result.status = link.write(p.value);
          emit = result.status === 0;
          break;
        case "descriptor.read":
          result.value = [link.cccd ? 1 : 0, 0];
          break;
        case "descriptor.write":
          result.status = link.subscribe(p.value);
          emit = result.status === 0;
          break;
        case "mtu":
          link.mtu = Math.min(247, p.mtu);
          result.mtu = link.mtu;
          break;
        case "rssi":
          result.rssi = -48;
          break;
      }
      reply(result);
      if (emit && link.notifying) {
        const value = [...link.value];
        this.after(() => {
          if (link.epoch === epoch && link.notifying)
            this.send({
              type: "event",
              event: "notification",
              connectionId: p.connectionId,
              attributeId: "char-1",
              value,
            });
        }, 10);
      }
    });
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    for (const l of this.links.values()) l.close();
    this.links.clear();
    this.scans.clear();
  }
}
