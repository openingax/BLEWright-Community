# ESP32-C6 专用 BLE 测试外设

独立 ESP-IDF / NimBLE Peripheral + GATT Server 工程，不修改 S3 Central 固件，也不属于 Mac RPC 的模拟后端。用于自己的 C6 测试板；S3 测试程序必须先通过 C6 USB 身份与被动广播双重匹配，才允许连接。

## 外设行为

- 名称 `BLEWright-C6`；服务 `FFF0`；特征 `FFF1`。
- FFF1 支持 Read、Write、Write Without Response、Notify；初值 ASCII `BLE`，写入后保存并向已订阅客户端回显通知。
- NimBLE 自动生成 CCCD 2902；订阅初次也发送当前值。
- 每次启动生成随机 4 字节 nonce。
- 传统广播共 29 字节：Flags 3 + FFF0 UUID16 4 + 完整名称 14 + Manufacturer 8；manufacturer payload 为 `FF FF`（测试 ID 0xFFFF，小端）加 nonce 的 4 个原始字节。
- 单连接；断开后重新广播。没有扫描或连接其它设备的 Central 能力。

## USB 身份与旧帧防护

固件每秒打印一次身份 JSON 供观察；**这些无 requestId 的周期行不能授权连接**。

USB 唯一可接受的请求是只读 identity 查询：

```json
{"op":"identity","requestId":"32位随机十六进制字符串"}
```

响应回显完全相同的 requestId，并包含 `chip=ESP32-C6`、`firmware=blewright-c6-fixture/0.2`、address、addressType、nonce、manufacturerId、advertising、connected 和读写/订阅计数。USB 没有 BLE 状态变更命令。

`tools/identity.py` 为每次查询生成新的 128 位随机 requestId，只接受与本次 ID 匹配的响应；跳过旧启动日志、旧 boot 身份和其它 requestId。不能用“睡眠后取最后一行”代替关联验证。工具清除 HUPCL，避免关闭串口时挂断；打开原生 USB 仍可能导致复位，必须重新获取当前 nonce。

实际身份存放 `build/identity.json`，已忽略入库。不要把别人的设备或仅同名设备写入该文件；必须由已核实 C6 USB 查询产生。Mac 受控后端使用 address/type/nonce，并在连接前要求近期被动广播匹配。

## 构建、刷入

以下命令从仓库根目录执行，使用本次 ESP-IDF v5.5.1 环境：

```sh
source "$HOME/esp/esp-idf/export.sh"
idf.py -C firmware/fixtures/esp32c6 set-target esp32c6
idf.py -C firmware/fixtures/esp32c6 build
idf.py -C firmware/fixtures/esp32c6 -p "${C6_PORT:?Set C6_PORT to the fixture port}" flash
```

默认配置针对已确认的 16MB C6；其它板必须先重新核实型号、Flash 和端口。本项目不擦除 NVS 初始化错误，不自动恢复或重刷别的开发板。

## 身份匹配与实板验证

不要运行旧 `firmware/tools/verify_hardware.py`（它指向 Mac 外设）。以下测试只允许连接本次 C6。

```sh
source "$HOME/esp/esp-idf/export.sh"
python firmware/fixtures/esp32c6/tests/test_identity.py
python firmware/fixtures/esp32c6/tools/verify_fixture.py \
  --c6-port "${C6_PORT:?Set C6_PORT to the fixture port}" \
  --s3-port "${S3_PORT:?Set S3_PORT to the adapter port}" \
  --prepare-gate firmware/fixtures/esp32c6/build/new-verification.gate
```

准备阶段保持 C6 USB 打开，通过关联查询获取身份，写 `build/identity.json` 并输出准备信息。在另一个终端确认该身份属于已授权 C6 后创建本次不存在的 gate 文件：

```sh
touch firmware/fixtures/esp32c6/build/new-verification.gate
```

测试只被动扫描，严格匹配 USB 地址、地址类型和 manufacturer nonce；匹配不足绝不发 connect。验证服务/特征/描述符、初值、带响应读写、CCCD 通知、无响应写入后断开。最后关闭 C6 USB，再启动一次新的 S3 被动扫描，确认同一个 nonce 仍在空中，然后释放 S3 串口。

完成后可把 `build/identity.json` 交给 Mac 受控后端。不要再次打开或复位 C6 USB；如必须重开，重新关联查询并验证广播，再更新身份文件。

## 证据边界

本轮验证的是自建 C6 专用外设与 S3 的实际无线链路；未连接其它设备。没有验证配对/加密、长期压力、多客户端、OTA 或真实产品业务协议。随机 nonce 是 USB 与当前广播的关联标识，不是密码学设备认证。
