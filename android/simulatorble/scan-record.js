import { Buffer } from "buffer";

const UUID_WIDTH = { 2: 2, 3: 2, 4: 4, 5: 4, 6: 16, 7: 16 };
const DATA_WIDTH = { 0x16: 2, 0x20: 4, 0x21: 16 };
function uuid(value) {
  if (typeof value !== "string") return null;
  const hex = value.replaceAll("-", "").toUpperCase();
  if (![4, 8, 32].includes(hex.length) || !/^[0-9A-F]+$/.test(hex)) return null;
  const key = hex.length === 4 ? "0000" + hex + "00001000800000805F9B34FB"
    : hex.length === 8 ? hex + "00001000800000805F9B34FB" : hex;
  return { key, bytes: [...Buffer.from(hex, "hex")].reverse() };
}
function keyLE(bytes) { return uuid(Buffer.from(bytes).reverse().toString("hex"))?.key; }
function binary(value) { return Array.isArray(value) && value.every(b => Number.isInteger(b) && b >= 0 && b <= 255); }

/** Android ScanRecord combines advertisement and scan response. RPC advertising is
 * the latest raw packet, while optional parsed fields already contain the server's
 * merged observations. Project those fields into missing AD structures, equally
 * for every backend. Never infer an absent name, UUID or manufacturer payload.
 */
export function nativeScanRecord(device) {
  const raw = device.advertising;
  if (!binary(raw)) throw Error("Invalid advertisement bytes");
  const fields = [];
  let end = 0;
  while (end < raw.length && raw[end] !== 0) {
    const length = raw[end];
    if (end + length >= raw.length) return raw; // Preserve malformed input for the native parser.
    fields.push({ type: raw[end + 1], value: raw.slice(end + 2, end + length + 1) });
    end += length + 1;
  }
  const output = raw.slice(0, end);
  let additions = 0;
  const add = (type, value) => {
    if (!binary(value) || value.length > 254) return;
    output.push(value.length + 1, type, ...value); additions++;
  };
  const names = fields.filter(f => f.type === 8 || f.type === 9);
  if (typeof device.name === "string" && device.name &&
      !names.some(f => Buffer.from(f.value).toString("utf8").replace(/\0+$/, "") === device.name)) {
    add(device.completeName === false ? 8 : 9, [...Buffer.from(device.name, "utf8")]);
  }
  const services = new Set();
  const data = new Set();
  for (const field of fields) {
    const width = UUID_WIDTH[field.type];
    if (width) for (let i = 0; i + width <= field.value.length; i += width)
      services.add(keyLE(field.value.slice(i, i + width)));
    const dataWidth = DATA_WIDTH[field.type];
    if (dataWidth && field.value.length >= dataWidth) data.add(keyLE(field.value.slice(0, dataWidth)));
  }
  if (Array.isArray(device.serviceUUIDs)) for (const value of device.serviceUUIDs) {
    const parsed = uuid(value);
    if (parsed && !services.has(parsed.key)) {
      add({ 2: 2, 4: 4, 16: 6 }[parsed.bytes.length], parsed.bytes);
      services.add(parsed.key);
    }
  }
  const manufacturer = device.manufacturerData;
  if (binary(manufacturer) && manufacturer.length >= 2 && !fields.some(f => f.type === 0xff &&
      f.value[0] === manufacturer[0] && f.value[1] === manufacturer[1])) add(0xff, manufacturer);
  if (device.serviceData && typeof device.serviceData === "object") for (const [value, payload] of Object.entries(device.serviceData)) {
    const parsed = uuid(value);
    if (parsed && binary(payload) && !data.has(parsed.key)) {
      add({ 2: 0x16, 4: 0x20, 16: 0x21 }[parsed.bytes.length], [...parsed.bytes, ...payload]);
      data.add(parsed.key);
    }
  }
  if (Number.isInteger(device.txPower) && device.txPower >= -127 && device.txPower <= 127 &&
      !fields.some(f => f.type === 0x0a && f.value.length === 1)) add(0x0a, [device.txPower & 255]);
  return additions ? output : raw;
}
