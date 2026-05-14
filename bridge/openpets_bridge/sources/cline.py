"""Cline CLI/source task watcher.

Preferred path is ``~/.config/cline/tasks/*.jsonl``. The secondary path probes
VS Code extension global storage where Cline commonly persists task data.

TODO: confirm Cline CLI task JSONL schema and VS Code storage path with real
sessions; this parser accepts common type/role/content records only.
"""

from __future__ import annotations

from pathlib import Path

from .llm_cli_common import JsonlChatSource


class ClineSource(JsonlChatSource):
    id = "cline"
    title = "Cline"

    def _roots(self) -> tuple[Path, ...]:
        root = (self.config.extra or {}).get("tasks_root")
        if root:
            return (Path(root),)
        return (
            Path.home() / ".config/cline/tasks",
            Path.home() / "Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/tasks",
        )
