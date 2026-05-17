"""Multi-pet display mode (one OpenPets host per AI source).

Each enabled source spawns its own ``openpets run --pet <pack> --socket <path>``
child process and routes its updates to that dedicated host. Bubbles still
use threadId per-conversation, but each AI now has a visually distinct
sprite (e.g. Mando for Cowork, Grogu for Codex CLI) on the desktop.

Defaults & failure handling:

* If a source has no ``[sources.<id>.extra] pet_dir = "..."``, that source
  falls back to the default OpenPets host (the menubar app's active pet).
* If ``pet_dir`` doesn't exist on disk, the source is skipped (with a clear
  log line pointing at ``openpets-bridge list-pets``).
* If the host's socket fails to bind within 2 s after spawn, the bridge
  warns and continues — notify will degrade gracefully.
* Stale orphan socket files from previous crashes are removed before bind.

Position management for multiple pets (avoid stacking) is left to the user
via the OpenPets tray menu / ``positions.json``.
"""

from __future__ import annotations

import logging
import os
import os.path
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Iterable

from ..openpets_client import OpenPetsClient, _resolve_binary
from ..sources.base import SourceUpdate, SourceConfig
from ..state import ThreadRecord, ThreadStore

log = logging.getLogger("openpets-bridge.mode.multi")


def _socket_alive(path: str, bin_path: str) -> bool:
    """Probe whether something is listening on the given socket."""
    try:
        return subprocess.run(
            [bin_path, "ping", "--socket", path],
            check=False, timeout=2,
            capture_output=True, text=True,
        ).returncode == 0
    except Exception:  # noqa: BLE001
        return False


