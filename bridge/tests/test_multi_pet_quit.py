"""Tests for the user-quit marker handling in MultiPetMode."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from openpets_bridge.modes.multi_pet import MultiPetMode
from openpets_bridge.sources.base import SourceConfig


class _FakeProc:
    """Minimal subprocess.Popen stand-in: poll() reports a fixed exit code."""

    def __init__(self, returncode: int | None = 0) -> None:
        self.returncode = returncode

    def poll(self):
        return self.returncode


def _make_mode(monkeypatch, tmp_path: Path, sources: dict[str, SourceConfig]) -> MultiPetMode:
    """Build a MultiPetMode without actually spawning any host or thread store."""
    # Patch _resolve_binary so __init__ doesn't go shopping for openpets.
    monkeypatch.setattr(
        "openpets_bridge.modes.multi_pet._resolve_binary",
        lambda: str(tmp_path / "fake-openpets"),
    )
    # Replace _spawn_hosts with a no-op so __init__ doesn't try to launch
    # real subprocesses. The tests will populate _hosts / _clients manually.
    monkeypatch.setattr(MultiPetMode, "_spawn_hosts", lambda self: None)
    mode = MultiPetMode(sources)
    return mode


def test_user_quit_marker_prevents_respawn(monkeypatch, tmp_path: Path):
    """Marker file → dead host is dropped, _spawn_hosts is NOT re-invoked."""
    cfg = SourceConfig(enabled=True, label="Cowork", icon="🤝",
                       redact_body=False, extra={})
    mode = _make_mode(monkeypatch, tmp_path, {"cowork": cfg})

    # Inject a dead host with a quit marker.
    mode._hosts["cowork"] = _FakeProc(returncode=0)  # type: ignore[assignment]
    marker = "/tmp/openpets-quit-cowork.marker"
    Path(marker).write_text("")
    assert os.path.exists(marker)

    # Track _spawn_hosts to make sure it's NOT called.
    spawn_calls = {"n": 0}

    def fake_spawn(self):
        spawn_calls["n"] += 1

    monkeypatch.setattr(MultiPetMode, "_spawn_hosts", fake_spawn)

    mode._respawn_dead_hosts()

    assert "cowork" not in mode._hosts, "user-quit source must be dropped from roster"
    assert spawn_calls["n"] == 0, "user-quit must NOT trigger _spawn_hosts"
    assert not os.path.exists(marker), "marker must be consumed"


def test_crash_without_marker_triggers_respawn(monkeypatch, tmp_path: Path):
    """No marker → crash recovery still kicks in (P2-2 behavior preserved)."""
    cfg = SourceConfig(enabled=True, label="Codex", icon="🟢",
                       redact_body=False, extra={})
    mode = _make_mode(monkeypatch, tmp_path, {"codex_cli": cfg})

    mode._hosts["codex_cli"] = _FakeProc(returncode=139)  # type: ignore[assignment]

    spawn_calls = {"n": 0}

    def fake_spawn(self):
        spawn_calls["n"] += 1

    monkeypatch.setattr(MultiPetMode, "_spawn_hosts", fake_spawn)

    # Ensure no marker exists.
    marker = "/tmp/openpets-quit-codex_cli.marker"
    if os.path.exists(marker):
        os.unlink(marker)

    mode._respawn_dead_hosts()

    assert "codex_cli" not in mode._hosts, "dead host dropped before respawn"
    assert spawn_calls["n"] == 1, "crashed host must trigger _spawn_hosts"


def test_mixed_quit_and_crash(monkeypatch, tmp_path: Path):
    """One user-quit + one crash → respawn only the crash."""
    cfg = SourceConfig(enabled=True, label="X", icon="·",
                      redact_body=False, extra={})
    mode = _make_mode(monkeypatch, tmp_path, {"cowork": cfg, "codex_cli": cfg})

    mode._hosts["cowork"] = _FakeProc(returncode=0)        # type: ignore[assignment]
    mode._hosts["codex_cli"] = _FakeProc(returncode=139)   # type: ignore[assignment]

    Path("/tmp/openpets-quit-cowork.marker").write_text("")
    # No marker for codex_cli.
    if os.path.exists("/tmp/openpets-quit-codex_cli.marker"):
        os.unlink("/tmp/openpets-quit-codex_cli.marker")

    spawn_calls = {"n": 0}

    def fake_spawn(self):
        spawn_calls["n"] += 1

    monkeypatch.setattr(MultiPetMode, "_spawn_hosts", fake_spawn)

    mode._respawn_dead_hosts()

    assert "cowork" not in mode._hosts
    assert "codex_cli" not in mode._hosts
    assert spawn_calls["n"] == 1, "exactly one _spawn_hosts call for the crashed source"
    assert not os.path.exists("/tmp/openpets-quit-cowork.marker")
