import AppKit
import Foundation

final class MenuBarController: NSObject, NSApplicationDelegate {
    private var item: NSStatusItem!
    private let menu = NSMenu()
    private var stateItem: NSMenuItem!
    private var detailItem: NSMenuItem!
    private var timer: Timer?
    private var busy = false
    private var checking = false
    private var actions: [NSMenuItem] = []
    private var home: URL {
        if let value = ProcessInfo.processInfo.environment["VAULT_RAG_HOME"] ?? Bundle.main.object(forInfoDictionaryKey: "VaultRagState") as? String {
            return URL(fileURLWithPath: value)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/VaultRag")
    }
    private var repo: URL {
        let adjacent = Bundle.main.bundleURL.deletingLastPathComponent()
        if FileManager.default.fileExists(atPath: adjacent.appendingPathComponent("vault_rag/service_control.py").path) { return adjacent }
        return URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "VaultRagRepository") as? String ?? "")
    }
    private var base: String {
        let data = try? Data(contentsOf: home.appendingPathComponent("config.json"))
        let config = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        return "http://127.0.0.1:\(config?["port"] as? Int ?? 18080)"
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        // The state-specific supervisor lock owns single-instance handling;
        // Finder's shell launcher can briefly share this bundle identifier.
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName: "books.vertical", accessibilityDescription: "本地知识库")
        item.button?.image?.isTemplate = true
        item.button?.title = " ◌"
        item.button?.toolTip = "本地知识库：正在检查服务"
        stateItem = NSMenuItem(title: "正在检查服务…", action: nil, keyEquivalent: "")
        detailItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        menu.addItem(stateItem); menu.addItem(detailItem); menu.addItem(.separator())
        add("打开网页", #selector(openWeb))
        add("刷新状态", #selector(refreshStatus))
        menu.addItem(.separator())
        for (title, selector) in [("启动服务", #selector(startService)), ("停止服务", #selector(stopService)), ("重启服务", #selector(restartService))] { actions.append(add(title, selector)) }
        menu.addItem(.separator())
        add("查看日志文件夹", #selector(openLogs))
        add("退出菜单栏（服务继续运行）", #selector(quit))
        stateItem.isEnabled = false; detailItem.isEnabled = false; menu.autoenablesItems = false
        item.menu = menu
        refreshStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refreshStatus() }
    }
    @discardableResult private func add(_ title: String, _ action: Selector) -> NSMenuItem {
        let entry = NSMenuItem(title: title, action: action, keyEquivalent: ""); entry.target = self; menu.addItem(entry); return entry
    }
    @objc private func refreshStatus() {
        if checking || busy { return }; checking = true
        var request = URLRequest(url: URL(string: base + "/api/status")!); request.timeoutInterval = 3
        if let token = try? String(contentsOf: home.appendingPathComponent("auth-token"), encoding: .utf8) { request.setValue("Bearer " + token.trimmingCharacters(in: .whitespacesAndNewlines), forHTTPHeaderField: "Authorization") }
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let status = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let running = error == nil && (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async {
                guard let self = self else { return }; self.checking = false
                if self.busy { return }
                self.stateItem.title = running ? "服务运行中 · HTTP MCP" : "服务未响应 / 已停止"
                let model = status?["model"] as? [String: Any]; let sync = status?["sync"] as? [String: Any]
                let modelState = model?["loaded"] as? Bool == true ? "模型已加载" : "模型未加载"
                self.detailItem.title = running ? "\(status?["num_files"] as? Int ?? 0) 篇 · \(sync?["state"] as? String ?? "检查中") · \(modelState)" : "点击「启动服务」恢复"
                if let error = status?["last_error"] as? String, !error.isEmpty { self.detailItem.title = "同步错误：" + String(error.prefix(65)) }
                self.item.button?.title = running ? " ●" : " ○"
                self.item.button?.toolTip = self.stateItem.title + "\n" + self.detailItem.title
            }
        }.resume()
    }
    private func control(_ action: String) {
        if busy { return }; busy = true; actions.forEach { $0.isEnabled = false }
        stateItem.title = ["start":"正在启动…", "stop":"正在停止…", "restart":"正在重启…"][action] ?? "处理中…"
        let directory = repo
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let task = Process(); task.executableURL = directory.appendingPathComponent(".venv/bin/python"); task.arguments = ["-m", "vault_rag.cli", "service", action]; task.currentDirectoryURL = directory
            let output = Pipe(); task.standardOutput = output; task.standardError = output
            var failure: String?
            do { try task.run(); let data = output.fileHandleForReading.readDataToEndOfFile(); task.waitUntilExit(); if task.terminationStatus != 0 { failure = String(data: data, encoding: .utf8) ?? "服务操作失败" } }
            catch { failure = error.localizedDescription }
            DispatchQueue.main.async {
                guard let self = self else { return }; self.busy = false; self.actions.forEach { $0.isEnabled = true }
                if let failure = failure { let alert = NSAlert(); alert.messageText = "服务操作失败"; alert.informativeText = failure; alert.runModal() }
                self.refreshStatus()
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.refreshStatus() }
            }
        }
    }
    @objc private func startService() { control("start") }
    @objc private func stopService() { control("stop") }
    @objc private func restartService() { control("restart") }
    @objc private func openWeb() {
        // Reuse the launcher: opens immediately if ready; starts the service otherwise.
        let task = Process(); task.executableURL = URL(fileURLWithPath: "/bin/bash"); task.arguments = [repo.appendingPathComponent("scripts/macos/launch.sh").path, "open"]; task.currentDirectoryURL = repo
        do { try task.run() } catch { let alert = NSAlert(); alert.messageText = "无法打开网页"; alert.informativeText = error.localizedDescription; alert.runModal() }
    }
    @objc private func openLogs() { NSWorkspace.shared.open(home.appendingPathComponent("logs")) }
    @objc private func quit() { timer?.invalidate(); NSApp.terminate(nil) }
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = MenuBarController()
app.delegate = controller
app.run()
