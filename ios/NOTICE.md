# 来源说明

CoreBluetooth 运行时初始化与对象代理的实现方式参考 ImpossiBLE（Michael Lauer，MIT）：https://github.com/mickeyl/ImpossiBLE ，审阅提交 `79f7b576cf3c9af511236f427c27326817aaff87`。

`BWObjects.m` 中通过 objc_msgSendSuper 调用基类初始化的辅助模式及 CoreBluetooth 对象投影设计由该实现启发/改写；许可全文保留在 [ImpossiBLE-LICENSE](ImpossiBLE-LICENSE)。本仓库的 RPC、会话、操作队列、测试与 Mac 服务接入独立实现，没有引入其运行时依赖。
