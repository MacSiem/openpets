"""TOML config loading + sensible defaults.

Layout:

    [bridge]
    mode = "single"       # "single" | "multi"
    poll_interval_s = 1.0
    push_throttle_s = 1.5

    [sources.cowork]
    enabled = true
    label = "Cowork"
    icon = "🤝"

    [sources.codex_cli]
    enabled = true
    label = "Codex"
    icon = "🟢"

    [sources.claude_code]
    enabled = false
    label = "Claude Code"
    icon = "🟠"

    # Multi-pet only — pet pack id per source
    [sources.cowork.multi_pet]
    pet = "mandalorian"
    socket = "/tmp/openpets-cowork.sock"

    [sources.codex_cli.multi_pet]
    pet = "starcorn"
    socket = "/tmp/openpets-codex.sock"
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib  # noqa
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .sources.base import SourceConfig


DEFAULT_CONFIG_PATH = Path.home() / ".config/openpets-bridge/config.toml"


# Sensible defaults — every popular AI source enabled with a recognizable icon.
# User overrides via TOML.
DEFAULT_SOURCES: dict[str, dict] = {
    "cowork": {
        "enabled": True,
        "muted": False,
        "label": "Cowork",
        "icon": "🤝",
        "extra": {},
    },
    "codex_cli": {
        "enabled": True,
        "muted": False,
        "label": "Codex",
        "icon": "🟢",
        "extra": {},
    },
    "claude_code": {
        "enabled": False,  # off by default — many users don't have CLI installed
        "muted": False,
        "label": "Claude Code",
        "icon": "🟠",
        "extra": {},
    },
    "aider": {
        "enabled": False,
        "muted": False,
        "label": "Aider",
        "icon": "🦅",
        "extra": {},
    },
    "gemini_cli": {
        "enabled": False,
        "muted": False,
        "label": "Gemini",
        "icon": "🪷",
        "extra": {},
    },
    "opencode": {
        "enabled": False,
        "muted": False,
        "label": "OpenCode",
        "icon": "🌊",
        "extra": {},
    },
    "continue_cli": {
        "enabled": False,
        "muted": False,
        "label": "Continue",
        "icon": "⏩",
        "extra": {},
    },
    "cline": {
        "enabled": False,
        "muted": False,
        "label": "Cline",
        "icon": "🧬",
        "extra": {},
    },
}

BUILTIN_SOURCES = frozenset({"cowork", "codex_cli", "claude_code"})


@dataclass(slots=True)
class BridgeConfig:
    mode: str = "single"           # "single" | "multi"
    poll_interval_s: float = 1.0
    push_throttle_s: float = 1.5
    # 0 / unset → bubbles for ended sessions PERSIST (last status per
    # session stays until the user clears manually via the menubar).
    # Set to e.g. 600 to auto-wipe a 'done' bubble after 10 min of quiet.
    auto_clear_after_s: float = 0.0
    log_path: str = str(Path.home() / "ai-stack/openpets-bridge/bridge.log")
    sources: dict[str, SourceConfig] = field(default_factory=dict)


def _build_source_config(sid: str, raw: dict) -> SourceConfig:
    defaults = DEFAULT_SOURCES.get(sid, {})
    extra = dict(defaults.get("extra", {}))
    extra.update(dict(raw.get("extra", {})))
    if isinstance(raw.get("multi_pet"), dict):
        extra.update(dict(raw["multi_pet"]))
    return SourceConfig(
        enabled=bool(raw.get("enabled", defaults.get("enabled", False))),
        muted=bool(raw.get("muted", defaults.get("muted", False))),
        label=str(raw.get("label", defaults.get("label", sid))),
        icon=str(raw.get("icon", defaults.get("icon", "•"))),
        pet=raw.get("pet"),
        redact_body=bool(raw.get("redact_body", defaults.get("redact_body", False))),
        extra=extra,
    )


def load(path: Path | str | None = None) -> BridgeConfig:
    """Load config from TOML, falling back to defaults."""
    cfg = BridgeConfig()
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    raw: dict = {}
    if p.is_file():
        with p.open("rb") as f:
            raw = tomllib.load(f)
    bridge_raw = raw.get("bridge", {}) or {}
    cfg.mode = str(bridge_raw.get("mode", cfg.mode))
    cfg.poll_interval_s = float(bridge_raw.get("poll_interval_s", cfg.poll_interval_s))
    cfg.push_throttle_s = float(bridge_raw.get("push_throttle_s", cfg.push_throttle_s))
    cfg.auto_clear_after_s = float(bridge_raw.get("auto_clear_after_s",
                                                   cfg.auto_clear_after_s))
    cfg.log_path = str(bridge_raw.get("log_path", cfg.log_path))

    sources_raw = raw.get("sources", {}) or {}
    # Merge with defaults so newly added sources work without config edits
    all_keys = set(DEFAULT_SOURCES) | set(sources_raw.keys())
    for sid in all_keys:
        cfg.sources[sid] = _build_source_config(sid, sources_raw.get(sid, {}))
    return cfg


def write_default(path: Path | None = None) -> Path:
    """Write the default config to ``path`` (or the standard location)."""
    p = path or DEFAULT_CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(_DEFAULT_TOML)
    return p


# ---------------------------------------------------------------------------
# Mutation helpers — used by `openpets-bridge config set-*` and by the
# OpenPets tray "Bridge ▸" submenu. We deliberately do regex-based edits
# instead of round-tripping through a full TOML AST so we don't clobber the
# user's comments and formatting on every flip.
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=str(path.parent), delete=False, suffix=".tmp"
    )
    try:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def _ensure_config_file(path: Path | None = None) -> Path:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        write_default(p)
    return p


def _source_block(source_id: str) -> str:
    defaults = DEFAULT_SOURCES[source_id]
    return (
        f"\n[sources.{source_id}]\n"
        f"enabled = {'true' if defaults['enabled'] else 'false'}\n"
        f"muted = {'true' if defaults.get('muted', False) else 'false'}\n"
        f"label = \"{defaults['label']}\"\n"
        f"icon = \"{defaults['icon']}\"\n"
        "redact_body = false\n"
    )


def add_source_preset(preset_id: str, path: Path | str | None = None) -> Path:
    """Add a known [sources.<preset_id>] block if it is missing."""
    if preset_id not in DEFAULT_SOURCES:
        raise ValueError(f"unknown source preset: {preset_id}")
    p = _ensure_config_file(Path(path) if path else None)
    text = p.read_text()
    if re.search(rf"^\[sources\.{re.escape(preset_id)}\]$", text, re.MULTILINE):
        return p
    sep = "" if text.endswith("\n") else "\n"
    _atomic_write(p, text + sep + _source_block(preset_id))
    return p


def remove_source(preset_id: str, path: Path | str | None = None) -> Path:
    """Remove a non-builtin source block and its child sections."""
    if preset_id in BUILTIN_SOURCES:
        raise ValueError(f"cannot remove builtin source: {preset_id}")
    p = _ensure_config_file(Path(path) if path else None)
    text = p.read_text()
    section_pat = re.compile(
        rf"^\[sources\.{re.escape(preset_id)}(?:\.[^\]]+)?\]\n"
        rf"(?:(?!^\[).*\n?)*",
        re.MULTILINE,
    )
    new_text = section_pat.sub("", text)
    _atomic_write(p, new_text)
    return p


def set_mode(mode: str, path: Path | None = None) -> Path:
    """Switch [bridge].mode to "single" or "multi"."""
    if mode not in ("single", "multi"):
        raise ValueError(f"mode must be 'single' or 'multi', got {mode!r}")
    p = _ensure_config_file(path)
    text = p.read_text()
    new_text, n = re.subn(
        r'(^\s*mode\s*=\s*)"(single|multi)"',
        lambda m: f'{m.group(1)}"{mode}"',
        text, count=1, flags=re.MULTILINE,
    )
    if n == 0:
        # No `mode = "..."` line found — inject under [bridge]
        new_text = re.sub(
            r"(\[bridge\]\s*\n)",
            f'\\1mode = "{mode}"\n',
            text, count=1,
        )
    _atomic_write(p, new_text)
    return p


def toggle_source(source_id: str, path: Path | None = None) -> tuple[Path, bool]:
    """Flip [sources.<id>].enabled. Returns (path, new_state)."""
    p = _ensure_config_file(path)
    text = p.read_text()
    # Find the [sources.<id>] section and the first `enabled = ...` inside it
    section_pat = re.compile(
        rf"(\[sources\.{re.escape(source_id)}\]\s*\n(?:(?!^\[).*\n)*?\s*enabled\s*=\s*)(true|false)",
        re.MULTILINE,
    )
    match = section_pat.search(text)
    if not match:
        raise ValueError(f"no [sources.{source_id}] enabled line found in config")
    current = match.group(2) == "true"
    new_state = not current
    new_text = section_pat.sub(
        lambda m: f"{m.group(1)}{'true' if new_state else 'false'}",
        text, count=1,
    )
    _atomic_write(p, new_text)
    return p, new_state


def _replace_or_insert_source_bool(
    source_id: str,
    key: str,
    value: bool,
    path: Path | None = None,
) -> Path:
    p = _ensure_config_file(path)
    text = p.read_text()
    section_pat = re.compile(
        rf"(\[sources\.{re.escape(source_id)}\]\s*\n(?:(?!^\[).*\n)*?)",
        re.MULTILINE,
    )
    section = section_pat.search(text)
    if not section:
        raise ValueError(f"no [sources.{source_id}] section found in config")

    value_text = "true" if value else "false"
    key_pat = re.compile(
        rf"(\[sources\.{re.escape(source_id)}\]\s*\n(?:(?!^\[).*\n)*?\s*{re.escape(key)}\s*=\s*)(true|false)",
        re.MULTILINE,
    )
    if key_pat.search(text):
        new_text = key_pat.sub(lambda m: f"{m.group(1)}{value_text}", text, count=1)
    else:
        insert_at = section.end(1)
        new_text = text[:insert_at] + f"{key} = {value_text}\n" + text[insert_at:]
    _atomic_write(p, new_text)
    return p


def set_source_mute(
    source_id: str,
    muted: bool,
    path: Path | None = None,
) -> tuple[Path, bool]:
    """Set [sources.<id>].muted. Returns (path, muted)."""
    p = _replace_or_insert_source_bool(source_id, "muted", muted, path)
    return p, muted


def set_source_pet(source_id: str, pet_dir: str, socket: str | None = None,
                    path: Path | None = None) -> Path:
    """Set [sources.<id>.multi_pet].pet = "<pet_dir>" + socket.

    Used in multi-pet mode to pick which sprite plays the role of a given AI.
    If the section doesn't exist yet, appends it.
    """
    p = _ensure_config_file(path)
    text = p.read_text()
    auto_socket = socket or f"/tmp/openpets-{source_id}.sock"

    # Try to replace existing pet = "..." inside [sources.<id>.multi_pet]
    section_header = f"[sources.{source_id}.multi_pet]"
    pet_line_pat = re.compile(
        rf"(\[sources\.{re.escape(source_id)}\.multi_pet\]\s*\n(?:(?!^\[).*\n)*?\s*pet\s*=\s*)\"[^\"]*\"",
        re.MULTILINE,
    )
    if pet_line_pat.search(text):
        new_text = pet_line_pat.sub(
            lambda m: f'{m.group(1)}"{pet_dir}"', text, count=1,
        )
    else:
        # Append a fresh section at end of file
        sep = "" if text.endswith("\n") else "\n"
        new_text = (
            text
            + sep
            + f'\n{section_header}\n'
            + f'pet = "{pet_dir}"\n'
            + f'socket = "{auto_socket}"\n'
        )
    _atomic_write(p, new_text)
    return p


def _set_bridge_float(key: str, value: float, path: Path | None = None) -> Path:
    p = _ensure_config_file(path)
    text = p.read_text()
    value_text = f"{value:g}"
    new_text, n = re.subn(
        rf"(^\s*{re.escape(key)}\s*=\s*)[-+]?[0-9]*\.?[0-9]+",
        lambda m: f"{m.group(1)}{value_text}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n == 0:
        new_text = re.sub(
            r"(\[bridge\]\s*\n)",
            f"\\1{key} = {value_text}\n",
            text,
            count=1,
        )
    _atomic_write(p, new_text)
    return p


def set_poll_interval(value: float, path: Path | None = None) -> Path:
    """Set [bridge].poll_interval_s."""
    if value <= 0:
        raise ValueError("poll_interval_s must be greater than 0")
    return _set_bridge_float("poll_interval_s", value, path)


def set_push_throttle(value: float, path: Path | None = None) -> Path:
    """Set [bridge].push_throttle_s."""
    if value < 0:
        raise ValueError("push_throttle_s must be greater than or equal to 0")
    return _set_bridge_float("push_throttle_s", value, path)


def set_auto_clear_after(value: float, path: Path | None = None) -> Path:
    """Set [bridge].auto_clear_after_s."""
    if value < 0:
        raise ValueError("auto_clear_after_s must be greater than or equal to 0")
    return _set_bridge_float("auto_clear_after_s", value, path)


def set_all_sources_redact_body(redact: bool, path: Path | None = None) -> Path:
    """Set redact_body for every configured source section."""
    p = _ensure_config_file(path)
    text = p.read_text()
    source_ids = re.findall(r"^\[sources\.([A-Za-z0-9_-]+)\]$", text, re.MULTILINE)
    if not source_ids:
        raise ValueError("no [sources.<id>] sections found in config")
    for source_id in source_ids:
        _replace_or_insert_source_bool(source_id, "redact_body", redact, p)
    return p


def export_json(path: Path | None = None) -> str:
    """Dump current loaded config as JSON. Consumed by the OpenPets tray
    "Bridge ▸" submenu to render checkmarks and current values."""
    cfg = load(path)
    from .discovery import discover_installed_sources

    discovery = discover_installed_sources()
    payload = {
        "mode": cfg.mode,
        "poll_interval_s": cfg.poll_interval_s,
        "push_throttle_s": cfg.push_throttle_s,
        "auto_clear_after_s": cfg.auto_clear_after_s,
        "log_path": cfg.log_path,
        "sources": {
            sid: {
                "enabled": s.enabled,
                "muted": s.muted,
                "label": s.label,
                "icon": s.icon,
                "pet": s.pet,
                "redact_body": s.redact_body,
                "extra": s.extra,
                "discovery": {
                    "installed": discovery.get(sid, {}).get("installed", False),
                    "watch_path": discovery.get(sid, {}).get("watch_path"),
                    "last_activity": (
                        discovery.get(sid, {}).get("last_activity").isoformat()
                        if discovery.get(sid, {}).get("last_activity") else None
                    ),
                },
            }
            for sid, s in cfg.sources.items()
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


_DEFAULT_TOML = """\
# openpets-bridge config — see https://github.com/MacSiem/openpets

