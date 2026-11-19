"""Compile the real AppKit controller with an isolated, hardware-free render harness."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'mac/desktop/main.swift').read_text().split('let delegate = AppDelegate()')[0]
harness = r'''
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let d = AppDelegate()
d.makeWindow(); d.makeMenu(); d.makeMainMenu()
let names = ["waiting":"等待 ESP32-S3 接入", "starting":"正在握手…", "ready":"服务已就绪", "stopped":"服务已停止", "error":"服务异常", "flashing":"正在刷写固件…", "restarting":"正在重启 S3…"]
var count = 0
for appearance in [NSAppearance.Name.aqua, .darkAqua] {
 d.window.appearance = NSAppearance(named: appearance)
 for backend in ["esp32", "esp32-scan", "esp32-controlled"] {
  d.modeInitialized = false
  for (state, title) in names {
   let busy = ["flashing", "restarting"].contains(state)
   let hasUSB = state != "waiting"
   let payload: [String: Any] = ["state":state, "busy":busy, "config":["serial":"S3-TEST", "mode":backend, "enabled":state != "stopped"], "serverVersion":"0.4.0", "firmware":"blewright-s3/0.2", "rpcAddress":"127.0.0.1:8766", "devices":hasUSB ? [["serial":"S3-TEST", "path":"/dev/cu.test"]] : [], "logs":state == "ready" ? ["服务已启动", "测试日志"] : [], "error":state == "error" ? "设备响应超时，请重新接入 USB。" : ""]
   d.render(payload)
   d.window.setContentSize(NSSize(width: 1000, height: 758))
   d.window.contentView!.layoutSubtreeIfNeeded()
   assert(d.stateLabel.stringValue == title)
   assert(d.sidebarStatus.stringValue == title)
   assert(d.mode.indexOfSelectedItem == (backend == "esp32-controlled" ? 2 : backend == "esp32-scan" ? 1 : 0))
   for b in d.actionButtons {
    let expected = b.action == #selector(AppDelegate.start) ? (!busy && state == "stopped") : b.action == #selector(AppDelegate.stop) ? (!busy && state != "stopped") : !busy
    assert(b.isEnabled == expected)
   }
   assert(d.menuStart.isEnabled == (!busy && state == "stopped"))
   assert(d.menuStop.isEnabled == (!busy && state != "stopped"))
   assert(d.device.isEnabled == !busy && d.mode.isEnabled == !busy)
   assert(d.menuRestart.isEnabled == (!busy && hasUSB))
   assert(d.errorLabel.isHidden == (state != "error"))
   assert(d.logEmptyLabel.isHidden == (state == "ready"))
   assert(d.logs.string == (state == "ready" ? "服务已启动\n测试日志" : ""))
   let root = d.window.contentView!
   for view in d.actionButtons + [d.device, d.mode] {
    let rect = view.convert(view.bounds, to: root)
    assert(root.bounds.contains(rect), "Control clipped: \(rect)")
   }
   assert(d.logs.enclosingScrollView!.frame.height >= 85)
   count += 1
  }
 }
}
// Polling must preserve an unsaved mode choice and USB selection.
d.mode.selectItem(at: 0)
d.render(["state":"ready", "config":["serial":"A", "mode":"esp32-controlled"], "devices":[["serial":"A", "path":"a"],["serial":"B", "path":"b"]]])
d.device.selectItem(at: 1)
d.render(["state":"ready", "config":["serial":"A", "mode":"esp32-controlled"], "devices":[["serial":"A", "path":"a2"],["serial":"B", "path":"b2"]]])
assert(d.mode.indexOfSelectedItem == 0)
assert(d.device.selectedItem?.representedObject as? String == "B")
assert(d.selectedFlashRequest()?["serial"] as? String == "B")
for enabled in [true, false] {
 for state in ["waiting", "starting", "ready", "stopped", "error"] {
  for pending in [true, false] {
   d.requestPending = pending
   d.render(["state":state, "config":["serial":"A", "enabled":enabled], "devices":[]])
   assert(d.menuStart.isEnabled == (!pending && !enabled))
   assert(d.menuStop.isEnabled == (!pending && enabled))
   assert(d.selectedFlashRequest() == nil)
  }
 }
}
print("PASS: \(count) state × mode × appearance render cases; minimum-size bounds, busy controls, logs, errors, menu status, unsaved selection retention")
'''
with tempfile.TemporaryDirectory(prefix='blewright-render-') as tmp:
    entry = Path(tmp) / 'main.swift'
    entry.write_text(source + harness)
    binary = Path(tmp) / 'verify'
    subprocess.run(['xcrun','swiftc','-swift-version','5',str(entry),str(root/'mac/desktop/Design.swift'),'-framework','AppKit','-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
