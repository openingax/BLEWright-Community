import { test } from "node:test";
import assert from "node:assert/strict";
import { Link } from "../../mac/backends/mock/model.js";
test("operations require connection and serialize until completion", () => {
  const l = new Link();
  assert.equal(l.begin(), null);
  l.connected();
  const e = l.begin();
  assert.equal(l.begin(), null);
  assert.ok(l.complete(e));
  assert.notEqual(l.begin(), null);
});
test("disconnect invalidates pending work", () => {
  const l = new Link();
  l.connected();
  l.localNotify = true;
  l.subscribe([1, 0]);
  const e = l.begin();
  l.disconnect();
  assert.equal(l.complete(e), false);
  assert.equal(l.notifying, false);
  assert.equal(l.begin(), null);
});
test("notifications require local registration and CCCD", () => {
  const l = new Link();
  l.connected();
  l.subscribe([1, 0]);
  assert.equal(l.notifying, false);
  l.localNotify = true;
  assert.equal(l.notifying, true);
  l.subscribe([0, 0]);
  assert.equal(l.notifying, false);
});
test("write/read copies buffers and rejects oversize", () => {
  const l = new Link();
  const a = [1, 2];
  assert.equal(l.write(a), 0);
  a[0] = 9;
  assert.deepEqual(l.value, [1, 2]);
  assert.equal(l.write(Array(21).fill(1)), 13);
  assert.deepEqual(l.value, [1, 2]);
});
test("unsupported CCCD fails", () => {
  const l = new Link();
  assert.equal(l.subscribe([2, 0]), 6);
  assert.equal(l.cccd, false);
});
test("close prevents connection completion", () => {
  const l = new Link();
  l.close();
  l.connected();
  assert.equal(l.state, "closed");
  assert.equal(l.begin(), null);
});
