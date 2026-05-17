"""Activity sources for openpets-bridge.

Built-in sources (registered via Python classes):

* `cowork`       — Claude desktop app's Cowork mode (audit.jsonl)
* `codex_cli`    — OpenAI Codex CLI sessions (~/.codex/sessions/)
* `claude_code`  — Anthropic Claude Code CLI projects (~/.claude/projects/)
* `aider`, `gemini_cli`, `opencode`, `continue_cli`, `cline` — LLM CLI presets

User-defined sources (config-only, no Python required):

Any TOML section ``[sources.<my_id>]`` whose ``extra.type = "generic_jsonl"``
is wired through :class:`GenericJsonlSource`. The user provides the watch
paths and patterns; the heuristics in ``llm_cli_common.map_chat_obj``
handle most chat-style JSONL schemas without further tuning. See
``bridge/README.md`` → "Adding your own LLM" for a worked example.

To register a brand-new built-in (rare), subclass
:class:`openpets_bridge.sources.base.Source`, set ``id``, implement ``poll``,
and add it to :data:`REGISTRY` below.
"""

from __future__ import annotations

import logging
from typing import Mapping

from .base import Source, SourceConfig, SourceUpdate
from .cowork import CoworkSource
from .codex_cli import CodexCliSource
from .claude_code import ClaudeCodeSource
from .aider import AiderSource
from .gemini_cli import GeminiCliSource
from .opencode import OpenCodeSource
from .continue_cli import ContinueCliSource
from .cline import ClineSource
from .generic import GenericJsonlSource

__all__ = [
    "Source",
    "SourceConfig",
    "SourceUpdate",
    "CoworkSource",
    "CodexCliSource",
    "ClaudeCodeSource",
    "AiderSource",
    "GeminiCliSource",
    "OpenCodeSource",
    "ContinueCliSource",
    "ClineSource",
    "GenericJsonlSource",
    "load_sources",
    "REGISTRY",
    "CUSTOM_SOURCE_TYPES",
]

REGISTRY: Mapping[str, type[Source]] = {
    "cowork": CoworkSource,
    "codex_cli": CodexCliSource,
    "claude_code": ClaudeCodeSource,
    "aider": AiderSource,
    "gemini_cli": GeminiCliSource,
    "opencode": OpenCodeSource,
    "continue_cli": ContinueCliSource,
    "cline": ClineSource,
}

#: Maps the user-facing ``extra.type`` value to the concrete Source class.
#: Generic / config-driven sources go here, NOT in REGISTRY (which is keyed
#: by the source's stable id).
CUSTOM_SOURCE_TYPES: Mapping[str, type[Source]] = {
    "generic_jsonl": GenericJsonlSource,
}


log = logging.getLogger("openpets-bridge.sources")


def load_sources(configs: Mapping[str, SourceConfig]) -> list[Source]:
    """Instantiate sources for each enabled config entry.

    Resolution order for an enabled ``[sources.<sid>]`` block:

    1. If ``sid`` is in :data:`REGISTRY` (built-in source), use that class.
    2. Otherwise, look at ``cfg.extra["type"]`` and resolve via
       :data:`CUSTOM_SOURCE_TYPES` (currently ``generic_jsonl``).
    3. Otherwise, warn once and skip.
    """
    out: list[Source] = []
    for sid, cfg in configs.items():
        if not cfg.enabled:
            continue
        cls: type[Source] | None = REGISTRY.get(sid)
        if cls is None:
            extra_type = ""
            if cfg.extra:
                extra_type = str(cfg.extra.get("type") or "").strip().lower()
            cls = CUSTOM_SOURCE_TYPES.get(extra_type) if extra_type else None
            if cls is None:
                log.warning(
                    "[sources.%s] not loaded — no built-in module and no "
                    "[sources.%s.extra] type=\"generic_jsonl\". See "
                    "bridge/README.md → 'Adding your own LLM'.",
                    sid, sid,
                )
                continue
        instance = cls(cfg)
        # GenericJsonlSource (and any future custom-type sources) get their
        # stable id from the TOML key, not the class.
        if sid not in REGISTRY:
            instance.id = sid
        out.append(instance)
    return out
