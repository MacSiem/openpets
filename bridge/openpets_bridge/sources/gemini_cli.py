"""Google Gemini CLI source.

Preferred watch path is ``~/.config/gemini-cli/sessions/*.jsonl`` with a
fallback to ``~/.gemini/history/*.jsonl``.

TODO: confirm canonical Gemini CLI session path and JSONL schema from a real
installation; this source currently parses common role/content/tool fields.
"""

from __future__ import annotations

from pathlib import Path

from .llm_cli_common import JsonlChatSource


class GeminiCliSource(JsonlChatSource):
    id = "gemini_cli"
    title = "Gemini"

    def _roots(self) -> tuple[Path, ...]:
        extra = self.config.extra or {}
        root = extra.get("sessions_root")
        history = extra.get("history_root")
        if root:
            return (Path(root),)
        if history:
            return (Path(history),)
        return (
            Path.home() / ".config/gemini-cli/sessions",
            Path.home() / ".gemini/history",
        )
