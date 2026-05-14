# Codex task spec — OpenPets fork: LLM CLI source presets

Authorization: explicit Maciej "Go" + earlier "Czy codex (personal limit) może dodać do aplikacji wybór LLM CLI?" (Cowork session 2026-05-14, continuation of bridge-v0.3.1 work).
Auth profile: **`~/.codex` (ChatGPT subscription)**. NOT API.
Routing class: `codex-worker`. Scope: in-repo Swift + Python only.
Repo: `/Users/maciej/Projects/openpets-fork` — same fork as v0.3.1.
Branch: `feat/llm-cli-sources` (new, branched off `feat/preferences-mute-scale-instance-id`).

## Why this exists

The bridge currently watches 3 hardcoded sources (Cowork, Codex CLI, Claude Code CLI). Maciej wants to extend the same mechanism to other popular LLM CLIs so the same pet (Mando in multi mode, or icon-prefixed bubbles in single mode) reflects activity from Aider, Gemini CLI, gpt-cli/OpenCode, Continue, and Cline. Bridge already has the right architecture (`sources/base.py` + per-source modules + multi/single mode + tray submenu); we just need to add new source modules + UI surface for enabling them.

## Baseline today

```
bridge/openpets_bridge/sources/
├── __init__.py           # source registry
├── base.py               # SourceConfig + Event dataclasses, common helpers
├── claude_code.py        # 76 lines — watches ~/.claude/projects/<encoded>/<uuid>.jsonl
├── codex_cli.py          # 158 lines — watches ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
└── cowork.py             # 263 lines — watches Cowork audit.jsonl
```

Config schema (`~/.config/openpets-bridge/config.toml`):

```toml
[sources.cowork]
enabled = true
muted = false
label = "Cowork"
icon = "🤝"
redact_body = false
[sources.cowork.extra]
pet_dir = "..."
socket = "..."
```

Tray:
- `Bridge ▸ Sources ▸` lists configured sources (already iterates from `BridgeState.sources` after v0.3.1, so new sources appear automatically once exposed in config)
- Each source row has nested `Enabled` + `Mute` checkboxes (v0.3.1)

Preferences window (3 tabs: Display / Bridge / Advanced) added in v0.3.1.

## Goal — implement ALL of the below

### S1 — Five new LLM CLI source modules

Create one Python module per CLI in `bridge/openpets_bridge/sources/`. Each module subclasses `Source` (or whatever the base class in `base.py` is) and implements `iter_events()` over the canonical jsonl/text logs of that CLI. Default state: `enabled = false` (user opts in).

**S1a — `aider.py` — Aider AI coding tool (paul-gauthier/aider)**
- Watch: `~/.aider/sessions/*.jsonl` plus per-cwd `.aider.chat.history.md` if jsonl absent. Detect newer-than-baseline lines on each poll.
- Format: Aider streams structured events including `{"role": "assistant", "tool_calls": [...]}` and shell commands via `/run`. Map to states:
  - `tool_calls` present → `running`
  - `assistant` text reply with no tool_calls → `done`
  - `user` waiting for input → `waiting`
