#!/usr/bin/env python3
"""Faux binaire devpod pour les tests. Simule les commandes principales."""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("devpod <command>", file=sys.stderr)
        return 1

    # Enregistrer chaque appel dans $DEVPOD_HOME/fake_calls.log
    devpod_home = os.environ.get("DEVPOD_HOME", "")
    if devpod_home and args:
        os.makedirs(devpod_home, exist_ok=True)
        calls_log = os.path.join(devpod_home, "fake_calls.log")
        with open(calls_log, "a", encoding="utf-8") as f:
            f.write(" ".join(args) + "\n")

    cmd = args[0]

    if cmd == "version":
        print("v0.6.15 (fake)")
        return 0

    if cmd == "up":
        ws_id = _get_flag(args, "--id") or "unknown"
        print(f"Starting workspace {ws_id}...")
        sys.stdout.flush()
        time.sleep(0.05)
        print(f"Workspace {ws_id} is ready")
        return 0

    if cmd == "stop":
        ws_id = args[1] if len(args) > 1 else "unknown"
        print(f"Stopped {ws_id}")
        return 0

    if cmd == "delete":
        ws_id = args[1] if len(args) > 1 else "unknown"
        print(f"Deleted {ws_id}")
        return 0

    if cmd == "list":
        if "--output" in args:
            idx = args.index("--output")
            if idx + 1 < len(args) and args[idx + 1] == "json":
                print(json.dumps([]))
        else:
            print("(no workspaces)")
        return 0

    if cmd == "provider":
        sub = args[1] if len(args) > 1 else ""
        if sub == "list":
            # Simuler le format tableau de devpod provider list (v0.6.15)
            # Si DEVPOD_HOME contient "provider_ok", simuler docker déjà présent
            home = os.environ.get("DEVPOD_HOME", "")
            if "provider_ok" in home:
                print("    NAME   | VERSION | DEFAULT |")
                print("  ---------+---------+---------+")
                print("   docker  | v0.0.1  | true    |")
            else:
                print("    NAME | VERSION | DEFAULT |")
                print("  -------+---------+---------+")
            return 0
        if sub == "add":
            name = args[2] if len(args) > 2 else ""
            print(f"Provider {name!r} added")
            return 0
        return 0

    if cmd == "ssh":
        # Simule devpod ssh --command "sleep N" : reste actif quelques dixièmes
        # pour que _start_port_forward puisse enregistrer le proc, puis s'arrête.
        time.sleep(0.3)
        return 0

    if cmd in ("--help", "-h", "help"):
        print("fake devpod help")
        return 0

    print(f"fake_devpod: unknown command {cmd!r}", file=sys.stderr)
    return 1


def _get_flag(args: list[str], flag: str) -> str | None:
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(f"{flag}="):
            return a.split("=", 1)[1]
    return None


if __name__ == "__main__":
    sys.exit(main())
