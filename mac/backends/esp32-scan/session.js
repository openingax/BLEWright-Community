import { AdvertisementCache } from "./advertisement.js";
export class ScanCoordinator {
  constructor(worker, { log = () => {} } = {}) {
    this.worker = worker;
    this.log = log;
    this.active = null;
    this.chain = Promise.resolve();
    this.cache = new AdvertisementCache();
    this.frames = 0;
    this.identities = new Set();
    worker.on("boardEvent", (e) => this.event(e));
  }
  enqueue(work) {
    const result = this.chain.then(work);
    this.chain = result.catch(() => {});
    return result;
  }
  start(session, scanId) {
    if (this.active && this.active.session !== session)
      return Promise.reject(Error("BUSY"));
    if (this.active) return Promise.reject(Error("ALREADY_STARTED"));
    const token = { session, scanId, boardScanId: null };
    this.active = token;
    this.cache.clear();
    return this.enqueue(async () => {
      if (this.active !== token) return;
      const r = await this.worker.command("scan.start");
      token.boardScanId = r.scanId;
    }).catch((error) => {
      if (this.active === token) this.active = null;
      throw error;
    });
  }
  stop(session, scanId) {
    if (
      !this.active ||
      this.active.session !== session ||
      (scanId && this.active.scanId !== scanId)
    )
      return Promise.resolve();
    this.active = null;
    this.cache.clear();
    return this.enqueue(() => this.worker.command("scan.stop"));
  }
  event(e) {
    const active = this.active;
    if (!active || active.boardScanId !== e.scanId) return;
    if (e.event === "advertisement") {
      let device;
      try {
        device = this.cache.update(e);
      } catch {
        return;
      }
      this.frames++;
      this.identities.add(device.identity);
      active.session.send({
        type: "event",
        event: "advertisement",
        scanId: active.scanId,
        device,
      });
    } else if (e.event === "scanStopped") {
      active.boardScanId = null;
      this.enqueue(async () => {
        if (this.active !== active) return;
        const r = await this.worker.command("scan.start");
        active.boardScanId = r.scanId;
      }).catch(() => active.session.fail());
    }
  }
  summary() {
    return {
      event: "passiveScanSummary",
      frames: this.frames,
      temporaryIdentities: this.identities.size,
      connectionsInitiated: 0,
    };
  }
}
export class ScanOnlySession {
  constructor({ send, coordinator }) {
    this.send = send;
    this.coordinator = coordinator;
    this.closed = false;
  }
  request(q) {
    const reply = (result) => {
      if (!this.closed) this.send({ type: "result", id: q.id, result });
    };
    const error = (code) => {
      if (!this.closed)
        this.send({ type: "result", id: q.id, error: { code } });
    };
    if (q.method === "ping") {
      reply({});
      return;
    }
    // Never forward any connection/GATT/unknown operation, even if a client bypasses its UI.
    if (!["scan.start", "scan.stop"].includes(q.method)) {
      error("SCAN_ONLY");
      return;
    }
    const scanId = q.params?.scanId;
    if (typeof scanId !== "string" || !scanId.length || scanId.length > 128) {
      error("INVALID_ARGUMENT");
      return;
    }
    const action =
      q.method === "scan.start"
        ? this.coordinator.start(this, scanId)
        : this.coordinator.stop(this, scanId);
    action
      .then(() => reply({}))
      .catch((e) =>
        error(
          ["BUSY", "ALREADY_STARTED"].includes(e.message)
            ? e.message
            : "SCAN_FAILED",
        ),
      );
  }
  fail() {
    this.close();
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    return this.coordinator.stop(this);
  }
}
