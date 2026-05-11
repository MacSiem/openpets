import AppKit
import Foundation

// MARK: - Bridge submenu (extension contributed by the MacSiem fork)
//
// The OpenPets menubar app primarily controls the *current* user's pet host.
// In addition, this fork ships an optional companion daemon —
// `openpets-bridge` — that watches activity logs from multiple AI agents
// (Cowork, Codex CLI, Claude Code CLI) and forwards their per-conversation
// status to OpenPets as threaded notifications.
//
// We expose minimal control of that daemon directly in the OpenPets tray
// menu (and in the right-click menu on the sprite, which uses the same
// builder), so users don't need a second menubar icon.
//
// The bridge is autodetected: if `openpets-bridge` isn't installed or its
// launchd agent isn't loaded, the submenu shows "Not installed" and links
// to the install instructions.

@MainActor
final class OpenPetsBridgeSubmenu: NSObject {
    static let shared = OpenPetsBridgeSubmenu()

    private let label = "openpets-bridge"
    private let launchdLabel = "sh.openpets.bridge"
    private var refreshTimer: Timer?

    // Items we update from the timer
    private lazy var statusItem: NSMenuItem = {
        let i = NSMenuItem(title: "Bridge: …", action: nil, keyEquivalent: "")
        i.isEnabled = false
        return i
    }()
    private lazy var startStopItem: NSMenuItem = {
        let i = NSMenuItem(title: "Start Bridge",
                           action: #selector(toggleBridge),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var restartItem: NSMenuItem = {
        let i = NSMenuItem(title: "Restart Bridge",
                           action: #selector(restartBridge),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var openConfigItem: NSMenuItem = {
        let i = NSMenuItem(title: "Open Bridge Config",
                           action: #selector(openConfig),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var openLogItem: NSMenuItem = {
        let i = NSMenuItem(title: "Open Bridge Log",
                           action: #selector(openLog),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var listPetsItem: NSMenuItem = {
        let i = NSMenuItem(title: "List Installed Pet Packs",
                           action: #selector(listPets),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var clearDoneItem: NSMenuItem = {
        let i = NSMenuItem(title: "Clear Done Bubbles",
                           action: #selector(clearDoneBubbles),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var clearAllItem: NSMenuItem = {
        let i = NSMenuItem(title: "Clear ALL Bubbles",
                           action: #selector(clearAllBubbles),
                           keyEquivalent: "")
        i.target = self
        return i
    }()
    private lazy var installItem: NSMenuItem = {
        let i = NSMenuItem(title: "Install openpets-bridge…",
                           action: #selector(showInstallInstructions),
                           keyEquivalent: "")
        i.target = self
        return i
    }()

    // Build the submenu item that gets attached to a parent menu.
    // We rebuild the submenu structure each time to allow for per-state items.
    func makeSubmenuItem() -> NSMenuItem {
        let parent = NSMenuItem(title: "Bridge", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Bridge")
        sub.autoenablesItems = false

        sub.addItem(statusItem)
        sub.addItem(.separator())
        sub.addItem(startStopItem)
        sub.addItem(restartItem)
        sub.addItem(.separator())
        sub.addItem(openConfigItem)
        sub.addItem(openLogItem)
        sub.addItem(listPetsItem)
        sub.addItem(.separator())
        sub.addItem(clearDoneItem)
        sub.addItem(clearAllItem)
        sub.addItem(.separator())
        sub.addItem(installItem)

        parent.submenu = sub
        refreshNow()
        ensureTimer()
        return parent
    }

    // MARK: - State refresh

    private func ensureTimer() {
        if refreshTimer != nil { return }
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 5.0,
                                            repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refreshNow() }
        }
        refreshTimer?.tolerance = 1.0
    }

    private func refreshNow() {
        let installed = (bridgeBinaryPath() != nil)
        let running = bridgeIsRunning()

        if !installed {
            statusItem.title = "Bridge: not installed"
            startStopItem.title = "Start Bridge"
            startStopItem.isEnabled = false
            restartItem.isEnabled = false
            openConfigItem.isEnabled = false
            openLogItem.isEnabled = false
            listPetsItem.isEnabled = false
            clearDoneItem.isEnabled = false
            clearAllItem.isEnabled = false
            installItem.isHidden = false
            return
        }

        installItem.isHidden = true
        startStopItem.isEnabled = true
        restartItem.isEnabled = true
        openConfigItem.isEnabled = true
        openLogItem.isEnabled = true
        listPetsItem.isEnabled = true
        clearDoneItem.isEnabled = true
        clearAllItem.isEnabled = true

        if running {
            statusItem.title = "Bridge: running"
            startStopItem.title = "Stop Bridge"
        } else {
            statusItem.title = "Bridge: stopped"
            startStopItem.title = "Start Bridge"
        }
    }

    // MARK: - Bridge detection

    private func bridgeBinaryPath() -> String? {
        let candidates = [
            "/opt/homebrew/bin/openpets-bridge",
            "/usr/local/bin/openpets-bridge",
            (NSHomeDirectory() as NSString).appendingPathComponent(".local/bin/openpets-bridge"),
        ]
        for path in candidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }
        return nil
    }

    private func bridgeIsRunning() -> Bool {
        // Ask launchd; an entry with a numeric PID means the agent is running.
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = ["list", launchdLabel]
        let out = Pipe()
        task.standardOutput = out
        task.standardError = Pipe()
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return false
        }
        guard task.terminationStatus == 0 else { return false }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        guard let txt = String(data: data, encoding: .utf8) else { return false }
        // Output lines: "PID" / "LastExitStatus" / "Label". A real PID is non-empty
        // and not "-".
        for line in txt.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("\"PID\"") {
                return !(trimmed.contains("= -") || trimmed.contains("= \"-\""))
            }
        }
        return false
    }

    // MARK: - Actions

    @objc private func toggleBridge() {
        if bridgeIsRunning() {
            _ = runLaunchctl(["bootout", "gui/\(getuid())/\(launchdLabel)"])
        } else {
            let plist = (NSHomeDirectory() as NSString)
                .appendingPathComponent("Library/LaunchAgents/\(launchdLabel).plist")
            if FileManager.default.fileExists(atPath: plist) {
                _ = runLaunchctl(["bootstrap", "gui/\(getuid())", plist])
            } else if let bin = bridgeBinaryPath() {
                _ = runBridge(bin: bin, args: ["install"])
            }
        }
        refreshNow()
    }

    @objc private func restartBridge() {
        _ = runLaunchctl(["bootout", "gui/\(getuid())/\(launchdLabel)"])
        let plist = (NSHomeDirectory() as NSString)
            .appendingPathComponent("Library/LaunchAgents/\(launchdLabel).plist")
        if FileManager.default.fileExists(atPath: plist) {
            _ = runLaunchctl(["bootstrap", "gui/\(getuid())", plist])
        }
        refreshNow()
    }

    @objc private func openConfig() {
        let cfg = (NSHomeDirectory() as NSString)
            .appendingPathComponent(".config/openpets-bridge")
        try? FileManager.default.createDirectory(atPath: cfg,
                                                 withIntermediateDirectories: true)
        NSWorkspace.shared.open(URL(fileURLWithPath: cfg))
    }

    @objc private func openLog() {
        let candidates = [
            (NSHomeDirectory() as NSString).appendingPathComponent("ai-stack/openpets-bridge/bridge.log"),
            (NSHomeDirectory() as NSString).appendingPathComponent(".local/state/openpets-bridge/bridge.log"),
        ]
        for path in candidates {
            if FileManager.default.fileExists(atPath: path) {
                NSWorkspace.shared.open(URL(fileURLWithPath: path))
                return
            }
        }
        // Fallback: open the directory
        let dir = (NSHomeDirectory() as NSString)
            .appendingPathComponent(".local/state/openpets-bridge")
        try? FileManager.default.createDirectory(atPath: dir,
                                                 withIntermediateDirectories: true)
        NSWorkspace.shared.open(URL(fileURLWithPath: dir))
    }

    @objc private func listPets() {
        guard let bin = bridgeBinaryPath() else { return }
        let result = runBridge(bin: bin, args: ["list-pets"])
        showAlert(title: "Installed Pet Packs",
                  body: result.isEmpty ? "(no pet packs found)" : result)
    }

    @objc private func clearDoneBubbles() {
        guard let bin = bridgeBinaryPath() else { return }
        _ = runBridge(bin: bin, args: ["clear", "--done-only"])
    }

    @objc private func clearAllBubbles() {
        guard let bin = bridgeBinaryPath() else { return }
        let alert = NSAlert()
        alert.messageText = "Clear all OpenPets bubbles?"
        alert.informativeText = "This removes every active and done bubble for every AI source."
        alert.addButton(withTitle: "Clear")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn {
            _ = runBridge(bin: bin, args: ["clear", "--all"])
        }
    }

    @objc private func showInstallInstructions() {
        let url = URL(string: "https://github.com/MacSiem/openpets/tree/main/bridge#quick-start")!
        NSWorkspace.shared.open(url)
    }

    // MARK: - Subprocess helpers

    @discardableResult
    private func runLaunchctl(_ args: [String]) -> Int32 {
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = args
        task.standardOutput = Pipe()
        task.standardError = Pipe()
        do {
            try task.run()
            task.waitUntilExit()
            return task.terminationStatus
        } catch {
            return -1
        }
    }

    private func runBridge(bin: String, args: [String]) -> String {
        let task = Process()
        task.launchPath = bin
        task.arguments = args
        let out = Pipe()
        task.standardOutput = out
        task.standardError = out
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return "Could not run \(bin): \(error.localizedDescription)"
        }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }

    private func showAlert(title: String, body: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = body
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
