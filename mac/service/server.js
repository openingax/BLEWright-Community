import net from "node:net";
import { serviceInfo } from "./version.js";
import { RPCConnection } from "./rpc-connection.js";
import { MockSession } from "../backends/mock/session.js";
export { database } from "../backends/mock/session.js";

export function createService({
  log = () => {},
  delay = 25,
  backendName = "mock",
  backendFactory,
  redactAdvertisements = false,
} = {}) {
  const sockets = new Set();
  const server = net.createServer((socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    let backend, ending = false;
    const connection = new RPCConnection(socket, {
      log,
      info: serviceInfo(backendName),
      redactAdvertisements,
      onRequest: (q) => {
        if (ending) return;
        if (q.method === "server.info") { connection.send({type: "result", id: q.id, result: serviceInfo(backendName)}); return; }
        if (q.method !== "session.end") { backend.request(q); return; }
        ending = true;
        Promise.resolve().then(() => backend.close()).then(() => {
          connection.send({type: "result", id: q.id, result: {}});
        }).catch(() => socket.destroy());
      },
      onClose: () => Promise.resolve(backend?.close()).catch(() => {}),
    });
    const options = { send: (data) => connection.send(data), log, delay };
    backend = backendFactory
      ? backendFactory(options)
      : new MockSession(options);
  });
  server.shutdown = () => {
    for (const socket of sockets) socket.destroy();
    return new Promise((resolve) => server.close(resolve));
  };
  return server;
}
