"""Continue CLI source.

Watches whole-session JSON files under ``~/.continue/sessions/*.json`` and
emits only newly appended ``history`` entries.

TODO: confirm Continue CLI/agent history schema across current releases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .base import Source, SourceUpdate
from .llm_cli_common import map_chat_obj


class ContinueCliSource(Source):
    id = "continue_cli"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._state: dict[Path, int] = {}

    def _root(self) -> Path:
        return Path((self.config.extra or {}).get("sessions_root", str(Path.home() / ".continue/sessions")))

    def iter_events(self) -> Iterable[SourceUpdate]:
        yield from self.poll()

    def poll(self) -> Iterable[SourceUpdate]:
        root = self._root()
        if not root.is_dir():
            return
        for path in root.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            history = raw.get("history", []) if isinstance(raw, dict) else []
            if not isinstance(history, list):
                continue
            previous = self._state.setdefault(path, len(history))
            if len(history) <= previous:
                continue
            for obj in history[previous:]:
                if not isinstance(obj, dict):
                    continue
                status, body, active = map_chat_obj(obj)
                yield SourceUpdate(self.id, path.stem, "Continue", body, status, active)
            self._state[path] = len(history)
