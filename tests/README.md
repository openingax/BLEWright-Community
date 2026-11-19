# 验证入口与证据

| 目录 | 验证层级 |
|---|---|
| unit/ | 模拟后端状态，不证明 Android 接管成功 |
| integration/ | 本机真实 TCP 请求/响应/通知、会话隔离与清理 |
| android/host/ | 无 Hook 的独立测试宿主 APK |
| ios/ | iOS 独立宿主、CoreBluetooth 探针与 XcodeGen 工程定义 |
| android/probe/ | 仅调用原生 Android BLE API 的正常/故障探针 |
| e2e/ | 启动临时 Mac 服务并在真实运行的模拟器内执行探针 |

从仓库根目录运行：

```sh
npm test
npm run build:probe
npm run build:host
npm run verify:android -- --serial emulator-5554
```

`verify:android` 需要已启动的 API 35 模拟器、Frida Server 和已安装的独立测试宿主。默认写入 `dist/tests/results/`；可用 `--output /绝对路径` 改变输出位置。该脚本自行启动并回收临时服务，不影响默认开发服务。

构建产物分别位于 `dist/android/agent.js`、`dist/tests/android/probe/classes.dex`、`dist/tests/android/host/blewright-host.apk`。构建脚本从自身位置定位仓库，不依赖调用目录。

验收必须同时检查：正常原生 API 探针 PASS、服务端确实收到对应请求且产生通知、断线/超时/服务缺失负向结果。`ready` 或单元测试通过不足以证明接管成功。

## iOS 验证

`npm run build:ios -- --simulator <UDID>` 构建到 `dist/ios/`；`npm run verify:ios -- --simulator <UDID>` 在已启动的模拟器执行，默认证据目录为 `dist/tests/ios-results/`。两种 delegate 队列的正常链路与服务终止、暂停超时、服务缺失分别验证，并断言服务端收到真实请求和产生通知。

固件独立帧测试和真实射频验证保留在 [firmware/tests 与固件说明](../firmware/README.md)，其证据不等价于公共 RPC 硬件链路已验证。

## 通用硬件服务回归

0.4 的 esp32 后端不限制目标；自动测试仍在测试客户端限制为 USB 核实的 C6。

```sh
.venv/bin/python tests/e2e/verify_c6_rpc.py --general --port 8876 --identity /绝对路径/identity.json --output dist/general-rpc.json
npm run verify:android:hardware -- --serial emulator-5554 --target-identity /绝对路径/identity.json
```

身份须由当前连接的 C6 新读取，包含地址、类型和启动 nonce。上述工具不会配置通用服务白名单。已有 iOS UI 按名称选择目标时可使用 fixture_rpc_proxy.py 作为仅测试的目标过滤代理；正式客户端直接连接 BLEWright，不使用代理。



## 独立 Android App 与双端对比

- `npm run test:explorer:filters`：名称、RSSI 边界与组合筛选的 JVM 测试。
- `npm run verify:explorer -- --serial <模拟器序列号>`：mock 主 UI 流程。
- `npm run verify:explorer:edges -- --serial <模拟器序列号>`：失败重试、取消、重复操作与超时。
- `npm run verify:explorer:filters -- --serial <模拟器序列号>`：多广播、空扫描响应、筛选设置及持久化。
- `npm run build:ui-tools`：构建标准 UI 自动化文本工具；不安装额外 APK、不替换 BLE API。
- `npm run verify:explorer:hardware -- --serial <序列号> --c6-port <C6串口>`：工作站实板 UI 验证。增加 `--native` 时直接在真机运行同一场景，使用 `--output` 保存独立证据。

UI 用例顺序运行，避免争用前台或 C6 单连接。实板用例仅对经过 USB 身份与广播 nonce 双重核实的 C6 读写测试特征值，并恢复原值；不会连接其它附近设备。完整准备步骤见 [工具说明](../android/explorer/README.md)。
