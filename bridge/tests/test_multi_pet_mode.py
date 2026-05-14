"""Tests for multi-pet host spawning."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from openpets_bridge.modes.multi_pet import MultiPetMode
from openpets_bridge.sources.base import SourceConfig


class FakePopen:
    calls: list[dict] = []

    def __init__(self, args, stdout=None, stderr=None, env=None):
        self.args = args
        self.stdout = stdout
        self.stderr = stderr
        self.env = env or {}
        self.terminated = False
        FakePopen.calls.append({"args": args, "env": self.env})

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_spawn_hosts_passes_source_and_instance_env(
    monkeypatch,
    tmp_path: Path,
):
    pet_dir = tmp_path / "pet"
    pet_dir.mkdir()
    socket_path = tmp_path / "cowork.sock"
    FakePopen.calls = []
    monkeypatch.setattr("openpets_bridge.modes.multi_pet._resolve_binary", lambda: "/bin/openpets")
    monkeypatch.setattr(os.path, "exists", lambda path: str(path) == str(socket_path))
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    mode = MultiPetMode({
        "cowork": SourceConfig(
            enabled=True,
            label="Cowork",
            icon="C",
            extra={"pet_dir": str(pet_dir), "socket": str(socket_path)},
        )
    })

    assert len(FakePopen.calls) == 1
    env = FakePopen.calls[0]["env"]
    assert env["OPENPETS_BRIDGE_SOURCE_ID"] == "cowork"
    assert len(env["OPENPETS_INSTANCE_ID"]) == 36
    assert FakePopen.calls[0]["args"] == [
        "/bin/openpets",
        "run",
        "--pet",
        str(pet_dir),
        "--socket",
        str(socket_path),
    ]
    mode.shutdown()


def test_muted_source_does_not_spawn_host(monkeypatch, tmp_path: Path):
    pet_dir = tmp_path / "pet"
    pet_dir.mkdir()
    FakePopen.calls = []
    monkeypatch.setattr("openpets_bridge.modes.multi_pet._resolve_binary", lambda: "/bin/openpets")
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    MultiPetMode({
        "cowork": SourceConfig(
            enabled=True,
            muted=True,
            label="Cowork",
            icon="C",
            extra={"pet_dir": str(pet_dir)},
        )
    })

    assert FakePopen.calls == []
