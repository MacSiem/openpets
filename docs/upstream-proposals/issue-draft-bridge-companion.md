# Issue draft — to be posted on `alterhq/openpets`

This is a draft. **Do not post automatically.** Maciej reviews and
opens manually via `gh issue create --repo alterhq/openpets …` so the
tone matches whatever the conversation with alterhq currently is.

---

**Title:** Multi-AI activity bridge for OpenPets (companion daemon) — discussion

**Body:**

Hi alterhq team — thanks for OpenPets. The `notify --thread` protocol
and `OpenPetsHostSession` API are clean enough that we've been able to
build a small **companion daemon** on top of it, with **zero
modifications** to your tree. Wanted to surface it in case it's
useful upstream, or in case you'd rather it stay strictly as a
downstream project.

## What it is

[`MacSiem/openpets`](https://github.com/MacSiem/openpets) ships
`openpets-bridge` (Python, stdlib only, MIT) — it watches the on-disk
session logs of multiple AI coding agents and forwards their activity
to OpenPets via the documented `notify --thread <uuid>` protocol, so
the same pet (or one pet per AI in multi-pet mode) reacts to whichever
agent is working.

Out-of-the-box sources:

| Source | Watches |
| --- | --- |
| Cowork | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../audit.jsonl` |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |
| Claude Code CLI | `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl` |
| Aider, Gemini CLI, OpenCode, Continue CLI, Cline | their respective session paths |

Plus a `generic_jsonl` source type so users can wire up any custom LLM
in `~/.config/openpets-bridge/config.toml` without writing Python.

A short `Bridge ▸` submenu in the OpenPets tray controls mode (single /
multi pet), per-source enable/mute, and the pet pack picker. A
`Preferences…` window with four tabs (Display / Bridge / Sources /
Advanced) replaces the hand-edit-config-file UX. All of that lives in
a handful of additive Swift files in `Sources/OpenPetsMenuBar/`; the
upstream files are untouched.

Privacy: a single `redact_body = true` config flag replaces every
bubble body with just the tool glyph (`▶ ✎ 📖 🔎 🌐`) — never echoes
file paths, commands, prompts, or queries. No telemetry, no network
calls, no analytics.

## What we'd like to discuss

1. **Are you interested in any of the small, general-purpose
   improvements** we made along the way? We've collected them under
   [`docs/upstream-proposals/`](https://github.com/MacSiem/openpets/tree/main/docs/upstream-proposals).
   The one most worth landing today is a one-line fix in `OpenPetsKit`
   that makes right-click context menus work for hosts running under
   `.accessory` activation policy — every consumer of
   `OpenPetsHostSession(contextMenuProvider:)` benefits.

2. **Would you want the bridge directory pulled into `alterhq/openpets`**
   as an optional companion (`bridge/` subdirectory, separate
   `pipx`-installed package, no Swift dependency), or do you prefer it
   stays as a separate fork? Either's fine on our end — we just
   wanted to ask before assuming.

3. **Is there a documented MCP contract you'd like us to follow** when
   adding new bubble metadata (e.g. source icon, instance ID,
   redact-body)? We've been using your `notify --thread <uuid>`
   shape verbatim, but if you have a roadmap for richer metadata
   we'd love to align.

No deadline on any of this — happy to keep the bridge downstream
indefinitely if that suits you better. Open question, no expectations.

Repo: https://github.com/MacSiem/openpets
Tag: `bridge-v0.4.1`
Fork commits ahead of `alterhq/openpets@main`: 10 (additive only).