- Label: `Aider`. Icon: `🦅`. (Aider's mascot is an aviator-style icon; pick a sensible emoji.)
- Default `enabled = false`.

**S1b — `gemini_cli.py` — Google Gemini CLI (google/generative-ai-cli)**
- Watch: `~/.config/gemini-cli/sessions/*.jsonl` if exists; fall back to `~/.gemini/history/*.jsonl`. If neither path is canonical, document the path discovery in module docstring and pick the most likely one based on actual installations.
- Format: similar `{"role", "content"}` lines. Map tool-call presence the same way as Aider.
- Label: `Gemini`. Icon: `🪷` (Gemini-ish stylized).
- Default `enabled = false`.

**S1c — `opencode.py` — Charm OpenCode / gpt-cli successor (charmbracelet/opencode)**
- Watch: `~/.local/share/opencode/sessions/*.jsonl` or `~/.opencode/sessions/*.jsonl` (pick whichever is canonical; doc in module).
- Format: OpenCode uses Bubbletea TUI and persists turns as jsonl. Each turn includes `role`, `parts` array with text + tool invocations.
- Label: `OpenCode`. Icon: `🌊` (Charm wave).
- Default `enabled = false`.

**S1d — `continue_cli.py` — Continue (continuedev/continue) CLI/agent**
- Watch: `~/.continue/sessions/*.json` (Continue stores per-session JSON, not jsonl; module must read whole file each poll and emit only new turns).
- Format: nested objects with `history` array.
- Label: `Continue`. Icon: `⏩`.
- Default `enabled = false`.

**S1e — `cline.py` — Cline (formerly Claude Dev VS Code extension, has CLI mode)**
- Watch: `~/.config/cline/tasks/*.jsonl` or VS Code extension data path (auto-detect both, prefer first that exists).
- Format: jsonl with `type`, `role`, `content` fields.
- Label: `Cline`. Icon: `🧬`.
- Default `enabled = false`.

For all five: module file MUST NOT exceed 200 lines. If a CLI's format isn't well-documented or the watch path is unknown, write the module with a "best-effort default path + TODO marker for upstream confirmation" rather than skipping.

### S2 — Source auto-discovery

Add `bridge/openpets_bridge/discovery.py` (new module, ~80-120 lines):

- Single function `discover_installed_sources() -> dict[str, dict]` that returns a dict keyed by source id with:
  - `installed: bool` — whether the CLI binary is on PATH or watch path has data
  - `watch_path: str | None` — resolved canonical path
  - `last_activity: datetime | None` — mtime of most recent file in watch dir
- Probe logic per source: check `which <cli_bin>` first, then check watch dir for `*.jsonl` / `*.json` files.
- Exposed via `openpets-bridge discover-sources` CLI verb (new) and via `config show` output (extend BridgeState JSON to include `discovery` field per source).

### S3 — Config schema extension

Update `bridge/openpets_bridge/config.py`:

- New mutation helper `add_source_preset(preset_id: str) -> Path` that writes `[sources.<preset_id>]` block with sane defaults if not present. Idempotent.
- New helper `remove_source(preset_id: str)` for the rare unbind case. Refuse on builtin sources (cowork/codex_cli/claude_code).
- Update `_export_json()` so it includes new sources without listing them as "unknown".

Update `default_config.toml` (or wherever the bundled default lives) to include commented-out blocks for all 5 new presets, with example `enabled = false` so users see them on first init.

### S4 — CLI verbs

Add to `bridge/openpets_bridge/cli.py`:

- `openpets-bridge discover-sources` — print human-readable table of discovery results (one row per known preset + builtin, columns: id, installed, watch_path, last_activity).
- `openpets-bridge config add-source-preset <preset_id>` — calls `add_source_preset()`, then `_restart_bridge_daemon()`.
- `openpets-bridge config remove-source <preset_id>` — calls `remove_source()`, then `_restart_bridge_daemon()`.

### S5 — Tray menu surfacing

`Sources/OpenPetsMenuBar/OpenPetsBridgeSubmenu.swift`:

- `Bridge ▸ Sources ▸` should already iterate dynamically over `BridgeState.sources` after v0.3.1. Verify that new sources from config show up without code changes.
- Add `Bridge ▸ Manage CLI sources…` item below `Sources ▸` that opens Preferences window directly to the Sources tab (see S6). Implementation: post `NSNotification.Name("OpenPetsPreferencesSourcesTab")` that the Preferences controller listens for.

### S6 — Preferences "Sources" tab

`Sources/OpenPetsMenuBar/OpenPetsPreferencesWindow.swift`:

- Add 4th `NSTabViewItem` with identifier `sources` and label "Sources".
- Tab contents: scrollable list of checkboxes, one per known preset (5 new + builtins). Each row shows:
  - Checkbox: `Enabled`
  - Source label + icon
  - Right-aligned status: `Installed`/`Not detected` (from discovery)
  - Optional: small "Reveal in Finder" button on `watch_path` if installed
- Apply: enabling a preset that's not in config calls `add-source-preset` via the bridge CLI; disabling calls `toggle-source` or removes it. Either way `_restart_bridge_daemon` happens.
- Listen for `OpenPetsPreferencesSourcesTab` notification → select Sources tab on window open.

### S7 — Tests

In `bridge/tests/`:

- `test_discovery.py` (new): fake CLI bins via `monkeypatch.setattr(shutil, "which", ...)`, fake watch dirs via tmp_path, verify `discover_installed_sources` returns correct dict.
- Extend `test_config.py` with `test_add_source_preset_*` and `test_remove_source_*` scenarios. Refuse-on-builtin must raise `ValueError`.
- `test_sources_aider.py` (new): minimal smoke test that `AiderSource(config).iter_events()` returns `Event` objects from a tmp jsonl fixture. Same kind of smoke for `gemini_cli`, `opencode`, `continue_cli`, `cline` if format is implemented. If format wasn't fully implementable (TODO marker), the test can be `@pytest.mark.skip("format TBD")` with reason.

Target: at least 6 new passing tests on top of the 16 from v0.3.1. Total ≥ 22 passing.

## Acceptance criteria

1. `swift build -c release --product openpets-menubar -Xlinker -rpath -Xlinker '@loader_path/../Frameworks'` PASS.
2. `swift build -c release --product openpets` PASS.
3. `cd bridge && /opt/homebrew/bin/python3 -m pytest -q` ≥ 22 passed.
4. `pyproject.toml` bump `0.3.1` → `0.4.0`. `__version__` matches.
5. `bridge/CHANGELOG.md` new `## [0.4.0]` section with one-line summary of S1-S7.
6. `FORK_NOTE.md` updated with the LLM CLI preset list.
7. NO commits to `main` yet — branch `feat/llm-cli-sources` only.
8. NO push to remote.
9. NO new external dependencies. Stdlib only on Python side, no Swift Package additions.
10. The bundled `default_config.toml` (or equivalent) includes commented-out preset blocks for all 5 new CLI presets so a fresh `openpets-bridge init` exposes them.

## Verification commands Codex must run

```bash
cd /Users/maciej/Projects/openpets-fork
swift build -c release --product openpets-menubar -Xlinker -rpath -Xlinker '@loader_path/../Frameworks' 2>&1 | tail -15
swift build -c release --product openpets 2>&1 | tail -15
cd bridge && /opt/homebrew/bin/python3 -m pytest -q 2>&1 | tail -10
cd .. && git status -sb
git diff --stat feat/preferences-mute-scale-instance-id..HEAD
```

## Final output

Write `CODEX_RUN_REPORT_LLM_CLI.md` with:
- per-preset implementation status (S1a..S1e — PASS / PARTIAL+reason / SKIPPED+reason)
- discovery + CLI verbs status (S2, S3, S4)
- tray + preferences status (S5, S6)
- test results (S7)
- verification command tail outputs
- TODO markers added (especially upstream-confirmation-needed paths)
- recommended commit message

## Constraints — DO NOT

- DO NOT commit secrets.
- DO NOT modify `Package.swift` to add deps.
- DO NOT touch the Sparkle appcast, Info.plist version (Maciej bumps Info.plist).
- DO NOT push to git remote.
- DO NOT change builtin source files (`cowork.py`, `codex_cli.py`, `claude_code.py`) beyond what's needed to integrate with new discovery (e.g. consistent `iter_events()` signature). Touching their core logic is out of scope.
- DO NOT vendor any CLI's session format. If a CLI's format is undocumented and you can't find samples, leave the source module with a `# TODO: confirm format from real session` and a working scaffolding that emits no events — better an empty source than a wrong parser.
- DO NOT remove `muted`, `enabled`, or other v0.3.1 fields from SourceConfig — only extend.

## Style

- Match v0.3.1 Swift style (4-space, MARK comments, @MainActor).
- Match existing Python style (4-space, type hints on public functions, one-line docstring summaries).
- Source modules should be self-contained — no shared global state.
- Discovery probe should never raise on missing path — return `installed=False` cleanly.
