import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseAdvertisement,
  AdvertisementCache,
} from "../../mac/backends/esp32-scan/advertisement.js";
const field = (type, value) => [value.length + 1, type, ...value];
test("decode 16/32/128-bit UUIDs, manufacturer, service data and signed TX power", () => {
  const uuid = Array.from({ length: 16 }, (_, i) => i);
  const r = parseAdvertisement([
    ...field(3, [0x0f, 0x18]),
    ...field(5, [0x78, 0x56, 0x34, 0x12]),
    ...field(7, uuid),
    ...field(0xff, [0x34, 0x12, 0x99]),
    ...field(0x16, [0x0f, 0x18, 42]),
    ...field(0x0a, [0xec]),
  ]);
  assert.deepEqual(r.serviceUUIDs, [
    "180F",
    "12345678",
    "0F0E0D0C-0B0A-0908-0706-050403020100",
  ]);
  assert.deepEqual(r.manufacturerData, [0x34, 0x12, 0x99]);
  assert.deepEqual(r.serviceData["180F"], [42]);
  assert.equal(r.txPower, -20);
});
test("truncated structures do not read beyond the packet; malformed bytes are rejected", () => {
  assert.equal(parseAdvertisement([5, 9, 65]).truncated, true);
  assert.deepEqual(parseAdvertisement([2, 3, 0xff]).serviceUUIDs, []);
  assert.throws(() => parseAdvertisement([256]));
});
test("merge scan response by address type; retain complete names and distinct identities", () => {
  const cache = new AdvertisementCache();
  const event = {
    address: "00:00:00:00:00:01",
    addressType: 0,
    rssi: -60,
    eventType: 0,
    advertising: field(9, [65, 66]),
  };
  assert.equal(cache.update(event).name, "AB");
  const updated = cache.update({
    ...event,
    rssi: -50,
    eventType: 4,
    advertising: field(8, [65]),
  });
  assert.equal(updated.name, "AB");
  assert.equal(updated.connectable, true);
  assert.equal(updated.rssi, -50);
  cache.update({ ...event, addressType: 1 });
  assert.equal(cache.devices.size, 2);
});
