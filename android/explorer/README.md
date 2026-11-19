# Android BLEExplorer

独立的原生 BLE 工具（最低 Android 15 / API 35），包名 `space.nomoloop.blewright.explorer`。与自动化探针宿主分开安装。

App 只使用 Android 的 BluetoothLeScanner / BluetoothGatt API；不引用 RPC、Frida、模拟设备数据或硬件后端。普通启动走系统蓝牙；通过外部启动器注入后，当前进程的原生调用交给 BLEWright。直接点击桌面图标**不会**自动启用 BLEWright。

## 构建与安装

使用现有 Android SDK platform 35、build-tools 36.0.0 和 JDK；不需要 Gradle 或额外 UI 库。

```sh
npm run build:explorer
npm run build:android
adb devices -l
adb -s <模拟器序列号> install -r dist/android/explorer/blewright-explorer.apk
```

APK 默认不预授予权限，首次扫描前点击「授权附近设备」。拒绝后可以再次授权；永久拒绝时前往应用权限设置。`neverForLocation` 声明与现有探针一致，Android 可能据此过滤某些用于定位的 BLE 广播，本工具不承诺完整的射频抓包能力。

## 无硬件运行

先按 [Android 接入说明](../README.md) 准备 API 35 模拟器与 Frida Server，然后：

```sh
export PATH="$HOME/Library/Android/sdk/platform-tools:$PATH"
npm run explorer:mock -- --serial <模拟器序列号>
```

该命令启动独立随机端口 mock 服务，注入已安装的 BLEExplorer，不访问 USB/ESP32，不改工作站当前后端。Ctrl-C 结束本次 App 和 mock 服务。启动器需保持运行；Mac 睡眠或连接中断后需重新运行命令。

1. 附近设备 → 开始扫描，看到 BLEWright 设备，地址为 `02:00:00:00:00:01`。
2. 连接设备 → 自动发现 FFF0 服务和 FFF1 特征值。
3. 读取 → 初始值 `42 4C 45`（BLE）；写入 `41 42 43` 后读取应为 ABC。
4. 订阅 → 写入新值，收到通知；取消订阅后继续写入，不再收到通知。
5. 操作日志查看原生回调、状态码，可复制或清空。

## 操作约束

- 扫描最长 15 秒，按地址去重，最多保留 200 台设备。支持无名称设备，显示广播原始字节、服务 UUID 和 RSSI。
- 一次一个连接；连接时停止扫描。GATT 请求串行执行，忙时禁用操作按钮；12 秒无回调会关闭连接，需重新连接，不自动重放写入。
- 读写使用 API 33+ 的值参数接口；写入输入为成对十六进制，最多 512 字节。当前不协商 MTU，实际写入长度受默认 MTU 和后端限制；默认 mock 超过 20 字节返回状态码 13。
- 按特征值属性显示读取、写入、通知或指示操作。订阅必须有 CCCD；仅在 CCCD 成功回调后显示已订阅。无响应写入的提交/回调不等于外设确认接收。
- 离开 App、旋转导致页面销毁或退出会停止扫描、关闭连接，前台重试需手动连接。首次授权和开启蓝牙不会自动开始扫描。
- 服务失联时显示不可用/断开，不自动重连。日志最多保留 300 条、仅存在当前页面实例中。
- 不实现配对加密、配网、固件升级、后台常驻、多设备连接或长写。按钮支持不等于所有后端和硬件已验证。

## UI 自动回归

先构建并安装 App，运行模拟器与 Frida Server，然后执行：

```sh
npm run verify:explorer -- --serial <模拟器序列号>
npm run verify:explorer:edges -- --serial <模拟器序列号>
```

脚本只重置本工具的蓝牙权限，通过系统授权弹窗和页面点击验证流程；使用独立 mock 服务，结束后清理自己启动的服务/注入进程。截图、原生回调和结果保存在 `dist/tests/explorer/`。两个 UI 回归命令须顺序运行，避免争用模拟器前台；edges 另测扫描失败重试、慢连接取消、重复操作、自动停止扫描与服务发现超时。

原生接管层既有回归：`npm run verify:android -- --serial <模拟器序列号>`（需要已安装原探针宿主）。

## 后续真实硬件验证

本轮不接 ESP32。板子重新连接后，由工作站启用目标后端，再运行：

```sh
npm run android:run -- --serial <模拟器序列号> --package space.nomoloop.blewright.explorer --rpc-port <工作站端口>
```

App 不需要切换实现。先选择只读扫描模式验证广播；需要 GATT 时再选择支持连接的后端。扫描到其它真实设备不代表授权操作，只连接明确选定的自有测试设备。真实 C6、配对、加密、MTU、后台和产品配网均不能用 mock 通过代替。

## 正式工作站对接入口（无板也可检查）

```sh
# 读取本机已安装工作站的状态；不启动 App，不扫描或连接 BLE 设备
npm run explorer:workstation -- --check

# 板卡连接并且工作站就绪后：自动使用工作站报告的端口
npm run explorer:workstation -- --serial <模拟器序列号>
```

此入口只读取 `/var/run/blewright/control.sock` 的 status 和公共 RPC hello，不修改配置、不启动/停止工作站服务、不刷固件、不占用硬件扫描会话。板卡未连接、服务停止、握手未完成、只读模式或协议不兼容时输出具体原因并退出（退出码 2）；不后台等待，不自动退回 mock。完整探索要求工作站处于通用 BLE 或受控测试模式，受控模式仍遵守已有目标限制。

