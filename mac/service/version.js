import { readFileSync } from "node:fs";
const protocol = JSON.parse(readFileSync(new URL("../../protocol/constants.json", import.meta.url), "utf8"));
export const serverVersion = "0.4.0";
export function serviceInfo(backend = "mock") {
  return { serverVersion, protocolVersion: 1, minimumProtocolVersion: 1, backend,
    requestTimeoutMs: protocol.requestTimeoutMs, requestTimeoutsMs: protocol.requestTimeoutsMs,
    capabilities: backend === "esp32-scan" ? ["passiveScan"] :
      ["scan", "connect", "discover", "read", "write", "notify", "mtu", "rssi"],
    ...(backend === "esp32" ? { targetPolicy: "any-device", scanModes: ["active", "passive"],
      limits: { maxConnections: 1, maxConcurrentHardwareSessions: 1, preferredMtu: 247 },
      unsupportedCapabilities: ["pairing", "bonding", "longWrite", "peripheral", "classicBluetooth", "phy", "l2cap"] } : {}),
    ...(backend === "esp32-controlled" ? { targetPolicy: "exact-allowlist" } : {}) };
}
