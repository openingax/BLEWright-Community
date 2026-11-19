// Deterministic advertisement-only fixture. No hardware backend imports or operations.
import { createService } from '../../mac/service/server.js';
import { MockSession } from '../../mac/backends/mock/session.js';
function advertisement(index, name, rssi) {
  const bytes = name === null ? [] : [...Buffer.from(name)];
  return { address: `02:00:00:00:00:0${index}`, name, rssi, type: 2,
    advertising: [2,1,6,...(name === null ? [] : [bytes.length+1,9,...bytes])] };
}
const devices = [advertisement(1,'Desk Sensor',-80), advertisement(2,'Boundary Sensor',-70),
  advertisement(3,'Far Sensor',-92), advertisement(4,null,-40), advertisement(5,'  ',-55),
  advertisement(6,'Unknown Signal',127)];
const server = createService({ backendName:'mock', log:entry => console.log(JSON.stringify(entry)),
  backendFactory:options => {
    const session = new MockSession(options);
    const request = session.request.bind(session);
    session.request = q => {
      if (q.method !== 'scan.start') { request(q); return; }
      const id=q.params.scanId, token={}; session.scans.set(id,token);
      options.send({type:'result',id:q.id,result:{}});
      const send = device => { if(session.scans.get(id)===token) options.send({type:'event',event:'advertisement',scanId:id,device}); };
      devices.forEach((device,index)=>session.after(()=>send(device),100+index*40));
      session.after(()=>send({ ...advertisement(1,'Desk Sensor',-48), advertising: [], completeName: true, serviceUUIDs: ['180F'], manufacturerData: [255,255,1,2,3,4] }),7000);
    };
    return session;
  }
});
server.listen(0,'127.0.0.1',()=>console.log(JSON.stringify({event:'listening',port:server.address().port})));
process.on('SIGTERM',async()=>{await server.shutdown();process.exit(0);});
