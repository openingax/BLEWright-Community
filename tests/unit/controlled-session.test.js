import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import {
  IdentityGate,
  OpenIdentityGate,
  validateAllow,
} from "../../mac/backends/esp32-controlled/identity.js";
import {
  ControlledCoordinator,
  ControlledSession,
  canonicalUUID,
} from "../../mac/backends/esp32-controlled/session.js";
const allow = {
  address: "00:00:00:00:00:01",
  addressType: 0,
  nonce: "01020304",
};
const adv = {
  event: "advertisement",
  scanId: 1,
  address: allow.address,
  addressType: 0,
  rssi: -50,
  eventType: 0,
  advertising: [7, 255, 255, 255, 1, 2, 3, 4],
};
class Worker extends EventEmitter {
  calls = [];
  generation = 0;
  value = [66, 76, 69];
  async command(method, params = {}) {
    this.calls.push({ method, params });
    if (method === "scan.start") return { status: 0, scanId: 1 };
    if (method === "connect")
      return { status: 0, generation: ++this.generation, mtu: 23 };
    if (method === "disconnect") {
      queueMicrotask(() =>
        this.emit("boardEvent", {
          event: "disconnected",
          generation: ++this.generation,
          reason: 534,
        }),
      );
      return { status: 0, generation: this.generation };
    }
    if (method === "services")
      return {
        status: 0,
        generation: this.generation,
        events: [{ event: "service", uuid: "0xfff0", start: 1, end: 9 }],
      };
    if (method === "characteristics")
      return {
        status: 0,
        generation: this.generation,
        events: [
          {
            event: "characteristic",
            uuid: "0xfff1",
            definitionHandle: 2,
            handle: 3,
            properties: 30,
          },
        ],
      };
    if (method === "descriptors")
      return {
        status: 0,
        generation: this.generation,
        events: [
          {
            event: "descriptor",
            uuid: "0x2902",
            characteristicHandle: 3,
            handle: 4,
          },
        ],
      };
    if (method === "read")
      return {
        status: 0,
        generation: this.generation,
        data: { value: this.value },
      };
    if (method === "write") {
      this.value = params.value;
      return { status: 0, generation: this.generation };
    }
    if (method === "mtu")
      return { status: 0, generation: this.generation, data: { mtu: 247 } };
    if (method === "rssi")
      return { status: 0, generation: this.generation, rssi: -51 };
    return { status: 0, generation: this.generation };
  }
}
const next = () => new Promise((r) => setImmediate(r));
function makeSetup(general = false) {
  const worker = new Worker(),
    coordinator = new ControlledCoordinator(worker, general ? { targetPolicy: new OpenIdentityGate() } : { allow }),
    frames = [];
  const session = new ControlledSession({
    coordinator,
    send: (f) => frames.push(f),
  });
  return { worker, coordinator, session, frames };
}
const setup = () => makeSetup();
test("general backend accepts public/random peers without fixture name or nonce and preserves scan mode", async () => {
  const x = makeSetup(true);
  await x.coordinator.handle(x.session, "scan.start", { scanId: "s", passive: false });
  assert.deepEqual(x.worker.calls[0], { method: "scan.start", params: { passive: false } });
  const peer = { ...adv, address: "12:34:56:78:9A:BC", addressType: 1, advertising: [2, 1, 6] };
  x.worker.emit("boardEvent", peer);
  assert.equal(x.frames[0].device.address, peer.address);
  assert.equal(x.frames[0].device.addressType, 1);
  await x.coordinator.handle(x.session, "connect", { connectionId: "c", address: peer.address });
  assert.deepEqual(x.worker.calls.find(c => c.method === "connect").params, { address: peer.address, addressType: 1 });
  await x.session.close();
  const y = makeSetup(true);
  await y.coordinator.handle(y.session, "connect", { connectionId: "c", address: "12:34:56:78:9A:BD", addressType: 0 });
  assert.equal(y.worker.calls.filter(c => c.method === "scan.start").length, 0);
  await y.session.close();
});
test("general service requires an unambiguous address type and never guesses public", () => {
  const gate = new OpenIdentityGate();
  assert.throws(() => gate.resolve(allow.address), /ADDRESS_TYPE_REQUIRED/);
  gate.observe(adv);
  assert.equal(gate.resolve(allow.address).addressType, 0);
  gate.observe({ ...adv, addressType: 1 });
  assert.throws(() => gate.resolve(allow.address), /ADDRESS_TYPE_REQUIRED/);
  assert.equal(gate.resolve(allow.address, 1).addressType, 1);
  assert.throws(() => gate.resolve("invalid", 0), /INVALID_ADDRESS/);
  assert.throws(() => gate.scanOptions({ passive: "true" }), /INVALID_ARGUMENT/);
});
test("general shared read-only port stays passive and denies GATT while the main port is unrestricted", async () => {
  const x = makeSetup(true);
  const office = new ControlledSession({ coordinator: x.coordinator, scanOnly: true, send: () => {} });
  await x.coordinator.handle(office, "scan.start", { scanId: "s", passive: false });
  assert.deepEqual(x.worker.calls[0].params, { passive: true });
  await assert.rejects(x.coordinator.handle(office, "connect", { connectionId: "c", address: allow.address, addressType: 0 }), /SCAN_ONLY/);
  await office.close();
  await x.coordinator.handle(x.session, "scan.start", { scanId: "s2", passive: true });
  x.worker.emit("boardEvent", { event: "scanStopped", scanId: 1 });
  await next();
  assert.deepEqual(x.worker.calls.filter(c => c.method === "scan.start").at(-1).params, { passive: true });
  await x.session.close();
});
async function connect(x, id = "c1") {
  x.worker.emit("boardEvent", adv);
  return x.coordinator.handle(x.session, "connect", {
    connectionId: id,
    address: allow.address,
  });
}
test("exact allow required; proof includes address type, nonce and freshness", () => {
  assert.throws(() => validateAllow(undefined));
  assert.throws(() => validateAllow({ ...allow, nonce: "*" }));
  let now = 0;
  const gate = new IdentityGate(allow, { now: () => now });
  assert.throws(() => gate.assertConnect(allow.address));
  gate.observe({ ...adv, addressType: 1 });
  assert.throws(() => gate.assertConnect(allow.address));
  gate.observe(adv);
  gate.assertConnect(allow.address);
  assert.throws(() => gate.assertConnect("00:00:00:00:00:02"));
  now = 30001;
  assert.throws(() => gate.assertConnect(allow.address));
  gate.observe(adv);
  gate.observe({ ...adv, advertising: [7, 255, 255, 255, 9, 9, 9, 9] });
  assert.throws(() => gate.assertConnect(allow.address));
});
test("wrong peer or nonce never sends connect to worker", async () => {
  const x = setup();
  await assert.rejects(
    x.coordinator.handle(x.session, "connect", {
      connectionId: "x",
      address: allow.address,
    }),
  );
  x.worker.emit("boardEvent", adv);
  await assert.rejects(
    x.coordinator.handle(x.session, "connect", {
      connectionId: "x",
      address: "00:00:00:00:00:02",
    }),
  );
  assert.equal(x.worker.calls.filter((c) => c.method === "connect").length, 0);
});
for (const general of [false, true]) {
const setup = () => makeSetup(general);
test(`connected session can scan and keep using GATT (${general ? 'general' : 'controlled'})`, async () => {
  const x = setup();
  await connect(x);
  await x.coordinator.handle(x.session, 'scan.start', { scanId: 'connected-scan' });
  assert.equal((await x.coordinator.handle(x.session, 'rssi', { connectionId: 'c1' })).status, 0);
  await x.coordinator.handle(x.session, 'scan.stop', { scanId: 'connected-scan' });
  await x.session.close();
});
test("real discovery events become generation-scoped schema and route reads/writes to handles", async () => {
  const x = setup();
  assert.equal((await connect(x)).status, 0);
  const r = await x.coordinator.handle(x.session, "discover", {
    connectionId: "c1",
  });
  const c = r.services[0].characteristics[0],
    d = c.descriptors[0];
  assert.equal(r.services[0].uuid, canonicalUUID("fff0"));
  assert.equal(c.id, "g1:c3");
  assert.equal(d.id, "g1:d4");
  assert.deepEqual(
    x.worker.calls.find((c) => c.method === "descriptors").params,
    { start: 3, end: 9, generation: 1 },
  );
  await x.coordinator.handle(x.session, "write", {
    connectionId: "c1",
    attributeId: c.id,
    value: [1, 2],
    writeType: 1,
  });
  assert.deepEqual(x.worker.calls.find((c) => c.method === "write").params, {
    handle: 3,
    value: [1, 2],
    withoutResponse: true,
    generation: 1,
  });
  assert.deepEqual(
    (
      await x.coordinator.handle(x.session, "read", {
        connectionId: "c1",
        attributeId: c.id,
      })
    ).value,
    [1, 2],
  );
});
test("notifications require registration and current generation; requested disconnect is not duplicated", async () => {
  const x = setup();
  await connect(x);
  await x.coordinator.handle(x.session, "discover", { connectionId: "c1" });
  const event = { event: "notification", generation: 1, handle: 3, value: [7] };
  x.worker.emit("boardEvent", event);
  assert.equal(x.frames.length, 0);
  await x.coordinator.handle(x.session, "notification.set", {
    connectionId: "c1",
    attributeId: "g1:c3",
    enabled: true,
  });
  x.worker.emit("boardEvent", { ...event, generation: 0 });
  assert.equal(x.frames.length, 0);
  x.worker.emit("boardEvent", event);
  assert.equal(x.frames[0].attributeId, "g1:c3");
  await x.coordinator.handle(x.session, "disconnect", { connectionId: "c1" });
  await next();
  assert.equal(x.frames.filter((f) => f.event === "disconnected").length, 0);
  await connect(x, "c2");
  await x.coordinator.handle(x.session, "discover", { connectionId: "c2" });
  const count = x.worker.calls.length;
  await assert.rejects(
    x.coordinator.handle(x.session, "read", {
      connectionId: "c2",
      attributeId: "g1:c3",
    }),
    /INVALID_ATTRIBUTE/,
  );
  assert.equal(x.worker.calls.length, count);
});
test("spontaneous disconnect sends one event and makes handles unusable", async () => {
  const x = setup();
  await connect(x);
  await x.coordinator.handle(x.session, "discover", { connectionId: "c1" });
  x.worker.emit("boardEvent", {
    event: "disconnected",
    generation: 2,
    reason: 531,
  });
  x.worker.emit("boardEvent", {
    event: "disconnected",
    generation: 2,
    reason: 531,
  });
  assert.equal(x.frames.filter((f) => f.event === "disconnected").length, 1);
  await assert.rejects(
    x.coordinator.handle(x.session, "read", {
      connectionId: "c1",
      attributeId: "g1:c3",
    }),
    /NOT_CONNECTED/,
  );
});
test("cancel before connection command prevents radio connect; owner close releases hardware", async () => {
  const x = setup();
  x.worker.emit("boardEvent", adv);
  const pending = x.coordinator.handle(x.session, "connect", {
    connectionId: "c1",
    address: allow.address,
  });
  const canceled = x.coordinator.handle(x.session, "disconnect", {
    connectionId: "c1",
  });
  assert.equal((await canceled).status, 0);
  assert.equal((await pending).status, 133);
  assert.equal(x.worker.calls.filter((c) => c.method === "connect").length, 0);
  await connect(x, "c2");
  x.session.close();
  await next();
  assert.equal(x.coordinator.owner, null);
  assert.ok(x.worker.calls.some((c) => c.method === "disconnect"));
});

test("NimBLE host errors are not misreported as ATT codes or successful writes", async () => {
  const x = setup();
  await connect(x);
  await x.coordinator.handle(x.session, "discover", { connectionId: "c1" });
  const original = x.worker.command.bind(x.worker);
  for (const [raw, expected] of [
    [4, 133],
    [0x10d, 13],
    [0x100, 133],
    [-1, 133],
  ]) {
    x.worker.command = async (method, params) =>
      method === "write"
        ? { status: raw, generation: 1, error: "synthetic" }
        : original(method, params);
    const result = await x.coordinator.handle(x.session, "write", {
      connectionId: "c1",
      attributeId: "g1:c3",
      value: [1],
      writeType: 2,
    });
    assert.equal(result.status, expected);
    assert.equal(result.nimbleStatus, raw);
    assert.equal(result.reason, "synthetic");
  }
});

}

