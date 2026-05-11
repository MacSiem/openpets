"""``openpets-bridge`` command-line entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _find_first_existing(*candidates: Path) -> str | None:
    for c in candidates:
        if c.is_file():
            return str(c)
    return None

from . import __version__
from . import config as bridgeconfig
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
    # Prefer Homebrew python explicitly so launchd doesn't break on PATH
    for cand in ("/opt/homebrew/bin/python3.12",
                 "/opt/homebrew/bin/python3",
                 sys.executable):
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
        print(f"    [{flag}] {sid:<14} {sc.icon}  {sc.label}")
    client = OpenPetsClient()
    print(f"  openpets ping    : {'pong' if client.ping() else 'NOT REACHABLE — is OpenPets.app running?'}")
    plist = _launchd_plist_path()
    print(f"  launchd plist    : {plist} {'(installed)' if plist.exists() else '(not installed — run `openpets-bridge install`)'}")
    return 0


def cmd_install(args) -> int:
    """Install the bridge launchd agent (controls live in OpenPets.app's tray)."""
    bridgeconfig.write_default()
    log_dir = Path.home() / "ai-stack/openpets-bridge"
    log_dir.mkdir(parents=True, exist_ok=True)
    uid = os.getuid()

    # Bridge daemon (the only agent we install — controls live in OpenPets.app)
    plist = _launchd_plist_path(LAUNCHD_LABEL)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_launchd_plist_xml(
        stdout_log=str(log_dir / "launchd.stdout.log"),
        stderr_log=str(log_dir / "launchd.stderr.log"),
    ))
    os.system(f"launchctl bootout gui/{uid}/{LAUNCHD_LABEL} 2>/dev/null")
    rc = os.system(f"launchctl bootstrap gui/{uid} {shutil_quote(str(plist))}")
    if rc != 0:
        print(f"WARN: bridge bootstrap returned {rc} — run `launchctl bootstrap "
              f"gui/$(id -u) {plist}` manually", file=sys.stderr)
    else:
        print(f"Installed bridge daemon agent: {plist}")

    # If a legacy rumps menubar agent from <= 0.1.5 is still loaded,
    # tear it down silently — controls now live in OpenPets.app.
    legacy_plist = _launchd_plist_path(LEGACY_MENUBAR_LABEL)
    if legacy_plist.exists():
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
              " from https://openpets.dev")
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


def shutil_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


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
