import AppKit
import Foundation
import OpenPetsKit

@MainActor
final class OpenPetsPreferencesWindowController: NSWindowController, NSToolbarDelegate {
    private enum TabID: String {
        case display = "display"
        case bridge = "bridge"
        case sources = "sources"
        case advanced = "advanced"
    }

    private let onApply: () -> Void
    private let tabView = NSTabView()
    private let displayTab = NSTabViewItem(identifier: TabID.display.rawValue)
    private let bridgeTab = NSTabViewItem(identifier: TabID.bridge.rawValue)
    private let sourcesTab = NSTabViewItem(identifier: TabID.sources.rawValue)
    private let advancedTab = NSTabViewItem(identifier: TabID.advanced.rawValue)

    private let scaleSlider = NSSlider(value: 1.0, minValue: 0.3, maxValue: 1.8, target: nil, action: nil)
    private let scaleValue = NSTextField(labelWithString: "")
    private let messageHeightStepper = NSStepper()
    private let messageHeightField = NSTextField(string: "")

    private let bridgeModeControl = NSSegmentedControl(labels: ["single", "multi"], trackingMode: .selectOne, target: nil, action: nil)
    private let pollStepper = NSStepper()
    private let pollField = NSTextField(string: "")
    private let pushStepper = NSStepper()
    private let pushField = NSTextField(string: "")
    private let autoClearStepper = NSStepper()
    private let autoClearField = NSTextField(string: "")
    private let redactBodyCheckbox = NSButton(checkboxWithTitle: "Redact body", target: nil, action: nil)
    private let sourcesStack = NSStackView()
    private var sourceCheckboxes: [String: NSButton] = [:]
    private var currentSources: [PreferencesSourceState] = []

    private let mcpHostField = NSTextField(string: "")
    private let mcpPortStepper = NSStepper()
    private let mcpPortField = NSTextField(string: "")
    private let socketPathField = NSTextField(labelWithString: "")
    private let configPathField = NSTextField(labelWithString: "")

