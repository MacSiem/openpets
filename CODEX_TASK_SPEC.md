# Codex task spec — OpenPets fork: tray / right-click / settings expansion

Authorization: explicit Maciej "niech codex api wdrozy wszystkie poprawki i dodatki i sugestie" (Cowork session 2026-05-14).
Auth profile: **`~/.codex-api` (API key, billed)**. NOT subscription.
Routing class: `codex-worker`. Scope: in-repo Swift + Python only. Non-destructive.
Repo: `/Users/maciej/Projects/openpets-fork` — fresh clone of `MacSiem/openpets@77806e1`.
Upstream we depend on: `alterhq/openpets` via `OpenPetsKit` Swift package.

## What exists today (audit baseline)

**Tray menu** (`Sources/OpenPetsMenuBar/OpenPetsMenuBar.swift:390-421`):
Start/Stop MCP, Server Status, Copy MCP URL, Wake/Stop Pet, Call my pet,
Active Pet▸ (radio per pack), Install pets..., Bridge▸ (status, start/stop/restart, Mode▸,
Sources▸, Pet for source▸, Open Config, Open Log, List Pets, Clear Done, Clear ALL,
Install), Open Config Folder, Install CLI, Set Up AI Assistants…, Check for Updates…,
version, Quit.

**Right-click on pet sprite — two paths:**
1. Tray-hosted main pet: `makePetContextMenu()` returns the **same** menu as tray
   (`OpenPetsMenuBar.swift:279-282`). No per-pet items.
2. CLI-spawned multi-pet hosts: `OpenPetsCLIContextMenu.make()` returns only
   `Open OpenPets…`, `Open Config Folder`, `openpets-bridge: status…`,
   `Quit this pet host` (`Sources/OpenPetsCLI/OpenPetsCLI.swift:39-80`).

**Settings:** no `OpenPetsPreferencesWindow`. Only `OpenPetsAgentOnboardingWindow`
(MCP onboarding for Claude Desktop / Cursor / VS Code) and
`OpenPetsInstallPreviewWindow` (pet pack preview before install).
All display/throttle/redact knobs are edit-the-file-by-hand
(`~/.config/openpets/config.json`, `~/.config/openpets-bridge/config.toml`).

**Bridge known issue (canonical note 2026-05-11):** right-click context menu on
sprite is reported "not appearing" even with `contextMenuProvider` correctly
injected. Confirm/repro before fixing.

## Goal — implement ALL of the below

### Quick wins (Swift only, in-tray UX)

**QW1 — Display ▸ Scale submenu in tray and right-click menu.**
- New tray section "Display ▸" inserted between Active Pet and Install pets...
- Sub-items: `0.5×`, `0.7×`, `1.0×`, `1.2×`, `1.5×` (radio, checkmark on current).
- Action persists `display.scale` to `~/.config/openpets/config.json` via
  `OpenPetsConfiguration` save path, then stops + re-wakes pet so the new scale
  takes effect (existing `selectPet` already does the restart dance — mirror it).
- Same submenu must appear in `makePetContextMenu()` (right-click on tray-hosted pet)
  AND in `OpenPetsCLIContextMenu.make()` for multi-pet CLI hosts.

**QW2 — Per-source Mute toggle in Bridge ▸ Sources▸.**
- Each existing source row (Cowork/Codex/Claude Code) gets a sub-submenu instead of
  a flat toggle: `Enabled` checkbox + `Mute (hide sprite, keep daemon listening)`
  checkbox. `Enabled=false` keeps current behavior (source disabled entirely).
  `Mute=true` keeps the daemon source running and consuming events but the
  spawned pet host (multi-mode) or sprite-icon (single-mode) is hidden.
- Persisted to `~/.config/openpets-bridge/config.toml` under
  `[sources.<id>] muted = true/false`. Default `false`.
- Mute toggle requires bridge restart (same `runBridgeNeeded` pattern as existing
  `toggle-source`).
- Bridge CLI gets `openpets-bridge config mute-source <id>` and the unmute
  inverse (or a single `set-mute <id> <on|off>`).
