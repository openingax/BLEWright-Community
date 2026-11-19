# 在 Mac 上运行 BLEWright

[English](guide.en.md) · [项目首页](../README.md)

以下命令均在 BLEWright 仓库根目录执行。第一次使用建议先连模拟外设，验证 App 与 Mac 服务之间的通信，再接 USB 开发板测试真实蓝牙。

## 1. 启动模拟外设

安装 Node.js 20 或更新版本，打开终端执行以下命令，并保持服务运行。

```sh
npm ci
npm run serve
```

终端出现包含 `"event":"listening"` 和 `"backend":"mock"` 的 JSON 行即表示服务就绪。服务监听 Mac 本机回环地址，每个客户端会看到一台名为 **BLEWright** 的模拟外设。连接后，发现服务 **FFF0**，读取其特征 **FFF1**，初始值应为 `42 4c 45`（ASCII 字符串 `BLE`）。写入新值后再次读取，应得到刚写入的内容。

| 后端 | 默认 TCP 端口 | 可验证的内容 |
| --- | --- | --- |
| 模拟外设 mock | 8765 | 每个会话拥有一台模拟外设 |
| ESP32-S3 硬件 | 8876 | 附近设备的真实广播，以及一路活动连接 |
| 被动扫描 | 8766 | 启用只读服务后可接收广播 |

## 2. 接入你的 iOS App

1. 在 Xcode 中打开 App 工程，选择 **File → Add Package Dependencies → Add Local**，选中 BLEWright 仓库根目录，在 App target 链接 **SimulatorBLE** 产品。
   也可在添加依赖窗口输入 `https://github.com/openingax/BLEWright-Community.git`，选择 `0.1.0` 版本并链接 **SimulatorBLE** 产品。
2. 在 App target 的 **Build Settings → Other Linker Flags** 展开 **Debug**，添加 **Any iOS Simulator SDK** 条件。保留已有的继承值，追加 `-ObjC`，使启动时安装适配器的 Objective-C 类能被加载。
3. 复制一份开发用 scheme，在 **Edit Scheme → Run → Info** 选择 **Debug**。在 **Arguments → Environment Variables** 添加并勾选 `BLEWRIGHT_ENABLE=1` 和 `BLEWRIGHT_PORT=8765`。
4. 选择 iPhone 模拟器并运行，进入 App 原来的蓝牙扫描页面。Xcode 控制台应出现 `SimulatorBLE installed`。若业务页面按产品名称或 UUID 过滤，模拟外设可能不会出现在列表。可以用无过滤扫描或下面的独立探针验证。
5. 在 scheme 中移除启用变量并重新启动，即恢复默认行为。Hook 仅编译在 Debug 模拟器条件下，真机和 Release 使用系统 CoreBluetooth。App 使用的第三方 SDK 也需要提供可在对应模拟器运行的二进制。

如需运行自带的探针，请安装 XcodeGen，在 Xcode 启动 iPhone 模拟器，执行 `xcrun simctl list devices booted` 并复制其 UUID。验证程序会自动启动和清理临时服务。

```sh
read -r 'simulator_id?已启动的模拟器 UUID: '
npm run build:ios -- --simulator "$simulator_id"
npm run verify:ios -- --simulator "$simulator_id"
```

交互输入命令适用于 macOS 默认的 zsh。探针覆盖回调、数据交换以及后端失联。适配器依赖模拟器中的 CoreBluetooth 运行时实现，升级 Xcode 后可重新运行探针验证。

## 3. 运行 Android 示例

准备一个支持 root、具备 BluetoothAdapter 的 Android 15 / API 35 开发 AVD。安装 JDK 17、Android SDK Platform 35、Build Tools 36.0.0 和 Platform Tools，确保能直接运行 `adb`。构建脚本默认从 `$HOME/Library/Android/sdk` 读取 SDK，可用 `ANDROID_SDK_ROOT` 和 `JAVA_HOME` 指定其他位置。使用自己的开发模拟器和有权调试的 App。

