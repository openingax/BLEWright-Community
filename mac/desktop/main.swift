import AppKit
#if canImport(Sparkle)
import Sparkle
#endif
import UniformTypeIdentifiers
import Darwin

final class ControlClient {
    let path = ProcessInfo.processInfo.environment["BLEWRIGHT_CONTROL_SOCKET"] ?? "/var/run/blewright/control.sock"
    func request(_ values: [String: Any]) throws -> [String: Any] {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw NSError(domain: "Socket", code: 1) }
        defer { close(fd) }
        var timeout = timeval(tv_sec: 3, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout)))
        var noSig: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSig, socklen_t(MemoryLayout.size(ofValue: noSig)))
        var addr = sockaddr_un(); addr.sun_family = sa_family_t(AF_UNIX)
        guard path.utf8.count < MemoryLayout.size(ofValue: addr.sun_path) else { throw NSError(domain: "路径过长", code: 1) }
        withUnsafeMutablePointer(to: &addr.sun_path) { ptr in
            ptr.withMemoryRebound(to: CChar.self, capacity: 104) { _ = strcpy($0, path) }
        }
        let size = socklen_t(MemoryLayout<sockaddr_un>.size)
        let connected = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(fd, $0, size) }
        }
        guard connected == 0 else { throw NSError(domain: "后台服务未运行，请安装 BLEWright.pkg", code: 1) }
        var q = values; q["apiVersion"] = 1
        var data = try JSONSerialization.data(withJSONObject: q); data.append(10)
        try data.withUnsafeBytes { bytes in
            var sent = 0
            while sent < bytes.count {
                let n = Darwin.write(fd, bytes.baseAddress!.advanced(by: sent), bytes.count - sent)
                guard n > 0 else { throw NSError(domain: "发送请求失败", code: 1) }
                sent += n
            }
        }
        var output = Data(); var bytes = [UInt8](repeating: 0, count: 8192)
        while output.count < 200_000 {
            let n = Darwin.read(fd, &bytes, bytes.count)
            guard n > 0 else { throw NSError(domain: "后台服务响应超时", code: 1) }
            output.append(contentsOf: bytes.prefix(n))
            if output.last == 10 { break }
        }
        let result = try JSONSerialization.jsonObject(with: output) as? [String: Any] ?? [:]
        guard result["ok"] as? Bool == true else { throw NSError(domain: result["error"] as? String ?? "操作失败", code: 1) }
        return result["result"] as? [String: Any] ?? [:]
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let client = ControlClient()
    var window: NSWindow!
    var statusItem: NSStatusItem!
    let stateLabel = NSTextField(labelWithString: "正在连接后台服务…")
    let detailLabel = NSTextField(wrappingLabelWithString: "")
    let errorLabel = NSTextField(wrappingLabelWithString: "")
    let device = NSPopUpButton()
    let mode = NSPopUpButton()
    let logs = NSTextView()
    let logEmptyLabel = NSTextField(labelWithString: "服务启动后，运行记录将显示在这里")
    let sidebarStatus = NSTextField(labelWithString: "正在连接")
    var actionButtons: [NSButton] = []
    var devices: [[String: Any]] = []
    var last: [String: Any] = [:]
    var modeInitialized = false
    var requestPending = false
    var polling = false
    var timer: Timer?
    var menuStatus = NSMenuItem(title: "正在连接…", action: nil, keyEquivalent: "")
    var menuUSB = NSMenuItem(title: "USB：未知", action: nil, keyEquivalent: "")
    var menuVersion = NSMenuItem(title: "RPC v1", action: nil, keyEquivalent: "")
    var menuStart: NSMenuItem!
    var menuStop: NSMenuItem!
    var menuRestart: NSMenuItem!
    #if canImport(Sparkle)
    let updaterController = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: nil, userDriverDelegate: nil)
    var updateObservation: NSKeyValueObservation?
    var updateMenuItems: [NSMenuItem] = []

    func addUpdateItem(to menu: NSMenu) {
        let item = NSMenuItem(title: "检查更新…", action: #selector(SPUStandardUpdaterController.checkForUpdates(_:)), keyEquivalent: "")
        item.target = updaterController
        item.isEnabled = updaterController.updater.canCheckForUpdates
        updateMenuItems.append(item); menu.addItem(item)
    }
    #endif

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let existing = NSRunningApplication.runningApplications(withBundleIdentifier: "dev.blewright.mac").first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
            existing.activate(options: [.activateAllWindows]); NSApp.terminate(nil); return
        }
        NSApp.setActivationPolicy(.accessory)
        makeWindow(); makeMenu(); makeMainMenu(); refresh()
        #if canImport(Sparkle)
        updateObservation = updaterController.updater.observe(\.canCheckForUpdates, options: [.initial, .new]) { [weak self] updater, _ in
            self?.updateMenuItems.forEach { $0.isEnabled = updater.canCheckForUpdates }
        }
        updaterController.startUpdater()
        #endif
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
        if !CommandLine.arguments.contains("--background") { showWindow() }
    }
    func label(_ text: String, size: CGFloat = 13, weight: NSFont.Weight = .regular) -> NSTextField {
        let v = NSTextField(labelWithString: text); v.font = .systemFont(ofSize: size, weight: weight); return v
    }
    func button(_ title: String, _ action: Selector) -> NSButton {
        let b = NSButton(title: title, target: self, action: action); b.bezelStyle = .rounded
        actionButtons.append(b); return b
    }
    func makeWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.delegate = self; window.title = "BLEWright"; window.minSize = NSSize(width: 1000, height: 780)
        window.isReleasedWhenClosed = false; window.titlebarAppearsTransparent = true; window.titleVisibility = .hidden; window.center()
        let root = WorkbenchPanel(WorkbenchStyle.background, radius: 0); window.contentView = root
        let sidebar = WorkbenchPanel(WorkbenchStyle.ink, radius: 0)
        root.addSubview(sidebar); sidebar.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([sidebar.leadingAnchor.constraint(equalTo: root.leadingAnchor), sidebar.topAnchor.constraint(equalTo: root.topAnchor), sidebar.bottomAnchor.constraint(equalTo: root.bottomAnchor), sidebar.widthAnchor.constraint(equalToConstant: 204)])
        let brand = NSImageView(); brand.image = Bundle.main.image(forResource: "AppIcon") ?? NSImage(systemSymbolName: "antenna.radiowaves.left.and.right", accessibilityDescription: "BLEWright")
        brand.imageScaling = .scaleProportionallyUpOrDown; brand.contentTintColor = WorkbenchStyle.mint
        brand.widthAnchor.constraint(equalToConstant: 64).isActive = true; brand.heightAnchor.constraint(equalToConstant: 64).isActive = true
        let brandStack = WorkbenchStyle.stack([brand, WorkbenchStyle.text("BLEWright", size: 23, weight: .bold, color: .white), WorkbenchStyle.text("蓝牙开发工作站", size: 12, color: .white.withAlphaComponent(0.55))], vertical: true, spacing: 10)
        sidebar.addSubview(brandStack); brandStack.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([brandStack.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 24), brandStack.topAnchor.constraint(equalTo: sidebar.topAnchor, constant: 64)])
        let selected = WorkbenchPanel(NSColor.white.withAlphaComponent(0.08), radius: 10)
        let selectedRow = WorkbenchStyle.stack([WorkbenchStyle.symbol("square.grid.2x2.fill", size: 16, color: WorkbenchStyle.mint), WorkbenchStyle.text("工作台", size: 13, weight: .semibold, color: .white)], spacing: 12)
        WorkbenchStyle.pin(selectedRow, in: selected, inset: 14)
        sidebar.addSubview(selected); selected.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([selected.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 14), selected.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -14), selected.topAnchor.constraint(equalTo: brandStack.bottomAnchor, constant: 38)])
        let sideFoot = WorkbenchStyle.stack([WorkbenchStyle.symbol("dot.radiowaves.left.and.right", size: 22, color: WorkbenchStyle.mint), sidebarStatus, WorkbenchStyle.text("关闭窗口，服务继续运行", size: 11, color: .white.withAlphaComponent(0.45)), WorkbenchStyle.text("LOCAL WORKSPACE  /  RPC v1", size: 9, weight: .medium, color: .white.withAlphaComponent(0.3))], vertical: true, spacing: 12)
        sidebarStatus.font = .systemFont(ofSize: 12, weight: .medium); sidebarStatus.textColor = .white.withAlphaComponent(0.8)
        sidebar.addSubview(sideFoot); sideFoot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([sideFoot.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 24), sideFoot.bottomAnchor.constraint(equalTo: sidebar.bottomAnchor, constant: -28)])

        let content = WorkbenchStyle.stack([], vertical: true, spacing: 18)
        root.addSubview(content); content.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([content.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: 28), content.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -28), content.topAnchor.constraint(equalTo: root.topAnchor, constant: 48), content.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -22)])
        func add(_ view: NSView) { content.addArrangedSubview(view); view.widthAnchor.constraint(equalTo: content.widthAnchor).isActive = true }
        let heading = WorkbenchStyle.stack([WorkbenchStyle.text("工作台", size: 27, weight: .bold), WorkbenchStyle.text("连接硬件，让蓝牙调试井然有序。", size: 12, color: .secondaryLabelColor)], vertical: true, spacing: 6)
        add(heading)
        let hero = WorkbenchPanel(WorkbenchStyle.ink)
        stateLabel.font = .systemFont(ofSize: 24, weight: .semibold); stateLabel.textColor = .white
        detailLabel.font = .monospacedSystemFont(ofSize: 11, weight: .regular); detailLabel.textColor = .white.withAlphaComponent(0.65)
        detailLabel.maximumNumberOfLines = 5
        let status = WorkbenchStyle.stack([WorkbenchStyle.text("CONNECTION OVERVIEW", size: 10, weight: .semibold, color: WorkbenchStyle.mint), stateLabel, detailLabel], vertical: true, spacing: 11)
        let artwork = WorkstationArtwork(); artwork.setAccessibilityElement(false)
        let heroRow = WorkbenchStyle.stack([status, artwork], spacing: 12)
        WorkbenchStyle.pin(heroRow, in: hero, inset: 22)
        artwork.widthAnchor.constraint(equalToConstant: 170).isActive = true; artwork.heightAnchor.constraint(equalToConstant: 132).isActive = true
        status.widthAnchor.constraint(equalTo: heroRow.widthAnchor, constant: -182).isActive = true
        add(hero)

        let configuration = WorkbenchPanel()
        let config = WorkbenchStyle.stack([], vertical: true, spacing: 14)
        WorkbenchStyle.pin(config, in: configuration, inset: 20)
        config.addArrangedSubview(WorkbenchStyle.stack([WorkbenchStyle.symbol("slider.horizontal.3", color: WorkbenchStyle.accent), label("设备与服务", size: 15, weight: .semibold)]))
        mode.addItems(withTitles: ["通用 BLE（扫描、连接与读写）", "只读广播（不连接设备）", "受控测试（导入 C6 身份）"])
        device.setAccessibilityLabel("ESP32-S3 开发板"); mode.setAccessibilityLabel("服务模式")
        device.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        mode.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let deviceColumn = WorkbenchStyle.stack([WorkbenchStyle.text("USB 开发板 · ESP32-S3", size: 11, weight: .medium, color: .secondaryLabelColor), device], vertical: true, spacing: 7)
        let modeColumn = WorkbenchStyle.stack([WorkbenchStyle.text("服务模式", size: 11, weight: .medium, color: .secondaryLabelColor), mode], vertical: true, spacing: 7)
        device.widthAnchor.constraint(equalTo: deviceColumn.widthAnchor).isActive = true
        mode.widthAnchor.constraint(equalTo: modeColumn.widthAnchor).isActive = true
        let fields = WorkbenchStyle.stack([deviceColumn, modeColumn], spacing: 16); fields.distribution = .fillEqually
        config.addArrangedSubview(fields); fields.widthAnchor.constraint(equalTo: config.widthAnchor).isActive = true
        let apply = button("应用设置…", #selector(configure)); apply.image = NSImage(systemSymbolName: "checkmark.circle", accessibilityDescription: nil); apply.imagePosition = .imageLeading
        let hint = WorkbenchStyle.text("选择开发板与模式后应用设置", size: 11, color: .secondaryLabelColor)
        let applyRow = WorkbenchStyle.stack([hint, NSView(), apply]); config.addArrangedSubview(applyRow); applyRow.widthAnchor.constraint(equalTo: config.widthAnchor).isActive = true
        add(configuration)
        let startButton = button("启动服务", #selector(start)); startButton.contentTintColor = WorkbenchStyle.accent
        startButton.image = NSImage(systemSymbolName: "play.fill", accessibilityDescription: nil); startButton.imagePosition = .imageLeading
        let stopButton = button("停止服务", #selector(stop)); stopButton.image = NSImage(systemSymbolName: "stop.fill", accessibilityDescription: nil); stopButton.imagePosition = .imageLeading
        let actions = WorkbenchStyle.stack([startButton, stopButton, NSView(), button("重启 S3…", #selector(restart)), button("刷写内置固件…", #selector(flash))], spacing: 10)
        add(actions)
        errorLabel.textColor = .systemRed; errorLabel.font = .systemFont(ofSize: 12); errorLabel.isHidden = true; add(errorLabel)
        let logPanel = WorkbenchPanel()
        let logStack = WorkbenchStyle.stack([], vertical: true, spacing: 12); WorkbenchStyle.pin(logStack, in: logPanel, inset: 18)
        let logHeader = WorkbenchStyle.stack([WorkbenchStyle.symbol("terminal", size: 16), label("运行记录", size: 14, weight: .semibold), NSView(), WorkbenchStyle.text("实时更新", size: 11, color: .secondaryLabelColor)])
        logStack.addArrangedSubview(logHeader); logHeader.widthAnchor.constraint(equalTo: logStack.widthAnchor).isActive = true
        logs.isEditable = false; logs.isSelectable = true; logs.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        logs.textColor = .secondaryLabelColor; logs.backgroundColor = .controlBackgroundColor; logs.textContainerInset = NSSize(width: 4, height: 8)
        let scroll = NSScrollView(); scroll.documentView = logs; scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true; scroll.borderType = .noBorder
        logStack.addArrangedSubview(scroll); scroll.widthAnchor.constraint(equalTo: logStack.widthAnchor).isActive = true; scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 86).isActive = true
        logEmptyLabel.font = .systemFont(ofSize: 12); logEmptyLabel.textColor = .tertiaryLabelColor
        scroll.addSubview(logEmptyLabel); logEmptyLabel.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([logEmptyLabel.centerXAnchor.constraint(equalTo: scroll.centerXAnchor), logEmptyLabel.centerYAnchor.constraint(equalTo: scroll.centerYAnchor)])
        add(logPanel)
        add(WorkbenchStyle.text("USB 状态每秒更新    ·    本地连接    ·    RPC v1", size: 10, color: .tertiaryLabelColor))
    }
    func makeMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "antenna.radiowaves.left.and.right", accessibilityDescription: "BLEWright")
        statusItem.button?.title = " BW"
        let menu = NSMenu(); menu.autoenablesItems = false
        for item in [menuStatus, menuUSB, menuVersion] { item.isEnabled = false; menu.addItem(item) }
        menu.addItem(.separator())
        let open = NSMenuItem(title: "显示 BLEWright", action: #selector(showWindow), keyEquivalent: ""); open.target = self; menu.addItem(open)
        menuStart = NSMenuItem(title: "启动服务", action: #selector(start), keyEquivalent: "")
        menuStop = NSMenuItem(title: "停止服务", action: #selector(stop), keyEquivalent: "")
        menuRestart = NSMenuItem(title: "重启 S3…", action: #selector(restart), keyEquivalent: "")
        for item in [menuStart!, menuStop!, menuRestart!] { item.target = self; menu.addItem(item) }
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "退出界面（服务继续运行）", action: #selector(quitUI), keyEquivalent: "q"); quit.target = self; menu.addItem(quit)
        #if canImport(Sparkle)
        addUpdateItem(to: menu)
        #endif
        statusItem.menu = menu
    }
    func makeMainMenu() {
        let bar = NSMenu()
        let appItem = NSMenuItem(); let appMenu = NSMenu(title: "BLEWright")
        let quit = NSMenuItem(title: "退出 BLEWright 界面", action: #selector(quitUI), keyEquivalent: "q"); quit.target = self
        #if canImport(Sparkle)
        addUpdateItem(to: appMenu)
        appMenu.addItem(.separator())
        #endif
        appMenu.addItem(quit); appItem.submenu = appMenu; bar.addItem(appItem)
        let editItem = NSMenuItem(); let edit = NSMenu(title: "编辑")
        edit.addItem(NSMenuItem(title: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c"))
        edit.addItem(NSMenuItem(title: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"))
        editItem.submenu = edit; bar.addItem(editItem)
        let windowItem = NSMenuItem(); let windowMenu = NSMenu(title: "窗口")
        let show = NSMenuItem(title: "显示主窗口", action: #selector(showWindow), keyEquivalent: "0"); show.target = self
        windowMenu.addItem(show); windowItem.submenu = windowMenu; bar.addItem(windowItem)
        NSApp.mainMenu = bar
    }
    @objc func showWindow() { NSApp.setActivationPolicy(.regular); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    func windowWillClose(_ notification: Notification) { NSApp.setActivationPolicy(.accessory) }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { showWindow(); return true }
    @objc func quitUI() { NSApp.terminate(nil) }
    func refresh() {
        guard !polling else { return }; polling = true
        DispatchQueue.global(qos: .utility).async {
            let result = Result { try self.client.request(["action": "status"]) }
            DispatchQueue.main.async {
                self.polling = false
                guard !self.requestPending else { return }
                switch result {
                case .success(let s): self.render(s)
                case .failure(let e):
                    self.stateLabel.stringValue = "后台服务未连接"
                    self.stateLabel.textColor = .white
                    self.sidebarStatus.stringValue = "后台服务未连接"
                    self.errorLabel.stringValue = e.localizedDescription
                    self.errorLabel.isHidden = false
                    self.menuStatus.title = "后台服务未连接"
                    self.menuUSB.title = "USB：状态不可用"
                    self.menuStart.isEnabled = false; self.menuStop.isEnabled = false; self.menuRestart.isEnabled = false
                    for b in self.actionButtons { b.isEnabled = false }
                }
            }
        }
    }
    func render(_ s: [String: Any]) {
        last = s
        let names = ["waiting":"等待 ESP32-S3 接入", "starting":"正在握手…", "ready":"服务已就绪", "stopped":"服务已停止", "error":"服务异常", "flashing":"正在刷写固件…", "restarting":"正在重启 S3…"]
        let state = s["state"] as? String ?? "error"
        stateLabel.stringValue = names[state] ?? state
        stateLabel.textColor = state == "ready" ? WorkbenchStyle.mint : .white
        sidebarStatus.stringValue = stateLabel.stringValue
        let config = s["config"] as? [String: Any] ?? [:]
        let serial = config["serial"] as? String ?? ""
        let backend = config["mode"] as? String ?? "esp32"
        let version = s["serverVersion"] as? String ?? "?"
        let firmware = s["firmware"] as? String ?? "尚未握手"
        detailLabel.stringValue = "服务 \(version)  ·  RPC v1  ·  \(s["rpcAddress"] ?? "")\n固件：\(firmware)  ·  当前模式：\(backend)\n绑定 USB：\(serial.isEmpty ? "请先选择开发板并应用设置" : serial)"
        errorLabel.stringValue = s["error"] as? String ?? ""
        errorLabel.isHidden = errorLabel.stringValue.isEmpty
        let found = s["devices"] as? [[String: Any]] ?? []
        let oldChoice = device.selectedItem?.representedObject as? String ?? serial
        if !NSArray(array: found).isEqual(to: devices) {
            devices = found; device.removeAllItems()
            for d in found {
                device.addItem(withTitle: "\(d["serial"] ?? "")  ·  \(d["path"] ?? "")")
                device.lastItem?.representedObject = d["serial"]
            }
            if let item = device.itemArray.first(where: { $0.representedObject as? String == oldChoice }) { device.select(item) }
        }
        if !modeInitialized { mode.selectItem(at: backend == "esp32-controlled" ? 2 : backend == "esp32-scan" ? 1 : 0); modeInitialized = true }
        let busy = (s["busy"] as? Bool ?? false) || requestPending
        let enabled = config["enabled"] as? Bool ?? (state != "stopped")
        let canStart = !busy && !enabled
        let canStop = !busy && enabled
        for b in actionButtons { b.isEnabled = !busy }
        device.isEnabled = !busy; mode.isEnabled = !busy
        for b in actionButtons {
            if b.action == #selector(start) { b.isEnabled = canStart }
            if b.action == #selector(stop) { b.isEnabled = canStop }
        }
        menuStart.isEnabled = canStart; menuStop.isEnabled = canStop
        menuRestart.isEnabled = !busy && found.contains(where: { $0["serial"] as? String == serial })
        menuStatus.title = stateLabel.stringValue
        menuUSB.title = "USB：" + (found.contains(where: { $0["serial"] as? String == serial }) ? "已连接" : "未连接")
        menuVersion.title = "BLEWright \(version) · RPC v1"
        statusItem.button?.toolTip = stateLabel.stringValue
        statusItem.button?.image = NSImage(systemSymbolName: state == "ready" ? "antenna.radiowaves.left.and.right" : "exclamationmark.circle", accessibilityDescription: stateLabel.stringValue)
        let text = (s["logs"] as? [String] ?? []).joined(separator: "\n")
        logEmptyLabel.isHidden = !text.isEmpty
        if logs.string != text { logs.string = text; logs.scrollToEndOfDocument(nil) }
    }
    func send(_ q: [String: Any]) {
        guard !requestPending else { return }
        requestPending = true
        menuStart.isEnabled = false; menuStop.isEnabled = false; menuRestart.isEnabled = false
        device.isEnabled = false; mode.isEnabled = false
        for b in actionButtons { b.isEnabled = false }
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try self.client.request(q) }
            DispatchQueue.main.async {
                self.requestPending = false
                if case .failure(let e) = result { self.alert(e.localizedDescription) }
                self.refresh()
            }
        }
    }
    func alert(_ text: String) { let a = NSAlert(); a.messageText = text; a.runModal() }
    func confirm(_ title: String, _ detail: String) -> Bool {
        let a = NSAlert(); a.messageText = title; a.informativeText = detail
        a.addButton(withTitle: "继续"); a.addButton(withTitle: "取消"); return a.runModal() == .alertFirstButtonReturn
    }
    @objc func configure() {
        guard let serial = device.selectedItem?.representedObject as? String else { alert("请先连接并选择 ESP32-S3"); return }
        var q: [String: Any] = ["action":"configure", "serial":serial, "mode":["esp32", "esp32-scan", "esp32-controlled"][mode.indexOfSelectedItem]]
        if mode.indexOfSelectedItem == 2 {
            let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]; panel.canChooseDirectories = false
            panel.message = "选择从受控 C6 USB 读取的身份 JSON"
            guard panel.runModal() == .OK, let url = panel.url else { return }
            do { q["allow"] = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) }
            catch { alert("无法读取身份文件"); return }
        }
        guard confirm("应用开发板和服务模式？", "将关闭当前 RPC 会话，并在所选开发板上启动服务。") else { return }
        send(q)
    }
    @objc func start() { send(["action":"start"]) }
    @objc func stop() { send(["action":"stop"]) }
    @objc func restart() {
        if confirm("重启所选 ESP32-S3？", "当前蓝牙会话将关闭。USB 重新接入后恢复服务，不自动重放操作。") { send(["action":"restart"]) }
    }
    func selectedFlashRequest() -> [String: Any]? {
        guard let serial = device.selectedItem?.representedObject as? String, !serial.isEmpty else { return nil }
        return ["action":"flash", "serial":serial]
    }
    @objc func flash() {
        guard let request = selectedFlashRequest(), let serial = request["serial"] as? String else {
            alert("请先连接并选择要刷写的 ESP32-S3"); return
        }
        if confirm("刷写内置 BLEWright 固件？", "目标开发板：\(serial)\n仅适用于 ESP32-S3。将覆盖引导程序、分区表和应用，停止现有会话。刷写不更改服务绑定，使用新板运行服务仍需应用设置。请勿拔掉 USB；不擦除整片 Flash 或修改 eFuse。") { send(request) }
    }
}
let delegate = AppDelegate()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
