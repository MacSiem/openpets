"""Tests for source preset discovery."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from openpets_bridge import discovery


def test_discover_installed_sources_detects_cli_binary(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/tmp/{name}" if name == "aider" else None)
    monkeypatch.setattr(discovery, "SOURCE_PROBES", {
        "aider": discovery.SourceProbe("aider", ("aider",), ((Path("/missing"), "*.jsonl"),)),
    })

    result = discovery.discover_installed_sources()

    assert result["aider"]["installed"] is True
    assert result["aider"]["watch_path"] is None
    assert result["aider"]["last_activity"] is None


def test_discover_installed_sources_detects_watch_files(tmp_path: Path, monkeypatch):
    watch_dir = tmp_path / "sessions"
    watch_dir.mkdir()
    session = watch_dir / "chat.jsonl"
    session.write_text("{}\n")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(discovery, "SOURCE_PROBES", {
        "gemini_cli": discovery.SourceProbe("gemini_cli", ("gemini",), ((watch_dir, "*.jsonl"),)),
    })

    result = discovery.discover_installed_sources()

    assert result["gemini_cli"]["installed"] is True
    assert result["gemini_cli"]["watch_path"] == str(watch_dir)
    assert isinstance(result["gemini_cli"]["last_activity"], datetime)
