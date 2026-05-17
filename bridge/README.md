# openpets-bridge

> Multi-AI Python orchestration layer for [OpenPets](https://github.com/alterhq/openpets)
> by [alterhq](https://github.com/alterhq).
>
> **All credit for the desktop pet, the MCP server, and the IPC API goes
> to the alterhq team** — this is just a small daemon that talks to their
> documented `notify --thread <uuid>` interface. The bridge lives in
> `bridge/` of the [MacSiem/openpets fork](https://github.com/MacSiem/openpets).

> One desktop pet for **every** AI agent on your Mac.
> See Cowork, Codex CLI, and Claude Code speak through one shared
> OpenPets sprite — or one sprite per AI.

`openpets-bridge` is a small Python daemon that watches the activity logs
of multiple AI coding agents and forwards their status to OpenPets as
**threaded, persistent bubbles** (title + body + status icon, just like
Codex's built-in pet). It works whether the agent supports OpenPets
natively or not — it just tails the on-disk session files the agents
already write.

```
[🤝 Cowork] Refactor Mando bridge   ▶ python3 -m openpets_bridge run
[🟢 Codex]  Plan trial premium      ✓ Done
[🟠 Claude] Review PR #312          ❓ Waiting for your approval
```

---

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/MacSiem/openpets/main/bridge/install.sh | bash
```

…or, if you'd rather inspect the script first (recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/MacSiem/openpets/main/bridge/install.sh -o install.sh
less install.sh
bash install.sh
```

The installer checks Python ≥ 3.10, pipx, and OpenPets.app, then installs
the bridge in an isolated pipx venv, writes a default config, registers
two launchd agents so they auto-start at login (the headless **bridge
daemon** + an optional **menu-bar app**), and prints a one-line summary.

After install you should see a 🐾 icon in your macOS menu bar — click it
for status, start/stop, open config, open log, list installed pet packs,
and a link to the docs.

For a headless install (server / CI / no menubar):

```bash
OPENPETS_BRIDGE_HEADLESS=1 bash install.sh
# or after install:
openpets-bridge install --no-menubar
```

> **Prerequisite:** [OpenPets ≥ 0.6](https://github.com/alterhq/openpets/releases/latest)
> (the **alterhq** native Swift build — not the older alvinunreal Electron
> one). Install OpenPets first, then run the bridge installer.

### Manual install (no curl-bash)

```bash
# Requires: macOS, Python 3.10+, pipx, OpenPets.app
pipx install 'git+https://github.com/MacSiem/openpets.git#subdirectory=bridge'
openpets-bridge init        # writes ~/.config/openpets-bridge/config.toml
openpets-bridge status      # sanity check (sources enabled + pet ping)
openpets-bridge install     # registers the launchd agent
```

### Discover installed pet packs

```bash
openpets-bridge list-pets
```

Walks `~/Library/Application Support/OpenPets/Pets/`, `~/.codex/pets/`,
and the standard XDG locations. Useful when configuring multi-pet mode.

### Recipes

Drop-in configs in [`examples/`](./examples):

* [`config.toml`](./examples/config.toml) — the default (one pet, AI icon prefix).
* [`config-multi-pet.toml`](./examples/config-multi-pet.toml) — one pet sprite per AI source.
* [`config-stream-safe.toml`](./examples/config-stream-safe.toml) — privacy mode for screen-sharing / live-streaming.
* [`config-codex-only.toml`](./examples/config-codex-only.toml) — follow only Codex CLI activity.

```bash
openpets-bridge run --config /path/to/recipe.toml
```

## Configure

**Easiest path: use the tray menu.** Click the 🐾 in your menu bar →
**Bridge ▸**, and you'll find live toggles for:

* **Mode** — switch between Single (one pet, AI icon per bubble) and
  Multi (one pet per AI).
* **Sources** — tick Cowork, Codex, Claude Code on or off without
  touching any file, or mute one while keeping its daemon source polling.
* **Pet for source** (Multi mode) — pick the sprite a given AI wears,
  from the pet packs you already have installed.

Each toggle atomically rewrites `~/.config/openpets-bridge/config.toml`
and restarts the bridge daemon. Comments and your formatting are
preserved.

You can also do everything from the CLI:

```bash
openpets-bridge config show                        # JSON dump
openpets-bridge config set-mode multi              # switch mode
openpets-bridge config toggle-source claude_code   # on/off
openpets-bridge config mute-source cowork          # hide output, keep polling
openpets-bridge config set-source-pet cowork \
  "/Users/you/Library/Application Support/OpenPets/Pets/mandalorian"
```

If you'd rather edit TOML directly, the full guide is in
[**docs/CONFIGURATION.md**](./docs/CONFIGURATION.md):

* **Easy** — install once, never edit anything. Cowork + Codex CLI auto-detected.
* **Common tweaks** — turn AIs on/off, change icons, enable privacy mode, switch pet sprite.
* **Advanced** — multi-pet mode, custom AI sources, alternate paths, no-launchd run.

Edit `~/.config/openpets-bridge/config.toml`. Defaults already enable
Cowork and Codex CLI; flip Claude Code on if you use the `claude` CLI.

```toml
[bridge]
mode = "single"            # "single" (one pet) | "multi" (one pet per AI)

[sources.cowork]
enabled = true
muted = false                # hide output while keeping the source polled
icon = "🤝"
label = "Cowork"
redact_body = false        # privacy mode (see below)

[sources.codex_cli]
enabled = true
muted = false
icon = "🟢"
label = "Codex"
redact_body = false

[sources.claude_code]
enabled = false            # turn on when you use the `claude` CLI
muted = false
icon = "🟠"
label = "Claude Code"
redact_body = false
```

After edits, restart the bridge:

```bash
launchctl bootout gui/$(id -u)/sh.openpets.bridge
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/sh.openpets.bridge.plist
```

### Single-pet vs multi-pet

| | `mode = "single"` (default) | `mode = "multi"` |
|---|---|---|
| OpenPets hosts | one shared | one per source |
| Sprite | your active OpenPets pet | one pet pack per source (configure under `[sources.*.extra]`) |
| Bubbles | stack on the same pet, prefixed with the source icon | each pet has its own bubble stack |
| Resource use | minimal | one extra Swift host per AI |
| Status | **stable** | beta — multi-host on separate sockets only verified for two AIs so far |

## Privacy

The bridge reads your AI session transcripts to detect activity. By
default the **bubble body** (the second line of each pet bubble) shows a
small slice of the latest tool input — the basename of the file being
edited, the first ~40 chars of a shell command, the search query, etc.
That helps you tell at a glance what's happening, but it does mean
fragments of your prompts and commands appear briefly on screen.

**If you stream, pair, or screen-share**, set `redact_body = true` per
source in `config.toml`. The bridge will then push only the **tool
glyph** (`▶ ✎ 📖 🔎 🌐 🤖 ❓ …`) — never the input.

The bridge **never logs** bubble titles or bodies to disk: the launchd
log records only `[<source>/<session-prefix>] status=<state>`. Configure
the same way you would any unprivileged user-level daemon. No telemetry,
no network calls, no analytics — zero runtime dependencies beyond Python's
standard library.

The bridge **does** persist a small state file at
`~/.local/state/openpets-bridge/threads.json` (file mode `0600`, user-only)
so that after a daemon restart the same conversation reuses the same
OpenPets `threadId` — that way the next `notify` *replaces* the existing
bubble instead of creating a duplicate. The state file mirrors what is
shown in the bubble, so it respects `redact_body = true` per source. If
you'd prefer no state on disk, set `redact_body = true` and clear the file
periodically — or `rm ~/.local/state/openpets-bridge/threads.json` (the
bridge will rebuild it).

## How it compares

| | `claude-pets` | `opencode-pets` | **`openpets-bridge`** |
|---|---|---|---|
| Activates from | Claude Code hooks | OpenCode plugin | direct file tail (works with Cowork too) |
| Bubble | brief test pulse | brief test pulse | **persistent threaded** (`notify --thread`) |
| Multi-AI | no | no | **yes — one icon per AI or one pet per AI** |
| Per-conversation | no | no | **yes — threadId per session** |
| Privacy toggle | n/a | n/a | **yes — `redact_body = true`** |
| Runtime deps | Bun + Node | Bun + Node | Python 3.10 stdlib only |

## Troubleshooting

**`openpets-bridge status` says `openpets ping: NOT REACHABLE`.**
Launch OpenPets.app first. The menu bar icon needs to be present and the
pet awake (use *Wake Pet* from the OpenPets tray menu, or run
`openpets notify --title test --status running --text test`).

**Bubbles don't appear even though the log shows `pushed`.**
The pet sprite may be off-screen. Open `~/.config/openpets/positions.json`,
delete the entry for your active pet, and relaunch OpenPets.

**Old / stale bubbles appeared when I started the bridge.**
The bridge silently **baselines** every session it finds at startup —
nothing emits for sessions that were already on disk. If you still see
stale bubbles immediately after install, they may be left over from the
official `claude-pets` test events; quit OpenPets, run
`openpets clear --thread <id>` for each, then relaunch.

**My prompts are showing up in the bubble.**
That's the default body. Set `redact_body = true` for that source.

**I want to disable the bridge temporarily.**
`launchctl bootout gui/$(id -u)/sh.openpets.bridge`. To re-enable:
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/sh.openpets.bridge.plist`.
To uninstall completely: `openpets-bridge uninstall && pipx uninstall openpets-bridge`.

## Adding your own LLM

You don't have to write any Python — most LLM CLIs already persist their
sessions as JSON-lines files, and the bridge ships a config-driven
`GenericJsonlSource` that reads them directly.

### Minimal example — Ollama

Add this block to `~/.config/openpets-bridge/config.toml`:

```toml
[sources.ollama]
enabled = true
label   = "Ollama"
icon    = "🦙"

[sources.ollama.extra]
type     = "generic_jsonl"
roots    = ["~/Library/Application Support/ollama/sessions"]
patterns = ["*.jsonl"]
```

Then `openpets-bridge config show` to confirm, and restart the daemon:
`launchctl kickstart -k gui/$(id -u)/sh.openpets.bridge`. New JSONL
records appended to any file under `roots` will surface as pet bubbles.

### How the mapping works (zero-config defaults)

The bridge looks at each new JSONL record and applies these heuristics
(in order):

1. Record has a `tool_calls` / `parts[tool]` / `tool_invocations` field
   → status **running** (the tool's name is shown in the bubble).
2. `role` is `user` / `ask` / `input` → status **waiting** (the pet
   shows "⌛ Waiting").
3. `role` is `assistant` → status **done** (the bubble shows the
   assistant's text reply, truncated to one line).
4. `role` is `error` / `failed` → status **failed**.
5. Anything else → status **message**.

That works out-of-the-box for: Ollama, llamafile, vLLM chat logs, any
OpenAI-compatible JSON streams persisted to disk, plus most homegrown
agent loops.

### Custom role mapping

If your tool uses a different field name or non-standard role labels,
override them in `extra`:

```toml
[sources.my_homegrown_agent.extra]
type     = "generic_jsonl"
roots    = ["~/dev/agent-logs"]
patterns = ["run-*.jsonl"]

role_field    = "speaker"             # default: "role" or "type"
running_roles = ["thinking", "tool"]
done_roles    = ["agent", "model"]
waiting_roles = ["human", "user"]
failed_roles  = ["error"]
```

### When `generic_jsonl` isn't enough

If your tool writes a really custom format (binary, multi-line records,
nested JSON-in-text, …), drop a Python module into
`bridge/openpets_bridge/sources/`, subclass
`openpets_bridge.sources.base.Source`, implement `poll()` to yield
`SourceUpdate` snapshots, and add it to the `REGISTRY` in
`sources/__init__.py`. The eight built-in sources are short worked
examples (≤ 200 lines each). PRs welcome.

## Acknowledgements

* [alterhq/openpets](https://github.com/alterhq/openpets) — the native
  macOS pet host and the rich `notify` API this whole project depends on.
* [openpets.sh](https://openpets.sh/gallery) — pet packs and the canonical
  spritesheet format.

## License

MIT — see [LICENSE](LICENSE).