test('read-only and C6 sessions share one owner; release awaits cleanup before transfer', async () => {
  const x = setup(), frames = [];
  const office = new ControlledSession({coordinator: x.coordinator, scanOnly: true, send: f => frames.push(f)});
  await x.coordinator.handle(office, 'scan.start', {scanId: 'office'});
  x.worker.emit('boardEvent', {...adv, address: '00:00:00:00:00:99'});
  assert.equal(frames.filter(f => f.event === 'advertisement').length, 1);
  for (const method of ['connect', 'read', 'write', 'notification.set', 'discover', 'cancel', 'unknown']) {
    await assert.rejects(x.coordinator.handle(office, method, {connectionId: 'c1', address: allow.address}), /SCAN_ONLY/);
  }
  await assert.rejects(x.coordinator.handle(x.session, 'scan.start', {scanId: 'c6'}), /BUSY/);
  assert.equal(x.worker.calls.filter(c => c.method === 'connect').length, 0);
  await office.close();
  await x.coordinator.handle(x.session, 'scan.start', {scanId: 'c6'});
  x.worker.emit('boardEvent', {...adv, address: '00:00:00:00:00:99'});
  assert.equal(x.frames.length, 0);
  x.worker.emit('boardEvent', adv);
  assert.equal(x.frames.filter(f => f.event === 'advertisement').length, 1);
  await x.session.close();
  assert.equal(x.coordinator.owner, null);
});

test('closing a connected C6 finishes disconnect before ownership is released', async () => {
  const x = setup();
  await connect(x);
  const original = x.worker.command.bind(x.worker);
  let release;
  x.worker.command = async (method, p) => {
    if (method === 'disconnect') await new Promise(r => { release = r; });
    return original(method, p);
  };
  const closing = x.session.close();
  await next();
  assert.equal(x.coordinator.owner, x.session);
  release(); await closing;
  assert.equal(x.coordinator.record, null);
  assert.equal(x.coordinator.owner, null);
});
