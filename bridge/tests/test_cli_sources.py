"""CLI coverage for source preset commands."""

from __future__ import annotations

from pathlib import Path

from openpets_bridge import cli


def test_cli_discover_sources_prints_table(monkeypatch, capsys):
    monkeypatch.setattr(cli, "discover_installed_sources", lambda: {
        "aider": {"installed": True, "watch_path": "/tmp/aider", "last_activity": None},
    })

    rc = cli.main(["discover-sources"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "aider" in out
    assert "/tmp/aider" in out


def test_cli_add_source_preset_uses_config_path(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[bridge]\nmode = \"single\"\n")
    monkeypatch.setattr(cli, "_restart_bridge_daemon", lambda: None)

    rc = cli.main(["config", "add-source-preset", "aider", "--config", str(cfg_path)])

    assert rc == 0
    assert "[sources.aider]" in cfg_path.read_text()


def test_cli_remove_source_uses_config_path(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[bridge]
mode = "single"

[sources.aider]
enabled = false
label = "Aider"
icon = "A"
""".lstrip()
    )
    monkeypatch.setattr(cli, "_restart_bridge_daemon", lambda: None)

    rc = cli.main(["config", "remove-source", "aider", "--config", str(cfg_path)])

    assert rc == 0
    assert "[sources.aider]" not in cfg_path.read_text()
