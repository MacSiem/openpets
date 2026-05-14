# Changelog

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