预检成功后复用现有 Android 启动器，并在实际注入会话再次检查后端与扫描/连接/GATT 能力，防止预检后配置变化导致误接。App 仍只使用原生 Android BLE API，不读取管理接口，也不包含后端分支。无硬件时继续使用 `explorer:mock`；正式硬件端口必须等工作站就绪才可验证。

对接脚本回归：`.venv/bin/python tests/unit/test_explorer_workstation.py`。测试使用本地临时 socket 和合成握手，不代表真实 ESP32 验证。

## 列表筛选与新版界面

- 默认隐藏未携带名称或名称仅为空白的广播设备。点击「筛选」可以关闭这个条件。
- 可开启信号强度筛选，设置 `−100…−30 dBm` 的 RSSI 下限；提供 `−85 / −70 / −55` 三个快捷值。数值 **大于或等于** 下限才显示，未知信号值在此模式下隐藏。
- 名称与信号条件同时满足才显示。筛选只处理本次扫描的已有结果，不重新扫描，不修改原生 ScanFilter，不触发设备连接或写入。过滤数量显示为「显示 X / 已发现 Y」。
- 修改后点击「应用」才生效；取消保留旧条件。偏好在 App 重启后保留。「恢复默认」回到隐藏无名称、信号不限；无匹配时「显示所有设备」同时关闭两个过滤条件。
- 列表使用紧凑设备卡片，展示名称、地址和信号。广播数据及服务 UUID 移至「广播详情」弹窗，连接入口仍独立保留。
- 底部导航、扫描/连接/读写/通知/日志操作及提示图标统一为本地矢量；增加 Android 自适应启动图标，支持系统主题图标。无网络图标或额外 UI 框架依赖。

验证入口（UI 命令按顺序执行，避免争用模拟器前台）：

```sh
npm run test:explorer:filters
npm run verify:explorer:filters -- --serial <模拟器序列号>
npm run verify:explorer -- --serial <模拟器序列号>
npm run verify:explorer:edges -- --serial <模拟器序列号>
```

筛选 UI 回归使用独立的广播测试数据，包含有名称、无名称、空白名称、阈值边界、动态 RSSI 更新和未知 RSSI；不会访问 S3 或附近真实设备。

Android 广播详情展示原生 ScanRecord。接管层会使用工作站已合并的广播元数据补齐空扫描响应中缺少的名称、服务 UUID 和厂商数据，避免已有设备被误当成无名称设备；不会推测未收到的字段。

实板 UI 回归（需要运行测试固件的自有 C6）：

```sh
npm run verify:explorer:hardware -- --serial <模拟器序列号> --c6-port <已核实的C6串口>
```

这条命令先经 C6 USB 关联请求读取新身份，在 App 广播详情中核对地址和本次 nonce 后才连接；验证 FFF1 读写、通知及取消订阅，并恢复初始特征值、断开连接。其它附近设备只扫描。S3 始终由工作站管理，脚本不会打开 S3 串口或刷写固件。该命令会实际写入 C6 测试特征值，不能用于任意外设。

## Xiaomi 真机与模拟器同包对比

App 最低 API 35；BLEWright 接管目前限定 API 35 模拟器。真机不注入接管层，直接使用系统蓝牙。本次对比设备为 Xiaomi 15 / Android 16 / API 36。

```sh
npm run build:explorer
npm run build:ui-tools
adb -s <真机序列号> install --no-incremental -r dist/android/explorer/blewright-explorer.apk
# 首次在手机允许本 App 的“附近设备”权限。
# --native 只直接启动 App，不使用 Frida 或工作站 RPC。
npm run verify:explorer:hardware -- --native --serial <真机序列号> --c6-port <C6串口> --output dist/tests/explorer/comparison/phone
# 真机完成并断开 C6 后，再测试模拟器。
npm run verify:explorer:hardware -- --serial <模拟器序列号> --c6-port <C6串口> --output dist/tests/explorer/comparison/emulator
```

两个模式使用同一 UI 场景；唯一启动差异是直接启动或调用已有工作站启动器。脚本核对已安装 APK 的 SHA-256 与本地文件一致，比较同一 C6 的广播身份、FFF1 属性、合法/非法输入、带响应/无响应写入及回读、通知与取消、断开及 USB 独立计数。测试结束恢复初始值。不要要求扫描数量或 RSSI 完全相等：系统版本、天线和位置会影响这些值。

`build:ui-tools` 生成标准 `uiautomator runtest` 测试 JAR，使用可见输入控件的 ACTION_SET_TEXT，避免厂商输入法处理 ADB 模拟按键造成字母丢失。仅定位本工具的十六进制输入框，不访问 BLE、不替换回调、不安装额外 APK；临时 JAR 在回归结束时从设备移除。API 36 使用简洁结果输出，避免旧测试打印器依赖已移除的注解类。`verify:explorer:hardware` 需要先构建该测试工具。

若手机拒绝 USB 安装，需要用户在手机允许安装。测试不会更改全局蓝牙、输入法或其它 App 的配置。真机和模拟器必须顺序运行，C6 仅支持一个连接；USB 重枚举时应重新获取身份，不复用旧 nonce 或重放写入。
