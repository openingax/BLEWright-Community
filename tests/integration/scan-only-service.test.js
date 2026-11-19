import { test } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { EventEmitter, once } from "node:events";
import { createService } from "../../mac/service/server.js";
import {
  ScanCoordinator,
  ScanOnlySession,
} from "../../mac/backends/esp32-scan/session.js";
test("scan-only TCP routes broadcasts, redacts logs, rejects connection/GATT before USB", async (t) => {
  class Worker extends EventEmitter {
    calls = [];
    async command(method) {
      this.calls.push(method);
      return { scanId: 1 };
    }
  }
  const worker = new Worker(),
    coordinator = new ScanCoordinator(worker),
    logs = [];
  const server = createService({
    log: (e) => logs.push(e),
    redactAdvertisements: true,
    backendFactory: (o) => new ScanOnlySession({ ...o, coordinator }),
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => server.shutdown());
  const socket = net.createConnection(server.address().port, "127.0.0.1");
  t.after(() => socket.destroy());
  socket.setEncoding("utf8");
  let buffer = "",
    sequence = 0;
  const frames = [],
    pending = [];
  socket.on("data", (chunk) => {
    buffer += chunk;
    while (buffer.includes("\n")) {
      const i = buffer.indexOf("\n");
      const frame = JSON.parse(buffer.slice(0, i));
      buffer = buffer.slice(i + 1);
      frames.push(frame);
      for (const p of [...pending])
        if (p.test(frame)) {
          clearTimeout(p.timer);
          pending.splice(pending.indexOf(p), 1);
          p.resolve(frame);
        }
    }
  });
  const wait = (test) => {
    const existing = frames.find(test);
    if (existing) return Promise.resolve(existing);
    return new Promise((resolve, reject) => {
      const p = {
        test,
        resolve,
        timer: setTimeout(() => reject(Error("frame timeout")), 2000),
      };
      pending.push(p);
    });
  };
  const hello = await wait((f) => f.type === "hello");
  async function request(method, params = {}) {
    const id = ++sequence;
    socket.write(
      JSON.stringify({
        version: 1,
        sessionId: hello.sessionId,
        id,
        method,
        params,
      }) + "\n",
    );
    return wait((f) => f.id === id);
  }
  assert.ok((await request("scan.start", { scanId: "scan" })).result);
  worker.emit("boardEvent", {
    event: "advertisement",
    scanId: 1,
    address: "00:00:00:00:00:01",
    addressType: 1,
    rssi: -50,
    eventType: 0,
    advertising: [5, 9, 84, 101, 115, 116],
  });
  const advertisement = await wait((f) => f.event === "advertisement");
  assert.equal(advertisement.device.name, "Test");
  assert.equal(advertisement.device.address, "00:00:00:00:00:01");
  assert.ok(!JSON.stringify(logs).includes("00:00:00:00:00:01"));
  assert.ok(!JSON.stringify(logs).includes("Test"));
  for (const method of [
    "connect",
    "discover",
    "read",
    "write",
    "notification.set",
  ])
    assert.equal(
      (
        await request(method, {
          connectionId: "synthetic",
          address: "00:00:00:00:00:01",
        })
      ).error.code,
      "SCAN_ONLY",
    );
  assert.deepEqual(worker.calls, ["scan.start"]);
  await request("scan.stop", { scanId: "scan" });
  assert.deepEqual(worker.calls, ["scan.start", "scan.stop"]);
});