- Python: `bridge/openpets_bridge/config.py` `set_source_mute(...)` mutation
  helper + export_json reports `muted` in source dict. `bridge/openpets_bridge/cli.py`
  exposes the CLI verb. Add a corresponding launchd reload step.
- Swift: `OpenPetsBridgeSubmenu.swift` parses `muted` field from BridgeState
  source rows; renders nested submenu instead of flat toggle.

**QW3 — Enrich OpenPetsCLI right-click menu** (`Sources/OpenPetsCLI/OpenPetsCLI.swift`):
Currently only 4 items. Add (above the `Quit this pet host` separator):
- `Hide this pet (until restart)` — call `NSApp.windows.first(where: { ... })?.orderOut(nil)`
  on the sprite overlay window; cheap "I'll be back" without disabling source.
  Reverse with a follow-up `Show this pet` item that flips visibility.
- `Switch pet pack ▸` — submenu listing all installed pet packs (from
  `~/Library/Application Support/OpenPets/Pets/`). Selecting one rewrites this
  source's `pet_dir` in bridge config + bootouts/bootstraps the agent, so
  the multi-mode spawner relaunches the host with the new pack. Reuse the
  same `runBridge args: ["config", "set-source-pet", sid, pet]` plumbing as
  the tray's `Pet for source ▸`. The CLI host needs to know which source
  it represents — pass `OPENPETS_BRIDGE_SOURCE_ID=<sid>` env when bridge
  spawns multi-mode hosts (see `bridge/openpets_bridge/modes/multi.py` or
  whatever launches `openpets run`).
- `Open Bridge submenu…` — opens the tray menu (just brings OpenPets.app
  to foreground; user can then click tray icon). Best-effort.

**QW4 — Bridge known issue triage** (right-click on multi-pet sprites empty):
- Repro by running `bridge mode = multi`, two sources enabled, restart bridge,
  right-click on a spawned sprite, observe.
- The 2026-05-11 hypothesis was "overlay window has ignoresMouseEvents for
  right-click, or OpenPetsCLIContextMenuTarget.shared lifecycle". With QW3
  the menu has more items and is more useful, so this becomes blocking.
- If the fix is local to `OpenPetsCLI.swift` (e.g. delegate target lifetime,
  responder chain, NSApp activation), do it. If it requires upstream
  `OpenPetsKit` SpriteView change (the contextMenuProvider isn't being
  invoked at all), document the upstream change needed in
  `bridge/FORK_NOTE.md` and leave a `// TODO upstream: ...` marker rather
  than vendoring OpenPetsKit.

### Medium — Preferences window

**M1 — `OpenPetsPreferencesWindow.swift` (new file).**
- NSWindowController + NSWindow with NSToolbar (3 tabs).
- Tab 1 "Display": scale slider 0.3–1.8 (replaces hand-edit of `config.json`),
  messageAreaHeight stepper 40–120. Live preview not required; save on Apply.
- Tab 2 "Bridge": Mode segment (single / multi), `poll_interval_s` stepper,
  `push_throttle_s` stepper, `auto_clear_after_s` stepper, Redact body checkbox.
- Tab 3 "Advanced": MCP host text, MCP port stepper, socket path text
  (read-only display), config folder path with "Reveal in Finder" button.
- Wired into tray menu as new item `Preferences…` (positioned before
  `Open Config Folder`). Keep `Open Config Folder` for power users.
- Persists via existing `OpenPetsConfiguration.save()` for `~/.config/openpets/config.json`
  AND shells out to `openpets-bridge config set-*` for bridge values.
- Hides "Bridge" tab if bridge binary not installed.

### Medium — per-spawn pet UUID (local-only, no upstream contract change)

**M2 — Track per-instance pet IDs in `OpenPetsHostSession` wrapper.**
- Currently multi-mode spawns one CLI host per source; each host knows its
  source but not a stable instance UUID. For future "spawn 2× Mando for Cowork"
  we need an ID.
- Add `bridge/openpets_bridge/modes/multi.py` (or equivalent) `instance_id`
  generation (UUID4 per spawn), pass via env `OPENPETS_INSTANCE_ID=<uuid>`.
