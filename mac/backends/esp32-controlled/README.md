# 共享 ESP32 硬件实现与受控测试策略

0.4 起此目录同时承载通用 esp32 后端和可选受控测试模式的共享连接/GATT/清理实现。目录路径保留兼容。通用模式由 OpenIdentityGate/OpenTargetPolicy 校验有效地址，不检查 C6 nonce，默认主动扫描并允许选择被动扫描。下文的白名单规则仅适用于 esp32-controlled 测试模式。

本模式只允许连接 USB 身份文件中明确列出的一个用户所有 C6。它与 `esp32-scan` 是不同后端，不会扩大附近只读模式的权限。

## main 接入接口

```js
const allow = JSON.parse(readFileSync(allowFile, 'utf8'));
const worker = new ControlledWorker({ port: serialPort, python, allow, log });
await worker.ready;
const coordinator = new ControlledCoordinator(worker, { allow, log });
const backendFactory = options => new ControlledSession({ ...options, coordinator });
```

`allow` 必须包含精确 `address`、`addressType`（0/1）和 `nonce`（4 字节数组或 8 位 HEX），未知/通配配置拒绝启动。额外 USB 身份字段可以保留，后端不使用名称作为授权条件。main 应监听 worker 与 coordinator 的 `unavailable` 并关闭服务；真实串口状态不明时不能继续对外声称就绪。

## 两层连接限制

- JS 与 Python 各自核对地址、地址类型和最近 30 秒实际收到的 `FF FF + nonce` 厂商广播。
- 已知 peripheral 直接重连但证据过期时，JS 最多进行 2 秒被动扫描刷新证据；仍未看到精确 nonce 就失败，不发 connect。
- Python 不提供任意串口透传。只有明确的 BLE 操作可进入 S3；连接后的操作还要求本进程授权的连接和精确 generation。
- 受控扫描只向 App 派发验证过的 C6，附近其它设备不会进入此模式的列表。
- 地址/nonce 匹配用于避免连错测试设备，不是密码学身份认证，不能抵御主动伪造广播。

## 数据与生命周期

一个 TCP 会话从首次操作取得硬件所有权，直到会话关闭；其他会话收到 BUSY。连接中的 cancel 可并发发送，Python 不使用阻塞的 Board.request 等待 connect。取消/close 不会重放写入；连接取消成功但实际已连上的竞态会继续断开该已授权 C6。

发现过程按 services → characteristics → descriptors 顺序执行。实例 ID 包含连接代次与真实 ATT handle；重新连接生成新 ID，旧 ID 不得复用。UUID 归一化为完整 128-bit，permissions=0 表示远端权限未知，不伪造权限。

读取值、MTU、RSSI、通知全部来自 S3。`notification.set` 只设置本地通知门控，CCCD 由客户端通过描述符写入。订阅后不会伪造初始通知。

原始 NimBLE 状态保留在 `nimbleStatus`：ATT 错误 0x101..<0x200 转为对应 ATT code；其他非零状态统一用 status 133，避免把 host EMSGSIZE=4 误判成 ATT Invalid PDU。异常 0x100 不会转成成功0。

主动 disconnect 只返回一条 RPC 结果，不再发重复 disconnected 事件；远端主动断开产生 event=disconnected（connectionId/reason/generation），客户端需显式处理。worker 每5秒只读 hello 保活并检查 droppedFrames；丢帧/重启/超时视为未知结果，不自动重试写入。

## 文件

- `identity.js`：JS 身份与广播证据规则。
- `board-worker.js`：配置、JS 二次连接检查，复用 `../serial-worker.js` 的纯 IPC 传输。
- `engine.py`：串口 pending 表、Python 独立白名单、generation 与事件关联。
- `worker.py`：只在 main 执行时打开串口，处理 stdin/串口与清理。
- `session.js`：公共 RPC 到受控硬件操作/handle 树的映射。

合成测试：`tests/unit/controlled-session.test.js`、`tests/unit/test_controlled_engine.py`。

## 已知边界

当前仍为单连接、前台开发原型；不支持配对/加密、多连接、长写、自动重放。完整 discover 是多步过程，客户端完整发现预算已统一为60秒，大型设备服务树仍应针对实际外设验收；本模式仅针对小型 C6 fixture。关闭 worker 时尝试清理3秒，未能确认断开时保留诊断，最终由 S3 的15秒租约回收兜底，不能把未知结果写成成功。

## App 内模式切换与共享串口

启动时可设置 `BLEWRIGHT_SCAN_PORT=8766`，在受控 8876 入口旁提供只读扫描入口；两者复用同一个 worker/coordinator，不重复打开串口。只读会话转发所有广播，但在公共 handle 入口拒绝全部连接/GATT 操作；受控会话仍仅转发并连接精确身份 C6。两种会话保持排他占用，不能抢占其它客户端。

客户端通过 `session.end` 等待停止扫描/断开完成后再建立新会话。传输层统一处理该控制方法，只有 backend.close 成功才回复，避免 App 模式已切换而硬件仍在旧会话。该方法也适用于 mock 与独立 scan-only 后端。断开或超时不会重放写入。
