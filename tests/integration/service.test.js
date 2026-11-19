import { test } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { once } from "node:events";
import { createService } from "../../mac/service/server.js";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function setup(t, options = {}) {
  const entries = [],
    server = createService({ log: (e) => entries.push(e), ...options });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => server.shutdown());
  const clients = [];
  async function client() {
    const socket = net.createConnection({
      host: "127.0.0.1",
      port: server.address().port,
    });
    let buffer = "",
      hello,
      seq = 0;
    const pending = new Map(),
      events = [];
    let resolveHello;
    const ready = new Promise((r) => (resolveHello = r));
    socket.setEncoding("utf8");
    socket.on("error", () => {});
    socket.on("data", (chunk) => {
      buffer += chunk;
      while (buffer.includes("\n")) {
        const i = buffer.indexOf("\n"),
          f = JSON.parse(buffer.slice(0, i));
        buffer = buffer.slice(i + 1);
        if (f.type === "hello") {
          hello = f;
          resolveHello();
        } else if (f.type === "result") {
          const p = pending.get(f.id);
          if (p) {
            clearTimeout(p.timer);
            pending.delete(f.id);
            p.resolve(f);
          }
        } else events.push(f);
      }
    });
    await ready;
    const c = {
      socket,
      events,
      request(method, params = {}) {
        const id = ++seq;
        return new Promise((resolve, reject) => {
          const timer = setTimeout(() => {
            pending.delete(id);
            reject(Error("response timeout " + method));
          }, 2000);
          pending.set(id, { resolve, timer });
          socket.write(
            JSON.stringify({
              version: 1,
              sessionId: hello.sessionId,
              id,
              method,
              params,
            }) + "\n",
          );
        });
      },
    };
    clients.push(c);
    t.after(() => socket.destroy());
    return c;
  }
  return { client, entries, server };
}
const connectionId = "c1";
const connect = (c) =>
  c.request("connect", { connectionId, address: "02:00:00:00:00:01" });
const request = (c, method, params = {}) =>
  c.request(method, { connectionId, ...params });
test("TCP RPC discovers, reads/writes, enforces both notification gates and unsubscribes", async (t) => {
  const { client } = await setup(t),
    c = await client();
  assert.equal((await connect(c)).result.status, 0);
  const schema = (await request(c, "discover")).result.services;
  assert.equal(schema[0].characteristics[0].id, "char-1");
  assert.deepEqual(
    (await request(c, "read", { attributeId: "char-1" })).result.value,
    [66, 76, 69],
  );
  await request(c, "descriptor.write", {
    attributeId: "desc-1",
    value: [1, 0],
  });
  await sleep(40);
  assert.equal(c.events.length, 0);
  await request(c, "notification.set", {
    attributeId: "char-1",
    enabled: true,
  });
  assert.equal(
    (await request(c, "write", { attributeId: "char-1", value: [1, 2, 3, 4] }))
      .result.status,
    0,
  );
  assert.deepEqual(
    (await request(c, "read", { attributeId: "char-1" })).result.value,
    [1, 2, 3, 4],
  );
  await sleep(30);
  assert.equal(c.events.length, 1);
  assert.deepEqual(c.events[0].value, [1, 2, 3, 4]);
  await request(c, "notification.set", {
    attributeId: "char-1",
    enabled: false,
  });
  await request(c, "write", { attributeId: "char-1", value: [9] });
  await sleep(40);
  assert.equal(c.events.length, 1);
});
test("scan stop and restart suppress stale advertisements; duplicate start fails", async (t) => {
  const { client } = await setup(t),
    c = await client();
  await c.request("scan.start", { scanId: "scan" });
  assert.equal(
    (await c.request("scan.start", { scanId: "scan" })).error.code,
    "ALREADY_STARTED",
  );
  await c.request("scan.stop", { scanId: "scan" });
  await sleep(110);
  assert.equal(c.events.length, 0);
  await c.request("scan.start", { scanId: "scan" });
  await sleep(110);
  assert.equal(c.events.length, 1);
  assert.equal(c.events[0].device.name, "BLEWright");
});
test("close cancels pending connect; a new connection can retry", async (t) => {
  const { client } = await setup(t),
    c = await client();
  const connecting = connect(c);
  await request(c, "close");
  assert.equal((await connecting).result.status, 133);
  assert.equal((await connect(c)).result.status, 0);
  await request(c, "disconnect");
  assert.equal(
    (await request(c, "read", { attributeId: "char-1" })).error.code,
    "NOT_CONNECTED",
  );
});
test("busy, oversize, invalid CCCD and attribute fail without changing stored data", async (t) => {
  const { client } = await setup(t),
    c = await client();
  await connect(c);
  // Deliver the overlapping operations together so TCP buffering cannot
  // postpone the read until after the simulated write completes.
  c.socket.cork();
  const write = request(c, "write", { attributeId: "char-1", value: [7] });
  const read = request(c, "read", { attributeId: "char-1" });
  c.socket.uncork();
  assert.equal((await read).error.code, "BUSY");
  await write;
  assert.equal(
    (
      await request(c, "write", {
        attributeId: "char-1",
        value: Array(21).fill(0),
      })
    ).result.status,
    13,
  );
  assert.equal(
    (
      await request(c, "descriptor.write", {
        attributeId: "desc-1",
        value: [2, 0],
      })
    ).result.status,
    6,
  );
  assert.equal(
    (await request(c, "read", { attributeId: "unknown" })).error.code,
    "INVALID_ATTRIBUTE",
  );
  assert.deepEqual(
    (await request(c, "read", { attributeId: "char-1" })).result.value,
    [7],
  );
});
test("client sessions isolate values and socket exit releases the session", async (t) => {
  const { client, entries } = await setup(t),
    a = await client(),
    b = await client();
  await Promise.all([connect(a), connect(b)]);
  await request(a, "write", { attributeId: "char-1", value: [9] });
  assert.deepEqual(
    (await request(b, "read", { attributeId: "char-1" })).result.value,
    [66, 76, 69],
  );
  a.socket.destroy();
  await sleep(30);
  assert.ok(entries.some((e) => e.event === "sessionClosed"));
  assert.equal((await request(b, "rssi")).result.rssi, -48);
});
test("service shutdown closes active TCP clients and cancels pending notifications", async (t) => {
  const { client, server } = await setup(t),
    c = await client();
  await connect(c);
  const closed = once(c.socket, "close");
  await server.shutdown();
  await closed;
  assert.ok(c.socket.destroyed);
});

test('session.end acknowledges cleanup and stops old mock notifications', async t => {
  const {client} = await setup(t);
  const c = await client();
  await c.request('scan.start', {scanId: 'old'});
  await c.request('session.end');
  const count = c.events.length;
  await sleep(100);
  assert.equal(c.events.length, count);
});


test('session.end waits for asynchronous backend cleanup before acknowledgement', async t => {
  let release, started = false;
  const closing = new Promise(resolve => { release = resolve; });
  const {client} = await setup(t, {backendFactory: () => ({
    request() { throw Error('Unexpected forwarding'); },
    close() { started = true; return closing; }
  })});
  const c = await client();
  let acknowledged = false;
  const end = c.request('session.end').then(() => { acknowledged = true; });
  await sleep(25);
  assert.equal(started, true);
  assert.equal(acknowledged, false);
  release(); await end;
  assert.equal(acknowledged, true);
});
