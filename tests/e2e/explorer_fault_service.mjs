// Test-only mock faults. This file imports no USB/hardware backend.
import { createService } from '../../mac/service/server.js';
import { MockSession } from '../../mac/backends/mock/session.js';
const mode = process.argv[2];
const server = createService({
  backendName: 'mock',
  log: entry => console.log(JSON.stringify(entry)),
  backendFactory: options => {
    const session = new MockSession(options);
    const request = session.request.bind(session);
    let scans = 0;
    session.request = q => {
      if (mode === 'retry' && q.method === 'scan.start' && ++scans === 1) {
        options.send({ type: 'result', id: q.id, error: { code: 'BUSY' } });
        return;
      }
      if (mode === 'timeout' && q.method === 'discover') return;
      session.delay = mode === 'retry' && ['connect', 'read'].includes(q.method) ? 6000 : 25;
      request(q);
    };
    return session;
  },
});
server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({ event: 'listening', port: server.address().port })));
process.on('SIGTERM', async () => { await server.shutdown(); process.exit(0); });
