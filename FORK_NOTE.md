# Fork note

This is **[MacSiem's fork](https://github.com/MacSiem/openpets)** of
[alterhq/openpets](https://github.com/alterhq/openpets). The fork stays
in sync with upstream; **all Swift / native macOS code is theirs**, and
they did the heavy lifting (the desktop app, the MCP server, the IPC
plumbing, the OpenPetsKit Swift package).

What this fork adds, all on top of the upstream tree:

```
Sources/OpenPetsMenuBar/OpenPetsBridgeSubmenu.swift
                     — Adds a "Bridge ▸" section to the OpenPets tray menu
                       (status, start/stop/restart, open config, open log,
                       list pet packs, clear bubbles). Status auto-refreshes
                       every 5s via /bin/launchctl probe.

Sources/OpenPetsMenuBar/OpenPetsMenuBar.swift
                     — Wires the Bridge submenu into the existing tray
                       menu builder, so it shows up in both the status-bar
                       click and the right-click on the pet sprite.

Sources/OpenPetsCLI/OpenPetsCLI.swift
                     — `openpets run` now uses OpenPetsHostSession with a
                       contextMenuProvider, so right-click on a CLI-spawned
                       sprite (the multi-pet mode openpets-bridge uses) gets
                       its own context menu. Without this, sprites spawned
                       outside the menubar app were silent on right-click.

bridge/              — openpets-bridge: a small Python daemon that watches
                       the on-disk session logs of multiple AI coding agents
                       (Cowork, Codex CLI, Claude Code CLI) and forwards
                       their activity to OpenPets via the documented
                       `notify --thread <uuid>` workflow. Useful when an
                       agent runtime does not natively call the `notify`
                       MCP tool. Controls live in OpenPets.app's tray —
                       no separate menubar app.
```

See [`bridge/README.md`](./bridge/README.md) for install / configure /
contribute. MIT licensed (same as upstream).

If you're looking for OpenPets itself — the desktop app, the MCP server,
the Swift package — install it from
[**alterhq's releases**](https://github.com/alterhq/openpets/releases/latest).
You don't need this fork. The bridge is opt-in extra glue on top.

The Swift changes in this fork are PR-able upstream. They're additive
(new file + small edits to existing builders) and behind the same MIT
license.
