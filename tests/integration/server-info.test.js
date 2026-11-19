import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { createService } from '../../mac/service/server.js';
for (const backendName of ['mock','esp32','esp32-scan','esp32-controlled']) {
  test(`version info preserves v1 for ${backendName}`, async () => {
    const server = createService({backendName});
    await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
    const socket = net.connect(server.address().port,'127.0.0.1');
    try {
      socket.setEncoding('utf8');
      const frames=[]; let buffer=''; let notify;
      socket.on('data', text => { buffer+=text; while(buffer.includes('\n')) {const i=buffer.indexOf('\n');frames.push(JSON.parse(buffer.slice(0,i)));buffer=buffer.slice(i+1);} notify?.(); });
      async function next() { if (!frames.length) await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('timeout')),2000);notify=()=>{clearTimeout(timer);resolve();};}); return frames.shift(); }
      const hello=await next(); assert.equal(hello.version,1); assert.equal(hello.serverVersion,'0.4.0'); assert.equal(hello.backend,backendName);
      socket.write(JSON.stringify({version:1,sessionId:hello.sessionId,id:1,method:'server.info'})+'\n');
      const info=await next(); assert.equal(info.result.protocolVersion,1); assert.equal(info.result.backend,backendName);
      if(backendName==='esp32-scan') assert.deepEqual(info.result.capabilities,['passiveScan']);
      if(backendName==='esp32') {
        assert.equal(info.result.targetPolicy,'any-device');
        assert.deepEqual(info.result.scanModes,['active','passive']);
        assert.equal(info.result.limits.maxConnections,1);
        assert.ok(info.result.unsupportedCapabilities.includes('pairing'));
      }
    } finally { socket.destroy(); await server.shutdown(); }
  });
}
