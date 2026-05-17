import AppKit
import Foundation
import OpenPetsKit

// MARK: - CLI-side runtime for `openpets run`
//
// Standalone hosts (multi-pet mode in openpets-bridge spawns one of these per AI)
// previously used `OpenPetsHost.run`, which builds an `OpenPetsHostSession` *without*
// a `contextMenuProvider` — so the right-click context menu on the sprite was empty.
//
// We replicate the small amount of glue `OpenPetsHost.run` does (NSApplication +
// app delegate so termination cleans up the host session) and inject a default
// CLI-side context menu provider.

@MainActor
private final class OpenPetsCLIRuntime {
    static var current: OpenPetsCLIRuntime?
    let delegate: OpenPetsCLIAppDelegate
    let sourceID: String?
    let instanceID: String?

    init(delegate: OpenPetsCLIAppDelegate, sourceID: String?, instanceID: String?) {
        self.delegate = delegate
        self.sourceID = sourceID
        self.instanceID = instanceID
    }
}

@MainActor
private final class OpenPetsCLIAppDelegate: NSObject, NSApplicationDelegate {
    let session: OpenPetsHostSession

    init(session: OpenPetsHostSession) {
        self.session = session
    }

    func applicationWillTerminate(_ notification: Foundation.Notification) {
        session.stop()
    }
}

@MainActor
enum OpenPetsCLIContextMenu {
    /// Append one diagnostic line per right-click into the bridge's log
    /// directory. Lets us prove `contextMenuProvider` is actually wired up
    /// from the spawned host's perspective (QW4 — the "right-click empty
    /// on multi-pet sprite" issue from 2026-05-11).
    private static func logInvocation() {
        let pid = ProcessInfo.processInfo.processIdentifier
        let env = ProcessInfo.processInfo.environment
        let src = env["OPENPETS_BRIDGE_SOURCE_ID"] ?? "(none)"
        let inst = env["OPENPETS_INSTANCE_ID"] ?? "(none)"
        let dir = (NSHomeDirectory() as NSString)
            .appendingPathComponent("Library/Logs/openpets-bridge")
        try? FileManager.default.createDirectory(atPath: dir,
                                                 withIntermediateDirectories: true)
        let path = (dir as NSString).appendingPathComponent("cli-host-debug.log")
        let ts = ISO8601DateFormatter().string(from: Date())
        let line = "\(ts) pid=\(pid) source=\(src) instance=\(inst) contextMenu.make()\n"
        if let data = line.data(using: .utf8) {
            if let h = FileHandle(forWritingAtPath: path) {
                defer { try? h.close() }
                _ = try? h.seekToEnd()
                try? h.write(contentsOf: data)
            } else {
                FileManager.default.createFile(atPath: path, contents: data)
            }
        }
    }