    init(onApply: @escaping () -> Void) {
        self.onApply = onApply
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 360),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "OpenPets Preferences"
        window.center()
        super.init(window: window)
        buildWindow()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        nil
    }

    func reload() {
        loadOpenPetsConfiguration()
        loadBridgeConfiguration()
        updateBridgeVisibility()
    }

    private func buildWindow() {
        guard let window else { return }
        tabView.translatesAutoresizingMaskIntoConstraints = false
        tabView.tabViewType = .noTabsNoBorder
        displayTab.label = "Display"
        bridgeTab.label = "Bridge"
        sourcesTab.label = "Sources"
        advancedTab.label = "Advanced"
        tabView.addTabViewItem(displayTab)
        tabView.addTabViewItem(bridgeTab)
        tabView.addTabViewItem(sourcesTab)
        tabView.addTabViewItem(advancedTab)
        displayTab.view = makeDisplayView()
        bridgeTab.view = makeBridgeView()
        sourcesTab.view = makeSourcesView()
        advancedTab.view = makeAdvancedView()

        let applyButton = NSButton(title: "Apply", target: self, action: #selector(applyPreferences))
        applyButton.bezelStyle = .rounded
        let cancelButton = NSButton(title: "Close", target: self, action: #selector(closeWindow))
        cancelButton.bezelStyle = .rounded

        let buttonRow = NSStackView(views: [NSView(), cancelButton, applyButton])
        buttonRow.orientation = .horizontal
        buttonRow.alignment = .centerY
        buttonRow.spacing = 8
        buttonRow.translatesAutoresizingMaskIntoConstraints = false
        buttonRow.setHuggingPriority(.defaultLow, for: .horizontal)

        let root = NSStackView(views: [tabView, buttonRow])
        root.orientation = .vertical
        root.spacing = 12
        root.edgeInsets = NSEdgeInsets(top: 18, left: 20, bottom: 16, right: 20)
        root.translatesAutoresizingMaskIntoConstraints = false
        window.contentView = root

        NSLayoutConstraint.activate([
            tabView.heightAnchor.constraint(greaterThanOrEqualToConstant: 260),
            root.widthAnchor.constraint(greaterThanOrEqualToConstant: 520),
            root.heightAnchor.constraint(greaterThanOrEqualToConstant: 340),
        ])

        let toolbar = NSToolbar(identifier: "OpenPetsPreferencesToolbar")
        toolbar.delegate = self
        toolbar.displayMode = .iconAndLabel
        toolbar.allowsUserCustomization = false
        window.toolbar = toolbar

        scaleSlider.target = self
        scaleSlider.action = #selector(scaleSliderChanged)
        for stepper in [messageHeightStepper, pollStepper, pushStepper, autoClearStepper, mcpPortStepper] {
            stepper.target = self
            stepper.action = #selector(stepperChanged(_:))
        }
    }

    private func makeDisplayView() -> NSView {
        messageHeightStepper.minValue = 40
        messageHeightStepper.maxValue = 120
        messageHeightStepper.increment = 1
        messageHeightField.alignment = .right
        return formStack(rows: [
            ("Scale", horizontal([scaleSlider, scaleValue])),
            ("Message area height", horizontal([messageHeightField, messageHeightStepper])),
        ])
    }

    private func makeBridgeView() -> NSView {
        pollStepper.minValue = 0.2
        pollStepper.maxValue = 30
        pollStepper.increment = 0.1
        pushStepper.minValue = 0
        pushStepper.maxValue = 30
        pushStepper.increment = 0.1
        autoClearStepper.minValue = 0
        autoClearStepper.maxValue = 86_400
        autoClearStepper.increment = 60
        for field in [pollField, pushField, autoClearField] {
            field.alignment = .right
        }
        return formStack(rows: [
            ("Mode", bridgeModeControl),
            ("Poll interval", horizontal([pollField, pollStepper])),
            ("Push throttle", horizontal([pushField, pushStepper])),
            ("Auto clear after", horizontal([autoClearField, autoClearStepper])),
            ("Privacy", redactBodyCheckbox),
        ])
    }

    private func makeAdvancedView() -> NSView {
        mcpPortStepper.minValue = 1
        mcpPortStepper.maxValue = 65_535
        mcpPortStepper.increment = 1
        mcpPortField.alignment = .right
        socketPathField.lineBreakMode = .byTruncatingMiddle
        configPathField.lineBreakMode = .byTruncatingMiddle

        let revealButton = NSButton(title: "Reveal in Finder", target: self, action: #selector(revealConfigFolder))
        revealButton.bezelStyle = .rounded

        return formStack(rows: [
            ("MCP host", mcpHostField),
            ("MCP port", horizontal([mcpPortField, mcpPortStepper])),
            ("Socket path", socketPathField),
            ("Config folder", horizontal([configPathField, revealButton])),
        ])
    }

    private func makeSourcesView() -> NSView {
        sourcesStack.orientation = .vertical
        sourcesStack.alignment = .leading
        sourcesStack.spacing = 8
        sourcesStack.translatesAutoresizingMaskIntoConstraints = false

        let documentView = NSView()
        documentView.translatesAutoresizingMaskIntoConstraints = false
        documentView.addSubview(sourcesStack)
        NSLayoutConstraint.activate([
            sourcesStack.leadingAnchor.constraint(equalTo: documentView.leadingAnchor),
            sourcesStack.trailingAnchor.constraint(equalTo: documentView.trailingAnchor),
            sourcesStack.topAnchor.constraint(equalTo: documentView.topAnchor),
            sourcesStack.bottomAnchor.constraint(lessThanOrEqualTo: documentView.bottomAnchor),
        ])

        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.borderType = .noBorder
        scroll.documentView = documentView
        NSLayoutConstraint.activate([
            documentView.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
        ])
        return scroll
    }

    private func formStack(rows: [(String, NSView)]) -> NSView {
        let grid = NSGridView()
        grid.translatesAutoresizingMaskIntoConstraints = false
        grid.rowSpacing = 12
        grid.columnSpacing = 12
        for (label, control) in rows {
            let labelView = NSTextField(labelWithString: label)
            labelView.alignment = .right
            labelView.widthAnchor.constraint(equalToConstant: 150).isActive = true
            control.translatesAutoresizingMaskIntoConstraints = false
            grid.addRow(with: [labelView, control])
        }
        grid.column(at: 0).xPlacement = .trailing
        grid.column(at: 1).xPlacement = .fill
        let wrapper = NSView()
        wrapper.addSubview(grid)
        NSLayoutConstraint.activate([
            grid.leadingAnchor.constraint(equalTo: wrapper.leadingAnchor),
            grid.trailingAnchor.constraint(equalTo: wrapper.trailingAnchor),
            grid.topAnchor.constraint(equalTo: wrapper.topAnchor),
        ])
        return wrapper
    }

    private func horizontal(_ views: [NSView]) -> NSStackView {
        let stack = NSStackView(views: views)
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 8
        if let first = views.first {
            first.setContentHuggingPriority(.defaultLow, for: .horizontal)
        }
        return stack
    }

    private func loadOpenPetsConfiguration() {
        let configuration = (try? OpenPetsConfiguration.loadOrCreateDefault()) ?? OpenPetsConfiguration()
        scaleSlider.doubleValue = Double(configuration.display.scale)
        scaleValue.stringValue = String(format: "%.1fx", scaleSlider.doubleValue)
        messageHeightStepper.doubleValue = Double(configuration.display.messageAreaHeight)
        messageHeightField.stringValue = String(format: "%.0f", messageHeightStepper.doubleValue)
        mcpHostField.stringValue = configuration.mcpHost
        mcpPortStepper.integerValue = configuration.mcpPort
        mcpPortField.stringValue = "\(configuration.mcpPort)"
        socketPathField.stringValue = configuration.socketPath
        configPathField.stringValue = OpenPetsPaths.defaultConfigurationDirectory.path
    }

    private func loadBridgeConfiguration() {
        guard let raw = runBridge(args: ["config", "show"])?.output,
              let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        let mode = (obj["mode"] as? String) ?? "single"
        bridgeModeControl.selectedSegment = mode == "multi" ? 1 : 0
        pollStepper.doubleValue = (obj["poll_interval_s"] as? Double) ?? 1.0
        pollField.stringValue = String(format: "%.1f", pollStepper.doubleValue)
        pushStepper.doubleValue = (obj["push_throttle_s"] as? Double) ?? 1.5
        pushField.stringValue = String(format: "%.1f", pushStepper.doubleValue)
        autoClearStepper.doubleValue = (obj["auto_clear_after_s"] as? Double) ?? 0.0
        autoClearField.stringValue = String(format: "%.0f", autoClearStepper.doubleValue)
        if let sources = obj["sources"] as? [String: [String: Any]] {
            let values = sources.values.compactMap { $0["redact_body"] as? Bool }
            redactBodyCheckbox.state = values.allSatisfy { $0 } && !values.isEmpty ? .on : .off
            currentSources = sources.map { sid, raw in
                let discovery = raw["discovery"] as? [String: Any]
                return PreferencesSourceState(
                    id: sid,
                    label: (raw["label"] as? String) ?? sid,
                    icon: (raw["icon"] as? String) ?? "•",
                    enabled: (raw["enabled"] as? Bool) ?? false,
                    installed: (discovery?["installed"] as? Bool) ?? false,
                    watchPath: discovery?["watch_path"] as? String
                )
            }.sorted { lhs, rhs in
                if lhs.enabled != rhs.enabled { return lhs.enabled }
                return lhs.label < rhs.label
            }
            rebuildSourcesList()
        }
    }

    private func updateBridgeVisibility() {
        let installed = bridgeBinaryPath() != nil
        let hasBridgeTab = tabView.tabViewItems.contains { ($0.identifier as? String) == TabID.bridge.rawValue }
        let hasSourcesTab = tabView.tabViewItems.contains { ($0.identifier as? String) == TabID.sources.rawValue }
        if installed && !hasBridgeTab {
            tabView.insertTabViewItem(bridgeTab, at: 1)
        } else if !installed && hasBridgeTab {
            tabView.removeTabViewItem(bridgeTab)
        }
        if installed && !hasSourcesTab {
            tabView.insertTabViewItem(sourcesTab, at: min(2, tabView.numberOfTabViewItems))
        } else if !installed && hasSourcesTab {
            tabView.removeTabViewItem(sourcesTab)
        }
    }

    func selectSourcesTab() {
        tabView.selectTabViewItem(withIdentifier: TabID.sources.rawValue)
    }

    private func rebuildSourcesList() {
        sourcesStack.arrangedSubviews.forEach { view in
            sourcesStack.removeArrangedSubview(view)
            view.removeFromSuperview()
        }
        sourceCheckboxes.removeAll()
        for source in currentSources {
            let row = makeSourceRow(source)
            sourcesStack.addArrangedSubview(row)
        }
    }

    private func makeSourceRow(_ source: PreferencesSourceState) -> NSView {
        let checkbox = NSButton(checkboxWithTitle: "Enabled", target: nil, action: nil)
        checkbox.state = source.enabled ? .on : .off
        sourceCheckboxes[source.id] = checkbox

        let label = NSTextField(labelWithString: "\(source.icon)  \(source.label)")
        label.setContentHuggingPriority(.defaultLow, for: .horizontal)

        let status = NSTextField(labelWithString: source.installed ? "Installed" : "Not detected")
        status.textColor = source.installed ? .systemGreen : .secondaryLabelColor
        status.alignment = .right
        status.widthAnchor.constraint(equalToConstant: 90).isActive = true

        var views: [NSView] = [checkbox, label, status]
        if let watchPath = source.watchPath {
            let reveal = NSButton(title: "Reveal in Finder", target: self, action: #selector(revealSourceWatchPath(_:)))
            reveal.bezelStyle = .rounded
            reveal.toolTip = watchPath
            views.append(reveal)
        }

        let row = NSStackView(views: views)
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10
        row.translatesAutoresizingMaskIntoConstraints = false
        row.widthAnchor.constraint(greaterThanOrEqualToConstant: 460).isActive = true
        return row
    }

    @objc private func scaleSliderChanged() {
        scaleValue.stringValue = String(format: "%.1fx", scaleSlider.doubleValue)
    }

    @objc private func stepperChanged(_ sender: NSStepper) {
        switch sender {
        case messageHeightStepper:
            messageHeightField.stringValue = String(format: "%.0f", sender.doubleValue)
        case pollStepper:
            pollField.stringValue = String(format: "%.1f", sender.doubleValue)
        case pushStepper:
            pushField.stringValue = String(format: "%.1f", sender.doubleValue)
        case autoClearStepper:
            autoClearField.stringValue = String(format: "%.0f", sender.doubleValue)
        case mcpPortStepper:
            mcpPortField.stringValue = "\(sender.integerValue)"
        default:
            break
        }
    }

    @objc private func applyPreferences() {
        do {
            var configuration = try OpenPetsConfiguration.loadOrCreateDefault()
            configuration.display.scale = CGFloat(scaleSlider.doubleValue)
            configuration.display.messageAreaHeight = CGFloat(messageHeightField.doubleValue)
            configuration.mcpHost = mcpHostField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            configuration.mcpPort = mcpPortField.integerValue
            try configuration.save()

            if bridgeBinaryPath() != nil && tabView.tabViewItems.contains(where: { ($0.identifier as? String) == TabID.bridge.rawValue }) {
                let mode = bridgeModeControl.selectedSegment == 1 ? "multi" : "single"
                try runRequiredBridgeCommand(args: ["config", "set-mode", mode])
                try runRequiredBridgeCommand(args: ["config", "set-poll-interval", "\(pollField.doubleValue)"])
                try runRequiredBridgeCommand(args: ["config", "set-push-throttle", "\(pushField.doubleValue)"])
                try runRequiredBridgeCommand(args: ["config", "set-auto-clear", "\(autoClearField.doubleValue)"])
                try runRequiredBridgeCommand(args: ["config", "set-redact-body", redactBodyCheckbox.state == .on ? "on" : "off"])
                try applySourcePreferences()
            }
            onApply()
        } catch {
            showError("Could not save preferences", detail: error.localizedDescription)
        }
    }

    @objc private func closeWindow() {
        close()
    }

    @objc private func revealConfigFolder() {
        try? FileManager.default.createDirectory(
            at: OpenPetsPaths.defaultConfigurationDirectory,
            withIntermediateDirectories: true
        )
        NSWorkspace.shared.activateFileViewerSelecting([OpenPetsPaths.defaultConfigurationDirectory])
    }

    @objc private func revealSourceWatchPath(_ sender: NSButton) {
        guard let path = sender.toolTip else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    @objc private func selectToolbarTab(_ sender: NSToolbarItem) {
        switch sender.itemIdentifier {
        case .displayPreferences:
            tabView.selectTabViewItem(withIdentifier: TabID.display.rawValue)
        case .bridgePreferences:
            tabView.selectTabViewItem(withIdentifier: TabID.bridge.rawValue)
        case .sourcesPreferences:
            tabView.selectTabViewItem(withIdentifier: TabID.sources.rawValue)
        case .advancedPreferences:
            tabView.selectTabViewItem(withIdentifier: TabID.advanced.rawValue)
        default:
            break
        }
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.displayPreferences, .bridgePreferences, .sourcesPreferences, .advancedPreferences]
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        if bridgeBinaryPath() == nil {
            return [.displayPreferences, .advancedPreferences]
        }
        return [.displayPreferences, .bridgePreferences, .sourcesPreferences, .advancedPreferences]
    }

    func toolbar(
        _ toolbar: NSToolbar,
        itemForItemIdentifier itemIdentifier: NSToolbarItem.Identifier,
        willBeInsertedIntoToolbar flag: Bool
    ) -> NSToolbarItem? {
        let item = NSToolbarItem(itemIdentifier: itemIdentifier)
        item.target = self
        item.action = #selector(selectToolbarTab(_:))
        switch itemIdentifier {
        case .displayPreferences:
            item.label = "Display"
            item.image = NSImage(systemSymbolName: "rectangle.and.arrow.up.right.and.arrow.down.left", accessibilityDescription: "Display")
        case .bridgePreferences:
            item.label = "Bridge"
            item.image = NSImage(systemSymbolName: "point.3.connected.trianglepath.dotted", accessibilityDescription: "Bridge")
        case .sourcesPreferences:
            item.label = "Sources"
            item.image = NSImage(systemSymbolName: "terminal", accessibilityDescription: "Sources")
        case .advancedPreferences:
            item.label = "Advanced"
            item.image = NSImage(systemSymbolName: "gearshape", accessibilityDescription: "Advanced")
        default:
            return nil
        }
        return item
    }

    private func bridgeBinaryPath() -> String? {
        return BridgeBinaryLocator.find()
    }

    @discardableResult
    private func runBridge(args: [String]) -> BridgeCommandResult? {
        guard let bin = bridgeBinaryPath() else { return nil }
        let task = Process()
        task.launchPath = bin
        task.arguments = args
        // stdout and stderr captured separately so callers parsing JSON
        // (e.g. `config show`) don't ingest warning noise.
        let outPipe = Pipe()
        let errPipe = Pipe()
        task.standardOutput = outPipe
        task.standardError = errPipe
        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return nil
        }
        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        return BridgeCommandResult(
            status: task.terminationStatus,
            output: String(data: data, encoding: .utf8) ?? ""
        )
    }

    private func runRequiredBridgeCommand(args: [String]) throws {
        guard let result = runBridge(args: args) else {
            throw OpenPetsPreferencesError.bridgeCommandFailed("Could not run openpets-bridge.")
        }
        guard result.status == 0 else {
            throw OpenPetsPreferencesError.bridgeCommandFailed(
                result.output.trimmingCharacters(in: .whitespacesAndNewlines)
            )
        }
    }

    private func showError(_ title: String, detail: String) {
        let alert = NSAlert()
        OpenPetsAppIcon.apply(to: alert)
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func applySourcePreferences() throws {
        let removable = Set(["aider", "gemini_cli", "opencode", "continue_cli", "cline"])
        for source in currentSources {
            guard let checkbox = sourceCheckboxes[source.id] else { continue }
            let desired = checkbox.state == .on
            if desired == source.enabled {
                continue
            }
            if desired {
                try runRequiredBridgeCommand(args: ["config", "add-source-preset", source.id])
                try runRequiredBridgeCommand(args: ["config", "toggle-source", source.id])
            } else if removable.contains(source.id) {
                try runRequiredBridgeCommand(args: ["config", "remove-source", source.id])
            } else {
                try runRequiredBridgeCommand(args: ["config", "toggle-source", source.id])
            }
        }
    }
}

private struct BridgeCommandResult {
    var status: Int32
    var output: String
}

private struct PreferencesSourceState {
    var id: String
    var label: String
    var icon: String
    var enabled: Bool
    var installed: Bool
    var watchPath: String?
}

private enum OpenPetsPreferencesError: Error, LocalizedError {
    case bridgeCommandFailed(String)

    var errorDescription: String? {
        switch self {
        case .bridgeCommandFailed(let message):
            return message.isEmpty ? "openpets-bridge returned a non-zero exit status." : message
        }
    }
}

private extension NSToolbarItem.Identifier {
    static let displayPreferences = NSToolbarItem.Identifier("openpets.preferences.display")
    static let bridgePreferences = NSToolbarItem.Identifier("openpets.preferences.bridge")
    static let sourcesPreferences = NSToolbarItem.Identifier("openpets.preferences.sources")
    static let advancedPreferences = NSToolbarItem.Identifier("openpets.preferences.advanced")
}
