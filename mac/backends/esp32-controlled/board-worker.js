import { fileURLToPath } from "node:url";
import { SerialWorker } from "../serial-worker.js";
import { IdentityGate, OpenIdentityGate, validateAllow } from "./identity.js";
export class ControlledWorker extends SerialWorker {
  constructor({ allow, general = false, ...options }) {
    const normalized = general ? null : validateAllow(allow);
    super({
      ...options,
      script: fileURLToPath(new URL("./worker.py", import.meta.url)),
      scriptArgs: general ? ["--general"] : ["--allow-json", JSON.stringify(normalized)],
      commandTimeout: 12000,
      closeGraceMs: 4000,
      allowedMethods: [
        "ping",
        "scan.start",
        "scan.stop",
        "connect",
        "cancel",
        "disconnect",
        "services",
        "characteristics",
        "descriptors",
        "read",
        "write",
        "mtu",
        "rssi",
      ],
    });
    this.identity = general ? new OpenIdentityGate() : new IdentityGate(normalized);
    this.on("boardEvent", (event) => {
      try {
        this.identity.observe(event);
      } catch {}
    });
  }
  command(method, params = {}) {
    if (method === "connect") {
      try {
        this.identity.assertConnect(params.address, params.addressType);
      } catch (e) {
        return Promise.reject(e);
      }
    }
    return super.command(method, params);
  }
}
