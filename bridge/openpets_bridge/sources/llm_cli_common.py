"""Shared helpers for best-effort LLM CLI log sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .base import Source, SourceUpdate


def truncate(value: object, limit: int = 64) -> str:
    """Return a compact one-line body fragment."""
    text = str(value or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def read_jsonl(path: Path) -> list[dict]:
    """Read JSON objects from a small-ish session JSONL file."""
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    except OSError:
        pass
    return out


def text_event_from_line(source_id: str, title: str, path: Path, line: str) -> SourceUpdate | None:
    """Map a Markdown/text history line to a conservative update."""
    clean = truncate(line)
    if not clean:
        return None
    lower = clean.lower()
    if lower.startswith("user") or lower.startswith("# user"):
        status = "waiting"
    elif lower.startswith("assistant") or lower.startswith("# assistant"):
        status = "done"
    else:
        status = "message"
    return SourceUpdate(source_id, path.stem, title, clean, status, status in ("running", "waiting"))


def pick_content(obj: dict) -> str:
    """Extract a short text field from common chat record shapes."""
    content = obj.get("content") or obj.get("text") or obj.get("message") or ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item.get("type") or ""))
            else:
                parts.append(str(item))
        return truncate(" ".join(parts))
    if isinstance(content, dict):
        return truncate(content.get("text") or content.get("content") or content.get("type") or "")
    return truncate(content)


def has_tool_call(obj: dict) -> bool:
    """Detect common tool invocation shapes without depending on one schema."""
    if obj.get("tool_calls") or obj.get("toolCalls") or obj.get("tool_invocations"):
        return True
    for key in ("parts", "content"):
        value = obj.get(key)
        if isinstance(value, list):
            for part in value:
                if isinstance(part, dict):
                    ptype = str(part.get("type") or part.get("kind") or "").lower()
                    if "tool" in ptype or part.get("tool") or part.get("toolCallId"):
                        return True
    return False


def map_chat_obj(obj: dict) -> tuple[str, str, bool]:
    """Map a generic chat record to (status, body, active)."""
    if has_tool_call(obj):
        return "running", "• tool", True
    role = str(obj.get("role") or obj.get("type") or "").lower()
    body = pick_content(obj)
    if role == "user" or role in ("ask", "input"):
        return "waiting", body or "⌛ Waiting", True
    if role == "assistant":
        return "done", body or "✓ Replied", False
    if role in ("error", "failed", "failure"):
        return "failed", body or "⚠ Failed", False
    return "message", body or "• Activity", True


class JsonlChatSource(Source):
    """Base class for append-only JSONL chat sources."""

    title = "LLM CLI"
    patterns = ("*.jsonl",)
    roots: tuple[Path, ...] = ()

    def __init__(self, config) -> None:
        super().__init__(config)
        self._state: dict[Path, int] = {}

    def _roots(self) -> tuple[Path, ...]:
        return self.roots

    def _map(self, obj: dict) -> tuple[str, str, bool]:
        return map_chat_obj(obj)

    def _paths(self) -> Iterable[Path]:
        for root in self._roots():
            if root.is_dir():
                for pattern in self.patterns:
                    yield from root.glob(pattern)

    def iter_events(self) -> Iterable[SourceUpdate]:
        yield from self.poll()

    def poll(self) -> Iterable[SourceUpdate]:
        for path in self._paths():
            rows = read_jsonl(path)
            previous = self._state.setdefault(path, len(rows))
            if len(rows) <= previous:
                continue
            for obj in rows[previous:]:
                status, body, active = self._map(obj)
                yield SourceUpdate(self.id, path.stem, self.title, body, status, active)
            self._state[path] = len(rows)
