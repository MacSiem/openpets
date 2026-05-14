"""Discover installed bridge source presets."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SourceProbe:
    """Probe definition for one source preset."""

    source_id: str
    binaries: tuple[str, ...]
    watches: tuple[tuple[Path, str], ...]


SOURCE_PROBES: dict[str, SourceProbe] = {
    "cowork": SourceProbe("cowork", (), (
        (Path.home() / "Library/Application Support/Claude/local-agent-mode-sessions", "**/audit.jsonl"),
    )),
    "codex_cli": SourceProbe("codex_cli", ("codex",), (
        (Path.home() / ".codex/sessions", "*/*/*/rollout-*.jsonl"),
    )),
    "claude_code": SourceProbe("claude_code", ("claude",), (
        (Path.home() / ".claude/projects", "*/*.jsonl"),
    )),
    "aider": SourceProbe("aider", ("aider",), (
        (Path.home() / ".aider/sessions", "*.jsonl"),
        (Path.cwd(), ".aider.chat.history.md"),
    )),
    "gemini_cli": SourceProbe("gemini_cli", ("gemini", "gemini-cli"), (
        (Path.home() / ".config/gemini-cli/sessions", "*.jsonl"),
        (Path.home() / ".gemini/history", "*.jsonl"),
    )),
    "opencode": SourceProbe("opencode", ("opencode",), (
        (Path.home() / ".local/share/opencode/sessions", "*.jsonl"),
        (Path.home() / ".opencode/sessions", "*.jsonl"),
    )),
    "continue_cli": SourceProbe("continue_cli", ("continue",), (
        (Path.home() / ".continue/sessions", "*.json"),
    )),
    "cline": SourceProbe("cline", ("cline",), (
        (Path.home() / ".config/cline/tasks", "*.jsonl"),
        (
            Path.home() / "Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/tasks",
            "*.jsonl",
        ),
    )),
}


def _latest_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    try:
        files = [p for p in root.glob(pattern) if p.is_file()]
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def discover_installed_sources() -> dict[str, dict]:
    """Return installed/watch-path/activity metadata for known source presets."""
    results: dict[str, dict] = {}
    for source_id, probe in SOURCE_PROBES.items():
        binary_found = any(shutil.which(binary) for binary in probe.binaries)
        watch_path: str | None = None
        last_activity: datetime | None = None
        for root, pattern in probe.watches:
            latest = _latest_file(root, pattern)
            if latest is None:
                continue
            watch_path = str(root)
            try:
                last_activity = datetime.fromtimestamp(latest.stat().st_mtime)
            except OSError:
                last_activity = None
            break
        results[source_id] = {
            "installed": bool(binary_found or watch_path),
            "watch_path": watch_path,
            "last_activity": last_activity,
        }
    return results
