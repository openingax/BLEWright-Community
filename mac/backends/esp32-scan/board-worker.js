import { fileURLToPath } from "node:url";
import { SerialWorker } from "../serial-worker.js";
export class BoardWorker extends SerialWorker {
  constructor(options) {
    super({
      ...options,
      script: fileURLToPath(new URL("./worker.py", import.meta.url)),
      allowedMethods: ["scan.start", "scan.stop", "ping"],
    });
  }
  command(method) {
    if (!["scan.start", "scan.stop", "ping"].includes(method))
      return Promise.reject(Error("SCAN_ONLY"));
    return super.command(method);
  }
}
