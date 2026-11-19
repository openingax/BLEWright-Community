import { test } from 'node:test';
import assert from 'node:assert/strict';
import { nativeScanRecord } from '../../android/simulatorble/scan-record.js';
import { parseAdvertisement, AdvertisementCache } from '../../mac/backends/esp32-scan/advertisement.js';
const field=(type,value)=>[value.length+1,type,...value];
const raw=[2,1,6,...field(3,[0xf0,0xff]),...field(9,[...Buffer.from('BLEWright-C6')]),...field(255,[255,255,1,2,3,4])];

test('empty active scan response retains the merged native name, service and manufacturer data',()=>{
 const cache=new AdvertisementCache();
 const initial={address:'02:00:00:00:00:01',addressType:0,rssi:-40,eventType:0,advertising:raw};
 cache.update(initial);
 const response=cache.update({...initial,eventType:4,advertising:[]});
 const projected=parseAdvertisement(nativeScanRecord(response));
 assert.equal(projected.name,'BLEWright-C6');assert.deepEqual(projected.serviceUUIDs,['FFF0']);
 assert.deepEqual(projected.manufacturerData,[255,255,1,2,3,4]);
 assert.deepEqual(response.advertising,[],'RPC raw bytes must not be mutated');
});
test('complete raw mock/passive records remain byte-for-byte unchanged, without duplicate fields',()=>{
 const device={advertising:[...raw,0,0],name:'BLEWright-C6',serviceUUIDs:['0000fff0-0000-1000-8000-00805f9b34fb'],manufacturerData:[255,255,1,2,3,4]};
 assert.deepEqual(nativeScanRecord(device),device.advertising);
});
test('short scan response name cannot erase the previously observed complete name',()=>{
 const projected=parseAdvertisement(nativeScanRecord({advertising:field(8,[65]),name:'ABC',completeName:true}));
 assert.equal(projected.name,'ABC');assert.equal(projected.completeName,true);
});
test('metadata projection covers 16/32/128-bit UUIDs, service data, TX power and preserves unknown structures',()=>{
 const u='00112233-4455-6677-8899-AABBCCDDEEFF';
 const record=nativeScanRecord({advertising:field(0x19,[1,2]),serviceUUIDs:['180F','12345678',u],
  serviceData:{'180F':[1],'12345678':[2],[u]:[3]},txPower:-20});
 assert.deepEqual(record.slice(0,4),field(0x19,[1,2]));
 const value=parseAdvertisement(record);
 assert.deepEqual(value.serviceUUIDs,['180F','12345678',u]);
 assert.deepEqual(value.serviceData,{'180F':[1],'12345678':[2],[u]:[3]});assert.equal(value.txPower,-20);
});
test('absent names stay unnamed; malformed raw records and oversized metadata are not invented',()=>{
 assert.deepEqual(nativeScanRecord({advertising:[],name:''}),[]);
 const malformed=[5,9,65];assert.deepEqual(nativeScanRecord({advertising:malformed,name:'AB'}),malformed);
 assert.deepEqual(nativeScanRecord({advertising:[],name:'A'.repeat(255)}),[]);
 assert.throws(()=>nativeScanRecord({advertising:[256]}));
});
test('padding does not prevent added metadata from reaching the native parser',()=>{
 assert.equal(parseAdvertisement(nativeScanRecord({advertising:[2,1,6,0,0],name:'Sensor'})).name,'Sensor');
});
