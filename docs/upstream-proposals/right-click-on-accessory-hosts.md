# Proposal: right-click context menu on accessory-policy hosts

**Target repo:** `alterhq/OpenPetsKit` (the `OpenPetsHost.swift` SpriteView code).
**Severity:** small — one-line fix, fully backwards compatible.
**Scope:** every consumer of `OpenPetsHostSession(contextMenuProvider:)`
who runs under `.accessory` activation policy.

## Problem

`OpenPetsHostSession` exposes a `contextMenuProvider` closure so any
consumer can attach a custom right-click menu to the pet sprite. The
upstream menubar app uses it for the tray's
`makePetContextMenu()`; downstream consumers (this fork's
`openpets run --pet … --socket …` CLI host, anyone embedding
`OpenPetsKit` in a Helper-style process, etc.) use it for their own
host-local context menu.

**Bug:** when the host process runs with `.accessory` activation
policy, the upstream menubar app's right-click works because that
process is already frontmost when its tray view is hit. The CLI host
spawned via `OpenPetsHost.run(configuration:)` / `app.setActivationPolicy(.accessory)`,
however, is **never** frontmost. AppKit's `NSMenu.popUpContextMenu(_:with:for:)`
silently dismisses the menu before it becomes visible — from the user's
POV, right-click on those sprites does nothing.

We hit this in the fork's `openpets run` hosts (multi-pet mode spawns
one `openpets run` child per AI source). Repro: any consumer that calls
`app.setActivationPolicy(.accessory)` and provides a non-nil
`contextMenuProvider`.

## Repro

```swift
import AppKit
import OpenPetsKit

let cfg = OpenPetsHostConfiguration(petDirectoryURL: …, socketPath: …)
let session = OpenPetsHostSession(
    configuration: cfg,
    terminatesApplicationOnShutdown: true,
    contextMenuProvider: {
        let m = NSMenu()
        m.addItem(NSMenuItem(title: "Hello", action: nil, keyEquivalent: ""))
        return m
    }
)
try session.start()
NSApplication.shared.setActivationPolicy(.accessory)
NSApplication.shared.run()
// → right-click on sprite: nothing happens
```

## Proposed fix

In `Sources/OpenPetsKit/OpenPetsHost.swift`, inside the `PetSpriteView`'s
`rightMouseDown(with:)` override (currently ≈line 3978):

```swift
override func rightMouseDown(with event: NSEvent) {
    guard let menu = contextMenuProvider?() else {
        super.rightMouseDown(with: event)
        return
    }
+   // Without this, hosts spawned under .accessory activation policy
+   // never see the popUpContextMenu open — AppKit dismisses it before
+   // it becomes visible because the host process isn't frontmost. The
+   // activate() is a no-op for the already-frontmost menubar app, so
+   // existing consumers are unaffected.
+   NSApplication.shared.activate(ignoringOtherApps: true)
    contextMenuPresenter(menu, event, self)
}
```

That's the entire patch — one line + a comment, in one method.

## Why upstream and not downstream?

This fork already has a downstream workaround (we call
`NSApplication.shared.activate(ignoringOtherApps:)` from inside our
`OpenPetsCLIContextMenu.make()` provider). It works, but:

* Every other consumer who copies the documented `contextMenuProvider`
  pattern hits the same trap.
* The fix is genuinely benign for the menubar consumer (the upstream
  app's process is already active when its right-click fires, so
  `activate()` is a no-op).
* Keeping the workaround in the provider closure means each closure
  has to remember to call `activate()` — easy to forget on second
  uses or by future maintainers.

Putting the activate call **inside the SpriteView** centralizes the
fix and makes the public `contextMenuProvider` contract "just work".

## Verification on this fork

We landed the equivalent workaround as the `QW4 fix` commit; verified
live with `~/Library/Logs/openpets-bridge/cli-host-debug.log` (one
`contextMenu.make()` line per right-click on each bridge-spawned host)
plus visual confirmation that the menu now opens for every sprite.
Tests `swift test`: 93/93 pass.

After landing this proposal upstream, the fork can drop its own
`activate()` call from `OpenPetsCLIContextMenu.make()` and rely on
`OpenPetsKit` to do the right thing.

## Suggested PR title

> Activate NSApp before popUpContextMenu so accessory-policy hosts can show the pet's right-click menu

## Suggested commit message

```
fix: activate NSApp before showing pet right-click menu

When the host process runs with .accessory activation policy it's
never frontmost, so AppKit dismisses popUpContextMenu before the menu
becomes visible. Forcing activation makes the menu work consistently
across the upstream menubar app and any downstream that wraps
OpenPetsHostSession in an .accessory process.

No-op for the already-frontmost menubar app.
```
