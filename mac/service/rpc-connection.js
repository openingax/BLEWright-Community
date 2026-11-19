import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const protocol = JSON.parse(
  readFileSync(
    new URL("../../protocol/constants.json", import.meta.url),
    "utf8",
  ),
);

// Shared framing and lifecycle. Backend implementations never own TCP sockets.
export class RPCConnection {
  constructor(
    socket,
    { log, onRequest, onClose, info = {}, redactAdvertisements = false },
  ) {
    this.socket = socket;
    this.log = log;
    this.onRequest = onRequest;
    this.onClose = onClose;
    this.redactAdvertisements = redactAdvertisements;
    this.id = randomUUID();
    this.lastId = 0;
    this.closed = false;
    this.buffer = "";
    socket.setEncoding("utf8");
    this.send({ type: "hello", version: protocol.version, sessionId: this.id, ...info });
    socket.on("data", (chunk) => this.input(chunk));
    socket.on("error", () => {});
    socket.on("close", () => this.close());
  }
  send(data) {
    if (this.closed) return;
    if (this.socket.writableLength > 1024 * 1024) {
      this.socket.destroy();
      return;
    }
    this.socket.write(
      JSON.stringify({
        version: protocol.version,
        sessionId: this.id,
        ...data,
      }) + "\n",
    );
    const safe =
      this.redactAdvertisements && data.event === "advertisement"
        ? {
            type: "event",
            event: "advertisement",
            scanId: data.scanId,
            bytes: data.device?.advertising?.length ?? 0,
          }
        : data;
    this.log({ sessionId: this.id, direction: "out", ...safe });
  }
  input(chunk) {
    this.buffer += chunk;
    while (this.buffer.includes("\n")) {
      const i = this.buffer.indexOf("\n");
      if (Buffer.byteLength(this.buffer.slice(0, i)) > protocol.maxFrameBytes) {
        this.socket.destroy();
        return;
      }
      const line = this.buffer.slice(0, i);
      this.buffer = this.buffer.slice(i + 1);
      try {
        const q = JSON.parse(line);
        if (
          q.version !== protocol.version ||
          q.sessionId !== this.id ||
          !Number.isSafeInteger(q.id) ||
          q.id <= this.lastId ||
          typeof q.method !== "string"
        )
          throw Error("Invalid envelope");
        this.lastId = q.id;
        this.log({
          sessionId: this.id,
          direction: "in",
          id: q.id,
          method: q.method,
          connectionId: q.params?.connectionId,
        });
        this.onRequest(q);
      } catch {
        this.socket.destroy();
        return;
      }
    }
    if (Buffer.byteLength(this.buffer) > protocol.maxFrameBytes)
      this.socket.destroy();
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.onClose();
    this.log({ sessionId: this.id, event: "sessionClosed" });
  }
}
