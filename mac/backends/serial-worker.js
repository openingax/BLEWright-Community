import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
export class SerialWorker extends EventEmitter {
  constructor({
    port,
    python,
    script,
    scriptArgs = [],
    allowedMethods,
    commandTimeout = 4500,
    closeGraceMs = 1000,
    log = () => {},
  }) {
    super();
    this.allowedMethods = new Set(allowedMethods);
    this.commandTimeout = commandTimeout;
    this.closeGraceMs = closeGraceMs;
    this.pending = new Map();
    this.sequence = 0;
    this.closed = false;
    this.buffer = "";
    this.child = spawn(python, [script, "--port", port, ...scriptArgs], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
    this.startup = setTimeout(
      () => this.fail("Board worker startup timeout"),
      6000,
    );
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => this.input(chunk));
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", (chunk) => {
      for (const line of chunk.split("\n")) {
        try {
          const x = JSON.parse(line);
          if (x.event === "usbCommands") log(x);
        } catch {}
      }
    });
    this.child.on("error", (e) => this.fail(e.message));
    this.child.on("exit", () => this.fail("Board worker exited"));
  }
  input(chunk) {
    this.buffer += chunk;
    if (this.buffer.length > 1024 * 1024) {
      this.fail("Board worker frame overflow");
      return;
    }
    while (this.buffer.includes("\n")) {
      const i = this.buffer.indexOf("\n"),
        line = this.buffer.slice(0, i);
      this.buffer = this.buffer.slice(i + 1);
      let f;
      try {
        f = JSON.parse(line);
      } catch {
        this.fail("Invalid board worker frame");
        return;
      }
      if (f.type === "ready") {
        clearTimeout(this.startup);
        this.resolveReady(f);
      } else if (f.type === "unavailable") this.fail(f.reason);
      else if (f.type === "result") {
        const p = this.pending.get(f.id);
        if (p) {
          this.pending.delete(f.id);
          clearTimeout(p.timer);
          f.error ? p.reject(Error(f.error)) : p.resolve(f.result);
        }
      } else if (f.type === "event")
        queueMicrotask(() => {
          if (!this.closed) this.emit("boardEvent", f.event);
        });
    }
  }
  command(method, params = {}) {
    if (!this.allowedMethods.has(method))
      return Promise.reject(Error("UNSUPPORTED"));
    if (this.closed) return Promise.reject(Error("BOARD_UNAVAILABLE"));
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => this.fail("Board command timeout"),
        this.commandTimeout,
      );
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(
        JSON.stringify({ id, method, params }) + "\n",
        (e) => {
          if (e) this.fail("Board pipe closed");
        },
      );
    });
  }
  fail(reason) {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.startup);
    this.rejectReady(Error(reason));
    for (const p of this.pending.values()) {
      clearTimeout(p.timer);
      p.reject(Error(reason));
    }
    this.pending.clear();
    this.child.stdin.end();
    this.emit("unavailable", reason);
  }
  close() {
    this.fail("Closed");
    setTimeout(() => {
      if (this.child.exitCode === null) this.child.kill("SIGTERM");
    }, this.closeGraceMs).unref();
  }
}