    static func make() -> NSMenu {
        logInvocation()
        // Bridge-spawned hosts run with .accessory activation policy and
        // never become the frontmost app on their own. Without an explicit
        // activate() the popUpContextMenu call inside upstream's
        // PetSpriteView dispatches to a window that isn't key, and AppKit
        // silently dismisses the menu before it's visible — which looks
        // exactly like "context menu does nothing" from the user's POV.
        // Forcing activation here fixes that.
        NSApplication.shared.activate(ignoringOtherApps: true)
        let menu = NSMenu()
        menu.autoenablesItems = false
        let target = OpenPetsCLIContextMenuTarget.shared

        let openApp = NSMenuItem(
            title: "Open OpenPets…",
            action: #selector(OpenPetsCLIContextMenuTarget.openApp),
            keyEquivalent: ""
        )
        openApp.target = target
        menu.addItem(openApp)

        let openConfig = NSMenuItem(
            title: "Open Config Folder",
            action: #selector(OpenPetsCLIContextMenuTarget.openConfig),
            keyEquivalent: ""
        )
        openConfig.target = target
        menu.addItem(openConfig)

        let bridgeStatus = NSMenuItem(
            title: "openpets-bridge: status…",
            action: #selector(OpenPetsCLIContextMenuTarget.bridgeStatus),
            keyEquivalent: ""
        )
        bridgeStatus.target = target
        menu.addItem(bridgeStatus)

        menu.addItem(.separator())

        let display = NSMenuItem(title: "Display", action: nil, keyEquivalent: "")
        display.submenu = makeDisplayMenu(target: target)
        menu.addItem(display)

        let hideTitle = target.isPetHidden ? "Show this pet" : "Hide this pet (until restart)"
        let hidePet = NSMenuItem(
            title: hideTitle,
            action: #selector(OpenPetsCLIContextMenuTarget.togglePetVisibility),
            keyEquivalent: ""
        )
        hidePet.target = target
        menu.addItem(hidePet)

        let switchPet = NSMenuItem(title: "Switch pet pack", action: nil, keyEquivalent: "")
        switchPet.submenu = makePetPackMenu(target: target)
        menu.addItem(switchPet)

        let openBridge = NSMenuItem(
            title: "Open Bridge submenu…",
            action: #selector(OpenPetsCLIContextMenuTarget.openBridgeSubmenu),
            keyEquivalent: ""
        )
        openBridge.target = target
        menu.addItem(openBridge)

        menu.addItem(.separator())

        let instanceSuffix = OpenPetsCLIRuntime.current?.instanceID.map { " (\($0.prefix(8)))" } ?? ""
        let quitPet = NSMenuItem(
            title: "Quit this pet host\(instanceSuffix)",
            action: #selector(OpenPetsCLIContextMenuTarget.quit),
            keyEquivalent: ""
        )
        quitPet.target = target
        menu.addItem(quitPet)

        return menu
    }

    private static func makeDisplayMenu(target: OpenPetsCLIContextMenuTarget) -> NSMenu {
        let menu = NSMenu(title: "Display")
        menu.autoenablesItems = false
        let configuration = (try? OpenPetsConfiguration.loadOrCreateDefault()) ?? OpenPetsConfiguration()
        let currentScale = Double(configuration.display.scale)
        for (title, scale) in [("0.5×", 0.5), ("0.7×", 0.7), ("1.0×", 1.0), ("1.2×", 1.2), ("1.5×", 1.5)] {
            let item = NSMenuItem(
                title: title,
                action: #selector(OpenPetsCLIContextMenuTarget.setDisplayScale(_:)),
                keyEquivalent: ""
            )
            item.target = target
            item.representedObject = scale
            item.state = abs(currentScale - scale) < 0.01 ? .on : .off
            menu.addItem(item)
        }
        return menu
    }

