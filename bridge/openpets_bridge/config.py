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
        "label": "Cowork",
        "icon": "🤝",
        "extra": {},
    },
    "codex_cli": {
        "enabled": True,
        "label": "Codex",
        "icon": "🟢",
        "extra": {},
    },
    "claude_code": {
        "enabled": False,  # off by default — many users don't have CLI installed
        "label": "Claude Code",
        "icon": "🟠",
        "extra": {},
    },
}


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
    return SourceConfig(
        enabled=bool(raw.get("enabled", defaults.get("enabled", False))),
        label=str(raw.get("label", defaults.get("label", sid))),
        icon=str(raw.get("icon", defaults.get("icon", "•"))),
        pet=raw.get("pet"),
        redact_body=bool(raw.get("redact_body", defaults.get("redact_body", False))),
        extra=dict(raw.get("extra", defaults.get("extra", {}))),
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
    p = path or DEFAULT_CONFIG_PATH
    if not p.exists():
        write_default(p)
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


def export_json(path: Path | None = None) -> str:
    """Dump current loaded config as JSON. Consumed by the OpenPets tray
    "Bridge ▸" submenu to render checkmarks and current values."""
    cfg = load(path)
    payload = {
        "mode": cfg.mode,
        "poll_interval_s": cfg.poll_interval_s,
        "push_throttle_s": cfg.push_throttle_s,
        "auto_clear_after_s": cfg.auto_clear_after_s,
        "log_path": cfg.log_path,
        "sources": {
            sid: {
                "enabled": s.enabled,
                "label": s.label,
                "icon": s.icon,
                "pet": s.pet,
                "redact_body": s.redact_body,
                "extra": s.extra,
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
label = "Cowork"
icon = "🤝"
# Set redact_body = true to never echo tool inputs (file paths, commands,
# search queries, prompts) into the bubble or the log — only the tool
# glyph remains. Useful when streaming, pair-coding, or screen-sharing.
redact_body = false

[sources.codex_cli]
enabled = true
label = "Codex"
icon = "🟢"
redact_body = false

[sources.claude_code]
enabled = false           # turn on when you use the `claude` CLI
label = "Claude Code"
icon = "🟠"
redact_body = false

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
