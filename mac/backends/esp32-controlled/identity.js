import { parseAdvertisement } from "../esp32-scan/advertisement.js";
export function validateAllow(allow) {
  if (
    !allow ||
    typeof allow.address !== "string" ||
    !/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(allow.address) ||
    ![0, 1].includes(allow.addressType)
  )
    throw Error("EXACT_C6_ALLOW_REQUIRED");
  const nonce =
    typeof allow.nonce === "string" && /^[0-9a-f]{8}$/i.test(allow.nonce)
      ? Array.from(Buffer.from(allow.nonce, "hex"))
      : allow.nonce;
  if (
    !Array.isArray(nonce) ||
    nonce.length !== 4 ||
    !nonce.every((x) => Number.isInteger(x) && x >= 0 && x <= 255)
  )
    throw Error("EXACT_C6_NONCE_REQUIRED");
  return Object.freeze({
    address: allow.address.toUpperCase(),
    addressType: allow.addressType,
    nonce: Object.freeze([...nonce]),
  });
}
export class IdentityGate {
  constructor(allow, { now = () => Date.now(), maxAgeMs = 30000 } = {}) {
    this.allow = validateAllow(allow);
    this.now = now;
    this.maxAgeMs = maxAgeMs;
    this.observedAt = null;
  }
  observe(event) {
    if (
      event.event !== "advertisement" ||
      event.address?.toUpperCase() !== this.allow.address ||
      event.addressType !== this.allow.addressType
    )
      return;
    const data = parseAdvertisement(event.advertising).manufacturerData;
    if (!data) return;
    const expected = [255, 255, ...this.allow.nonce];
    this.observedAt =
      data.length === expected.length && data.every((b, i) => b === expected[i])
        ? this.now()
        : null;
  }
  assertConnect(address, addressType = this.allow.addressType) {
    if (
      typeof address !== "string" ||
      address.toUpperCase() !== this.allow.address ||
      addressType !== this.allow.addressType
    )
      throw Error("TARGET_NOT_ALLOWED");
    if (
      this.observedAt === null ||
      this.now() - this.observedAt > this.maxAgeMs
    )
      throw Error("C6_ADVERTISEMENT_PROOF_REQUIRED");
  }
  resolve(address, addressType = this.allow.addressType) {
    if (typeof address !== "string" || address.toUpperCase() !== this.allow.address || addressType !== this.allow.addressType)
      throw Error("TARGET_NOT_ALLOWED");
    return { address: address.toUpperCase(), addressType };
  }
  scanOptions() { return { passive: true }; }
  accepts(event) {
    try { this.assertConnect(event.address, event.addressType); return true; }
    catch { return false; }
  }
}

// General service policy: any valid peer, with address type resolved from real
// scan evidence when a legacy v1 client only supplies the address.
export class OpenIdentityGate {
  constructor() { this.addresses = new Map(); }
  observe(event) {
    if (event.event !== "advertisement" || typeof event.address !== "string" || ![0, 1, 2, 3].includes(event.addressType)) return;
    const address = event.address.toUpperCase();
    const types = this.addresses.get(address) ?? new Set();
    types.add(event.addressType % 2);
    this.addresses.delete(address);
    this.addresses.set(address, types);
    if (this.addresses.size > 1024) this.addresses.delete(this.addresses.keys().next().value);
  }
  resolve(address, addressType) {
    if (typeof address !== "string" || !/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(address)) throw Error("INVALID_ADDRESS");
    address = address.toUpperCase();
    if (addressType === undefined) {
      const types = this.addresses.get(address);
      if (!types || types.size !== 1) throw Error("ADDRESS_TYPE_REQUIRED");
      addressType = [...types][0];
    }
    if (![0, 1].includes(addressType)) throw Error("INVALID_ADDRESS_TYPE");
    return { address, addressType };
  }
  assertConnect(address, addressType) { this.resolve(address, addressType); }
  accepts() { return true; }
  scanOptions(params = {}) {
    if (params.passive !== undefined && typeof params.passive !== "boolean") throw Error("INVALID_ARGUMENT");
    return { passive: params.passive ?? false };
  }
}