- CLI host reads env, stores in `OpenPetsCLIRuntime`, and the right-click menu
  shows `Quit this pet host` -> `Quit this pet host (<uuid:8>)` for clarity
  when multiple Mandos are alive.
- This is groundwork — no UI yet to spawn duplicates. Leave a `// TODO: duplicate
  spawn UI in Preferences` marker.

## Out of scope (HEAVY refactor — do NOT do)

- Changing the `OpenPetsKit.OpenPetsHostSession.contextMenuProvider` contract
  to take a per-instance ID. That's an upstream PR to `alterhq/openpets` and
  requires their review. If QW4 reveals SpriteView itself doesn't call the
  provider, file the issue/PR upstream, don't vendor.
- Public release, App Store, GitHub release tag bump beyond `bridge-v0.3.1`,
  Sparkle appcast update — Maciej only.

## Acceptance criteria

1. `swift build -c release --product openpets-menubar -Xlinker -rpath -Xlinker '@loader_path/../Frameworks'` succeeds.
2. `swift build -c release --product openpets` succeeds.
3. `cd bridge && python3 -m pytest -q` shows ALL existing tests still pass + new tests for `set_source_mute` and `instance_id` propagation.
4. `pyproject.toml` bridge version bumped `0.3.0` → `0.3.1`. `openpets_bridge/__init__.py` `__version__` bumped to match.
5. Manual smoke checklist documented in `bridge/CHANGELOG.md` under `## [0.3.1]`:
   - tray shows `Display ▸` with 5 scale options
   - selecting a scale option restarts pet at new size
   - Bridge ▸ Sources ▸ Cowork ▸ shows Enabled + Mute sub-items
   - `openpets-bridge config mute-source cowork` works from CLI
   - tray has new `Preferences…` item opening 3-tab window
   - multi-mode right-click shows enriched menu (Hide, Switch pet pack ▸, etc.)
6. No new Swift warnings beyond the pre-existing baseline.
7. `FORK_NOTE.md` updated with the new feature list.
8. NO commits to `main` branch yet — work on branch `feat/preferences-mute-scale-instance-id`.
9. NO push to remote. Maciej reviews diff first.
10. NO new external dependencies (Swift packages, pip packages). Stdlib only on Python side; no new packages on Swift side beyond what's already in `Package.swift`.

## Verification commands Codex must run before declaring done

```bash
cd /Users/maciej/Projects/openpets-fork
swift build -c release --product openpets-menubar -Xlinker -rpath -Xlinker '@loader_path/../Frameworks' 2>&1 | tail -20
swift build -c release --product openpets 2>&1 | tail -20
cd bridge && python3 -m pytest -q 2>&1 | tail -10
cd .. && git status -sb
git diff --stat main..feat/preferences-mute-scale-instance-id
```

Codex must report each command's tail output in the final summary.

## Final output format

In the working directory, write `CODEX_RUN_REPORT.md` with:
- changed files list (`git diff --name-only main..HEAD`)
- per-feature status (QW1/QW2/QW3/QW4/M1/M2 — PASS/PARTIAL/SKIPPED + reason)
- verification command outputs
- any TODO markers added (upstream-required or otherwise)
- next-step recommendation for Maciej (review checklist + suggested commit message)

## Constraints — DO NOT

- DO NOT commit secrets, .env values, or API keys.
- DO NOT modify `Package.swift` to add dependencies. Reuse what's there.
- DO NOT touch `Sparkle.framework`, `Packaging/`, `Info.plist` version strings
  beyond what's strictly needed for `bridge-v0.3.1` tag bump (leave the version-bump for Maciej).
- DO NOT push to git remote. Local commits only on the feature branch.
- DO NOT delete the existing `OpenPetsBridgeSubmenu` tray entry. The Preferences
  window is additive, not a replacement.
- DO NOT bypass the 1-pet-per-source assumption in multi mode without the
  per-spawn UUID infrastructure (M2) in place first.

## Style

- Match existing Swift style in the repo (4-space indents, MARK comments,
  `@MainActor` annotations where AppKit is involved).
- Match existing Python style (4-space indents, type hints on new public
  functions, docstrings with one-line summary).
- New tests follow the pattern in `bridge/tests/test_cowork_source.py` /
  `test_config.py` if present.
