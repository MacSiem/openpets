"""Tests for the user-configurable GenericJsonlSource."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openpets_bridge.sources import (
    GenericJsonlSource,
    REGISTRY,
    load_sources,
)
from openpets_bridge.sources.base import SourceConfig


def _cfg(**extra) -> SourceConfig:
    return SourceConfig(
        enabled=True,
        label="MyLLM",
        icon="🎯",
        redact_body=False,
        extra=extra,
    )


def test_generic_source_resolves_via_extra_type(tmp_path: Path):
    """User-defined source id (not in REGISTRY) routes through GenericJsonlSource."""
    cfg = _cfg(type="generic_jsonl", roots=[str(tmp_path)], patterns=["*.jsonl"])
    sources = load_sources({"my_custom_llm": cfg})
    assert len(sources) == 1
    src = sources[0]
    assert isinstance(src, GenericJsonlSource)
    # The instance id reflects the TOML section key, not the class default.
    assert src.id == "my_custom_llm"


def test_unknown_source_without_type_is_skipped(tmp_path: Path, caplog):
    """An [sources.foo] block without extra.type is dropped with a warning."""
    cfg = _cfg()  # no type set
    with caplog.at_level("WARNING", logger="openpets-bridge.sources"):
        sources = load_sources({"unknown_llm": cfg})
    assert sources == []
    assert any("not loaded" in r.message for r in caplog.records)


def test_generic_source_emits_running_for_tool_call(tmp_path: Path):
    """Standard chat schema with a tool_calls entry → running."""
    session = tmp_path / "session-1.jsonl"
    session.write_text("")
    cfg = _cfg(type="generic_jsonl", roots=[str(tmp_path)], patterns=["*.jsonl"])
    src = GenericJsonlSource(cfg)
    src.id = "ollama"

    # First poll = baseline (zero new lines, but `_state` does set length).
    initial = list(src.poll())
    assert initial == []

    # Append a tool-call line and re-poll.
    with session.open("a") as f:
        f.write(json.dumps({
            "role": "assistant",
            "tool_calls": [{"name": "shell", "input": {"cmd": "ls"}}]
        }) + "\n")

    updates = list(src.poll())
    assert len(updates) == 1
    u = updates[0]
    assert u.source_id == "ollama"
    assert u.status == "running"
    assert u.is_active is True


def test_generic_source_emits_done_for_assistant_text(tmp_path: Path):
    """Plain assistant reply (no tool call) → done."""
    session = tmp_path / "chat.jsonl"
    session.write_text("")
    cfg = _cfg(type="generic_jsonl", roots=[str(tmp_path)])
    src = GenericJsonlSource(cfg)
    src.id = "myllm"

    list(src.poll())  # baseline
    with session.open("a") as f:
        f.write(json.dumps({
            "role": "assistant",
            "content": "All done.",
        }) + "\n")
    updates = list(src.poll())
    assert len(updates) == 1
    assert updates[0].status == "done"


def test_custom_role_mapping_overrides_defaults(tmp_path: Path):
    """User-supplied role lists outrank the default heuristics."""
    session = tmp_path / "log.jsonl"
    session.write_text("")
    cfg = _cfg(
        type="generic_jsonl",
        roots=[str(tmp_path)],
        role_field="speaker",
        waiting_roles=["human"],
        done_roles=["agent"],
    )
    src = GenericJsonlSource(cfg)
    src.id = "myllm"

    list(src.poll())  # baseline
    with session.open("a") as f:
        f.write(json.dumps({"speaker": "human", "content": "do thing"}) + "\n")
        f.write(json.dumps({"speaker": "agent", "content": "ok"}) + "\n")

    updates = list(src.poll())
    statuses = [u.status for u in updates]
    assert "waiting" in statuses, statuses
    assert "done" in statuses, statuses


def test_generic_source_handles_missing_roots(caplog):
    """A config with no roots[] logs a warning at construction."""
    cfg = _cfg(type="generic_jsonl")  # no roots
    with caplog.at_level("WARNING", logger="openpets-bridge.source.generic"):
        src = GenericJsonlSource(cfg)
    src.id = "broken"
    assert any("no [sources." in r.message for r in caplog.records)
    # Polling without roots yields nothing rather than crashing.
    assert list(src.poll()) == []


def test_registry_contains_eight_builtins():
    """Sanity: the built-in source registry is exactly the 8 advertised ones."""
    assert set(REGISTRY.keys()) == {
        "cowork", "codex_cli", "claude_code",
        "aider", "gemini_cli", "opencode", "continue_cli", "cline",
    }
