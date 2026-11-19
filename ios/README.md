# iOS SimulatorBLE

已实现 Simulator 专用 CoreBluetooth 接管层，直接通过 TCP RPC 连接 Mac BLEWright 服务。没有修改测试 App 的扫描、连接、读写或 delegate 调用。

**实测范围：Xcode 27.1、iPhone Duo / iOS 27.1 Simulator、arm64、Debug。** 当前是开发工具原型，不是 Apple 支持的 CoreBluetooth 扩展机制，也不是其它 runtime 的兼容性承诺。

## 文件与边界

- `Package.swift`：本地 Swift Package，产品名 SimulatorBLE。
- `Sources/SimulatorBLE/BWHooks.m`：可选自动安装、CBCentralManager 方法接管；保留真实 manager 对象。
- `BWObjects.*`：CBPeripheral / CBService / CBCharacteristic / CBDescriptor 的原生类型代理。
- `BWCentral.*`：对象图、扫描过滤、连接代次、操作串行与 delegate 队列。只保存平台状态投影，不包含模拟设备数据。
- `BWRPC.*`：Network.framework TCP、NDJSON、会话、请求关联、心跳和失联处理。
- `BWProtocol.generated.h`：从根 `protocol/constants.json` 生成的发布用头文件，不手改；用 `tools/generate_protocol.py` 更新，构建前执行 `--check`。
- `NOTICE.md` / `ImpossiBLE-LICENSE`：参考实现及 MIT 许可记录。

Mac RPC v1 未改变。iOS 的 `setNotifyValue` 在适配层串行执行 `notification.set` 与 CCCD 写入，对 App 仍呈现一个 CoreBluetooth 操作；服务端继续是通知与数据的唯一来源。

## App 接入

1. 在 Xcode 添加本仓库 `ios/` 目录为本地 Swift Package，链接 SimulatorBLE。也可以使用仓库根目录的 Swift Package。
2. Debug Simulator 链接设置加入 `-ObjC`，确保静态包的自动安装类被加载；或在第一个 CBCentralManager 创建前调用一次 `BWSimulatorBLEInstall()`。
3. 调试 scheme 启动环境设置 `BLEWRIGHT_ENABLE=1`、`BLEWRIGHT_PORT=8765`。默认端口来自公共常量。
4. Mac 运行 `npm run serve`，App 原来的 CoreBluetooth 调用保持不变。

自动安装只在 `TARGET_OS_SIMULATOR && DEBUG` 编译分支内生效，默认不开启。真机及 Release 的安装函数返回 NO。Simulator Debug 包的显式安装函数不依赖环境开关，调用者需自行仅在调试入口调用。

测试宿主以动态 framework 链接同一份源码，靠环境开关在启动时安装；原生探针没有调用自定义 BLE 方法。Swift Package 的 Simulator Debug 与 iOS device Release 构建也已通过。

## CocoaPods 本地接入

`ios/SimulatorBLE.podspec` 供本地开发使用；Podfile 在模拟器模式加入：

```ruby
pod 'SimulatorBLE', :path => '<BLEWright目录>/ios', :configurations => ['Debug']
```

仍需 `BLEWRIGHT_ENABLE=1`。`BWSimulatorBLEIsInstalled()` 可检查当前进程是否已安装钩子。启用时 CBManager 的类/实例 authorization 返回虚拟 allowedAlways，状态仍跟随 RPC 可用性；这不是系统权限授予。非 Simulator Debug 不安装，也不投影权限。

Podfile 使用本地源码路径。

## 重复验证

从仓库根目录执行：

```sh
npm run build:ios -- --simulator <已存在的模拟器UDID>
npm run verify:ios -- --simulator <已启动的模拟器UDID>
```

构建需要 Xcode 和 XcodeGen，生成工程和产物都在 `dist/ios/`。验证器安装独立宿主 `space.nomoloop.blewright.iosprobe`，为每个场景启动临时 Mac 服务，结束后停止测试 App 和临时服务。

结果写入 `dist/tests/ios-results/`，可加 `--output /绝对路径`。正常探针包含主队列/自定义队列两轮；还测试服务关闭、暂停超时、未启动场景。PASS 必须同时与服务端 RPC 请求/通知证据匹配。

## 实现与验证范围

已实测：扫描和 UUID 过滤、停止、连接与立即取消、重复取消、服务/特征/描述符发现及父子对象关系、带响应写入与回读、超长写入失败、通知开启/关闭、无响应写入的通知与 ready 回调、主/自定义 delegate 队列、失联 poweredOff 与断开。

`readRSSI`、描述符读写和已知设备 identifier 查询已有实现，但未在当前原生探针覆盖，不标为已实测。

限制：

- 代理对象依赖 CoreBluetooth 的运行时实现。iOS 27.1 的 CBPeripheral 析构会移除 delegate 自观察；代理构造时建立对应观察以匹配释放，已通过两轮对象释放验证，不能外推到其他系统。
- 旧 mock 的原始广播回退解析为 16 位 UUID；硬件后端归一化的 16/32/128 位 UUID、厂商数据、Service Data 和 TX power 会映射到标准 CoreBluetooth 广播字段。mock 每次扫描发送一次广播，真实只读后端随被动扫描报告更新。
- 不支持 Peripheral、L2CAP、included services、后台恢复、连接事件注册、复杂连接选项与完整 KVO 状态观察。真实设备权限行为不模拟；启用后的 CBManager.authorization 是虚拟 allowedAlways，用于接入 App 权限门控。
- 连接后请求 ATT MTU 247，使用协商值计算最大写入长度。以 MTU 23 起步时可发送 20 字节，MTU 247 时可发送 244 字节。无响应写入错误只有诊断日志，没有伪造 didWrite 回调。
- 每个 central 拥有一个独立 RPC 会话；没有承诺跨 central 的全局 peripheral 身份与共享连接语义。
- 若 SDK 没有 arm64-simulator 二进制，它仍不能加载；本库不解决该问题。

## 运行时选择后端

宿主 App 可在集成层调用 `BWSimulatorBLESetPort`，配置后续创建的 CBCentralManager；既有会话保留创建时的端口。切换前先停止使用旧对象、清空 delegate，再调用 `BWSimulatorBLEEndSession(manager, completion)` 等待后台清理确认或错误，最后创建新 central。结束 API 保持旧 manager 存活到回调，以免析构提前取消确认。完成回调在主队列。CoreBluetooth 业务不需要导入桥接库。

这些 API 仅在 Simulator Debug 生效，真机/Release 不改变原生蓝牙。BLEExplorer 已使用分段控件实现切换和选择持久化，测试启动仍可显式用环境变量覆盖初始端口。
