# MacSiem's fork of OpenPets

This is a fork of [**alterhq/openpets**](https://github.com/alterhq/openpets).

## All credit to alterhq

The desktop pet, the spritesheet renderer, the per-pet position store, the
MCP server, the `notify --thread` IPC protocol, the launchd integration,
the OpenPetsKit Swift package, and the install/upgrade story — **all of
that is upstream alterhq's work.** They did the hard parts.

If you want to use OpenPets normally, you don't need this fork at all.
Install the official build from
[**alterhq's releases**](https://github.com/alterhq/openpets/releases/latest).

## What this fork adds

A small set of additive features layered on top of the upstream tree. All
the upstream code is untouched (no behavior regressions), and these
changes are PR-able back to alterhq if/when they want them.

### 1. `openpets-bridge` — a multi-AI activity daemon (Python)

Lives entirely in [`bridge/`](./bridge/) — a self-contained Python
package with zero runtime dependencies (stdlib only) installable via
`pipx`. It watches the on-disk session logs of multiple AI coding
agents and forwards their activity to OpenPets through the documented
`notify --thread <uuid>` protocol — so the pet reacts to whichever
agent is currently working, with **per-conversation persistent bubbles**
(like Codex's built-in pet, but for every AI you run).

Supported sources out of the box:

| Source           | Watches                                   |
| ---------------- | ----------------------------------------- |
| **Cowork**       | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../audit.jsonl` |
| **Codex CLI**    | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| **Claude Code CLI** | `~/.claude/projects/<encoded-cwd>/<sessionUUID>.jsonl` |
| **Aider**        | `~/.aider/sessions/*.jsonl` or `.aider.chat.history.md` |
| **Gemini CLI**   | `~/.config/gemini-cli/sessions/*.jsonl` or `~/.gemini/history/*.jsonl` |
| **OpenCode**     | `~/.local/share/opencode/sessions/*.jsonl` or `~/.opencode/sessions/*.jsonl` |
| **Continue CLI** | `~/.continue/sessions/*.json` |
| **Cline**        | `~/.config/cline/tasks/*.jsonl` or VS Code extension task storage |

The LLM CLI presets are disabled by default. Use `openpets-bridge discover-sources`,
`openpets-bridge config add-source-preset <preset_id>`, or the native
Preferences `Sources` tab to detect and enable them.

**Adding your own LLM** — for any tool not listed above, the bridge ships a
config-only `generic_jsonl` source type. Drop a `[sources.<my_id>]` block
into `~/.config/openpets-bridge/config.toml` with `extra.type =
"generic_jsonl"` and the path(s) to watch. No Python required. Full guide:
[`bridge/README.md`](./bridge/README.md#adding-your-own-llm).

Two display modes — switchable from the tray menu (no config file edit
needed):

* **Single pet** — one shared pet sprite, each bubble title prefixed with
  the source icon (🤝 Cowork, 🟢 Codex, 🟠 Claude Code …).
* **Multi-pet** — one OpenPets host per AI source, each with its own
  sprite (e.g. Mando for Cowork, Grogu for Codex).

Privacy-first: a single config flag (`redact_body = true`) replaces every
bubble body with just the tool glyph (`▶ ✎ 📖 🔎 🌐 🤖 ❓ …`) — never
echoes file paths, commands, prompts, or queries to screen or to logs.
No telemetry, no network calls, no analytics, no SaaS.

See [`bridge/README.md`](./bridge/README.md) for the full guide
(install / configure / contribute).

### 2. "Bridge ▸" section in the OpenPets tray menu (Swift)

Implemented in
[`Sources/OpenPetsMenuBar/OpenPetsBridgeSubmenu.swift`](./Sources/OpenPetsMenuBar/OpenPetsBridgeSubmenu.swift)
and wired into the existing tray menu builder. No extra menubar icon
needed — controls live alongside the upstream OpenPets entries.

Submenu contents (live-refreshed; checkmarks always reflect the actual
config and daemon state):

```
Bridge ▸
  Bridge: running                  (or "stopped" / "not installed")
  ──────
  Start / Stop / Restart Bridge
  ──────
  Mode ▸
      ✓ Single pet (icon per bubble)
        Multi-pet (one pet per AI)
  Sources ▸
      🤝 Cowork ▸
          ✓ Enabled
            Mute (hide sprite, keep daemon listening)
      🟢 Codex ▸
          ✓ Enabled
            Mute (hide sprite, keep daemon listening)
      🟠 Claude Code ▸
            Enabled
            Mute (hide sprite, keep daemon listening)
  Pet for source ▸                 (multi mode only)
      🤝 Cowork ▸  Mandalorian / Starcorn / …
      🟢 Codex  ▸  Grogu Kid / …
  ──────
  Open Bridge Config
  Open Bridge Log
  List Installed Pet Packs
  ──────
  Clear Done Bubbles
  Clear ALL Bubbles
```

Each toggle/pick atomically rewrites `~/.config/openpets-bridge/config.toml`
and restarts the bridge daemon. Comments and formatting in the user's
config are preserved.

The main tray also adds **Preferences…** with **four native tabs**:

* **Display** — pet display settings (scale, message area height).
* **Bridge** — bridge mode, poll/throttle intervals, redact-body toggle.
* **Sources** — checkbox list of every known LLM CLI preset with
  Installed / Not detected status from `discover-sources` and a "Reveal
  in Finder" shortcut to the watch path. Right place to enable Aider,
  Gemini, OpenCode, Continue, Cline.
* **Advanced** — MCP host/port, socket path, config folder reveal.

Bridge ▸ also has a top-level **Manage CLI sources…** shortcut that
opens Preferences directly to the Sources tab.

(Earlier fork builds shipped a separate `Display ▸` scale picker in the
tray; that's been removed in favour of upstream's per-pet `Scale ▸`
submenu, which does the same job and integrates with OpenPetsKit 0.2.1.)

### 3. Right-click on CLI-spawned sprites (Swift)

[`Sources/OpenPetsCLI/OpenPetsCLI.swift`](./Sources/OpenPetsCLI/OpenPetsCLI.swift)
— `openpets run` now uses `OpenPetsHostSession` with a
`contextMenuProvider`, so multi-pet hosts spawned by `openpets-bridge`
get a right-click context menu on the sprite ("Open OpenPets", "Open
Config", "Display", "Hide this pet", "Switch pet pack", "Open Bridge
submenu", and "Quit this pet host"). Bridge-spawned hosts receive
`OPENPETS_BRIDGE_SOURCE_ID` and `OPENPETS_INSTANCE_ID`; the latter appears
as an 8-character suffix in the Quit menu item so duplicate-spawn
groundwork is available without changing the upstream OpenPetsKit API.
The upstream behavior of `OpenPetsHost.run` (used by the menubar's
"Wake Pet") is unchanged.

## Quickstart

```bash
# 1) Install the OpenPets desktop app from this fork (single command,
#    inspect first if you want):
curl -fsSL https://raw.githubusercontent.com/MacSiem/openpets/main/bridge/install.sh | bash

# 2) Open the 🐾 in your menu bar. Under "Bridge ▸" you can switch mode,
#    toggle which AIs the pet reacts to, and pick a sprite per AI.
```

## License

MIT — same as upstream. See [`LICENSE`](./LICENSE).

## Submitting changes back

The Swift additions in this fork are deliberately small, isolated, and
behind no special build flags. The ones we'd most like to see merged
upstream are collected in
[`docs/upstream-proposals/`](./docs/upstream-proposals/) — each as a
short markdown doc with problem statement, repro, exact diff, and
suggested PR title/commit message. They're stand-alone (no bridge
dependency) and rebased onto upstream `main` semantics so they're
ready to PR as soon as alterhq says yes.

We also keep a discussion-only issue draft for `alterhq/openpets` at
[`docs/upstream-proposals/issue-draft-bridge-companion.md`](./docs/upstream-proposals/issue-draft-bridge-companion.md)
so the bridge's existence isn't a surprise if alterhq browses fork
network.
