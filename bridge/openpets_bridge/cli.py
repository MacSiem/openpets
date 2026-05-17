"""``openpets-bridge`` command-line entry point."""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from pathlib import Path
from shlex import quote as shlex_quote


def _find_first_existing(*candidates: Path) -> str | None:
    for c in candidates:
        if c.is_file():
            return str(c)
    return None

from . import __version__
from . import config as bridgeconfig
from .discovery import discover_installed_sources
from . import orchestrator
from . import pets as petsmod
from .openpets_client import OpenPetsClient


LAUNCHD_LABEL = "sh.openpets.bridge"
# Legacy: the old standalone rumps menubar lived under this label. We no longer
# install it (the controls are in OpenPets.app's tray now), but `uninstall`
# still bootouts and removes it for users upgrading from <= 0.1.5.
LEGACY_MENUBAR_LABEL = "sh.openpets.bridge.menubar"


def _launchd_plist_path(label: str = LAUNCHD_LABEL) -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{label}.plist"


def _python_executable() -> str:
    """Pick the Python interpreter that goes into the launchd plist.

    We prefer newer Homebrew Pythons first so that on M-series Macs running
    3.14 we don't lock the agent to whichever 3.12 install happens to exist
    today (and then break if the user upgrades to 3.15 and prunes 3.14).
    """
    # 1. Explicit Homebrew versioned bins, newest first. Covers both Apple
    #    Silicon (/opt/homebrew) and Intel (/usr/local) prefixes.
    versioned_candidates = [
        "/opt/homebrew/bin/python3.14",
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3.10",
        "/usr/local/bin/python3.14",
        "/usr/local/bin/python3.13",
        "/usr/local/bin/python3.12",
        "/usr/local/bin/python3.11",
        "/usr/local/bin/python3.10",
    ]
    for cand in versioned_candidates:
        if os.path.isfile(cand):
            return cand
    # 2. Glob /opt/homebrew/bin/python3.* to catch new minors (3.15+) we
    #    haven't enumerated yet. Sort descending so the newest wins.
    for cand in sorted(glob.glob("/opt/homebrew/bin/python3.*"), reverse=True):
        if os.path.isfile(cand) and not cand.endswith(("-config", "t")):
            return cand
    # 3. Generic symlink, then the current interpreter as a final fallback.
    for cand in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3", sys.executable):
        if os.path.isfile(cand):
            return cand
    return sys.executable


def _launchd_plist_xml(stdout_log: str, stderr_log: str,
                       label: str = LAUNCHD_LABEL,
                       module: str = "openpets_bridge",
                       subcommand: str = "run") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>            <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{_python_executable()}</string>
        <string>-u</string>
        <string>-m</string>
        <string>{module}</string>
        <string>{subcommand}</string>
    </array>
    <key>RunAtLoad</key>        <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key> <false/>
        <key>Crashed</key>        <true/>
    </dict>
    <key>ThrottleInterval</key> <integer>10</integer>
    <key>StandardOutPath</key>  <string>{stdout_log}</string>
    <key>StandardErrorPath</key><string>{stderr_log}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""


def cmd_init(args) -> int:
    p = bridgeconfig.write_default()
    print(f"wrote {p}")
    return 0


def cmd_run(args) -> int:
    cfg = bridgeconfig.load(args.config)
    return orchestrator.run(cfg)


def cmd_status(args) -> int:
    cfg = bridgeconfig.load(args.config)
    print(f"openpets-bridge {__version__}")
    print(f"  mode             : {cfg.mode}")
    print(f"  poll_interval_s  : {cfg.poll_interval_s}")
    print(f"  log              : {cfg.log_path}")
    print( "  sources:")
    for sid, sc in cfg.sources.items():
        flag = "ON " if sc.enabled else "off"
        muted = " muted" if sc.muted else ""
        print(f"    [{flag}] {sid:<14} {sc.icon}  {sc.label}{muted}")
    client = OpenPetsClient()
    print(f"  openpets ping    : {'pong' if client.ping() else 'NOT REACHABLE — is OpenPets.app running?'}")
    plist = _launchd_plist_path()
    print(f"  launchd plist    : {plist} {'(installed)' if plist.exists() else '(not installed — run `openpets-bridge install`)'}")
    return 0


