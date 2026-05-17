# Changelog

## [0.4.1]

### Added

- **GenericJsonlSource**: users can now add their own LLM without writing
  Python. Drop a `[sources.<my_id>]` block in `config.toml` with
  `extra.type = "generic_jsonl"` and the bridge picks it up. Supports
  custom role mappings (`role_field`, `running_roles`, `done_roles`, …)
  for tools whose schema differs from the chat-completion default. Worked
  example for Ollama in `bridge/README.md` → "Adding your own LLM".
- New test file `tests/test_generic_source.py` (7 tests). Total now 39.

### Fixed

- **Logging**: removed the duplicate `StreamHandler` in `orchestrator.py`
  — every bridge log line used to land in both `bridge.log` AND
  `launchd.stderr.log`. New runs only write `bridge.log`.
- **Log rotation**: `FileHandler` → `RotatingFileHandler` (1 MB × 3
  backups). Bridge log can no longer grow unbounded.
- **Cowork "done after idle"** (`sources/cowork.py`): added a
  `grew_under_watch` flag so the final `✓ Done` bubble actually fires
  when a Cowork session goes quiet. Previously the comparison
  `last_size < stt.st_size` was structurally always False, so the
  branch never executed.
- **launchd reload race** (`cli.py`): extracted `_reload_launchd_agent`
  helper with `bootout → sleep(0.8) → bootstrap → retry`. `cmd_install`
  now uses the same path as `_restart_bridge_daemon`, so first-time
  installs don't hit "Bootstrap failed: 5: Input/output error".
- **Python detection**: `_python_executable()` probes 3.14, 3.13, 3.12,
  3.11, 3.10 across both `/opt/homebrew/bin` and `/usr/local/bin`, then
  globs `python3.*`. No more hardcoded Python 3.12 in the launchd plist.
- **Atomic state save** (`state.py`): `os.replace` failures clean up
  their orphan `*.tmp` file; `ThreadStore.load()` prunes stale `*.tmp`
  files older than 5 minutes from previous crashes.
- **Dead host respawn**: `MultiPetMode.tick` checks `proc.poll()` on
  each child `openpets run` host and re-spawns the dead ones.
  `_spawn_hosts` is idempotent (skips sources already alive).
- **Default log location**: new installs write to
  `~/Library/Logs/openpets-bridge/bridge.log` (macOS convention). Old
  configs pointing at `~/ai-stack/openpets-bridge/bridge.log` keep
  working.

### Changed

- `_setup_logging` is now idempotent — re-calls remove old handlers
  before adding the new ones.
- `install.sh`: pipx URL gained `#subdirectory=bridge` so the advertised
  one-liner actually works against this fork's repo layout.
- Replaced bespoke `shutil_quote()` with stdlib `shlex.quote`.
- "No pet packs found" hint now points at `https://openpets.sh/gallery`
  (matches upstream's gallery URL — was `openpets.dev`).

### Swift-side companions (OpenPets.app)

These changes ship in the same fork commit but belong to the menubar app
rather than the Python bridge; listed here so the deployment story stays
in one place.

- **"Quit this pet host" actually quits**: the CLI now drops a
  `/tmp/openpets-quit-<source>.marker` before terminating, and
  `MultiPetMode._respawn_dead_hosts` checks for the marker before
  re-spawning. Without this, the bridge's crash-recovery (P2-2) was
  immediately re-launching every user-quit host, making the menu item
  useless. Crashes (no marker) still respawn as before. New file
  `tests/test_multi_pet_quit.py` covers user-quit, plain crash, and
  mixed cases — pytest now 42/42.
- **QW4 fix**: right-click on bridge-spawned multi-pet sprites now
  actually shows the context menu. The CLI host runs with `.accessory`
  activation policy and was never frontmost, so AppKit silently
  dismissed `popUpContextMenu` before the menu appeared. The
  `OpenPetsCLIContextMenu.make()` provider now calls
  `NSApplication.shared.activate(ignoringOtherApps: true)` first, which
  fixes the empty-right-click reported on 2026-05-11. Verified live
  with `~/Library/Logs/openpets-bridge/cli-host-debug.log` (HOST_STARTED
  + per-click `contextMenu.make()` invocations).
- `OpenPetsBridgeSubmenu` refactored to stop sharing `NSMenuItem`
  instances across menus. Fixes the `NSInternalInconsistencyException`
  that fired when the Bridge submenu was attached to both the status
  menu and the pet right-click menu (the failing test
  `testPetContextMenuMatchesStatusMenuTopLevelItems` now passes).
- `Timer.scheduledTimer` replaced with `Task` + `Task.sleep` loop, per
  the project's Agents.md style guide.
- `bridgeIsRunning()` now uses `launchctl print gui/$UID/<label>`
  instead of fragile substring parsing of `launchctl list`.
- Subprocess helpers capture stdout/stderr separately so JSON parsers
  don't ingest log noise.
- Single shared `BridgeBinaryLocator` (with PATH fallback) used from the
  Bridge submenu, Preferences window, and CLI.
- Optional diagnostic logging in `OpenPetsCLIContextMenu` writes one
  line per right-click to `~/Library/Logs/openpets-bridge/cli-host-debug.log`
  — keeps future QW4-style regressions easy to root-cause.

## [0.4.0]

- Added opt-in LLM CLI source presets for Aider, Gemini CLI, OpenCode, Continue, and Cline, with source discovery, config verbs, tray/preference surfacing, and smoke tests.

## [0.3.1]

- Tray shows `Display ▸` with 5 scale options.
- Selecting a scale option restarts the pet at the new size.
- `Bridge ▸ Sources ▸ Cowork ▸` shows `Enabled` and `Mute (hide sprite, keep daemon listening)` sub-items.
- `openpets-bridge config mute-source cowork` works from CLI and reloads launchd when installed.
- Tray has a new `Preferences…` item opening a 3-tab window.
- Multi-mode right-click shows enriched menu items including Hide, Switch pet pack, Display, Bridge, and instance-specific Quit.
- Multi-pet hosts receive `OPENPETS_BRIDGE_SOURCE_ID` and `OPENPETS_INSTANCE_ID`.
