"""Smoke test for the Cowork source — exercises baseline + emit-on-growth."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from openpets_bridge.sources.base import SourceConfig
from openpets_bridge.sources.cowork import CoworkSource


def _make_session(root: Path, sid: str, *, title: str = "Test session",
                  events: list[dict] | None = None) -> Path:
    """Create a minimal Cowork-like session layout under root."""
    session_dir = root / "host" / "run" / f"local_{sid}"
    session_dir.mkdir(parents=True, exist_ok=True)
    audit = session_dir / "audit.jsonl"
    audit.write_text("")
    (session_dir.parent / f"local_{sid}.json").write_text(
        json.dumps({"title": title, "isAgentCompleted": False})
    )
    if events:
        with audit.open("a") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")
    return audit


def _cfg() -> SourceConfig:
    return SourceConfig(enabled=True, label="Cowork", icon="🤝",
                        redact_body=False, extra={})


def test_baseline_skips_existing_sessions(tmp_path: Path):
    """A session that already exists at startup must NOT emit on first poll."""
    audit = _make_session(tmp_path, "abc", events=[
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
        ]}}
    ])
    cfg = _cfg()
    cfg.extra["sessions_root"] = str(tmp_path)
    src = CoworkSource(cfg)

    # First poll = baseline only
    updates = list(src.poll())
    assert updates == [], f"first poll should baseline, got {updates}"


def test_emit_on_growth_after_baseline(tmp_path: Path):
    audit = _make_session(tmp_path, "def", events=[
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
        ]}}
    ])
    cfg = _cfg()
    cfg.extra["sessions_root"] = str(tmp_path)
    src = CoworkSource(cfg)

    list(src.poll())  # baseline

    # Append a new tool_use → file grew → next poll should emit
    with audit.open("a") as f:
        f.write(json.dumps({
            "type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "/tmp/foo.py"}}
            ]}
        }) + "\n")
    # Touch mtime to "now" so is_active picks it up
    audit.touch()

    updates = list(src.poll())
    assert len(updates) == 1, f"expected one update, got {updates}"
    u = updates[0]
    assert u.source_id == "cowork"
    assert u.session_id == "local_def"
    assert u.status == "running"
    assert "foo.py" in u.body  # body should reflect the Edit input


def test_session_id_format(tmp_path: Path):
    """session_id should be the local_<uuid> directory name."""
    _make_session(tmp_path, "xyz")
    cfg = _cfg()
    cfg.extra["sessions_root"] = str(tmp_path)
    src = CoworkSource(cfg)
    list(src.poll())  # baseline

    audit = tmp_path / "host" / "run" / "local_xyz" / "audit.jsonl"
    with audit.open("a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "echo hi"}}
        ]}}) + "\n")
    audit.touch()

    updates = list(src.poll())
    assert updates and updates[0].session_id == "local_xyz"


def test_done_emitted_after_session_goes_idle(tmp_path: Path, monkeypatch):
    """A watched session that grew, then went quiet > IDLE_AFTER_S, emits done once."""
    import openpets_bridge.sources.cowork as cowork_mod

    audit = _make_session(tmp_path, "idle_one")
    cfg = _cfg()
    cfg.extra["sessions_root"] = str(tmp_path)
    src = CoworkSource(cfg)

    list(src.poll())  # baseline (empty file)

    # 1. Watched growth — appends a tool_use; activity is fresh.
    with audit.open("a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
        ]}}) + "\n")
    audit.touch()
    growth_updates = list(src.poll())
    assert len(growth_updates) == 1
    assert growth_updates[0].status == "running"

    # 2. Now jump time forward past IDLE_AFTER_S and ACTIVITY_WINDOW_S so the
    #    session is "idle". We monkeypatch time.time so we don't need to sleep.
    real_time = time.time()
    later = real_time + cowork_mod.IDLE_AFTER_S + 1
    monkeypatch.setattr(cowork_mod.time, "time", lambda: later)

    idle_updates = list(src.poll())
    assert len(idle_updates) == 1, f"expected one 'done' bubble after idle, got {idle_updates}"
    assert idle_updates[0].status == "done"
    assert idle_updates[0].is_active is False

    # 3. Subsequent polls should NOT re-emit done (emitted_done flag).
    monkeypatch.setattr(cowork_mod.time, "time", lambda: later + 5)
    again = list(src.poll())
    assert again == [], f"done should be emitted only once, got {again}"


# --- status flip tests ---------------------------------------------------

from openpets_bridge.sources.cowork import _derive_status_text


def test_derive_done_when_tool_result_present():
    """tool_use followed by matching tool_result → status=done (not running)."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_1", "name": "Bash",
             "input": {"command": "ls"}}
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}
        ]}},
    ]
    status, body = _derive_status_text(events)
    assert status == "done"
    assert "▶" in body


def test_derive_running_when_tool_result_missing():
    """tool_use without matching tool_result → status=running (in flight)."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_2", "name": "Edit",
             "input": {"file_path": "/tmp/foo.py"}}
        ]}}
    ]
    status, body = _derive_status_text(events)
    assert status == "running"
    assert "foo.py" in body


def test_derive_done_for_taskupdate_completed():
    """TaskUpdate(status=completed) is itself a terminal signal."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_3", "name": "TaskUpdate",
             "input": {"taskId": "1", "status": "completed",
                       "subject": "Audit mobile listings"}}
        ]}}
    ]
    status, body = _derive_status_text(events)
    assert status == "done"
    assert "completed" in body or "Audit" in body


def test_derive_waiting_for_askuserquestion():
    """AskUserQuestion stays waiting even if (later) tool_result arrives."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "tu_4", "name": "AskUserQuestion",
             "input": {"questions": [{"question": "Which option?"}]}}
        ]}}
    ]
    status, body = _derive_status_text(events)
    assert status == "waiting"
    assert "❓" in body


def test_derive_done_for_plain_text_assistant_reply():
    """Assistant text-only reply (no tool_use) → status=done."""
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Here is the answer you wanted."}
        ]}}
    ]
    status, body = _derive_status_text(events)
    assert status == "done"
    assert "replied" in body or "✓" in body