[bridge]
mode = "single"            # "single" (one pet, AI icon per bubble) | "multi"
poll_interval_s = 1.0
push_throttle_s = 1.5
# 0 (default) = the LAST bubble per session persists indefinitely. The user
# clears manually via the menubar ("Clear all bubbles" / "Clear done").
# Set e.g. 600.0 to auto-wipe each session's bubble 10 minutes after it
# went 'done'.
auto_clear_after_s = 0.0

# ---- Sources --------------------------------------------------------------
# Set enabled=true for each agent runtime you want the pet to react to.
# You can override label/icon to taste; icons render inside the bubble title.

[sources.cowork]
enabled = true
muted = false
label = "Cowork"
icon = "🤝"
# Set redact_body = true to never echo tool inputs (file paths, commands,
# search queries, prompts) into the bubble or the log — only the tool
# glyph remains. Useful when streaming, pair-coding, or screen-sharing.
redact_body = false

[sources.codex_cli]
enabled = true
muted = false
label = "Codex"
icon = "🟢"
redact_body = false

[sources.claude_code]
enabled = false           # turn on when you use the `claude` CLI
muted = false
label = "Claude Code"
icon = "🟠"
redact_body = false

# Optional LLM CLI source presets. They are disabled by default and can be
# enabled from Preferences ▸ Sources or with:
#   openpets-bridge config add-source-preset <preset_id>
#
# [sources.aider]
# enabled = false
# muted = false
# label = "Aider"
# icon = "🦅"
# redact_body = false
#
# [sources.gemini_cli]
# enabled = false
# muted = false
# label = "Gemini"
# icon = "🪷"
# redact_body = false
#
# [sources.opencode]
# enabled = false
# muted = false
# label = "OpenCode"
# icon = "🌊"
# redact_body = false
#
# [sources.continue_cli]
# enabled = false
# muted = false
# label = "Continue"
# icon = "⏩"
# redact_body = false
#
# [sources.cline]
# enabled = false
# muted = false
# label = "Cline"
# icon = "🧬"
# redact_body = false

# ---- Multi-pet mode (optional) -------------------------------------------
# When mode = "multi", each enabled source gets its OWN OpenPets host on a
# separate socket. Specify which pet pack to wear and where the socket lives:
#
# [sources.cowork.multi_pet]
# pet = "mandalorian"
# socket = "/tmp/openpets-cowork.sock"
#
# [sources.codex_cli.multi_pet]
# pet = "starcorn"
# socket = "/tmp/openpets-codex.sock"
"""
