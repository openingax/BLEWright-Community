import protocol from "../../protocol/constants.json";
import Java from "frida-java-bridge";
import { nativeScanRecord } from "./scan-record.js";
// This module contains Android projections only. Device data and BLE outcomes live on Mac.
const links = new Map(),
  remoteLinks = new Map(),
  scans = new Map(),
  devices = new Map(),
  jobs = new Map(),
  pending = new Map();
const replacements = [];
let C,
  main,
  context,
  installed = false,
  nextTask = 0,
  nextRequest = 0,
  nextConnection = 0,
  nextScan = 0;
let probeClass = "space.nomoloop.blewright.NativeProbe";
let online = Boolean(globalThis.BLEWRIGHT_SESSION);
let radioScan = null;
let scanTransition = Promise.resolve();
// One physical scan serves all Android callbacks. Serialize transitions so a
// new start never overtakes the previous hardware stop.
function reconcileScan() {
  scanTransition = scanTransition.then(() => new Promise((resolve) => {
    if (!online) return resolve();
    if (scans.size && !radioScan) {
      const id = "radio-" + ++nextScan;
      radioScan = id;
      requestRpc("scan.start", { scanId: id }, (result) => {
        if (result.error) {
          radioScan = null;
          const affected = [...scans.values()];
          scans.clear();
          for (const s of affected) later(main, () => s.cb.onScanFailed(3));
          log("scanRejected", { code: result.error.code });
        }
        resolve();
      });
    } else if (!scans.size && radioScan) {
      const id = radioScan;
      radioScan = null;
      requestRpc("scan.stop", { scanId: id }, (result) => {
        if (result.error) transportLost("scan stop failed: " + result.error.code);
        resolve();
      });
    } else resolve();
  }));
}
function log(event, extra = {}) {
  send({ event, ...extra });
}
function key(o) {
  return String(C.System.identityHashCode(o));
}
function bytes(a) {
  return Java.array(
    "byte",
    Array.from(a, (x) => (x > 127 ? x - 256 : x)),
  );
}
function unsigned(a) {
  return Array.from(a, (x) => (x + 256) % 256);
}
function later(handler, fn, delay = 0) {
  const id = ++nextTask;
  jobs.set(id, fn);
  if (!handler.postDelayed(C.Task.$new(id), delay)) jobs.delete(id);
}
function state(g) {
  const s = links.get(key(g));
  if (!s) throw C.Unsupported.$new("BLEWright: unmanaged GATT");
  return s;
}
function unsupported(name) {
  log("unsupported", { method: name });
  throw C.Unsupported.$new("BLEWright prototype does not support " + name);
}
function ensureContext() {
  if (!context) {
    const a = Java.use("android.app.ActivityThread").currentApplication();
    if (!a) throw Error("Application not attached");
    context = Java.retain(a.getApplicationContext());
  }
}
function permission(name) {
  ensureContext();
  if (context.checkSelfPermission("android.permission." + name) !== 0)
    throw C.Security.$new("BLEWright requires " + name);
}
function callback(s, name, ...args) {
  s.cb[name](s.g, ...args);
  log("callback", { method: name });
}
function transportLost(reason) {
  if (!online) return;
  online = false;
  for (const p of pending.values()) clearTimeout(p.timer);
  pending.clear();
  log("rpcUnavailable", { reason });
  Java.perform(() => {
    for (const scan of scans.values())
      later(main, () => scan.cb.onScanFailed(3));
    scans.clear();
    for (const s of links.values())
      if (!["closed", "disconnected"].includes(s.phase)) {
        s.phase = "disconnected";
        s.epoch++;
        s.busy = false;
        const epoch = s.epoch;
        later(s.handler, () => {
          if (s.phase === "disconnected" && s.epoch === epoch)
            callback(s, "onConnectionStateChange", 133, 0);
        });
      }
  });
}
function requestRpc(method, params = {}, done = () => {}) {
  if (!online) return false;
  const id = ++nextRequest;
  const timer = setTimeout(
    () => transportLost("RPC timeout: " + method),
    protocol.requestTimeoutsMs?.[method] ?? protocol.requestTimeoutMs,
  );
  pending.set(id, { done, timer });
  send({
    event: "rpcRequest",
    request: {
      version: protocol.version,
      sessionId: globalThis.BLEWRIGHT_SESSION,
      id,
      method,
      params,
    },
  });
  return true;
}
function receive() {
  recv("rpc-frame", (message) => {
    const f = message.payload;
    if (f.type === "transportLost") transportLost(f.reason);
    else if (
      f.sessionId === globalThis.BLEWRIGHT_SESSION &&
      f.version === protocol.version &&
      online
    ) {
      if (f.type === "result") {
        const p = pending.get(f.id);
        if (p) {
          pending.delete(f.id);
          clearTimeout(p.timer);
          Java.perform(() =>
            p.done(f.error ? { status: 133, error: f.error } : f.result),
          );
        }
      } else if (f.type === "event") Java.perform(() => remoteEvent(f));
    }
    receive();
  });
}
receive();
setInterval(() => {
  if (installed && online) requestRpc("ping");
}, protocol.heartbeatIntervalMs);
function remoteEvent(f) {
  if (f.event === "advertisement") {
    if (f.scanId !== radioScan) return;
    const d = f.device;
    devices.set(d.address, d);
    const record = C.Record.parseFromBytes(bytes(nativeScanRecord(d)));
    const device = C.Adapter.getDefaultAdapter().getRemoteDevice(d.address);
    const result = Java.retain(
      C.Result.$new(device, record, d.rssi, C.Clock.elapsedRealtimeNanos()),
    );
    for (const scan of scans.values()) {
      let matches = !scan.filters || scan.filters.isEmpty();
      if (scan.filters)
        for (let i = 0; i < scan.filters.size(); i++)
          if (Java.cast(scan.filters.get(i), C.Filter).matches(result))
            matches = true;
      if (matches)
        later(main, () => {
          if (online && scans.get(scan.key) === scan) {
            scan.cb.onScanResult(1, result);
            log("scanResult", { address: d.address, source: "rpc" });
          }
        });
    }
  } else if (f.event === "disconnected") {
    const s = remoteLinks.get(f.connectionId);
    if (!s || ["closed", "disconnected"].includes(s.phase)) return;
    s.phase = "disconnected";
    s.epoch++;
    s.busy = false;
    s.notifications.clear();
    const epoch = s.epoch;
    later(s.handler, () => {
      if (s.phase === "disconnected" && s.epoch === epoch)
        callback(s, "onConnectionStateChange", 133, 0);
    });
    log("remoteDisconnect", { reason: f.reason });
  } else if (f.event === "notification") {
    const s = remoteLinks.get(f.connectionId),
      c = s?.characteristics.get(f.attributeId);
    if (
      !s ||
      !c ||
      s.phase !== "connected" ||
      !s.notifications.has(f.attributeId)
    )
      return;
    const epoch = s.epoch,
      value = [...f.value];
    later(s.handler, () => {
      if (
        online &&
        s.epoch === epoch &&
        s.phase === "connected" &&
        s.notifications.has(f.attributeId)
      ) {
        c.setValue(bytes(value));
        callback(s, "onCharacteristicChanged", c, bytes(value));
      }
    });
  }
}
function operation(g, method, params, done) {
  permission("BLUETOOTH_CONNECT");
  const s = state(g);
  if (!online || s.phase !== "connected" || s.busy) return false;
  s.busy = true;
  const epoch = s.epoch;
  requestRpc(method, { connectionId: s.id, ...params }, (result) =>
    later(s.handler, () => {
      if (!online || s.epoch !== epoch || s.phase !== "connected") return;
      s.busy = false;
      done(s, result);
    }),
  );
  return true;
}
function hook(klass, name, impl) {
  for (const ov of klass[name].overloads) {
    replacements.push(ov);
    ov.implementation = function (...a) {
      return impl.call(this, a, ov);
    };
  }
}
function typesafeOpportunistic(ov, a) {
  return ov.argumentTypes[4]?.className === "boolean" && a[4];
}
function schema(s, services) {
  if (s.discovered) return;
  for (const def of services) {
    const service = Java.retain(
      C.Service.$new(C.UUID.fromString(def.uuid), def.type),
    );
    for (const cd of def.characteristics) {
      const c = Java.retain(
        C.Char.$new(C.UUID.fromString(cd.uuid), cd.properties, cd.permissions),
      );
      s.characteristics.set(cd.id, c);
      for (const dd of cd.descriptors) {
        const d = Java.retain(
          C.Desc.$new(C.UUID.fromString(dd.uuid), dd.permissions),
        );
        c.addDescriptor(d);
        s.descriptors.set(dd.id, d);
      }
      service.addCharacteristic(c);
    }
    s.services.push(service);
  }
  s.discovered = true;
}
function attribute(map, object) {
  for (const [id, value] of map) if (value.equals(object)) return id;
  return null;
}
function newGatt(device, cb, handler, transport, phy) {
  const g = C.Gatt.$new(
    null,
    device,
    transport,
    false,
    phy,
    context.getAttributionSource(),
  );
  const s = {
    id: "connection-" + ++nextConnection,
    g: Java.retain(g),
    cb: Java.retain(cb),
    handler: handler ? Java.retain(handler) : main,
    phase: "connecting",
    epoch: 0,
    busy: false,
    services: [],
    characteristics: new Map(),
    descriptors: new Map(),
    notifications: new Set(),
    discovered: false,
  };
  links.set(key(g), s);
  remoteLinks.set(s.id, s);
  requestRpc(
    "connect",
    { connectionId: s.id, address: String(device.getAddress()) },
    (result) =>
      later(s.handler, () => {
        if (!online || s.phase !== "connecting") return;
        s.phase = result.status === 0 ? "connected" : "disconnected";
        callback(
          s,
          "onConnectionStateChange",
          result.status,
          result.status === 0 ? 2 : 0,
        );
      }),
  );
  return g;
}
function scan(filters, settings, cb) {
  permission("BLUETOOTH_SCAN");
  if (!cb) throw C.Illegal.$new("callback required");
  const id = key(cb),
    retained = Java.retain(cb);
  if (scans.has(id)) {
    later(main, () => retained.onScanFailed(1));
    return;
  }
  if (!online) {
    later(main, () => retained.onScanFailed(3));
    return;
  }
  if (
    settings &&
    (settings.getReportDelayMillis() != 0 || settings.getCallbackType() !== 1)
  ) {
    later(main, () => retained.onScanFailed(4));
    return;
  }
  const scan = {
    key: id,
    id: "scan-" + ++nextScan,
    cb: retained,
    filters: filters ? Java.retain(filters) : null,
  };
  scans.set(id, scan);
  reconcileScan();
}
Java.perform(() => {
  try {
    if (Java.use("android.os.Build$VERSION").SDK_INT.value !== 35)
      throw Error("Only API 35 is supported by this prototype");
    C = {};
    for (const [k, n] of Object.entries({
      System: "java.lang.System",
      Unsupported: "java.lang.UnsupportedOperationException",
      Illegal: "java.lang.IllegalArgumentException",
      Security: "java.lang.SecurityException",
      Adapter: "android.bluetooth.BluetoothAdapter",
      Device: "android.bluetooth.BluetoothDevice",
      Gatt: "android.bluetooth.BluetoothGatt",
      Service: "android.bluetooth.BluetoothGattService",
      Char: "android.bluetooth.BluetoothGattCharacteristic",
      Desc: "android.bluetooth.BluetoothGattDescriptor",
      Scanner: "android.bluetooth.le.BluetoothLeScanner",
      Record: "android.bluetooth.le.ScanRecord",
      Result: "android.bluetooth.le.ScanResult",
      Filter: "android.bluetooth.le.ScanFilter",
      UUID: "java.util.UUID",
      List: "java.util.ArrayList",
      Clock: "android.os.SystemClock",
    }))
      C[k] = Java.use(n);
    // Validate the private constructor before mutating any framework method.
    C.Gatt.$init.overload(
      "android.bluetooth.IBluetoothGatt",
      "android.bluetooth.BluetoothDevice",
      "int",
      "boolean",
      "int",
      "android.content.AttributionSource",
    );
    C.Task = Java.registerClass({
      name: "space.nomoloop.blewright.DispatchTask",
      implements: [Java.use("java.lang.Runnable")],
      fields: { id: "int" },
      methods: {
        $init: [
          {
            returnType: "void",
            argumentTypes: ["int"],
            implementation: function (id) {
              this.$super.$init();
              this.id.value = id;
            },
          },
        ],
        run: function () {
          const id = this.id.value,
            fn = jobs.get(id);
          jobs.delete(id);
          try {
            fn?.();
          } catch (e) {
            log("callbackError", { error: String(e) });
          }
        },
      },
    });
    main = Java.use("android.os.Handler").$new(
      Java.use("android.os.Looper").getMainLooper(),
    );
    hook(C.Adapter, "isEnabled", () => online);
    hook(C.Adapter, "getState", () => (online ? 12 : 10));
    hook(C.Adapter, "isLeEnabled", () => online);
    hook(C.Adapter, "getBluetoothLeScanner", function () {
      ensureContext();
      return online ? C.Scanner.$new(this) : null;
    });
    hook(C.Device, "getName", function (a, ov) {
      const d = devices.get(String(this.getAddress()));
      if (d) return d.name;
      return ov.call(this, ...a);
    });
    hook(C.Device, "getType", function (a, ov) {
      const d = devices.get(String(this.getAddress()));
      if (d) return d.type;
      return ov.call(this, ...a);
    });
    hook(C.Device, "connectGatt", function (a, ov) {
      permission("BLUETOOTH_CONNECT");
      if (!online) return null;
      if (a[1]) return unsupported("autoConnect=true");
      if (a[3] === 1) return unsupported("BR/EDR transport");
      if (typesafeOpportunistic(ov, a))
        return unsupported("opportunistic connection");
      if (!a[2]) throw C.Illegal.$new("callback required");
      const types = ov.argumentTypes.map((t) => t.className),
        hi = types.indexOf("android.os.Handler");
      return newGatt(
        this,
        a[2],
        hi >= 0 ? a[hi] : null,
        typeof a[3] === "number" ? a[3] : 2,
        types[4] === "boolean" ? (a[5] ?? 1) : (a[4] ?? 1),
      );
    });
    hook(C.Scanner, "startScan", function (a, ov) {
      if (
        ov.argumentTypes.some(
          (t) => t.className === "android.app.PendingIntent",
        )
      )
        return unsupported("PendingIntent scan");
      if (a.length === 1) return scan(null, null, a[0]);
      if (a.length === 3) return scan(a[0], a[1], a[2]);
      return unsupported("scan overload");
    });
    hook(C.Scanner, "stopScan", function (a, ov) {
      if (ov.argumentTypes[0].className !== "android.bluetooth.le.ScanCallback")
        return unsupported("PendingIntent stop");
      const scan = scans.get(key(a[0]));
      scans.delete(key(a[0]));
      if (scan) reconcileScan();
    });
    hook(C.Scanner, "flushPendingScanResults", () => unsupported("batch scan"));
    hook(C.Gatt, "discoverServices", function () {
      return operation(this, "discover", {}, (s, r) => {
        if (r.status === 0) schema(s, r.services);
        callback(s, "onServicesDiscovered", r.status);
      });
    });
    hook(C.Gatt, "getServices", function () {
      const list = C.List.$new();
      for (const service of state(this).services)
        list.add.overload("java.lang.Object").call(list, service);
      return list;
    });
    hook(C.Gatt, "getService", function (a) {
      const service = state(this).services.find(
        (s) => String(s.getUuid()) === String(a[0]),
      );
      return service ? Java.retain(service) : null;
    });
    hook(C.Gatt, "readCharacteristic", function (a) {
      const s = state(this),
        id = attribute(s.characteristics, a[0]);
      if (!id) return false;
      return operation(this, "read", { attributeId: id }, (s, r) => {
        const c = s.characteristics.get(id);
        if (r.status === 0) c.setValue(bytes(r.value));
        callback(s, "onCharacteristicRead", c, bytes(r.value ?? []), r.status);
      });
    });
    hook(C.Gatt, "writeCharacteristic", function (a) {
      const s = state(this),
        id = attribute(s.characteristics, a[0]),
        modern = a.length === 3,
        rejected = modern ? 201 : false;
      if (!id) return rejected;
      const value = modern ? a[1] : a[0].getValue();
      if (!value) return rejected;
      const accepted = operation(
        this,
        "write",
        {
          attributeId: id,
          value: unsigned(value),
          writeType: modern ? a[2] : a[0].getWriteType(),
        },
        (s, r) =>
          callback(
            s,
            "onCharacteristicWrite",
            s.characteristics.get(id),
            r.status,
          ),
      );
      return accepted ? (modern ? 0 : true) : rejected;
    });
    hook(C.Gatt, "setCharacteristicNotification", function (a) {
      permission("BLUETOOTH_CONNECT");
      const s = state(this),
        id = attribute(s.characteristics, a[0]);
      if (!online || s.phase !== "connected" || !id) return false;
      if (a[1]) s.notifications.add(id);
      else s.notifications.delete(id);
      requestRpc(
        "notification.set",
        { connectionId: s.id, attributeId: id, enabled: a[1] },
        (r) => {
          if (r.error) transportLost("notification registration failed");
        },
      );
      return true;
    });
    hook(C.Gatt, "writeDescriptor", function (a) {
      const s = state(this),
        id = attribute(s.descriptors, a[0]),
        modern = a.length === 2,
        rejected = modern ? 201 : false;
      if (!id) return rejected;
      const value = modern ? a[1] : a[0].getValue();
      if (!value) return rejected;
      const snapshot = unsigned(value);
      const accepted = operation(
        this,
        "descriptor.write",
        { attributeId: id, value: snapshot },
        (s, r) => {
          const d = s.descriptors.get(id);
          if (r.status === 0) d.setValue(bytes(snapshot));
          callback(s, "onDescriptorWrite", d, r.status);
        },
      );
      return accepted ? (modern ? 0 : true) : rejected;
    });
    hook(C.Gatt, "readDescriptor", function (a) {
      const s = state(this),
        id = attribute(s.descriptors, a[0]);
      if (!id) return false;
      return operation(this, "descriptor.read", { attributeId: id }, (s, r) => {
        const d = s.descriptors.get(id);
        if (r.status === 0) d.setValue(bytes(r.value));
        callback(s, "onDescriptorRead", d, r.status, bytes(r.value ?? []));
      });
    });
    hook(C.Gatt, "requestMtu", function (a) {
      return operation(this, "mtu", { mtu: a[0] }, (s, r) =>
        callback(s, "onMtuChanged", r.mtu ?? 23, r.status),
      );
    });
    hook(C.Gatt, "readRemoteRssi", function () {
      return operation(this, "rssi", {}, (s, r) =>
        callback(s, "onReadRemoteRssi", r.rssi ?? 0, r.status),
      );
    });
    hook(C.Gatt, "disconnect", function () {
      const s = state(this);
      if (["closed", "disconnected", "disconnecting"].includes(s.phase)) return;
      s.phase = "disconnecting";
      s.epoch++;
      s.busy = false;
      s.notifications.clear();
      const epoch = s.epoch;
      requestRpc("disconnect", { connectionId: s.id }, (r) =>
        later(s.handler, () => {
          if (s.epoch !== epoch || s.phase !== "disconnecting") return;
          s.phase = "disconnected";
          callback(s, "onConnectionStateChange", r.status ?? 133, 0);
        }),
      );
    });
    hook(C.Gatt, "close", function () {
      const s = state(this);
      if (s.phase === "closed") return;
      s.phase = "closed";
      s.epoch++;
      s.busy = false;
      s.notifications.clear();
      remoteLinks.delete(s.id);
      requestRpc("close", { connectionId: s.id });
    });
    for (const name of [
      "connect",
      "readPhy",
      "setPreferredPhy",
      "requestConnectionPriority",
      "beginReliableWrite",
      "executeReliableWrite",
      "abortReliableWrite",
      "readUsingCharacteristicUuid",
      "refresh",
    ])
      if (C.Gatt[name]) hook(C.Gatt, name, () => unsupported(name));
    for (const name of [
      "startLeScan",
      "stopLeScan",
      "getBluetoothLeAdvertiser",
    ])
      if (C.Adapter[name]) hook(C.Adapter, name, () => unsupported(name));
    for (const name of [
      "getConnectedDevices",
      "getConnectionState",
      "getDevicesMatchingConnectionStates",
    ])
      if (C.Gatt[name]) hook(C.Gatt, name, () => unsupported(name));
    installed = true;
    log("ready", {
      api: 35,
      mode: "RPC — Mac service owns BLE backend",
      sessionId: globalThis.BLEWRIGHT_SESSION,
    });
  } catch (e) {
    for (const ov of replacements.reverse()) ov.implementation = null;
    log("installError", { error: String(e), stack: e.stack });
  }
});
rpc.exports = {
  applicationReady() {
    return new Promise((resolve) =>
      Java.perform(() =>
        resolve(
          Java.use("android.app.ActivityThread").currentApplication() !== null,
        ),
      ),
    );
  },
  status() {
    return { installed, connections: links.size, scans: scans.size };
  },
  probeResult() {
    return new Promise((resolve, reject) =>
      Java.perform(() => {
        try {
          resolve(String(Java.use(probeClass).result.value));
        } catch (e) {
          reject(String(e));
        }
      }),
    );
  },
  probe(path, kind, target) {
    return new Promise((resolve, reject) =>
      Java.perform(() => {
        try {
          Java.openClassFile(path).load();
          probeClass =
            kind === "scan" ? "space.nomoloop.blewright.ScanOnlyProbe" : kind === "loss"
              ? "space.nomoloop.blewright.ServiceLossProbe"
              : "space.nomoloop.blewright.NativeProbe";
          const app = Java.use("android.app.ActivityThread").currentApplication();
          if (kind === "c6") {
            if (target) Java.use(probeClass).configureTarget(target.address.toUpperCase(), target.nonce);
            Java.use(probeClass).startHardware(app);
          }
          else Java.use(probeClass).start(app);
          resolve("started; inspect BLEWrightProbe logcat for PASS/FAIL");
        } catch (e) {
          reject(String(e));
        }
      }),
    );
  },
};
