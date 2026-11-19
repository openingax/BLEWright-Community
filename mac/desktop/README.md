# BLEWright macOS 工作站

## 结构与运行

- `desktop/main.swift`：原生 AppKit 主窗口和状态栏。用户权限运行；关闭窗口保留状态栏，退出界面不停止后台服务。
- `manager/manager.py`：系统 LaunchDaemon（root），固定管理命令、USB 枚举、串口所有权与 Node 子进程生命周期。
- `service/`：原有 TCP RPC；业务实现仍在既有 backend 中。GUI 不实现另一套蓝牙业务。
- pkg 将 App 安装到 `/Applications/BLEWright.app`，运行资源安装到 `/Library/Application Support/BLEWright`，daemon/agent 分别安装到 `/Library/LaunchDaemons` 和 `/Library/LaunchAgents`。开机启动系统服务，各用户登录启动状态栏。
- Python、pyserial、esptool、Node、固件均随 pkg 提供。使用者不需要 Homebrew、Python 环境、ESP-IDF 或命令行。
- 当前构建目标：Apple Silicon、macOS 13+。Intel 包需要独立构建及验证。

## 初次使用

1. 将 ESP32-S3 的原生 USB Serial/JTAG 口连接 Mac，打开 BLEWright，按 USB 序列号选择 S3 并应用设置。S3/C6 的 VID/PID 可能相同，不能仅靠 USB 型号选择。
2. 新配置默认「通用 BLE」，主 RPC 为 `127.0.0.1:8876`，无需目标身份文件；客户端可以选择任意有效 BLE 设备。同时提供 `8766` 只读兼容入口。升级保留原配置，旧安装需在界面切换为通用 BLE 并应用设置。
3. 如设备尚未运行 BLEWright 固件，在下拉框选择目标板后点击“刷写内置固件”，无需先应用设置；确认弹窗会显示目标 USB 序列号。刷写只使用本次选择，设备断开或身份不唯一时拒绝操作，不回退到已绑定的板。刷写不更改服务绑定，之后使用新板运行服务仍需应用设置。仅写 bootloader、partition table、app，校验随包 SHA-256，由 esptool 再校验芯片型号和写入结果；不擦全片，不改 eFuse。定制分区/已有数据的板卡应先备份。当前只提供随包固件，不接受任意路径交给 root 刷写。
4. 可选「受控测试」模式要求导入从 C6 USB 读取的精确身份 JSON（address/addressType/nonce）。保持 `127.0.0.1:8876` 受控入口，同时提供 `8766` 只读入口，两者共享一个串口 worker。该测试模式保留白名单；通用模式不受此限制。
5. 停止服务会持久化，重新插入也不会自行启动。USB 断开后关闭旧会话；接回同一序列号自动重新握手，仅恢复服务，不重放扫描、连接或写入。C6 重启后 nonce 变化，需要重新导入身份。

## 状态与权限

USB 枚举每秒检查；固件由既有 worker 每 5 秒保活，超时/退出会让服务不可用并触发重新握手。USB 插入不等于服务就绪：主窗口区分等待、握手、就绪、停止、重启、刷写和异常。固件日志展示刷写输出及脱敏服务生命周期，不额外打开被业务独占的串口。

启动/停止按钮与菜单栏共用服务启用状态：已启用（包括握手中、等待 USB、自动重试）时只能停止，未启用时只能启动；维护和请求处理中均禁用。刷写管理请求必须携带目标 `serial`，后台在释放业务串口后重新枚举确认目标。

管理 API 是 `/var/run/blewright/control.sock` 的本地 JSON Lines，`apiVersion:1`，不开放管理 TCP 端口。所有用户可读取状态；变更操作通过 `getpeereid` 校验实际连接用户为 root 或 admin 组。没有执行 shell、透传 USB、任意固件路径或任意文件写入入口。程序、配置和运行目录由 root 持有；子进程清除外部 NODE_OPTIONS/PYTHONPATH 等注入环境。

升级安装前检查是否正在维护固件，忙碌时拒绝升级；持久配置不打入安装包，升级保留绑定信息。单实例锁防止两个 supervisor 占用串口。关闭服务先让 Node/worker 执行清理，超时才终止残留进程组。

## API 兼容承诺

既有 RPC envelope、请求/响应、错误和 `session.end` 行为保持协议 **v1**。hello 增加可忽略字段：`serverVersion`、`protocolVersion`、`minimumProtocolVersion`、`backend`、`capabilities`（受控后端另有 `targetPolicy`）。新增无硬件副作用的 `server.info` 方法，返回同样的软件/协议/能力信息。

客户端应检查 hello.version，只在兼容主版本继续，并忽略未知可选字段。新增可选字段和方法不增加协议主版本；改变已有语义或移除字段才升级协议主版本并提供迁移期。管理 API 与公共 RPC 独立版本化，BLE Explorer 不需要调用管理 API。

mock CLI 的 8765 入口和 iOS/Android 默认配置不变。桌面工作站只管理真实硬件；mock 测试服务可继续独立运行。`--port` 仅用于隔离测试，覆盖后不额外开共享扫描入口。

## 从源码构建 Apple Silicon 安装包

在仓库根目录运行以下命令。构建机需要 Xcode 命令行工具、Python 和网络连接。先按[固件说明](../../firmware/README.md)构建 S3 固件，确认 `firmware/build/flasher_args.json` 已生成。

```sh
python3 -m venv .venv
.venv/bin/pip install -r mac/manager/requirements.txt
bash mac/packaging/build.sh
```

输出为 `dist/BLEWright-0.4.1-arm64.pkg`。本地构建使用 ad-hoc 应用签名。发行者可选用自己的 `APPLICATION_IDENTITY` 和 `INSTALLER_IDENTITY` 签署应用及安装包。该源码构建独立于在线更新服务。