class MultiPetMode:
    def __init__(
        self,
        source_configs: dict[str, SourceConfig],
        push_throttle_s: float = 1.5,
        auto_clear_after_s: float | None = None,
        store: ThreadStore | None = None,
    ) -> None:
        self._configs = source_configs
        self._throttle = push_throttle_s
        self._auto_clear_after_s = auto_clear_after_s
        # source_id → OpenPetsClient bound to that host's socket
        self._clients: dict[str, OpenPetsClient] = {}
        # source_id → child process (the openpets run host)
        self._hosts: dict[str, subprocess.Popen] = {}
        self._store = store or ThreadStore()
        self._store.load()
        self._spawn_hosts()

    # ------------------------------------------------------------------
    def _spawn_hosts(self) -> None:
        """Spawn an `openpets run` host for each enabled, unmuted source.

        Idempotent: sources that already have a live entry in ``self._hosts``
        or ``self._clients`` are skipped, so this can safely be called from
        ``_respawn_dead_hosts`` to fill in only the missing slots.
        """
        bin_path = _resolve_binary()
        for sid, cfg in self._configs.items():
            if not cfg.enabled or cfg.muted:
                continue
            if sid in self._hosts or sid in self._clients:
                continue  # already running — don't double-spawn
            extra = cfg.extra or {}
            pet_dir = extra.get("pet_dir") or extra.get("pet")
            socket_path = extra.get("socket") or f"/tmp/openpets-{sid}.sock"

            if not pet_dir:
                log.warning(
                    "multi-pet: source %s has no pet pack — set "
                    "[sources.%s.extra] pet_dir=\"...\". Falling back to the "
                    "default OpenPets host (menubar app's active pet).",
                    sid, sid,
                )
                self._clients[sid] = OpenPetsClient(socket_path=None, binary=bin_path)
                continue

            pet_path = os.path.expanduser(str(pet_dir))
            if not os.path.isdir(pet_path):
                log.error(
                    "multi-pet: pet pack for %s not found at %s — skipping. "
                    "Run `openpets-bridge list-pets` to see installed packs.",
                    sid, pet_path,
                )
                continue

            # If a stale socket file exists (orphaned from a previous crash),
            # remove it — Unix sockets can't be re-bound otherwise.
            if os.path.exists(socket_path) and not _socket_alive(socket_path, bin_path):
                try:
                    os.unlink(socket_path)
                except OSError:
                    pass

            args = [bin_path, "run", "--pet", pet_path, "--socket", socket_path]
            instance_id = str(uuid.uuid4())
            log.info("multi-pet: spawning %s → %s", sid, shlex.join(args))
            try:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={**os.environ,
                         "PATH": "/opt/homebrew/bin:" + os.environ.get("PATH", ""),
                         "OPENPETS_BRIDGE_SOURCE_ID": sid,
                         "OPENPETS_INSTANCE_ID": instance_id},
                )
            except Exception as e:  # noqa: BLE001
                log.error("multi-pet: failed to spawn %s host: %s", sid, e)
                continue

            # Give the host ~2 s to come up + bind the socket.
            for _ in range(20):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            else:
                log.warning(
                    "multi-pet: %s socket %s did not appear within 2 s — the "
                    "host may have failed to start. Check `pgrep -f 'openpets "
                    "run'` and the OpenPets logs.",
                    sid, socket_path,
                )
            self._hosts[sid] = proc
            self._clients[sid] = OpenPetsClient(socket_path=socket_path,
                                                binary=bin_path)

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        for sid, proc in list(self._hosts.items()):
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._hosts.clear()
        self._clients.clear()

    # ------------------------------------------------------------------
    def consume(self, updates: Iterable[SourceUpdate]) -> None:
        for u in updates:
            client = self._clients.get(u.source_id)
            if client is None:
                continue  # this source has no host (skipped above)
            cfg = self._configs.get(u.source_id)
            icon = cfg.icon if cfg else ""
            title = f"{icon} {u.title}".strip()
            if cfg and cfg.redact_body:
                text = (u.body.split(" ", 1)[0] if u.body else "·")
            else:
                text = u.body or " "

            rec = self._store.get(u.source_id, u.session_id)
            if rec is None:
                rec = ThreadRecord(
                    source_id=u.source_id, session_id=u.session_id,
                    thread_id=str(uuid.uuid4()).upper(),
                )

            now = time.time()
            same = (rec.last_status == u.status and rec.last_text == text)
            if same and (now - rec.last_push_ts) < self._throttle:
                continue

            prev_status = rec.last_status
            new_tid = client.notify(
                title=title, text=text, status=u.status, thread_id=rec.thread_id,
            )
            if new_tid and new_tid != rec.thread_id:
                rec.thread_id = new_tid
            rec.last_status = u.status
            rec.last_text = text
            rec.last_push_ts = now
            rec.done_at = now if u.status == "done" else None
            self._store.upsert(rec)
            # Privacy: log only metadata, never bubble content.
            # INFO when status transitions, DEBUG otherwise — avoids the
            # log spam we used to emit on every poll cycle even when the
            # bubble was unchanged.
            level = logging.INFO if prev_status != u.status else logging.DEBUG
            log.log(level, "[multi/%s/%s] status=%s",
                    u.source_id, u.session_id[:8] + "…", u.status)
        self._store.save()

    # ------------------------------------------------------------------
    def tick(self) -> None:
        """Periodic upkeep — auto-clear stale bubbles + respawn dead hosts."""
        self._respawn_dead_hosts()
        if self._auto_clear_after_s is None or self._auto_clear_after_s <= 0:
            return
        now = time.time()
        for rec in list(self._store.all()):
            if rec.done_at is None:
                continue
            if (now - rec.done_at) < self._auto_clear_after_s:
                continue
            client = self._clients.get(rec.source_id)
            if client is not None:
                client.clear(rec.thread_id)
            self._store.drop(rec.source_id, rec.session_id)
            log.info("[multi/%s/%s] cleared (auto, idle for %.0fs after done)",
                     rec.source_id, rec.session_id[:8] + "…",
                     now - rec.done_at)
        self._store.save()

    # ------------------------------------------------------------------
    def _respawn_dead_hosts(self) -> None:
        """Re-launch any ``openpets run`` child that exited since last tick.

        launchd's KeepAlive watches `openpets-bridge` itself, but the
        per-source pet hosts it spawns are vanilla subprocesses — without
        this they stay dead until the bridge daemon is restarted.

        Exception: if the user picked "Quit this pet host" from the
        sprite's right-click menu, the CLI drops a marker file at
        ``/tmp/openpets-quit-<source_id>.marker`` BEFORE terminating.
        We honour that signal by dropping the source from our roster
        and NOT respawning — otherwise the menu item would be useless
        (the pet keeps coming back). Re-enabling the source from the
        tray (or restarting the daemon) brings it back.
        """
        if not self._hosts:
            return
        dead: list[tuple[str, bool]] = []   # (sid, user_quit)
        for sid, proc in self._hosts.items():
            if proc.poll() is None:
                continue
            marker = f"/tmp/openpets-quit-{sid}.marker"
            user_quit = os.path.exists(marker)
            if user_quit:
                try:
                    os.unlink(marker)
                except OSError:
                    pass
                log.info(
                    "multi-pet: host for %s exited (rc=%s) — user-initiated "
                    "quit; not respawning",
                    sid, proc.returncode,
                )
            else:
                log.warning(
                    "multi-pet: host for %s exited (rc=%s) — respawning",
                    sid, proc.returncode,
                )
            dead.append((sid, user_quit))
        if not dead:
            return
        # Drop the dead entries. Live hosts are left alone via the
        # `sid in self._hosts` guard inside _spawn_hosts. User-quit
        # sources are also dropped so the next tick won't see them in
        # _hosts — but since we don't call _spawn_hosts() unless we
        # have crash-exits left, they stay down until external action.
        had_crash = False
        for sid, user_quit in dead:
            self._hosts.pop(sid, None)
            self._clients.pop(sid, None)
            if not user_quit:
                had_crash = True
        if had_crash:
            self._spawn_hosts()
