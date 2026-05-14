"""Smoke tests for LLM CLI source presets."""

from __future__ import annotations

import json
from pathlib import Path

from openpets_bridge.sources.aider import AiderSource
from openpets_bridge.sources.base import SourceConfig
from openpets_bridge.sources.cline import ClineSource
from openpets_bridge.sources.continue_cli import ContinueCliSource
from openpets_bridge.sources.gemini_cli import GeminiCliSource
from openpets_bridge.sources.opencode import OpenCodeSource


def _cfg(source_id: str, root: Path) -> SourceConfig:
    return SourceConfig(
        enabled=True,
        label=source_id,
        icon="*",
        extra={"sessions_root": str(root), "history_root": str(root), "tasks_root": str(root)},
    )


def test_aider_source_emits_assistant_text_after_baseline(tmp_path: Path):
    path = tmp_path / "chat.jsonl"
    path.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")
    source = AiderSource(_cfg("aider", tmp_path))
    assert list(source.poll()) == []
    with path.open("a") as f:
        f.write(json.dumps({"role": "assistant", "content": "done"}) + "\n")
    path.touch()

    updates = list(source.iter_events())

    assert len(updates) == 1
    assert updates[0].status == "done"
    assert updates[0].source_id == "aider"


def test_gemini_source_maps_tool_call_to_running(tmp_path: Path):
    path = tmp_path / "chat.jsonl"
    path.write_text("{}\n")
    source = GeminiCliSource(_cfg("gemini_cli", tmp_path))
    assert list(source.poll()) == []
    with path.open("a") as f:
        f.write(json.dumps({"role": "assistant", "tool_calls": [{"name": "read"}]}) + "\n")
    path.touch()

    updates = list(source.iter_events())

    assert updates and updates[0].status == "running"


def test_opencode_source_reads_parts_tool_invocation(tmp_path: Path):
    path = tmp_path / "chat.jsonl"
    path.write_text("{}\n")
    source = OpenCodeSource(_cfg("opencode", tmp_path))
    assert list(source.poll()) == []
    with path.open("a") as f:
        f.write(json.dumps({"role": "assistant", "parts": [{"type": "tool", "name": "bash"}]}) + "\n")
    path.touch()

    updates = list(source.iter_events())

    assert updates and updates[0].body.startswith("•")


def test_continue_source_reads_new_history_items(tmp_path: Path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"history": [{"role": "user", "content": "hi"}]}))
    source = ContinueCliSource(_cfg("continue_cli", tmp_path))
    assert list(source.poll()) == []
    path.write_text(json.dumps({"history": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]}))
    path.touch()

    updates = list(source.iter_events())

    assert updates and updates[0].status == "done"


def test_cline_source_maps_user_turn_to_waiting(tmp_path: Path):
    path = tmp_path / "task.jsonl"
    path.write_text("{}\n")
    source = ClineSource(_cfg("cline", tmp_path))
    assert list(source.poll()) == []
    with path.open("a") as f:
        f.write(json.dumps({"type": "message", "role": "user", "content": "continue?"}) + "\n")
    path.touch()

    updates = list(source.iter_events())

    assert updates and updates[0].status == "waiting"
