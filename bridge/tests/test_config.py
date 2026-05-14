"""Tests for bridge config mutation helpers."""

from __future__ import annotations

import json
from pathlib import Path

from openpets_bridge import config


def test_set_source_mute_updates_existing_source(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[bridge]
mode = "single"

[sources.cowork]
enabled = true
label = "Cowork"
icon = "C"
muted = false
""".lstrip()
    )

    path, muted = config.set_source_mute("cowork", True, cfg_path)

    assert path == cfg_path
    assert muted is True
    loaded = config.load(cfg_path)
    assert loaded.sources["cowork"].muted is True
    exported = json.loads(config.export_json(cfg_path))
    assert exported["sources"]["cowork"]["muted"] is True


def test_set_source_mute_inserts_missing_line(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[bridge]
mode = "single"

[sources.codex_cli]
enabled = true
label = "Codex"
icon = "X"
""".lstrip()
    )

    _, muted = config.set_source_mute("codex_cli", True, cfg_path)

    assert muted is True
    text = cfg_path.read_text()
    assert "[sources.codex_cli]" in text
    assert "muted = true" in text
    assert config.load(cfg_path).sources["codex_cli"].muted is True


def test_set_source_mute_accepts_string_path(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"

    path, muted = config.set_source_mute("cowork", True, str(cfg_path))

    assert path == cfg_path
    assert muted is True
    assert config.load(cfg_path).sources["cowork"].muted is True


def test_set_source_mute_rejects_unknown_source(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[bridge]\nmode = \"single\"\n")

    try:
        config.set_source_mute("missing", True, cfg_path)
    except ValueError as error:
        assert "no [sources.missing]" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_load_merges_multi_pet_section_into_extra(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[bridge]
mode = "multi"

[sources.cowork]
enabled = true
label = "Cowork"
icon = "C"

[sources.cowork.multi_pet]
pet = "/tmp/pet"
socket = "/tmp/cowork.sock"
""".lstrip()
    )

    source = config.load(cfg_path).sources["cowork"]

    assert source.extra["pet"] == "/tmp/pet"
    assert source.extra["socket"] == "/tmp/cowork.sock"
