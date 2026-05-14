"""Tests for single-pet mode display filtering."""

from __future__ import annotations

from pathlib import Path

from openpets_bridge.modes.single_pet import SinglePetMode
from openpets_bridge.sources.base import SourceConfig, SourceUpdate
from openpets_bridge.state import ThreadStore


class FakeClient:
    notifications: list[dict] = []

    def notify(self, title, text, status, thread_id):
        self.notifications.append({
            "title": title,
            "text": text,
            "status": status,
            "thread_id": thread_id,
        })
        return thread_id

    def clear(self, thread_id):
        return True


def test_muted_source_is_polled_but_not_displayed(monkeypatch, tmp_path: Path):
    FakeClient.notifications = []
    monkeypatch.setattr("openpets_bridge.modes.single_pet.OpenPetsClient", FakeClient)
    mode = SinglePetMode(
        {
            "cowork": SourceConfig(
                enabled=True,
                muted=True,
                label="Cowork",
                icon="C",
                extra={},
            )
        },
        store=ThreadStore(path=tmp_path / "threads.json"),
    )

    mode.consume([
        SourceUpdate(
            source_id="cowork",
            session_id="session-1",
            title="Work",
            body="running",
            status="running",
            is_active=True,
        )
    ])

    assert FakeClient.notifications == []