    private static func makePetPackMenu(target: OpenPetsCLIContextMenuTarget) -> NSMenu {
        let menu = NSMenu(title: "Switch pet pack")
        menu.autoenablesItems = false
        guard OpenPetsCLIRuntime.current?.sourceID != nil else {
            let item = NSMenuItem(title: "(source unknown)", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
            return menu
        }

        let packs = target.installedPetPacks()
        if packs.isEmpty {
            let item = NSMenuItem(title: "(no pet packs installed)", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
            return menu
        }

        for pack in packs {
            let item = NSMenuItem(
                title: pack.displayName,
                action: #selector(OpenPetsCLIContextMenuTarget.switchPetPack(_:)),
                keyEquivalent: ""
            )
            item.target = target
            item.representedObject = pack.path
            menu.addItem(item)
        }
        return menu
    }
}

@MainActor
final class OpenPetsCLIContextMenuTarget: NSObject {
    static let shared = OpenPetsCLIContextMenuTarget()
    private(set) var isPetHidden = false
    private var restoreStatusItem: NSStatusItem?

    @objc func openApp() {
        let url = URL(fileURLWithPath: "/Applications/OpenPets.app")
        NSWorkspace.shared.open(url)
    }

    @objc func openConfig() {
        let cfg = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/openpets", isDirectory: true)
        try? FileManager.default.createDirectory(at: cfg, withIntermediateDirectories: true)
        NSWorkspace.shared.open(cfg)
    }

    @objc func bridgeStatus() {
        // Best-effort: open the bridge log dir; users see status in the menubar app
        // and via `openpets-bridge status`. We just make the log accessible.
        let logDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".local/state/openpets-bridge", isDirectory: true)
        if FileManager.default.fileExists(atPath: logDir.path) {
            NSWorkspace.shared.open(logDir)
        } else {
            let url = URL(fileURLWithPath: "/Applications/OpenPets.app")
            NSWorkspace.shared.open(url)
        }
    }

    @objc func togglePetVisibility() {
        guard let window = NSApp.windows.first else {
            return
        }
        if isPetHidden {
            window.orderFrontRegardless()
            isPetHidden = false
            if let restoreStatusItem {
                NSStatusBar.system.removeStatusItem(restoreStatusItem)
                self.restoreStatusItem = nil
            }
        } else {
            window.orderOut(nil)
            isPetHidden = true
            installRestoreStatusItem()
        }
    }

    @objc func openBridgeSubmenu() {
        let url = URL(fileURLWithPath: "/Applications/OpenPets.app")
        NSWorkspace.shared.open(url)
    }

    @objc func setDisplayScale(_ sender: NSMenuItem) {
        guard let scale = sender.representedObject as? Double else {
            return
        }
        do {
            var configuration = try OpenPetsConfiguration.loadOrCreateDefault()
            configuration.display.scale = CGFloat(scale)
            try configuration.save()
            if OpenPetsCLIRuntime.current?.sourceID != nil {
                restartBridgeDaemon()
            }
            NSApplication.shared.terminate(nil)
        } catch {
            FileHandle.standardError.write(Data("openpets: could not save display scale: \(error.localizedDescription)\n".utf8))
        }
    }

    @objc func switchPetPack(_ sender: NSMenuItem) {
        guard let sourceID = OpenPetsCLIRuntime.current?.sourceID,
              let petPath = sender.representedObject as? String else {
            return
        }
        _ = runBridge(args: ["config", "set-source-pet", sourceID, petPath])
        NSApplication.shared.terminate(nil)
    }

    @objc func quit() {
        // The bridge's MultiPetMode.tick() respawns any `openpets run`
        // child that exited — necessary so a real crash recovers
        // automatically, but it also defeats this menu item. Drop a
        // marker file before terminating so the bridge knows this was a
        // user-initiated quit and skips the respawn for this source.
        // The bridge unlinks the marker after seeing it; the user can
        // bring the pet back by un-muting in the tray Bridge submenu
        // or by restarting the daemon.
        if let sourceID = OpenPetsCLIRuntime.current?.sourceID, !sourceID.isEmpty {
            let marker = "/tmp/openpets-quit-\(sourceID).marker"
            FileManager.default.createFile(atPath: marker, contents: Data())
        }
        NSApplication.shared.terminate(nil)
    }

    struct PetPack {
        var displayName: String
        var path: String
    }

    func installedPetPacks() -> [PetPack] {
        let root = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/OpenPets/Pets", isDirectory: true)
        guard let children = try? FileManager.default.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }
        return children.compactMap { url in
            guard (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true else {
                return nil
            }
            return PetPack(displayName: url.lastPathComponent, path: url.path)
        }.sorted { $0.displayName.localizedCaseInsensitiveCompare($1.displayName) == .orderedAscending }
    }

    private func runBridge(args: [String]) -> String {
        // OpenPetsCLI is a standalone executable target that cannot import
        // OpenPetsMenuBar, so this duplicates the bridge-binary lookup. Keep
        // both implementations in sync (see BridgeBinaryLocator in
        // OpenPetsBridgeSubmenu.swift).
        let candidates = [
            "/opt/homebrew/bin/openpets-bridge",
            "/usr/local/bin/openpets-bridge",
            (NSHomeDirectory() as NSString).appendingPathComponent(".local/bin/openpets-bridge"),
        ]
        var bin = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) })
        if bin == nil {
            // Fallback to PATH via /usr/bin/env which.
            let probe = Process()
            probe.launchPath = "/usr/bin/env"
            probe.arguments = ["which", "openpets-bridge"]
            let probeOut = Pipe()
            probe.standardOutput = probeOut
            probe.standardError = Pipe()
            do {
                try probe.run()
                probe.waitUntilExit()
                if probe.terminationStatus == 0 {
                    let data = probeOut.fileHandleForReading.readDataToEndOfFile()
                    if let s = String(data: data, encoding: .utf8) {
                        let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
                        if FileManager.default.isExecutableFile(atPath: trimmed) {
                            bin = trimmed
                        }
                    }
                }
            } catch {
                bin = nil
            }
        }
        guard let resolvedBin = bin else { return "" }
        let task = Process()
        task.launchPath = resolvedBin
        task.arguments = args
        // stdout and stderr captured separately so we never accidentally mix
        // warnings into a parser's input.
        let outPipe = Pipe()
        let errPipe = Pipe()
        task.standardOutput = outPipe
        task.standardError = errPipe
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return ""
        }
        return String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    }

    private func installRestoreStatusItem() {
        if restoreStatusItem != nil {
            return
        }
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName: "pawprint.fill", accessibilityDescription: "Show OpenPets pet")
        let menu = NSMenu()
        let show = NSMenuItem(
            title: "Show this pet",
            action: #selector(togglePetVisibility),
            keyEquivalent: ""
        )
        show.target = self
        menu.addItem(show)
        item.menu = menu
        restoreStatusItem = item
    }

    private func restartBridgeDaemon() {
        let label = "sh.openpets.bridge"
        let uid = getuid()
        let plist = (NSHomeDirectory() as NSString)
            .appendingPathComponent("Library/LaunchAgents/\(label).plist")
        guard FileManager.default.fileExists(atPath: plist) else {
            return
        }
        _ = runProcess(path: "/bin/launchctl", args: ["bootout", "gui/\(uid)/\(label)"])
        _ = runProcess(path: "/bin/launchctl", args: ["bootstrap", "gui/\(uid)", plist])
    }

    @discardableResult
    private func runProcess(path: String, args: [String]) -> Int32 {
        let task = Process()
        task.launchPath = path
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
}