def cmd_install(args) -> int:
    """Install the bridge launchd agent (controls live in OpenPets.app's tray)."""
    bridgeconfig.write_default()
    # Canonical macOS log location (~/Library/Logs/openpets-bridge). The
    # legacy ~/ai-stack/openpets-bridge path is still recognised as a fallback
    # in the tray menu's "Open Bridge Log" action.
    log_dir = Path.home() / "Library/Logs/openpets-bridge"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Bridge daemon (the only agent we install — controls live in OpenPets.app)
    plist = _launchd_plist_path(LAUNCHD_LABEL)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_launchd_plist_xml(
        stdout_log=str(log_dir / "launchd.stdout.log"),
        stderr_log=str(log_dir / "launchd.stderr.log"),
    ))
    rc = _reload_launchd_agent(LAUNCHD_LABEL, plist)
    if rc != 0:
        print(f"WARN: bridge bootstrap returned {rc} — run `launchctl bootstrap "
              f"gui/$(id -u) {plist}` manually", file=sys.stderr)
    else:
        print(f"Installed bridge daemon agent: {plist}")

    # If a legacy rumps menubar agent from <= 0.1.5 is still loaded,
    # tear it down silently — controls now live in OpenPets.app.
    legacy_plist = _launchd_plist_path(LEGACY_MENUBAR_LABEL)
    if legacy_plist.exists():
        uid = os.getuid()
        os.system(f"launchctl bootout gui/{uid}/{LEGACY_MENUBAR_LABEL} 2>/dev/null")
        legacy_plist.unlink()
        print(f"Removed legacy menubar agent: {legacy_plist}")
        print("  Bridge controls are now in OpenPets.app's tray menu (🐾 icon).")
    return 0


def cmd_list_pets(args) -> int:
    """List installed OpenPets pet packs across the standard locations."""
    pets = petsmod.discover()
    if not pets:
        print("No pet packs found in any of:")
        for root in petsmod.DEFAULT_PET_ROOTS:
            print(f"  - {root}")
        print("\nInstall a pack into one of those folders, or download one"
              " from https://openpets.sh/gallery")
        return 1
    print(f"{len(pets)} pet pack(s) installed:\n")
    for p in pets:
        marker = "✓" if p.has_spritesheet else "✗ (missing spritesheet)"
        print(f"  {marker} {p.display_name}  [{p.pet_id}]")
        print(f"      {p.path}")
        if p.description:
            print(f"      {p.description}")
        print()
    print("To use one in multi-pet mode, copy its absolute path into your config:\n")
    print('  [sources.<source_id>.extra]')
    print(f'  pet_dir = "{pets[0].path}"')
    print(f'  socket  = "/tmp/openpets-<source_id>.sock"')
    return 0


