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

    init(delegate: OpenPetsCLIAppDelegate) {
        self.delegate = delegate
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
    static func make() -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false

        let openApp = NSMenuItem(
            title: "Open OpenPets…",
            action: #selector(OpenPetsCLIContextMenuTarget.openApp),
            keyEquivalent: ""
        )
        openApp.target = OpenPetsCLIContextMenuTarget.shared
        menu.addItem(openApp)

        let openConfig = NSMenuItem(
            title: "Open Config Folder",
            action: #selector(OpenPetsCLIContextMenuTarget.openConfig),
            keyEquivalent: ""
        )
        openConfig.target = OpenPetsCLIContextMenuTarget.shared
        menu.addItem(openConfig)

        let bridgeStatus = NSMenuItem(
            title: "openpets-bridge: status…",
            action: #selector(OpenPetsCLIContextMenuTarget.bridgeStatus),
            keyEquivalent: ""
        )
        bridgeStatus.target = OpenPetsCLIContextMenuTarget.shared
        menu.addItem(bridgeStatus)

        menu.addItem(.separator())

        let quitPet = NSMenuItem(
            title: "Quit this pet host",
            action: #selector(OpenPetsCLIContextMenuTarget.quit),
            keyEquivalent: ""
        )
        quitPet.target = OpenPetsCLIContextMenuTarget.shared
        menu.addItem(quitPet)

        return menu
    }
}

@MainActor
final class OpenPetsCLIContextMenuTarget: NSObject {
    static let shared = OpenPetsCLIContextMenuTarget()

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

    @objc func quit() {
        NSApplication.shared.terminate(nil)
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
                contextMenuProvider: { OpenPetsCLIContextMenu.make() }
            )
            try session.start()
            let app = NSApplication.shared
            let delegate = OpenPetsCLIAppDelegate(session: session)
            OpenPetsCLIRuntime.current = OpenPetsCLIRuntime(delegate: delegate)
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