@main
struct OpenPetsCLI {
    @MainActor
    static func main() {
        do {
            try run(arguments: Array(CommandLine.arguments.dropFirst()))
        } catch {
            FileHandle.standardError.write(Data("openpets: \(error.localizedDescription)\n".utf8))
            Foundation.exit(1)
        }
    }

    @MainActor
    private static func run(arguments: [String]) throws {
        guard let command = arguments.first else {
            printUsage()
            return
        }

        switch command {
        case "install":
            let parsed = parseOptionsAndPositionals(Array(arguments.dropFirst()))
            guard let source = parsed.positionals.first else {
                throw CLIError.missingArgument("source")
            }
            let result = try OpenPetsPetInstaller().install(
                source: source,
                activate: !parsed.flags.contains("no-activate")
            )
            print("Installed \(result.displayName) (\(result.petID))")
            if result.activated {
                print("Activated \(result.petID)")
            }

        case "run":
            let options = parseOptions(Array(arguments.dropFirst()))
            guard let petPath = options.values["pet"] else {
                throw CLIError.missingRequiredOption("--pet")
            }
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let socketPath = options.values["socket"] ?? userConfiguration.socketPath
            var display = userConfiguration.display
            if let scale = options.values["scale"].flatMap(Double.init).map({ CGFloat($0) }) {
                display.scale = scale
            }
            let configuration = OpenPetsHostConfiguration(
                petDirectoryURL: URL(fileURLWithPath: petPath).standardizedFileURL,
                socketPath: socketPath,
                display: display
            )

            // Build a session WITH a context menu provider so that right-click
            // on the pet sprite shows useful actions even when the host was
            // spawned from the CLI (e.g. by openpets-bridge in multi-pet mode).
            let session = OpenPetsHostSession(
                configuration: configuration,
                terminatesApplicationOnShutdown: true,
                // TODO: duplicate spawn UI in Preferences.
                contextMenuProvider: { OpenPetsCLIContextMenu.make() }
            )
            try session.start()
            let app = NSApplication.shared
            let delegate = OpenPetsCLIAppDelegate(session: session)
            OpenPetsCLIRuntime.current = OpenPetsCLIRuntime(
                delegate: delegate,
                sourceID: ProcessInfo.processInfo.environment["OPENPETS_BRIDGE_SOURCE_ID"],
                instanceID: ProcessInfo.processInfo.environment["OPENPETS_INSTANCE_ID"]
            )
            // Mark "host alive" in the bridge log dir so we can correlate it
            // with later contextMenu.make() invocations during right-click
            // diagnosis. One line per spawn, never blocks if the dir isn't
            // writable for some reason.
            do {
                let env = ProcessInfo.processInfo.environment
                let src = env["OPENPETS_BRIDGE_SOURCE_ID"] ?? "(none)"
                let inst = env["OPENPETS_INSTANCE_ID"] ?? "(none)"
                let pid = ProcessInfo.processInfo.processIdentifier
                let dir = (NSHomeDirectory() as NSString)
                    .appendingPathComponent("Library/Logs/openpets-bridge")
                try? FileManager.default.createDirectory(atPath: dir,
                                                         withIntermediateDirectories: true)
                let path = (dir as NSString).appendingPathComponent("cli-host-debug.log")
                let ts = ISO8601DateFormatter().string(from: Date())
                let line = "\(ts) pid=\(pid) source=\(src) instance=\(inst) HOST_STARTED pet=\(petPath) socket=\(socketPath)\n"
                if let data = line.data(using: .utf8) {
                    if let h = FileHandle(forWritingAtPath: path) {
                        defer { try? h.close() }
                        _ = try? h.seekToEnd()
                        try? h.write(contentsOf: data)
                    } else {
                        FileManager.default.createFile(atPath: path, contents: data)
                    }
                }
            }
            app.delegate = delegate
            app.setActivationPolicy(.accessory)
            app.run()

        case "notify":
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let parsed = parseOptionsAndPositionals(Array(arguments.dropFirst()))
            guard let title = parsed.values["title"], !title.isEmpty else {
                throw CLIError.missingRequiredOption("--title")
            }
            guard let status = parsed.values["status"], !status.isEmpty else {
                throw CLIError.missingRequiredOption("--status")
            }
            let text = parsed.values["text"] ?? parsed.positionals.joined(separator: " ")
            try send(
                .notify(PetNotification(
                    title: title,
                    text: text.isEmpty ? nil : text,
                    status: status,
                    threadId: parsed.values["thread"],
                    url: parsed.values["url"],
                    buttonLabel: parsed.values["button"],
                    ttlSeconds: parsed.values["ttl"].flatMap(Double.init)
                )),
                socketPath: parsed.values["socket"] ?? userConfiguration.socketPath
            )

        case "animate":
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let parsed = parseOptionsAndPositionals(Array(arguments.dropFirst()))
            guard let animationName = parsed.positionals.first else {
                throw CLIError.missingArgument("animation")
            }
            guard let animation = PetAnimation(cliValue: animationName) else {
                throw CLIError.invalidArgument("Unknown animation '\(animationName)'")
            }
            let loop = parsed.flags.contains("loop") ? true : (parsed.flags.contains("once") ? false : nil)
            try send(
                .playAnimation(
                    name: animation,
                    loop: loop,
                    ttlSeconds: parsed.values["ttl"].flatMap(Double.init)
                ),
                socketPath: parsed.values["socket"] ?? userConfiguration.socketPath
            )

        case "clear":
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let options = parseOptions(Array(arguments.dropFirst()))
            guard let threadId = options.values["thread"], !threadId.isEmpty else {
                throw CLIError.missingRequiredOption("--thread")
            }
            try send(.clearMessage(threadId: threadId), socketPath: options.values["socket"] ?? userConfiguration.socketPath)

        case "stop-animation":
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let options = parseOptions(Array(arguments.dropFirst()))
            try send(.stopAnimation, socketPath: options.values["socket"] ?? userConfiguration.socketPath)

        case "ping":
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let options = parseOptions(Array(arguments.dropFirst()))
            try send(.ping, socketPath: options.values["socket"] ?? userConfiguration.socketPath)

        case "stop":
            let userConfiguration = try OpenPetsConfiguration.loadOrCreateDefault()
            let options = parseOptions(Array(arguments.dropFirst()))
            try send(.shutdown, socketPath: options.values["socket"] ?? userConfiguration.socketPath)

        case "help", "--help", "-h":
            printUsage()

        default:
            throw CLIError.invalidArgument("Unknown command '\(command)'")
        }
    }

