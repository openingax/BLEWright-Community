# Android SimulatorBLE

- `simulatorble/agent.js`：仅在目标 App 进程中接管 Android BLE 方法；缓存原生对象、回调与请求状态，不拥有模拟设备数据。
- `launcher/run.py`：检查 API 35 模拟器、连接 Mac RPC、spawn 并注入目标进程，可加载测试探针。
- `launcher/rpc_relay.py`：Frida 与 TCP 消息转发，不解析设备业务。
- `launcher/requirements.txt`：只用于启动器的 Python 依赖。

构建命令在仓库根目录统一执行：`npm run build:android`。输出为 `dist/android/agent.js`。API 35 内部构造器在 Hook 前检查；不同 Android API 明确拒绝。服务失联时适配器状态变为关闭、扫描失败、连接断开；不会自动重放请求。

## 准备模拟器与 Frida

使用可 root 的 API 35 开发 AVD，已有非空 BluetoothAdapter。Google Play 生产镜像通常不能 root。已验证 arm64 模拟器。以下序列号应替换成 `adb devices -l` 中的实际值。

下载与 AVD ABI 相同的 [Frida Server 17.5.1](https://github.com/frida/frida/releases/tag/17.5.1)，解压后：

```sh
adb devices -l
adb -s emulator-5554 shell getprop ro.product.cpu.abi
adb -s emulator-5554 root
adb -s emulator-5554 wait-for-device
adb -s emulator-5554 push /实际路径/frida-server /data/local/tmp/blewright-frida-server
adb -s emulator-5554 shell chmod 755 /data/local/tmp/blewright-frida-server
adb -s emulator-5554 shell '/data/local/tmp/blewright-frida-server >/data/local/tmp/blewright-frida.log 2>&1 &'
```

安装独立测试宿主（它不包含 Hook，原生 API 探针由启动器动态加载）：

```sh
npm run build:host
npm run build:probe
adb -s emulator-5554 install -r -g dist/tests/android/host/blewright-host.apk
```

`-g` 只为这个测试 APK 授予声明的运行时权限。业务 App 需要自行获得 BLUETOOTH_SCAN / BLUETOOTH_CONNECT；启动器不会替它授予权限。

在另一个终端启动 `npm run serve` 后：

```sh
npm run android:run -- --serial emulator-5554 --package space.nomoloop.blewright.host --probe
```

观察现有 App 时，替换包名并去掉 `--probe`，例如 `--package com.example.myapp`。`--rpc-port` 可选择服务端口。启动器退出会结束它启动的 App 进程，保留模拟器与 Frida Server；正常重新打开 App 即不再注入。

只有 `PASS:` 且退出码 0 才表示探针成功，`ready` 仅代表 Hook 安装完成。原生对象和连接暂保留至进程退出，尚不适合长时间运行。

无显式 Handler 时原型在主线程回调；这不是系统默认 Binder 线程行为的完整复刻。扫描过滤使用原生 ScanFilter；每次扫描由服务发一次模拟广播。按厂商广播过滤的 SDK 可能无法发现内置模拟设备。

## 接入已运行的 BLEWright 工作站

ESP32 只由 BLEWright 管理。Android 启动器只连接公共 RPC，不打开 USB、不启动硬件服务、不修改固件。启动日志显示实际服务版本、后端及能力；8765 为 mock，8766 为只读扫描，8876 为通用 BLE（或显式选择的受控测试模式）。

```sh
npm run android:run -- --serial emulator-5554 --package com.example.myapp --rpc-port 8876
```

通用模式由 App 选择设备，没有 C6 白名单；受控测试模式才限定 C6。运行前由工作站配置模式；切换端口需退出本次启动器再重新启动，不支持 App 内热切换。BLEExplorer 和 Android 不要同时占用硬件，另一会话占用时服务会返回 BUSY。

多个 Android ScanCallback 共用一次后端扫描，分别执行原生 ScanFilter；停止一个回调不影响其它回调，最后一个停止时才停止后端。启停串行化，已停止回调不会收到排队中的结果。该逻辑对 mock 和真实硬件一致。

## 硬件回归

使用已运行的 API 35 模拟器、Frida Server 和已安装的独立测试宿主；这些命令不会构建或安装 APK，也不会启动模拟器。PATH 需包含 Android SDK platform-tools。

```sh
npm run build:android
npm run build:probe
# BLEWright 只读模式；附近需有广播中的测试 C6，不连接任何外设。
npm run verify:android:hardware -- --serial emulator-5554 --scan-only
# BLEWright 通用模式；测试客户端使用新读取的 C6 身份限定自动操作目标。
npm run verify:android:hardware -- --serial emulator-5554 --target-identity /绝对路径/identity.json
# 可选旧受控模式仍支持不传 target-identity 运行。
```

可用 `--rpc-port` 指定服务端口，`--output` 指定证据目录。GATT 探针识别通用 esp32/any-device 或受控 esp32-controlled/exact-allowlist，拒绝误把 mock 当实板通过；扫描探针要求 esp32-scan。通用服务不做设备白名单，自动测试必须提供 C6 USB 身份，探针以真实地址和厂商 nonce 过滤后才连接；该限制只存在于测试客户端。

受控探针覆盖并发扫描/过滤/停止、重复回调拒绝、两轮连接/发现/读写/通知、旧版与新版 API、指定 Handler、断开和立即 close 取消。两轮使用不同写入值；允许真实设备包含额外标准服务。不代表真机后台行为、配对、长写或外设业务协议已验证。mock 与服务失联回归继续运行 `npm run verify:android`。

## 独立 Android BLEExplorer

交互式原生 BLE 测试 App 位于 [`explorer/`](explorer/README.md)，与上面的独立自动化探针宿主分开安装。提供扫描、连接、服务/特征值浏览、读写、通知和日志；App 不直接连接 RPC。`npm run build:explorer` 构建 APK，`npm run explorer:mock -- --serial <模拟器序列号>` 启动无硬件测试，`npm run verify:explorer -- --serial <模拟器序列号>` 执行页面回归。

广播转换会将当前原始包与服务已合并的名称、服务 UUID、厂商/服务数据和发射功率投影到 Android 原生 ScanRecord。空的主动扫描响应不会清掉已知名称；完整原始记录不重复添加字段。该逻辑对全部后端共用，不在业务 App 中补假数据。