def cmd_config(args) -> int:
    """Inspect or mutate ~/.config/openpets-bridge/config.toml.

    Sub-actions are dispatched on ``args.config_cmd``:
      show           — dump current config as JSON (used by tray menu)
      set-mode       — switch [bridge].mode to single|multi
      toggle-source  — flip [sources.<id>].enabled
      mute-source    — set [sources.<id>].muted = true
      unmute-source  — set [sources.<id>].muted = false
      set-source-pet — set [sources.<id>.multi_pet].pet (+ socket)

    All mutating actions trigger a launchd restart so the daemon reloads.
    """
    sub = args.config_cmd
    if sub == "show":
        print(bridgeconfig.export_json(getattr(args, "config", None)))
        return 0

    if sub == "set-mode":
        p = bridgeconfig.set_mode(args.mode, getattr(args, "config", None))
        print(f"set [bridge].mode = {args.mode!r} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "toggle-source":
        try:
            p, new_state = bridgeconfig.toggle_source(
                args.source_id, getattr(args, "config", None)
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"set [sources.{args.source_id}].enabled = "
              f"{'true' if new_state else 'false'} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub in ("mute-source", "unmute-source"):
        muted = sub == "mute-source"
        try:
            p, new_state = bridgeconfig.set_source_mute(
                args.source_id, muted, getattr(args, "config", None)
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"set [sources.{args.source_id}].muted = "
              f"{'true' if new_state else 'false'} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "set-mute":
        try:
            p, new_state = bridgeconfig.set_source_mute(
                args.source_id, args.state == "on", getattr(args, "config", None)
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"set [sources.{args.source_id}].muted = "
              f"{'true' if new_state else 'false'} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "set-source-pet":
        p = bridgeconfig.set_source_pet(
            args.source_id, args.pet_dir, args.socket,
            getattr(args, "config", None),
        )
        print(f"set [sources.{args.source_id}.multi_pet].pet "
              f"= {args.pet_dir!r} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "set-poll-interval":
        p = bridgeconfig.set_poll_interval(args.seconds, getattr(args, "config", None))
        print(f"set [bridge].poll_interval_s = {args.seconds:g} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "set-push-throttle":
        p = bridgeconfig.set_push_throttle(args.seconds, getattr(args, "config", None))
        print(f"set [bridge].push_throttle_s = {args.seconds:g} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "set-auto-clear":
        p = bridgeconfig.set_auto_clear_after(args.seconds, getattr(args, "config", None))
        print(f"set [bridge].auto_clear_after_s = {args.seconds:g} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "set-redact-body":
        p = bridgeconfig.set_all_sources_redact_body(
            args.state == "on", getattr(args, "config", None)
        )
        print(f"set [sources.*].redact_body = {args.state == 'on'} in {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "add-source-preset":
        try:
            p = bridgeconfig.add_source_preset(args.preset_id, getattr(args, "config", None))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"added [sources.{args.preset_id}] to {p}")
        _restart_bridge_daemon()
        return 0

    if sub == "remove-source":
        try:
            p = bridgeconfig.remove_source(args.preset_id, getattr(args, "config", None))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"removed [sources.{args.preset_id}] from {p}")
        _restart_bridge_daemon()
        return 0

    print(f"unknown config sub-command: {sub}", file=sys.stderr)
    return 2


def cmd_discover_sources(args) -> int:
    """Print a table of source discovery results."""
    rows = discover_installed_sources()
    print(f"{'id':<14} {'installed':<9} {'watch_path':<62} last_activity")
    for sid in sorted(rows):
        row = rows[sid]
        installed = "yes" if row["installed"] else "no"
        watch_path = row["watch_path"] or "-"
        last_activity = row["last_activity"].isoformat(sep=" ", timespec="seconds") if row["last_activity"] else "-"
        print(f"{sid:<14} {installed:<9} {watch_path:<62} {last_activity}")
    return 0


def _reload_launchd_agent(label: str, plist: Path) -> int:
    """Atomic bootout + bootstrap cycle for a single launchd label.

    launchd needs a short pause after bootout before bootstrap accepts the
    same label again — otherwise it returns ``Bootstrap failed: 5: Input/output
    error``. We retry once with a longer pause if the first bootstrap fails.

    Returns the exit code of the final bootstrap attempt (0 on success).
    Errors are best-effort: we never raise.
    """
    uid = os.getuid()
    # bootout is allowed to fail (e.g. agent not loaded yet) — ignore rc.
    os.system(f"launchctl bootout gui/{uid}/{label} 2>/dev/null")
    time.sleep(0.8)  # let launchd actually unload the service
    quoted = shlex_quote(str(plist))
    rc = os.system(f"launchctl bootstrap gui/{uid} {quoted} 2>/dev/null")
    if rc != 0:
        time.sleep(1.0)  # one retry after a longer pause
        rc = os.system(f"launchctl bootstrap gui/{uid} {quoted} 2>/dev/null")
    return rc


def _restart_bridge_daemon() -> None:
    """Best-effort restart so the bridge picks up new config."""
    plist = _launchd_plist_path(LAUNCHD_LABEL)
    if not plist.exists():
        return  # daemon not installed → nothing to restart
    rc = _reload_launchd_agent(LAUNCHD_LABEL, plist)
    if rc != 0:
        print(f"  note: launchd reload returned {rc} — restart manually if needed",
              file=sys.stderr)


def cmd_clear(args) -> int:
    """Clear OpenPets bubbles for tracked threads.

    --all       : clear every persisted thread (active + done)
    --done-only : clear only threads where status was last reported as 'done'
    """
    from .state import ThreadStore
    store = ThreadStore()
    store.load()
    targets = []
    for rec in store.all():
        if args.done_only and rec.done_at is None:
            continue
        targets.append(rec)
    if not targets:
        print("No matching threads to clear.")
        return 0

    cfg = bridgeconfig.load(getattr(args, "config", None))
    # Map source_id → socket (multi-pet mode); fallback to default socket.
    source_sockets: dict[str, str | None] = {}
    for sid, sc in cfg.sources.items():
        sock = (sc.extra or {}).get("socket") if sc.extra else None
        source_sockets[sid] = sock

    cleared = 0
    for rec in targets:
        sock = source_sockets.get(rec.source_id)
        client = OpenPetsClient(socket_path=sock) if sock else OpenPetsClient()
        if client.clear(thread_id=rec.thread_id):
            cleared += 1
            store.drop(rec.source_id, rec.session_id)
    store.save(force=True)
    print(f"Cleared {cleared}/{len(targets)} bubble(s).")
    return 0


def cmd_uninstall(args) -> int:
    """Stop + remove the bridge daemon (and any legacy menubar agent)."""
    uid = os.getuid()
    for label in (LEGACY_MENUBAR_LABEL, LAUNCHD_LABEL):
        os.system(f"launchctl bootout gui/{uid}/{label} 2>/dev/null")
        plist = _launchd_plist_path(label)
        if plist.exists():
            plist.unlink()
            print(f"Removed {plist}")
    print("openpets-bridge uninstalled (config + logs left in place)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="openpets-bridge",
        description="Multi-AI desktop pet bridge for OpenPets.",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_run = sub.add_parser("run", help="Run the bridge in the foreground")
    sp_run.add_argument("--config", default=None, help="Path to config.toml")
    sp_run.set_defaults(func=cmd_run)

    sp_init = sub.add_parser("init", help="Write a default config.toml")
    sp_init.set_defaults(func=cmd_init)

    sp_st = sub.add_parser("status", help="Show config + connectivity")
    sp_st.add_argument("--config", default=None)
    sp_st.set_defaults(func=cmd_status)

    sp_inst = sub.add_parser("install", help="Install + start the bridge launchd agent")
    sp_inst.set_defaults(func=cmd_install)

    sp_un = sub.add_parser("uninstall", help="Stop + remove launchd agent")
    sp_un.set_defaults(func=cmd_uninstall)

    sp_pets = sub.add_parser("list-pets",
                             help="Discover installed OpenPets pet packs")
    sp_pets.set_defaults(func=cmd_list_pets)

    sp_discover = sub.add_parser("discover-sources",
                                 help="Discover installed AI CLI source presets")
    sp_discover.set_defaults(func=cmd_discover_sources)

    sp_cfg = sub.add_parser("config",
                            help="Inspect or mutate the bridge config.toml")
    cfg_sub = sp_cfg.add_subparsers(dest="config_cmd", required=True)

    cfg_show = cfg_sub.add_parser("show",
                                   help="Dump current config as JSON")
    cfg_show.add_argument("--config", default=None)

    cfg_mode = cfg_sub.add_parser("set-mode",
                                   help="Switch single ↔ multi pet mode")
    cfg_mode.add_argument("mode", choices=["single", "multi"])
    cfg_mode.add_argument("--config", default=None)

    cfg_tog = cfg_sub.add_parser("toggle-source",
                                  help="Flip enabled for a source")
    cfg_tog.add_argument("source_id",
                         help="cowork | codex_cli | claude_code | …")
    cfg_tog.add_argument("--config", default=None)

    cfg_mute = cfg_sub.add_parser("mute-source",
                                  help="Hide a source's pet output while keeping it polled")
    cfg_mute.add_argument("source_id",
                          help="cowork | codex_cli | claude_code | …")
    cfg_mute.add_argument("--config", default=None)

    cfg_unmute = cfg_sub.add_parser("unmute-source",
                                    help="Show a muted source again")
    cfg_unmute.add_argument("source_id",
                            help="cowork | codex_cli | claude_code | …")
    cfg_unmute.add_argument("--config", default=None)

    cfg_set_mute = cfg_sub.add_parser("set-mute",
                                      help="Set source muted state")
    cfg_set_mute.add_argument("source_id")
    cfg_set_mute.add_argument("state", choices=["on", "off"])
    cfg_set_mute.add_argument("--config", default=None)

    cfg_pet = cfg_sub.add_parser("set-source-pet",
                                  help="Pick the pet pack a source wears in multi mode")
    cfg_pet.add_argument("source_id")
    cfg_pet.add_argument("pet_dir",
                         help="Absolute path to a pet pack directory")
    cfg_pet.add_argument("--socket", default=None,
                         help="Override socket path (default /tmp/openpets-<id>.sock)")
    cfg_pet.add_argument("--config", default=None)

    cfg_poll = cfg_sub.add_parser("set-poll-interval",
                                  help="Set bridge poll_interval_s")
    cfg_poll.add_argument("seconds", type=float)
    cfg_poll.add_argument("--config", default=None)

    cfg_push = cfg_sub.add_parser("set-push-throttle",
                                  help="Set bridge push_throttle_s")
    cfg_push.add_argument("seconds", type=float)
    cfg_push.add_argument("--config", default=None)

    cfg_clear_after = cfg_sub.add_parser("set-auto-clear",
                                         help="Set bridge auto_clear_after_s")
    cfg_clear_after.add_argument("seconds", type=float)
    cfg_clear_after.add_argument("--config", default=None)

    cfg_redact = cfg_sub.add_parser("set-redact-body",
                                    help="Set redact_body for every configured source")
    cfg_redact.add_argument("state", choices=["on", "off"])
    cfg_redact.add_argument("--config", default=None)

    cfg_add = cfg_sub.add_parser("add-source-preset",
                                 help="Add a known source preset to config")
    cfg_add.add_argument("preset_id")
    cfg_add.add_argument("--config", default=None)

    cfg_remove = cfg_sub.add_parser("remove-source",
                                    help="Remove a non-builtin source from config")
    cfg_remove.add_argument("preset_id")
    cfg_remove.add_argument("--config", default=None)

    sp_cfg.set_defaults(func=cmd_config)

    sp_clear = sub.add_parser("clear",
                              help="Clear OpenPets bubbles for tracked threads")
    grp = sp_clear.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true",
                     help="Clear every persisted thread (active + done)")
    grp.add_argument("--done-only", action="store_true",
                     help="Clear only threads currently in 'done' state")
    sp_clear.add_argument("--config", default=None)
    sp_clear.set_defaults(func=cmd_clear)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