    private static func send(_ command: PetCommand, socketPath: String?) throws {
        let response = try OpenPetsClient(socketPath: socketPath ?? OpenPetsPaths.defaultSocketPath).send(command)
        if let message = response.message, !message.isEmpty {
            print(message)
        } else if let threadId = response.threadId, !threadId.isEmpty {
            print(threadId)
        } else if !response.ok {
            print("failed")
        }
        if !response.ok {
            Foundation.exit(2)
        }
    }

    private static func printUsage() {
        print(
            """
            Usage:
              openpets run --pet /Users/sam/.codex/pets/starcorn [--socket PATH] [--scale 0.42]
              openpets install URL_OR_PET_ID [--no-activate]
              openpets notify --title TITLE --status KIND [--text TEXT] [--thread UUID] [--url URL] [--button LABEL] [--ttl SECONDS] [--socket PATH]
              openpets animate ANIMATION [--loop|--once] [--ttl SECONDS] [--socket PATH]
              openpets clear --thread UUID [--socket PATH]
              openpets stop-animation [--socket PATH]
              openpets ping [--socket PATH]
              openpets stop [--socket PATH]

            Animations: idle, running-right, running-left, waving, jumping, failed, waiting, running, review
            """
        )
    }

    private static func parseOptions(_ arguments: [String]) -> ParsedArguments {
        parseOptionsAndPositionals(arguments)
    }

