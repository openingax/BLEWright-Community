# Contributing · 参与贡献

Run the mock scan and the commands under **Develop and share** in the README before opening a pull request. For a behavior change, include the smallest repeatable example, the platform/API version and the backend used. A hardware-only change should identify the board model, firmware version and expected GATT event.

提交 PR 前请运行 README 中的扫描示例和开发检查。涉及行为变化时，请附最小复现、系统/API 版本、所用后端。硬件问题请提供开发板型号、固件版本和预期的 GATT 事件。

A useful issue report compares expected and observed callbacks for a single operation. Share a short redacted trace. Remove Wi-Fi credentials, account IDs, hardware identifiers, private paths and application payloads before posting.

反馈问题时尽量聚焦一次操作，写清预期和实际回调。请在发布前从日志中移除 Wi-Fi 凭据、账号、硬件标识、私人路径和业务数据。
