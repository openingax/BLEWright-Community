// Run a private loopback service on an ephemeral port and scan its fixture.
import net from 'node:net';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { createService } from '../mac/service/server.js';

const server = createService();
server.listen(0, '127.0.0.1');
await once(server, 'listening');
const socket = net.connect(server.address().port, '127.0.0.1');
socket.setTimeout(5000, () => socket.destroy(new Error('Mock scan timed out')));
const frames = createInterface({ input: socket, crlfDelay: Infinity });
let found = false;
try {
  for await (const line of frames) {
    const msg = JSON.parse(line);
    if (msg.type === 'hello') {
      socket.write(JSON.stringify({
        version: msg.version, sessionId: msg.sessionId, id: 1,
        method: 'scan.start', params: { scanId: 'first-scan' }
      }) + '\n');
    }
    if (msg.error) throw Error(msg.error.code);
    if (msg.event === 'advertisement') {
      console.log(`Found ${msg.device.name}  ${msg.device.address}  ${msg.device.rssi} dBm (mock)`);
      found = true;
      break;
    }
  }
  if (!found) throw Error('Session ended before receiving an advertisement');
} finally {
  frames.close();
  socket.destroy();
  await server.shutdown();
}