    private static func parseOptionsAndPositionals(_ arguments: [String]) -> ParsedArguments {
        var values: [String: String] = [:]
        var flags = Set<String>()
        var positionals: [String] = []
        var index = 0

        while index < arguments.count {
            let argument = arguments[index]
            if argument.hasPrefix("--") {
                let name = String(argument.dropFirst(2))
                if ["loop", "once", "no-activate"].contains(name) {
                    flags.insert(name)
                    index += 1
                    continue
                }
                if index + 1 < arguments.count {
                    values[name] = arguments[index + 1]
                    index += 2
                } else {
                    flags.insert(name)
                    index += 1
                }
            } else {
                positionals.append(argument)
                index += 1
            }
        }

        return ParsedArguments(values: values, flags: flags, positionals: positionals)
    }
}

private struct ParsedArguments {
    var values: [String: String]
    var flags: Set<String>
    var positionals: [String]
}

private enum CLIError: Error, LocalizedError {
    case missingRequiredOption(String)
    case missingArgument(String)
    case invalidArgument(String)

    var errorDescription: String? {
        switch self {
        case .missingRequiredOption(let option):
            "Missing required option \(option)"
        case .missingArgument(let argument):
            "Missing required argument: \(argument)"
        case .invalidArgument(let message):
            message
        }
    }
}
