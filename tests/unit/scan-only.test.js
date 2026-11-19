import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import {
  ScanCoordinator,
  ScanOnlySession,
} from "../../mac/backends/esp32-scan/session.js";
const settle = () => new Promise((r) => setImmediate(r));
class FakeWorker extends EventEmitter {
  calls = [];
  next = 0;
  async command(method) {
    this.calls.push(method);
    return { scanId: ++this.next };
  }
}
function client(coordinator) {
  const frames = [];
  return {
    frames,
    session: new ScanOnlySession({ coordinator, send: (f) => frames.push(f) }),
  };
}
test("all connect/GATT/unknown requests are rejected without touching USB", () => {
  const w = new FakeWorker(),
    c = new ScanCoordinator(w),
    a = client(c);
  for (const method of [
    "connect",
    "disconnect",
    "close",
    "discover",
    "read",
    "write",
    "descriptor.read",
    "descriptor.write",
    "notification.set",
    "mtu",
    "rssi",
    "raw",
  ])
    a.session.request({ id: 1, method, params: { connectionId: "test" } });
  assert.equal(w.calls.length, 0);
  assert.ok(a.frames.every((f) => f.error?.code === "SCAN_ONLY"));
});
test("one owner, stop/restart generations and stale frames", async () => {
  const w = new FakeWorker(),
    c = new ScanCoordinator(w),
    a = client(c),
    b = client(c);
  a.session.request({ id: 1, method: "scan.start", params: { scanId: "a" } });
  await settle();
  b.session.request({ id: 1, method: "scan.start", params: { scanId: "b" } });
  await settle();
  assert.equal(b.frames[0].error.code, "BUSY");
  const event = {
    event: "advertisement",
    scanId: 1,
    address: "00:00:00:00:00:01",
    addressType: 0,
    eventType: 0,
    rssi: -50,
    advertising: [2, 1, 6],
  };
  w.emit("boardEvent", event);
  assert.equal(a.frames.filter((f) => f.type === "event").length, 1);
  a.session.request({ id: 2, method: "scan.stop", params: { scanId: "a" } });
  a.session.request({
    id: 3,
    method: "scan.start",
    params: { scanId: "next" },
  });
  await settle();
  w.emit("boardEvent", event);
  assert.equal(a.frames.filter((f) => f.type === "event").length, 1);
  w.emit("boardEvent", { ...event, scanId: 3 });
  assert.equal(a.frames.filter((f) => f.type === "event").length, 2);
  a.session.close();
  await settle();
  assert.deepEqual(w.calls, [
    "scan.start",
    "scan.stop",
    "scan.start",
    "scan.stop",
  ]);
});
test("end of hardware scan renews only an active scan; closed sessions do not renew", async () => {
  const w = new FakeWorker(),
    c = new ScanCoordinator(w),
    a = client(c);
  a.session.request({ id: 1, method: "scan.start", params: { scanId: "a" } });
  await settle();
  w.emit("boardEvent", { event: "scanStopped", scanId: 1 });
  await settle();
  assert.deepEqual(w.calls, ["scan.start", "scan.start"]);
  a.session.close();
  await settle();
  w.emit("boardEvent", { event: "scanStopped", scanId: 2 });
  await settle();
  assert.equal(w.calls.length, 3);
});
