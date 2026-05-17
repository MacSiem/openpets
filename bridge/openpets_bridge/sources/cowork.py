"""Cowork (Claude desktop app) activity source.

Watches per-session audit.jsonl files under
``~/Library/Application Support/Claude/local-agent-mode-sessions/<host>/<run>/local_<id>/``
and yields SourceUpdate snapshots for each active conversation.

The Cowork JSON-RPC stream uses the same shape as Claude Code (assistant
messages with tool_use blocks) — we read the most recent assistant block
to derive the visible status.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

from .base import Source, SourceUpdate


SESSIONS_ROOT = Path.home() / "Library/Application Support/Claude/local-agent-mode-sessions"
ACTIVITY_WINDOW_S = 6
IDLE_AFTER_S = 8   # was 25 — flip to "done" faster after assistant goes quiet
TAIL_BYTES = 32_768  # bumped: we now look further back for matching tool_result

# Map Cowork tool name → (OpenPets status, body glyph)
TOOL_MAP: dict[str, tuple[str, str]] = {
    "Bash": ("running", "▶"),
    "Shell": ("running", "▶"),
    "bash": ("running", "▶"),
    "Edit": ("running", "✎"),
    "Write": ("running", "✎"),
    "MultiEdit": ("running", "✎"),
    "create_file": ("running", "✎"),
    "edit_block": ("running", "✎"),
    "write_file": ("running", "✎"),
    "Read": ("running", "📖"),
    "read_file_content": ("running", "📖"),
    "Grep": ("running", "🔎"),
    "Glob": ("running", "🔎"),
    "WebSearch": ("running", "🔎"),
    "WebFetch": ("running", "🌐"),
    "web_fetch": ("running", "🌐"),
    "screenshot": ("running", "📸"),
    "Task": ("running", "🤖"),
    "TaskCreate": ("running", "➕"),
    "TaskUpdate": ("running", "✓"),
    "TaskGet": ("running", "📋"),
    "TaskList": ("running", "📋"),
    "AskUserQuestion": ("waiting", "❓"),
    "Skill": ("running", "🎯"),
    "ToolSearch": ("running", "🧰"),
}


def _truncate(s: str, n: int = 60) -> str:
    s = s.strip().replace("\n", " ")
    return s if len(s) <= n else (s[: n - 1] + "…")


def _basename(p: str) -> str:
    return p.rsplit("/", 1)[-1] if p else ""


def _short_for_tool(tool: str, tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return ""
    if tool in ("Bash", "Shell", "bash"):
        return _truncate(tool_input.get("command", ""))
    if tool in ("Edit", "Write", "MultiEdit", "create_file", "edit_block", "write_file"):
        return _basename(tool_input.get("file_path", tool_input.get("path", "")))
    if tool in ("Read", "read_file_content"):
        return _basename(tool_input.get("file_path", tool_input.get("path", "")))
    if tool in ("Grep", "Glob"):
        return _truncate(tool_input.get("pattern", ""))
    if tool == "WebSearch":
        return _truncate(tool_input.get("query", ""))
    if tool in ("WebFetch", "web_fetch"):
        url = tool_input.get("url", "")
        return url.split("//", 1)[-1].split("/", 1)[0] if url else ""
    if tool == "Task":
        return _truncate(tool_input.get("description", ""))
    if tool == "TaskCreate":
        return _truncate(tool_input.get("subject", ""))
    if tool == "TaskUpdate":
        st = tool_input.get("status", "")
        sb = tool_input.get("subject", "")
        if st == "completed":
            return _truncate(f"completed: {sb}" if sb else "task done")
        if st == "in_progress":
            return _truncate(f"started: {sb}" if sb else "task started")
        return _truncate(f"task {st}" if st else "task")
    if tool == "AskUserQuestion":
        qs = tool_input.get("questions") or []
        if qs and isinstance(qs[0], dict):
            return _truncate(qs[0].get("question", ""))
        return "Waiting for answer"
    if tool == "Skill":
        return _truncate(tool_input.get("skill", ""))
    if tool == "ToolSearch":
        return _truncate(tool_input.get("query", ""))
    return _truncate(tool)


def _tail_json_lines(path: Path, n: int = 6) -> list[dict]:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read()
        text = chunk.decode("utf-8", errors="replace")
        out: list[dict] = []
        for line in text.split("\n")[-n - 1:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return out[-n:]
    except OSError:
        return []


def _session_title(audit_path: Path) -> str:
    sess_json = audit_path.parent.parent / (audit_path.parent.name + ".json")
    try:
        with sess_json.open("rb") as f:
            data = json.load(f)
        return str(data.get("title", "")).strip() or "Cowork session"
    except (OSError, json.JSONDecodeError, ValueError):
        return "Cowork session"


def _derive_status_text(events: list[dict]) -> tuple[str, str]:
    """Return (openpets_status, body) from latest events.

    Status logic (in priority order):
      1. TaskUpdate(status=completed)         → "done"
      2. AskUserQuestion / waiting tool        → "waiting"
      3. last tool_use has matching tool_result downstream → "done"
      4. last assistant block is plain text (no tool_use) → "done"
      5. last assistant block is in-flight tool_use → "running"
      6. fallback                              → "running" / "💭 thinking…"
    """
    # Locate the LATEST assistant tool_use anywhere in the tail
    last_tool_use: dict | None = None
    last_tool_use_idx = -1
    for idx, ev in enumerate(events):
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message", {}) or {}
        for block in (msg.get("content", []) or []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                last_tool_use = block
                last_tool_use_idx = idx

    if last_tool_use is None:
        # No tool calls in tail — check whether assistant produced text
        for ev in reversed(events):
            if ev.get("type") != "assistant":
                continue
            msg = ev.get("message", {}) or {}
            content = msg.get("content", []) or []
            if any(isinstance(b, dict) and b.get("type") == "text"
                   and (b.get("text") or "").strip()
                   for b in content):
                return "done", "✓ replied"
            break
        return "running", "💭 thinking…"

    tool = last_tool_use.get("name", "") or ""
    if tool.startswith("mcp__"):
        tool = tool.rsplit("__", 1)[-1]
    tool_input = last_tool_use.get("input", {}) or {}
    short = _short_for_tool(tool, tool_input)
    status, glyph = TOOL_MAP.get(tool, ("running", "•"))
    body = (f"{glyph} {short}".strip()) if short else glyph

    # Override: TaskUpdate→completed is itself a terminal signal.
    if tool == "TaskUpdate" and tool_input.get("status") == "completed":
        return "done", body

    # waiting tools (AskUserQuestion) should stay waiting regardless of result
    if status == "waiting":
        return status, body

    # Did this exact tool call already get a tool_result back? → done
    tool_use_id = last_tool_use.get("id")
    if tool_use_id:
        for ev in events[last_tool_use_idx + 1:]:
            if ev.get("type") != "user":
                continue
            msg = ev.get("message", {}) or {}
            for block in (msg.get("content", []) or []):
                if (isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") == tool_use_id):
                    return "done", body

    return status, body


class _SessionState:
    """Per-file bookkeeping for the cowork poller.

    ``grew_under_watch`` is True once we've observed any size growth on this
    session since we started polling. We need that flag to emit a final
    "done" bubble when the session goes idle — without it, we'd never know
    whether a session that ends up quiet was "we watched it grow then stop"
    (emit done) or "it was already on disk and never moved" (stay silent).
    """

    __slots__ = ("last_mtime", "last_size", "emitted_done", "grew_under_watch")

    def __init__(self, mtime: float, size: int) -> None:
        self.last_mtime = mtime
        self.last_size = size
        self.emitted_done = False
        self.grew_under_watch = False


class CoworkSource(Source):
    id = "cowork"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._sessions_root = Path(self.config.extra.get("sessions_root", str(SESSIONS_ROOT))) \
            if self.config.extra else SESSIONS_ROOT
        self._state: dict[Path, _SessionState] = {}

    def poll(self) -> Iterable[SourceUpdate]:
        now = time.time()
        if not self._sessions_root.is_dir():
            return
        for path in self._sessions_root.glob("*/*/local_*/audit.jsonl"):
            try:
                stt = path.stat()
            except OSError:
                continue

            # First time we see this path → silently baseline it. We never
            # emit anything for sessions that were already on disk before
            # the bridge started; only NEW activity (size growth) after
            # baseline counts. This keeps the cold-start clean — no flood
            # of historical "done" or stale "running" bubbles when the
            # daemon (re)starts and finds 100s of old session files.
            if path not in self._state:
                self._state[path] = _SessionState(stt.st_mtime, stt.st_size)
                continue

            st = self._state[path]
            size_grew = stt.st_size > st.last_size
            is_active = (now - stt.st_mtime) < ACTIVITY_WINDOW_S

            session_id = path.parent.name  # local_<uuid>

            if is_active and size_grew:
                status, body = _derive_status_text(_tail_json_lines(path))
                st.last_mtime = stt.st_mtime
                st.last_size = stt.st_size
                st.emitted_done = False
                st.grew_under_watch = True
                yield SourceUpdate(
                    source_id=self.id, session_id=session_id,
                    title=_session_title(path),
                    body=body, status=status, is_active=True,
                )
            elif (not is_active and not st.emitted_done
                  and st.grew_under_watch
                  and (now - stt.st_mtime) > IDLE_AFTER_S):
                # Was observed growing → now quiet long enough → emit done
                # exactly once. We use the in-state `grew_under_watch` flag
                # (set on the first growth poll above) rather than comparing
                # the current size to a stored size, because we always update
                # `last_size` on every growth poll — so a size comparison
                # would never be true here.
                st.last_mtime = stt.st_mtime
                st.last_size = stt.st_size
                st.emitted_done = True
                yield SourceUpdate(
                    source_id=self.id, session_id=session_id,
                    title=_session_title(path),
                    body="✓ Done", status="done", is_active=False,
                )
            else:
                # Update bookkeeping silently
                st.last_mtime = stt.st_mtime
                st.last_size = stt.st_size
