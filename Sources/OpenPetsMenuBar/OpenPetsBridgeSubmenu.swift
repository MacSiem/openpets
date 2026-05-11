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

// Parsed `openpets-bridge config show` output. Mirrors the Python `export_json`.
struct BridgeState {
    var mode: String              // "single" | "multi"
    var sources: [SourceState]

    struct SourceState {
        var id: String
        var label: String
        var icon: String
        var enabled: Bool
        var petDir: String?       // from extra.pet_dir or multi_pet.pet
    }
}

// Pet pack discovered on disk — for the per-source pet picker.
struct BridgePetPack {
    var displayName: String
    var path: String              // absolute path to pet pack directory
}

@MainActor
final class OpenPetsBridgeSubmenu: NSObject {
    static let shared = OpenPetsBridgeSubmenu()

    private let label = "openpets-bridge"
    private let launchdLabel = "sh.openpets.bridge"
    private var refreshTimer: Timer?

    // Cached state — refreshed on each refreshNow() call.
    private var state: BridgeState?
    private var pets: [BridgePetPack] = []

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
    // The submenu is a NSMenu delegate target — we rebuild its contents
    // on `menuNeedsUpdate` so toggles always reflect the latest config.toml.
    func makeSubmenuItem() -> NSMenuItem {
        let parent = NSMenuItem(title: "Bridge", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Bridge")
        sub.autoenablesItems = false
        sub.delegate = self
        rebuildSubmenu(sub)   // initial contents
        parent.submenu = sub
        refreshNow()
        ensureTimer()
        return parent
    }

    private weak var submenuRef: NSMenu?

    private func rebuildSubmenu(_ sub: NSMenu) {
        submenuRef = sub
        sub.removeAllItems()
        let installed = (bridgeBinaryPath() != nil)

        sub.addItem(statusItem)
        sub.addItem(.separator())
        sub.addItem(startStopItem)
        sub.addItem(restartItem)

        if installed {
            sub.addItem(.separator())
            sub.addItem(makeModeItem())
            sub.addItem(makeSourcesItem())
            if state?.mode == "multi" {
                sub.addItem(makePetsItem())
            }
        }

        sub.addItem(.separator())
        sub.addItem(openConfigItem)
        sub.addItem(openLogItem)
        sub.addItem(listPetsItem)
        sub.addItem(.separator())
        sub.addItem(clearDoneItem)
        sub.addItem(clearAllItem)

        if !installed {
            sub.addItem(.separator())
            sub.addItem(installItem)
        }
    }

    // MARK: - Mode submenu (Single | Multi)

    private func makeModeItem() -> NSMenuItem {
        let parent = NSMenuItem(title: "Mode", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Mode")
        sub.autoenablesItems = false

        let currentMode = state?.mode ?? "single"

        let single = NSMenuItem(title: "Single pet (icon per bubble)",
                                 action: #selector(setModeSingle),
                                 keyEquivalent: "")
        single.target = self
        single.state = (currentMode == "single") ? .on : .off
        sub.addItem(single)

        let multi = NSMenuItem(title: "Multi-pet (one pet per AI)",
                                action: #selector(setModeMulti),
                                keyEquivalent: "")
        multi.target = self
        multi.state = (currentMode == "multi") ? .on : .off
        sub.addItem(multi)

        parent.submenu = sub
        return parent
    }

    @objc private func setModeSingle() {
        _ = runBridgeNeeded(args: ["config", "set-mode", "single"])
    }
    @objc private func setModeMulti() {
        _ = runBridgeNeeded(args: ["config", "set-mode", "multi"])
    }

    // MARK: - Sources submenu (per-AI toggles)

    private func makeSourcesItem() -> NSMenuItem {
        let parent = NSMenuItem(title: "Sources", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Sources")
        sub.autoenablesItems = false

        let sources = state?.sources ?? []
        if sources.isEmpty {
            let empty = NSMenuItem(title: "(no sources configured)",
                                    action: nil, keyEquivalent: "")
            empty.isEnabled = false
            sub.addItem(empty)
        } else {
            for src in sources {
                let title = "\(src.icon)  \(src.label)"
                let it = NSMenuItem(title: title,
                                    action: #selector(toggleSource(_:)),
                                    keyEquivalent: "")
                it.target = self
                it.representedObject = src.id
                it.state = src.enabled ? .on : .off
                sub.addItem(it)
            }
        }

        parent.submenu = sub
        return parent
    }

    @objc private func toggleSource(_ sender: NSMenuItem) {
        guard let sid = sender.representedObject as? String else { return }
        _ = runBridgeNeeded(args: ["config", "toggle-source", sid])
    }

    // MARK: - Pets submenu (pet pack picker per source — multi mode only)

    private func makePetsItem() -> NSMenuItem {
        let parent = NSMenuItem(title: "Pet for source", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Pet for source")
        sub.autoenablesItems = false

        let sources = (state?.sources ?? []).filter { $0.enabled }
        if sources.isEmpty {
            let empty = NSMenuItem(title: "(enable a source first)",
                                    action: nil, keyEquivalent: "")
            empty.isEnabled = false
            sub.addItem(empty)
        } else {
            for src in sources {
                sub.addItem(makeSinglePetPickerItem(for: src))
            }
        }

        parent.submenu = sub
        return parent
    }

    private func makeSinglePetPickerItem(for src: BridgeState.SourceState) -> NSMenuItem {
        let parent = NSMenuItem(title: "\(src.icon)  \(src.label)",
                                action: nil, keyEquivalent: "")
        let sub = NSMenu(title: src.label)
        sub.autoenablesItems = false

        if pets.isEmpty {
            let empty = NSMenuItem(title: "(no pet packs installed)",
                                    action: nil, keyEquivalent: "")
            empty.isEnabled = false
            sub.addItem(empty)
        } else {
            for pet in pets {
                let it = NSMenuItem(title: pet.displayName,
                                    action: #selector(pickPetForSource(_:)),
                                    keyEquivalent: "")
                it.target = self
                it.representedObject = ["source": src.id, "pet": pet.path]
                if let current = src.petDir, current == pet.path {
                    it.state = .on
                }
                sub.addItem(it)
            }
        }

        parent.submenu = sub
        return parent
    }

    @objc private func pickPetForSource(_ sender: NSMenuItem) {
        guard let dict = sender.representedObject as? [String: String],
              let sid = dict["source"],
              let pet = dict["pet"] else { return }
        _ = runBridgeNeeded(args: ["config", "set-source-pet", sid, pet])
    }

    // MARK: - State refresh from JSON

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

        if installed {
            loadState()
            loadPets()
        }

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

    // MARK: - Bridge command + state load

    /// Run `openpets-bridge <args>` and immediately refresh the cached state
    /// and rebuild the submenu so checkmarks update without the user having
    /// to re-open the menu.
    @discardableResult
    private func runBridgeNeeded(args: [String]) -> String {
        guard let bin = bridgeBinaryPath() else { return "" }
        let output = runBridge(bin: bin, args: args)
        refreshNow()
        if let sub = submenuRef {
            rebuildSubmenu(sub)
        }
        return output
    }

    /// Call `openpets-bridge config show` and parse the JSON into BridgeState.
    private func loadState() {
        guard let bin = bridgeBinaryPath() else { state = nil; return }
        let raw = runBridge(bin: bin, args: ["config", "show"])
        guard let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { state = nil; return }

        let mode = (obj["mode"] as? String) ?? "single"
        var sources: [BridgeState.SourceState] = []
        if let srcDict = obj["sources"] as? [String: [String: Any]] {
            for (sid, raw) in srcDict {
                let enabled = (raw["enabled"] as? Bool) ?? false
                let label = (raw["label"] as? String) ?? sid
                let icon = (raw["icon"] as? String) ?? "•"
                var petDir: String? = nil
                if let extra = raw["extra"] as? [String: Any] {
                    petDir = extra["pet_dir"] as? String ?? extra["pet"] as? String
                }
                sources.append(.init(id: sid, label: label, icon: icon,
                                     enabled: enabled, petDir: petDir))
            }
        }
        // Stable ordering: enabled first, then alphabetical by label
        sources.sort { (a, b) -> Bool in
            if a.enabled != b.enabled { return a.enabled }
            return a.label < b.label
        }
        state = BridgeState(mode: mode, sources: sources)
    }

    /// Call `openpets-bridge list-pets` and parse the plain-text output
    /// into a list of pet packs for the picker submenu.
    private func loadPets() {
        guard let bin = bridgeBinaryPath() else { pets = []; return }
        let raw = runBridge(bin: bin, args: ["list-pets"])
        var packs: [BridgePetPack] = []
        var pendingName: String? = nil
        // Format from cmd_list_pets:
        //   "  ✓ Mandalorian  [mandalorian]"
        //   "      /Users/maciej/Library/Application Support/OpenPets/Pets/mandalorian"
        for rawLine in raw.split(separator: "\n", omittingEmptySubsequences: false) {
            let line = String(rawLine)
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("✓ ") {
                // strip leading "✓ " and trailing "  [id]"
                var name = String(trimmed.dropFirst(2))
                if let bracket = name.range(of: "  [") {
                    name = String(name[..<bracket.lowerBound])
                }
                pendingName = name.trimmingCharacters(in: .whitespaces)
            } else if let n = pendingName,
                      trimmed.hasPrefix("/") {
                packs.append(BridgePetPack(displayName: n, path: trimmed))
                pendingName = nil
            }
        }
        pets = packs
    }
}

// MARK: - NSMenuDelegate (live rebuild on each open)

extension OpenPetsBridgeSubmenu: NSMenuDelegate {
    nonisolated func menuNeedsUpdate(_ menu: NSMenu) {
        // menuNeedsUpdate is called on the main thread by AppKit anyway —
        // just dispatch to MainActor without recapturing `menu` across the
        // isolation boundary (we reach it through submenuRef instead).
        Task { @MainActor in
            self.refreshNow()
            if let sub = self.submenuRef {
                self.rebuildSubmenu(sub)
            }
        }
    }
}
