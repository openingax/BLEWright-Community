# ESP32-S3 BLE 固件

当前已实现并在 ESP32-S3 实板上验证：USB 帧握手、真实 BLE 扫描/连接、服务/特征/描述符发现、读写、CCCD 订阅与通知、MTU/RSSI、断开。Mac 的硬件后端通过 USB 与该固件通信。

## 目录与边界

- `main/main.c`：ESP-IDF + NimBLE Central / GATT Client，单连接，所有命令与 BLE 状态在 NimBLE 主机事件队列上处理。
- `main/wire.c` / `wire.h`：有界长度 + CRC32 串口帧，不依赖 ESP-IDF，可在 Mac 编译测试。
- `tools/serial_client.py`：串口协议客户端，不重试写入。
- `tools/verify_passive_scan.py`：仅发送 hello / scan.start(passive=true) / scan.stop，校验前后未连接；只输出帧数和临时地址身份数量，不输出设备名称、地址或原始广播。
- `tools/verify_hardware.py`：仅连接名为 BLEWright-HW 的自建测试外设，验证真实无线链路。
- `tools/PeripheralFixture.swift`：独立 Mac CoreBluetooth 测试外设。不是 Mac RPC 模拟后端。
- `tests/test_wire.py`：C/Python 双向编解码、损坏帧、分片输入等测试。
- `USB_PROTOCOL.md`：USB 操作、帧、状态码与取消/租约约定。
- `build/`、sdkconfig：本机生成文件，已忽略。原始 Flash 备份也在 build/，不入库。

只支持 BLE，不实现经典蓝牙或上层设备业务协议。ESP-IDF 5.5 将 incoming ATT notification 分发放在 BLE_GATTS 条件编译中，因此配置启用了 GATT_SERVER / ROLE_PERIPHERAL 依赖；固件没有调用广播或注册业务 GATT 服务，实际对外功能仍为 Central。

## 构建与烧录

本次使用 ESP-IDF v5.5.1。先加载自己的 IDF 环境，例如：

```sh
source "$HOME/esp/esp-idf/export.sh"
# 缺少 S3 编译器时安装该 IDF 版本要求的工具：
python "$IDF_PATH/tools/idf_tools.py" install --targets esp32s3
# 安装后重新加载 export.sh
idf.py -C firmware set-target esp32s3
idf.py -C firmware build
idf.py -C firmware -p "${S3_PORT:?Set S3_PORT to the board serial port}" flash
```

先根据 USB 枚举结果设置 S3_PORT。仓库默认按 16 MB Flash 构建。其他容量须先调整配置并验证分区表。烧录仅覆盖 bootloader、分区表、应用区，没有改 eFuse 或擦整片 Flash；不会在 NVS 初始化错误时擅自擦除 NVS。

## 只监听真实广播（不连接设备）

固件 0.2 已支持显式被动扫描。此流程不启动 Mac 测试外设，也不运行旧的连接探针：

```sh
source "$HOME/esp/esp-idf/export.sh"
python firmware/tests/test_passive_scan.py
python firmware/tools/verify_passive_scan.py --port "${S3_PORT:?Set S3_PORT to the board serial port}" --seconds 10
```

工具只检查 hello 并启动 passive=true 扫描、停止扫描；已连接/正在连接、固件缺少被动扫描能力或扫描模式未被确认时直接失败，不发送任何 connect、cancel、disconnect、read、write 或订阅命令。输出仅为聚合计数；临时 BLE 地址可能轮换，地址身份数量不等于物理设备数量。

不要使用 `serial_client.py --scan` 做禁止主动扫描的验收，它为兼容旧流程保留默认主动扫描。不要使用下面的旧完整链路验证命令，除非另有明确允许连接自建外设的授权。

## 独立实板验证（会连接自建外设，仅在允许连接时使用）

在仓库根目录执行（使用 IDF Python 环境，内含 pyserial；其他环境可安装 tools/requirements.txt）：

```sh
python firmware/tests/test_wire.py
sh firmware/tools/build_fixture.sh
firmware/build/BLEWrightHardwareFixture.app/Contents/MacOS/Fixture
```

测试外设显示 `ADVERTISING BLEWright-HW / FFF0` 后，另开终端：

```sh
source "$HOME/esp/esp-idf/export.sh"
python firmware/tools/serial_client.py --port "${S3_PORT:?Set S3_PORT to the board serial port}" --scan 3
python firmware/tools/verify_hardware.py --port "${S3_PORT:?Set S3_PORT to the board serial port}"
```

完整验证包括 15 秒无主机命令的租约超时，通常需约 20 秒。测试程序只连接自建的 BLEWright-HW 外设；附近设备的广告不会写入提交的证据文件。
