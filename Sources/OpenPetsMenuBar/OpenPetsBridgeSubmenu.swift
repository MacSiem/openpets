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
        var muted: Bool
        var petDir: String?       // from extra.pet_dir or multi_pet.pet
        var installed: Bool
        var watchPath: String?
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

    private let launchdLabel = "sh.openpets.bridge"

    // Background refresh loop. Replaces the previous `Timer.scheduledTimer`
    // per project Agents.md ("Prefer async/await, Task, ContinuousClock…").
    private var refreshTask: Task<Void, Never>?

    // Cached state — refreshed on each refreshNow() call. The submenu's
    // NSMenuItems are NOT cached on `self`: they're created fresh inside
    // `rebuildSubmenu` so each menu (status menu, pet context menu) owns
    // its own item instances. AppKit rejects the same NSMenuItem being
    // added to two NSMenus simultaneously, which previously crashed the
    // menubar app when `makeSubmenuItem()` was called for both menus.
    private var state: BridgeState?
    private var pets: [BridgePetPack] = []
    private var bridgeInstalled: Bool = false
    private var bridgeRunning: Bool = false

    // Weak references to every Bridge submenu currently attached to a parent
    // menu. `refreshNow` walks this set and rebuilds each one in place; AppKit
    // automatically releases dead entries when their owning NSMenu drops.
    private let attachedMenus: NSHashTable<NSMenu> = .weakObjects()

    // Build the submenu item that gets attached to a parent menu.
    // The submenu is a NSMenu delegate target — we rebuild its contents
    // on `menuNeedsUpdate` so toggles always reflect the latest config.toml.
    func makeSubmenuItem() -> NSMenuItem {
        let parent = NSMenuItem(title: "Bridge", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Bridge")
        sub.autoenablesItems = false
        sub.delegate = self
        attachedMenus.add(sub)
        rebuildSubmenu(sub)   // initial contents
        parent.submenu = sub
        refreshNow()
        ensureRefreshLoop()
        return parent
    }

    private func rebuildSubmenu(_ sub: NSMenu) {
        sub.removeAllItems()

        // --- Status row ---
        let statusItem = NSMenuItem(title: statusTitle(), action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        sub.addItem(statusItem)
        sub.addItem(.separator())

        // --- Start/Stop/Restart ---
        let startStopItem = NSMenuItem(
            title: bridgeRunning ? "Stop Bridge" : "Start Bridge",
            action: #selector(toggleBridge),
            keyEquivalent: ""
        )
        startStopItem.target = self
        startStopItem.isEnabled = bridgeInstalled
        sub.addItem(startStopItem)

        let restartItem = NSMenuItem(title: "Restart Bridge",
                                     action: #selector(restartBridge),
                                     keyEquivalent: "")
        restartItem.target = self
        restartItem.isEnabled = bridgeInstalled
        sub.addItem(restartItem)

        if bridgeInstalled {
            sub.addItem(.separator())
            sub.addItem(makeModeItem())
            sub.addItem(makeSourcesItem())

            let manageCliItem = NSMenuItem(title: "Manage CLI sources…",
                                           action: #selector(manageCliSources),
                                           keyEquivalent: "")
            manageCliItem.target = self
            sub.addItem(manageCliItem)

            if state?.mode == "multi" {
                sub.addItem(makePetsItem())
            }
        }

        sub.addItem(.separator())

        let openConfigItem = NSMenuItem(title: "Open Bridge Config",
                                        action: #selector(openConfig),
                                        keyEquivalent: "")
        openConfigItem.target = self
        openConfigItem.isEnabled = bridgeInstalled
        sub.addItem(openConfigItem)

        let openLogItem = NSMenuItem(title: "Open Bridge Log",
                                     action: #selector(openLog),
                                     keyEquivalent: "")
        openLogItem.target = self
        openLogItem.isEnabled = bridgeInstalled
        sub.addItem(openLogItem)

        let listPetsItem = NSMenuItem(title: "List Installed Pet Packs",
                                      action: #selector(listPets),
                                      keyEquivalent: "")
        listPetsItem.target = self
        listPetsItem.isEnabled = bridgeInstalled
        sub.addItem(listPetsItem)

        sub.addItem(.separator())

        let clearDoneItem = NSMenuItem(title: "Clear Done Bubbles",
                                       action: #selector(clearDoneBubbles),
                                       keyEquivalent: "")
        clearDoneItem.target = self
        clearDoneItem.isEnabled = bridgeInstalled
        sub.addItem(clearDoneItem)

        let clearAllItem = NSMenuItem(title: "Clear ALL Bubbles",
                                      action: #selector(clearAllBubbles),
                                      keyEquivalent: "")
        clearAllItem.target = self
        clearAllItem.isEnabled = bridgeInstalled
        sub.addItem(clearAllItem)

        if !bridgeInstalled {
            sub.addItem(.separator())
            let installItem = NSMenuItem(title: "Install openpets-bridge…",
                                         action: #selector(showInstallInstructions),
                                         keyEquivalent: "")
            installItem.target = self
            sub.addItem(installItem)
        }
    }

    private func statusTitle() -> String {
        if !bridgeInstalled { return "Bridge: not installed" }
        return bridgeRunning ? "Bridge: running" : "Bridge: stopped"
    }

    private func rebuildAllAttachedMenus() {
        for menu in attachedMenus.allObjects {
            rebuildSubmenu(menu)
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
                sub.addItem(makeSourceControlsItem(for: src))
            }
        }

        parent.submenu = sub
        return parent
    }

    private func makeSourceControlsItem(for src: BridgeState.SourceState) -> NSMenuItem {
        let parent = NSMenuItem(title: "\(src.icon)  \(src.label)",
                                action: nil,
                                keyEquivalent: "")
        let sub = NSMenu(title: src.label)
        sub.autoenablesItems = false

        let enabled = NSMenuItem(title: "Enabled",
                                 action: #selector(toggleSource(_:)),
                                 keyEquivalent: "")
        enabled.target = self
        enabled.representedObject = ["source": src.id, "enabled": src.enabled] as [String: Any]
        enabled.state = src.enabled ? .on : .off
        sub.addItem(enabled)

        let muted = NSMenuItem(title: "Mute (hide sprite, keep daemon listening)",
                               action: #selector(toggleSourceMute(_:)),
                               keyEquivalent: "")
        muted.target = self
        muted.representedObject = ["source": src.id, "muted": !src.muted] as [String: Any]
        muted.state = src.muted ? .on : .off
        sub.addItem(muted)

        parent.submenu = sub
        return parent
    }

    @objc private func toggleSource(_ sender: NSMenuItem) {
        guard let dict = sender.representedObject as? [String: Any],
              let sid = dict["source"] as? String,
              let enabled = dict["enabled"] as? Bool else { return }
        if !enabled {
            _ = runBridgeNeeded(args: ["config", "add-source-preset", sid])
        }
        _ = runBridgeNeeded(args: ["config", "toggle-source", sid])
    }

    @objc private func toggleSourceMute(_ sender: NSMenuItem) {
        guard let dict = sender.representedObject as? [String: Any],
              let sid = dict["source"] as? String,
              let muted = dict["muted"] as? Bool else { return }
        _ = runBridgeNeeded(args: ["config", "set-mute", sid, muted ? "on" : "off"])
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

    // MARK: - State refresh

    private func ensureRefreshLoop() {
        if refreshTask != nil { return }
        refreshTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard let self else { return }
                self.refreshNow()
                self.rebuildAllAttachedMenus()
            }
        }
    }

    private func refreshNow() {
        bridgeInstalled = (BridgeBinaryLocator.find() != nil)
        bridgeRunning = bridgeIsRunning()

        if bridgeInstalled {
            loadState()
            loadPets()
        } else {
            state = nil
            pets = []
        }
    }

    // MARK: - Bridge detection

    private func bridgeIsRunning() -> Bool {
        // Prefer `launchctl print` — it returns 0 iff the agent is bootstrapped,
        // and its output contains `state = running` when the process is alive.
        // Falls back to `launchctl list` parsing for older macOS.
        let label = "gui/\(getuid())/\(launchdLabel)"
        let task = Process()
        task.launchPath = "/bin/launchctl"
        task.arguments = ["print", label]
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
        // `launchctl print` returns blocks like:
        //   state = running
        // or `state = not running` when stopped but bootstrapped.
        for line in txt.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("state =") {
                return trimmed.contains("running") && !trimmed.contains("not running")
            }
        }
        return false
    }

    // MARK: - Actions

    @objc private func toggleBridge() {
        if bridgeRunning {
            _ = runLaunchctl(["bootout", "gui/\(getuid())/\(launchdLabel)"])
        } else {
            let plist = (NSHomeDirectory() as NSString)
                .appendingPathComponent("Library/LaunchAgents/\(launchdLabel).plist")
            if FileManager.default.fileExists(atPath: plist) {
                _ = runLaunchctl(["bootstrap", "gui/\(getuid())", plist])
            } else if let bin = BridgeBinaryLocator.find() {
                _ = runBridge(bin: bin, args: ["install"])
            }
        }
        refreshNow()
        rebuildAllAttachedMenus()
    }

    @objc private func restartBridge() {
        _ = runLaunchctl(["bootout", "gui/\(getuid())/\(launchdLabel)"])
        let plist = (NSHomeDirectory() as NSString)
            .appendingPathComponent("Library/LaunchAgents/\(launchdLabel).plist")
        if FileManager.default.fileExists(atPath: plist) {
            _ = runLaunchctl(["bootstrap", "gui/\(getuid())", plist])
        }
        refreshNow()
        rebuildAllAttachedMenus()
    }

    @objc private func openConfig() {
        let cfg = (NSHomeDirectory() as NSString)
            .appendingPathComponent(".config/openpets-bridge")
        try? FileManager.default.createDirectory(atPath: cfg,
                                                 withIntermediateDirectories: true)
        NSWorkspace.shared.open(URL(fileURLWithPath: cfg))
    }

    @objc private func openLog() {
        // Prefer the canonical macOS log location, then the bridge's legacy ones.
        let candidates = [
            (NSHomeDirectory() as NSString).appendingPathComponent("Library/Logs/openpets-bridge/bridge.log"),
            (NSHomeDirectory() as NSString).appendingPathComponent("ai-stack/openpets-bridge/bridge.log"),
            (NSHomeDirectory() as NSString).appendingPathComponent(".local/state/openpets-bridge/bridge.log"),
        ]
        for path in candidates {
            if FileManager.default.fileExists(atPath: path) {
                NSWorkspace.shared.open(URL(fileURLWithPath: path))
                return
            }
        }
        // Fallback: open the canonical log directory.
        let dir = (NSHomeDirectory() as NSString)
            .appendingPathComponent("Library/Logs/openpets-bridge")
        try? FileManager.default.createDirectory(atPath: dir,
                                                 withIntermediateDirectories: true)
        NSWorkspace.shared.open(URL(fileURLWithPath: dir))
    }

    @objc private func listPets() {
        guard let bin = BridgeBinaryLocator.find() else { return }
        let result = runBridge(bin: bin, args: ["list-pets"])
        showAlert(title: "Installed Pet Packs",
                  body: result.isEmpty ? "(no pet packs found)" : result)
    }

    @objc private func manageCliSources() {
        NotificationCenter.default.post(
            name: Notification.Name("OpenPetsPreferencesSourcesTab"),
            object: nil
        )
    }

    @objc private func clearDoneBubbles() {
        guard let bin = BridgeBinaryLocator.find() else { return }
        _ = runBridge(bin: bin, args: ["clear", "--done-only"])
    }

    @objc private func clearAllBubbles() {
        guard let bin = BridgeBinaryLocator.find() else { return }
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
        // stdout and stderr are captured into separate pipes so JSON parsers
        // (`config show`) never see warning noise mixed in.
        let task = Process()
        task.launchPath = bin
        task.arguments = args
        let outPipe = Pipe()
        let errPipe = Pipe()
        task.standardOutput = outPipe
        task.standardError = errPipe
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return "Could not run \(bin): \(error.localizedDescription)"
        }
        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
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
    /// and rebuild every attached submenu so checkmarks update without the
    /// user having to re-open the menu.
    @discardableResult
    private func runBridgeNeeded(args: [String]) -> String {
        guard let bin = BridgeBinaryLocator.find() else { return "" }
        let output = runBridge(bin: bin, args: args)
        refreshNow()
        rebuildAllAttachedMenus()
        return output
    }

    /// Call `openpets-bridge config show` and parse the JSON into BridgeState.
    private func loadState() {
        guard let bin = BridgeBinaryLocator.find() else { state = nil; return }
        let raw = runBridge(bin: bin, args: ["config", "show"])
        guard let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { state = nil; return }

        let mode = (obj["mode"] as? String) ?? "single"
        var sources: [BridgeState.SourceState] = []
        if let srcDict = obj["sources"] as? [String: [String: Any]] {
            for (sid, raw) in srcDict {
                let enabled = (raw["enabled"] as? Bool) ?? false
                let muted = (raw["muted"] as? Bool) ?? false
                let label = (raw["label"] as? String) ?? sid
                let icon = (raw["icon"] as? String) ?? "•"
                var petDir: String? = nil
                if let extra = raw["extra"] as? [String: Any] {
                    petDir = extra["pet_dir"] as? String ?? extra["pet"] as? String
                }
                let discovery = raw["discovery"] as? [String: Any]
                let installed = (discovery?["installed"] as? Bool) ?? false
                let watchPath = discovery?["watch_path"] as? String
                sources.append(.init(id: sid, label: label, icon: icon,
                                     enabled: enabled, muted: muted, petDir: petDir,
                                     installed: installed, watchPath: watchPath))
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
        guard let bin = BridgeBinaryLocator.find() else { pets = []; return }
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
        // menuNeedsUpdate is called on the main thread by AppKit. We hop to
        // the MainActor without recapturing `menu` across the isolation
        // boundary — the attachedMenus weak set lets us rebuild any visible
        // submenu safely.
        Task { @MainActor in
            self.refreshNow()
            self.rebuildAllAttachedMenus()
        }
    }
}

// MARK: - Shared bridge-binary locator

/// Finds the `openpets-bridge` executable across the locations where it can
/// reasonably end up (Homebrew prefix, system `/usr/local/bin`, the user's
/// `~/.local/bin` for `pip install --user`, or anywhere on `PATH`).
///
/// Centralized here so OpenPetsBridgeSubmenu, OpenPetsPreferencesWindow, and
/// OpenPetsCLI don't each maintain their own copy of the path list.
@MainActor
enum BridgeBinaryLocator {
    static let knownCandidates: [String] = [
        "/opt/homebrew/bin/openpets-bridge",
        "/usr/local/bin/openpets-bridge",
        (NSHomeDirectory() as NSString).appendingPathComponent(".local/bin/openpets-bridge"),
    ]

    static func find() -> String? {
        for path in knownCandidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }
        // Fallback: ask the shell's PATH via /usr/bin/env. Useful for users
        // whose bridge lives in a venv or conda env on PATH but not in the
        // hard-coded list above.
        let task = Process()
        task.launchPath = "/usr/bin/env"
        task.arguments = ["which", "openpets-bridge"]
        let out = Pipe()
        task.standardOutput = out
        task.standardError = Pipe()
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return nil
        }
        guard task.terminationStatus == 0 else { return nil }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        guard let s = String(data: data, encoding: .utf8) else { return nil }
        let path = s.trimmingCharacters(in: .whitespacesAndNewlines)
        if path.isEmpty { return nil }
        return FileManager.default.isExecutableFile(atPath: path) ? path : nil
    }
}