安装启动器依赖并构建自带的 BLE Explorer 示例。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r android/launcher/requirements.txt
npm run build:android
npm run build:explorer
adb devices -l
```

将 `avd` 替换为已启动的模拟器序列号。按下面命令输出的 ABI 下载 Android **frida-server 17.5.1**（`arm64-v8a` 对应 `android-arm64`），解压后把可执行文件放到 `/tmp/frida-server`。启动器依赖的 Frida 版本需与模拟器上的服务端一致。[Frida 17.5.1 下载页](https://github.com/frida/frida/releases/tag/17.5.1)

```sh
avd=emulator-5554
adb -s "$avd" shell getprop ro.product.cpu.abi
adb -s "$avd" root
adb -s "$avd" wait-for-device
adb -s "$avd" push /tmp/frida-server /data/local/tmp/blewright-frida-server
adb -s "$avd" shell chmod 755 /data/local/tmp/blewright-frida-server
adb -s "$avd" shell '/data/local/tmp/blewright-frida-server >/data/local/tmp/blewright-frida.log 2>&1 &'
adb -s "$avd" install -r -g dist/android/explorer/blewright-explorer.apk
npm run explorer:mock -- --serial "$avd"
```

启动器会为这次运行单独创建 mock 服务。在 BLE Explorer 中开始扫描，选中 **BLEWright**，连接、发现服务并读取 **FFF1**。调试期间保持启动器运行，按 Ctrl-C 可结束本次会话。完成第 4 步的硬件配置后，可以用以下命令让已安装的示例改连硬件服务。

```sh
npm run android:run -- --serial "$avd" --package space.nomoloop.blewright.explorer --rpc-port 8876
```

## 4. 切换到真实外设

准备一块带**原生 USB Serial/JTAG** 接口的 ESP32-S3、一条数据线和另一台可测试的 BLE 外设。仓库默认配置面向 **16 MB Flash**，烧录前先核对开发板规格。烧录会覆盖桥接板当前固件。若电脑连接了多块板，可拔插桥接板并对比串口列表，确定目标。

在已安装并激活 ESP-IDF **v5.5.1** 的终端中执行以下命令。

```sh
python -m serial.tools.list_ports -v
read -r 'bridge_port?ESP32-S3 串口路径: '
idf.py -C firmware set-target esp32s3
idf.py -C firmware build
idf.py -C firmware -p "$bridge_port" flash
```

关闭串口监视器。继续在同一终端执行以下命令，按需创建仓库虚拟环境，安装串口依赖并启动服务。一个串口同一时间由一个进程占用。

```sh
test -x .venv/bin/python || python3 -m venv .venv
.venv/bin/python -m pip install -r firmware/tools/requirements.txt
BLEWRIGHT_BACKEND=esp32 BLEWRIGHT_SERIAL="$bridge_port" npm run serve
```

终端应依次出现 `boardReady` 和后端为 `esp32` 的 `listening`。把模拟器客户端端口改为 **8876** 并重新启动。让待测外设进入广播状态，扫描、选择目标并连接，发现服务后即可查看它实际支持的读、写和订阅能力。桥接板会与外设协商 ATT MTU，应用应读取当前连接的最大写入长度。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| iOS 提示蓝牙未打开 | 先看控制台是否有安装日志。缺少日志时检查模拟器目标、Debug 配置、链接标志和 scheme 环境变量。有日志时核对服务监听端口并重新启动 App。 |
| 服务已就绪，App 设备列表为空 | 用无过滤扫描检查。模拟外设广播 FFF0；硬件模式下确认外设正在广播，服务日志中的后端为 `esp32`。 |
| 硬件返回 `BUSY` | 退出之前占用硬件的客户端，等待会话关闭，再从新客户端连接。重启服务前关闭串口监视器。 |
| 有串口，但服务没有出现 `boardReady` | 检查接口、固件目标和选中的端口。USB 转 UART 接口也可能出现在列表中，本固件使用 S3 的原生 USB 接口传输数据。 |
| Android 提示版本不支持，或无法 root | 检查 `ro.build.version.sdk` 是否为 35，选用可 root 的开发 AVD，核对模拟器 ABI 及两端 Frida 版本。 |
| 已连接，但传输卡住 | 对比当前协商的写入长度和应用发送的载荷长度。后端支持单个 ATT 载荷和通知；外设协议要求分包时，请按该协议分包。 |
