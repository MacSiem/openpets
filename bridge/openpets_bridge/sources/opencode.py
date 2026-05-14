"""Charm OpenCode CLI source.

Watches ``~/.local/share/opencode/sessions/*.jsonl`` first, then
``~/.opencode/sessions/*.jsonl``.

TODO: confirm OpenCode's persisted turn schema from real Bubbletea sessions;
the parser currently handles role plus parts arrays with tool-like entries.
"""

from __future__ import annotations

from pathlib import Path

from .llm_cli_common import JsonlChatSource


class OpenCodeSource(JsonlChatSource):
    id = "opencode"
    title = "OpenCode"

    def _roots(self) -> tuple[Path, ...]:
        root = (self.config.extra or {}).get("sessions_root")
        if root:
            return (Path(root),)
        return (
            Path.home() / ".local/share/opencode/sessions",
            Path.home() / ".opencode/sessions",
        )
