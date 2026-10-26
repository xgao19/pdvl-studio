import AppKit

final class Launcher: NSObject, NSApplicationDelegate {
    let resources = Bundle.main.resourceURL!
    let directory = URL(fileURLWithPath: ProcessInfo.processInfo.environment["PDVL_HOME"] ??
        NSHomeDirectory() + "/Library/Application Support/PDVL Studio", isDirectory: true)
    var server: Process?
    var address: URL?
    var stopping = false
    var buffer = ""

    func environment() -> [String: String] {
        var env: [String: String] = [:]
        for key in ["HOME", "USER", "LOGNAME", "TMPDIR", "LANG"] {
            env[key] = ProcessInfo.processInfo.environment[key]
        }
        env["PATH"] = resources.appendingPathComponent("runtime/bin").path + ":/usr/bin:/bin:/usr/sbin:/sbin"
        env["PDVL_HOME"] = directory.path
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        return env
    }

    func process(_ arguments: [String] = []) -> Process {
        let child = Process()
        child.executableURL = resources.appendingPathComponent("runtime/bin/python3")
        child.arguments = [resources.appendingPathComponent("app/launch.py").path] + arguments
        child.environment = environment()
        child.currentDirectoryURL = resources.appendingPathComponent("app")
        return child
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let item = NSMenuItem()
        menu.addItem(item)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "打开工作台", action: #selector(openWorkbench), keyEquivalent: "o").target = self
        appMenu.addItem(withTitle: "API 设置…", action: #selector(settings), keyEquivalent: ",").target = self
        appMenu.addItem(withTitle: "查看本地数据", action: #selector(openData), keyEquivalent: "").target = self
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "退出 PDVL Studio", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu
        NSApp.mainMenu = menu
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700])
            if !FileManager.default.fileExists(atPath: directory.appendingPathComponent("settings.json").path) {
                guard configure() else { NSApp.terminate(nil); return }
            }
            try start()
        } catch { fail("无法启动 PDVL Studio。请查看本地数据目录中的 desktop.log。") }
    }

    func configure() -> Bool {
        let existing = directory.appendingPathComponent("settings.json")
        let defaults = resources.appendingPathComponent("app/configs/desktop.json")
        guard let data = try? Data(contentsOf: FileManager.default.fileExists(atPath: existing.path) ? existing : defaults),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
            fail("无法读取 API 配置。"); return false
        }
        let alert = NSAlert()
        alert.messageText = "连接你的模型 API"
        alert.informativeText = "默认使用 Ollama 的 DeepSeek Flash。密钥只保存在本机；对话会发送到所填的 API 地址。保存设置会停止当前任务并重启工作台。"
        alert.addButton(withTitle: "保存并启动")
        alert.addButton(withTitle: "取消")
        let key = NSSecureTextField(string: config["api_key"] ?? "")
        key.placeholderString = "粘贴 API key"
        let endpoint = NSTextField(string: config["base_url"] ?? "")
        let model = NSTextField(string: config["model"] ?? "")
        let stack = NSStackView(views: [NSTextField(labelWithString: "API key"), key,
            NSTextField(labelWithString: "API 地址"), endpoint, NSTextField(labelWithString: "模型"), model])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 6
        stack.frame = NSRect(x: 0, y: 0, width: 380, height: 180)
        for field in [key, endpoint, model] { field.widthAnchor.constraint(equalToConstant: 380).isActive = true }
        alert.accessoryView = stack
        alert.window.initialFirstResponder = key
        NSApp.activate(ignoringOtherApps: true)
        guard alert.runModal() == .alertFirstButtonReturn else { return false }
        let input = ["api_key": key.stringValue, "base_url": endpoint.stringValue, "model": model.stringValue]
        let child = process(["--configure"])
        let stdin = Pipe(), stderr = Pipe()
        child.standardInput = stdin
        child.standardOutput = FileHandle.nullDevice
        child.standardError = stderr
        do {
            // Validate and save through the same Python path used by startup.
            stop()
            try child.run()
            stdin.fileHandleForWriting.write(try JSONSerialization.data(withJSONObject: input))
            try stdin.fileHandleForWriting.close()
            child.waitUntilExit()
            if child.terminationStatus != 0 {
                let message = String(data: stderr.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "配置无效。"
                let error = NSAlert(); error.messageText = "无法保存 API 设置"; error.informativeText = message; error.runModal()
                return configure()
            }
            return true
        } catch { fail("无法保存 API 设置。"); return false }
    }

    func start() throws {
        stopping = false
        buffer = ""
        let child = process(), output = Pipe()
        let log = directory.appendingPathComponent("desktop.log")
        if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        let handle = try FileHandle(forWritingTo: log)
        try handle.seekToEnd()
        child.standardError = handle
        child.standardOutput = output
        output.fileHandleForReading.readabilityHandler = { [weak self] pipe in
            let bytes = pipe.availableData
            if bytes.isEmpty { pipe.readabilityHandler = nil; return }
            guard let part = String(data: bytes, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.buffer += part
                while let end = self.buffer.firstIndex(of: "\n") {
                    let line = String(self.buffer[..<end]); self.buffer.removeSubrange(...end)
                    if line.hasPrefix("PDVL_READY "), let url = URL(string: String(line.dropFirst(11))) {
                        self.address = url; self.openWorkbench()
                    }
                }
            }
        }
        child.terminationHandler = { [weak self] task in
            DispatchQueue.main.async {
                guard let self = self, self.server === task, !self.stopping else { return }
                if task.terminationStatus != 0 { self.fail("工作台已停止。请查看本地数据目录中的 desktop.log。") }
            }
        }
        server = child
        try child.run()
    }

    func stop() {
        stopping = true
        if let task = server, task.isRunning { task.terminate(); task.waitUntilExit() }
        server = nil
        address = nil
    }

    @objc func openWorkbench() { if let url = address { NSWorkspace.shared.open(url) } }
    @objc func openData() { NSWorkspace.shared.open(directory) }
    @objc func settings() { if configure() || server == nil { do { try start() } catch { fail("无法启动工作台。") } } }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { openWorkbench(); return false }
    func applicationWillTerminate(_ notification: Notification) { stop() }
    func fail(_ message: String) { let alert = NSAlert(); alert.messageText = message; alert.runModal(); NSApp.terminate(nil) }
}

let application = NSApplication.shared
let launcher = Launcher()
application.delegate = launcher
application.setActivationPolicy(.regular)
application.run()
