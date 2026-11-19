// Decode standard AD structures only. No identification of people or private payload semantics.
export function uuidLE(bytes) {
  const h = Buffer.from(bytes).reverse().toString("hex").toUpperCase();
  if (bytes.length === 2 || bytes.length === 4) return h;
  if (bytes.length === 16)
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  return null;
}
export function parseAdvertisement(bytes) {
  if (
    !Array.isArray(bytes) ||
    !bytes.every((b) => Number.isInteger(b) && b >= 0 && b <= 255)
  )
    throw Error("Invalid advertisement bytes");
  const result = { serviceUUIDs: [], serviceData: {} };
  for (let i = 0; i < bytes.length; ) {
    const n = bytes[i];
    if (n === 0) break;
    if (i + n >= bytes.length) {
      result.truncated = true;
      break;
    }
    const type = bytes[i + 1],
      value = bytes.slice(i + 2, i + n + 1);
    if (type === 8 || type === 9) {
      const name = Buffer.from(value).toString("utf8").replace(/\0+$/, "");
      if (name && (type === 9 || !result.name)) {
        result.name = name;
        result.completeName = type === 9;
      }
    }
    const size = { 2: 2, 3: 2, 4: 4, 5: 4, 6: 16, 7: 16 }[type];
    if (size)
      for (let j = 0; j + size <= value.length; j += size)
        result.serviceUUIDs.push(uuidLE(value.slice(j, j + size)));
    const dataSize = { 0x16: 2, 0x20: 4, 0x21: 16 }[type];
    if (dataSize && value.length >= dataSize)
      result.serviceData[uuidLE(value.slice(0, dataSize))] =
        value.slice(dataSize);
    if (type === 0xff) result.manufacturerData = value;
    if (type === 0x0a && value.length === 1)
      result.txPower = value[0] > 127 ? value[0] - 256 : value[0];
    i += n + 1;
  }
  result.serviceUUIDs = [...new Set(result.serviceUUIDs)];
  return result;
}
export class AdvertisementCache {
  constructor(limit = 512) {
    this.limit = limit;
    this.devices = new Map();
  }
  update(event) {
    if (
      typeof event.address !== "string" ||
      ![0, 1, 2, 3].includes(event.addressType) ||
      !Number.isFinite(event.rssi)
    )
      throw Error("Invalid advertisement event");
    const identity = `${event.addressType}:${event.address.toUpperCase()}`;
    const old = this.devices.get(identity),
      parsed = parseAdvertisement(event.advertising);
    const name =
      parsed.name && (!old?.completeName || parsed.completeName)
        ? parsed.name
        : (old?.name ?? "");
    const device = {
      address: event.address.toUpperCase(),
      identity,
      addressType: event.addressType % 2,
      name,
      completeName: Boolean(old?.completeName || parsed.completeName),
      type: 2,
      rssi: event.rssi,
      advertising: event.advertising,
      serviceUUIDs: [
        ...new Set([...(old?.serviceUUIDs ?? []), ...parsed.serviceUUIDs]),
      ],
      manufacturerData: parsed.manufacturerData ?? old?.manufacturerData,
      serviceData: { ...old?.serviceData, ...parsed.serviceData },
      txPower: parsed.txPower ?? old?.txPower,
      connectable:
        event.eventType === 4
          ? (old?.connectable ?? false)
          : [0, 1].includes(event.eventType),
    };
    this.devices.delete(identity);
    this.devices.set(identity, device);
    if (this.devices.size > this.limit)
      this.devices.delete(this.devices.keys().next().value);
    return device;
  }
  clear() {
    this.devices.clear();
  }
}
