"""Aider CLI source.

Watches ``~/.aider/sessions/*.jsonl``. If no JSONL sessions directory exists,
falls back to per-cwd ``.aider.chat.history.md`` supplied through
``extra.history_file`` or the current working directory.

TODO: confirm Aider's upstream JSONL session schema against real sessions;
the parser intentionally accepts only common role/content/tool_calls shapes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .base import SourceUpdate
from .llm_cli_common import JsonlChatSource, text_event_from_line


class AiderSource(JsonlChatSource):
    id = "aider"
    title = "Aider"

    def _roots(self) -> tuple[Path, ...]:
        root = (self.config.extra or {}).get("sessions_root", str(Path.home() / ".aider/sessions"))
        return (Path(root),)

    def _history_file(self) -> Path:
        extra = self.config.extra or {}
        return Path(extra.get("history_file", Path.cwd() / ".aider.chat.history.md"))

    def poll(self) -> Iterable[SourceUpdate]:
        emitted = False
        for update in super().poll():
            emitted = True
            yield update
        if emitted:
            return
        history = self._history_file()
        if not history.is_file():
            return
        try:
            lines = history.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        key = history
        previous = self._state.setdefault(key, len(lines))
        for line in lines[previous:]:
            update = text_event_from_line(self.id, self.title, history, line)
            if update is not None:
                yield update
        self._state[key] = len(lines)
