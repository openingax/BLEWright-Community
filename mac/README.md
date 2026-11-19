# Mac BLEWright 服务

`service/main.js` 提供命令行入口，`service/server.js` 选择会话后端，`service/rpc-connection.js` 统一处理 TCP 帧、会话和请求校验。`backends/mock/session.js` 与 model.js 保存模拟操作及状态；`backends/esp32-scan/` 提供真实硬件的只读广播后端。原生桌面端、状态栏和系统 pkg 见 [macOS 工作站](desktop/README.md)。

从仓库根目录运行 `npm run serve`。一个 TCP 连接对应一个会话，各会话独立持有模拟状态；断开时清理扫描、连接、订阅及定时任务。服务不引用 Android/iOS 接管实现，不应依赖 Frida。

模拟设备：BLEWright / 02:00:00:00:00:01；服务 FFF0、特征 FFF1、CCCD 2902；初始值 ASCII BLE。支持单 payload 读写，默认 MTU 23，模拟最大 MTU 247；写后读取返回最近值，开启通知与 CCCD 后产生回显。这里是测试后端定义，不属于公共协议。

## 通用 BLE 硬件后端（默认硬件模式）

桌面端选择「通用 BLE」并绑定 S3。无需导入目标身份文件，主入口 `127.0.0.1:8876` 提供扫描、连接、GATT 发现、特征/描述符读写、通知、MTU 协商和 RSSI。客户端选择设备；服务不按名称、厂商、UUID、C6 地址或 nonce 限制设备。

开发时也可直接运行（先停止工作站，避免两个进程占用同一串口）：

```sh
BLEWRIGHT_BACKEND=esp32 BLEWRIGHT_SERIAL="${S3_PORT:?Set S3_PORT to the board serial port}" node mac/service/main.js
```

只设置 BLEWRIGHT_SERIAL 时也默认选 esp32；未指定硬件和后端时保留 mock CLI 行为。设置 BLEWRIGHT_SCAN_PORT=8766 可在同一串口所有者上额外提供只读入口。工作站默认开启该兼容入口。

- 通用扫描默认主动扫描，scan.start 可传 passive:true；停止后续扫保留所选模式。
- connect 可传 address/addressType（0 public、1 random）。旧客户端只传 address 时，从真实扫描记录推断唯一地址类型；没有记录或地址类型有歧义时返回 ADDRESS_TYPE_REQUIRED，不猜测。
- 通用、受控 C6 共用 `backends/esp32-controlled/` 中的生命周期与 GATT 实现（目录名保留兼容）。仅目标校验和扫描策略不同，通用模式通过 OpenIdentityGate/OpenTargetPolicy，不检查测试身份。
- 当前固件为单连接；一个客户端持有硬件会话，其它客户端收到 BUSY。结束 session.end 或关闭 TCP 才交还所有权。已连接会话可重新启动扫描；发起连接会停止先前扫描。
- MTU 使用固件首选值 247 与外设协商，返回实际结果，不保证满足客户端请求值。尚无配对/绑定、长写、多连接、Peripheral、经典蓝牙、PHY 或 L2CAP 接口。server.info 明确报告当前限制，不能把通用模式理解为已实现整个蓝牙规范。
- 平台库共享按操作划分的超时：普通请求 7 秒、连接/会话清理 15 秒、完整服务发现 60 秒。第三方客户端可读取 hello/server.info 的 requestTimeoutMs/requestTimeoutsMs；超时仍使会话失效，不重放写入。

自动测试仍仅操作 USB 核实的自有 C6；目标过滤属于测试客户端，不是通用服务授权策略。

## ESP32-S3 只读广播后端

```sh
.venv/bin/pip install -r firmware/tools/requirements.txt
BLEWRIGHT_SERIAL="${S3_PORT:?Set S3_PORT to the board serial port}" npm run serve:office
```

需要 firmware 0.2（hello.passiveScanSupported=true），并且板卡未连接、未连接中、未扫描。串口独占，默认监听 127.0.0.1:8766，与 mock 的 8765 分开。

- 每次硬件扫描强制 passive=true，只接收广播，不发送扫描请求。
- 一个活动扫描所有者；同一会话停止/重新开始有代次隔离；固件每 10 秒结束扫描后，只在客户端仍扫描时续扫。
- RPC 会话只接受 ping、scan.start、scan.stop。连接、发现、读写、通知等一律返回 SCAN_ONLY。
- Python 串口 worker 再次白名单限制，只能发 hello、ping、scan.start(passive:true)、scan.stop。没有透传任意串口命令的入口。
- Node 日志将真实广播脱敏为帧长度；最终输出聚合计数和 USB 命令审计，不保存附近设备名称/地址/载荷。
- worker 退出或串口异常会关闭服务连接；需要显式重启服务，不自动重放。

在 BLEExplorer 选择「附近广播」。它增加第二层 App 连接禁用，不把广播元数据当作 GATT 发现结果。

## 后端契约与下一步

所有会话后端实现 request(q) / close()；公共 TCP 帧、sessionId、请求顺序和关闭通知只在 RPCConnection 中实现一次。mock 的既有行为保持不变。

只读入口仍不提供 GATT；正式客户端使用通用硬件主入口。Mac GUI 作为服务的控制与观察界面，复用上述后端，不另写一套 BLE 逻辑。
