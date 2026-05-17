"""Generic JSONL chat source — configurable purely from TOML.

This is the escape hatch for any LLM CLI (or other AI agent) that:

* writes its session transcript as append-only JSON-lines files
* uses one of the common chat schemas (``role``/``content`` records,
  ``tool_calls``/``parts`` arrays, etc.)

Users get a working bridge for their tool without writing a single line
of Python — they describe the source entirely in
``~/.config/openpets-bridge/config.toml``::

    [sources.ollama]
    enabled = true
    label   = "Ollama"
    icon    = "🦙"

    [sources.ollama.extra]
    type     = "generic_jsonl"
    roots    = ["~/Library/Application Support/ollama/sessions"]
    patterns = ["*.jsonl"]

For tools whose schema doesn't fit the heuristics in
:func:`openpets_bridge.sources.llm_cli_common.map_chat_obj`, users can
further tune the role → status mapping::

    [sources.ollama.extra]
    type     = "generic_jsonl"
    roots    = ["~/.ollama/logs"]
    patterns = ["chat-*.jsonl"]
    role_field = "speaker"      # default: "role" / "type"
    running_roles = ["thinking", "tool"]
    done_roles    = ["assistant", "model"]
    waiting_roles = ["user", "human"]

If even that's not enough, the user can still ship a real Python class
in :mod:`openpets_bridge.sources` and register it in
:data:`openpets_bridge.sources.REGISTRY` — the legacy path.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from .base import SourceUpdate
from .llm_cli_common import (
    JsonlChatSource,
    has_tool_call,
    map_chat_obj,
    pick_content,
)

log = logging.getLogger("openpets-bridge.source.generic")


class GenericJsonlSource(JsonlChatSource):
    """JSONL chat source whose paths and mapping come from ``cfg.extra``.

    The class itself contains no source-specific knowledge — it reads
    ``roots`` and ``patterns`` from the source's ``extra`` block and
    inherits the standard ``poll``/``map`` plumbing from
    :class:`JsonlChatSource`.
    """

    # The orchestrator sets ``self.id`` from the config key, not from the
    # class. We give it a sentinel so REGISTRY lookups don't collide.
    id = "generic_jsonl"

    def __init__(self, config) -> None:
        super().__init__(config)
        extra = dict(config.extra or {})
        self._roots_tuple = tuple(self._expand_paths(extra.get("roots") or []))
        self._patterns_tuple = tuple(extra.get("patterns") or ("*.jsonl",))
        self.title = str(extra.get("title") or config.label or "Custom LLM")

        # Optional role-mapping override. Empty → fall back to map_chat_obj.
        self._role_field = str(extra.get("role_field") or "")
        self._running_roles = self._lower_set(extra.get("running_roles"))
        self._done_roles = self._lower_set(extra.get("done_roles"))
        self._waiting_roles = self._lower_set(extra.get("waiting_roles"))
        self._failed_roles = self._lower_set(extra.get("failed_roles"))

        if not self._roots_tuple:
            log.warning(
                "[%s] generic_jsonl source has no [sources.%s.extra].roots — "
                "the bridge will never emit anything. Add at least one "
                "directory path to watch.",
                config.label, config.label,
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _expand_paths(values) -> list[Path]:
        if isinstance(values, (str, os.PathLike)):
            values = [values]
        out: list[Path] = []
        for v in values:
            if not v:
                continue
            out.append(Path(os.path.expanduser(str(v))).expanduser())
        return out

    @staticmethod
    def _lower_set(values) -> frozenset[str]:
        if not values:
            return frozenset()
        if isinstance(values, str):
            values = [values]
        return frozenset(str(v).lower() for v in values)

    # ------------------------------------------------------------------
    def _roots(self) -> tuple[Path, ...]:
        return self._roots_tuple

    @property
    def patterns(self) -> tuple[str, ...]:  # type: ignore[override]
        return self._patterns_tuple

    @patterns.setter
    def patterns(self, value) -> None:
        # JsonlChatSource defines ``patterns`` as a class attribute. The
        # setter exists only so super().__init__ can assign to it without
        # AttributeError on some Python versions; we ignore the assignment
        # and keep using whatever ``_patterns_tuple`` we computed.
        pass

    def _map(self, obj: dict) -> tuple[str, str, bool]:
        # If the user gave a custom role mapping, honour it first.
        if self._role_field:
            role = str(obj.get(self._role_field) or "").lower()
            body = pick_content(obj)
            if role in self._failed_roles:
                return "failed", body or "⚠ Failed", False
            if role in self._waiting_roles:
                return "waiting", body or "⌛ Waiting", True
            if role in self._running_roles or has_tool_call(obj):
                return "running", body or "• Working", True
            if role in self._done_roles:
                return "done", body or "✓ Replied", False
        # Fallback to the shared heuristic used by built-in CLI sources.
        return map_chat_obj(obj)

    # ------------------------------------------------------------------
    def poll(self) -> Iterable[SourceUpdate]:
        if not self._roots_tuple:
            return
        yield from super().poll()
