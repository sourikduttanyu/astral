#!/usr/bin/env python3
"""Astral statusline badge.

Reads the current project's `.astral/state.json` (written by astral_monitor.py
on every prompt) and prints a context-budget badge: ``[ASTRAL <pct>%]``,
colored by warn band (0=calm, 1=getting full, 2=near auto-compact).

Receives Claude Code's statusline JSON on stdin; uses only the cwd from it.
Prints nothing if there's no state yet (fresh project) — so it's safe to chain
after another statusline command (e.g. caveman's badge).
"""
import json, os, sys

# 256-color codes: blue-grey (calm) / amber (warn) / red (danger).
BAND_COLOR = {0: 109, 1: 179, 2: 167}


def main():
    try:
        data = json.loads(sys.stdin.read(8192) or "{}")
    except Exception:
        return
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or os.getcwd()
    path = os.path.join(cwd, ".astral", "state.json")
    # Refuse symlinks (a planted link could feed attacker-controlled bytes).
    if os.path.islink(path) or not os.path.isfile(path):
        return
    try:
        with open(path) as f:
            st = json.load(f)
        pct = float(st.get("pct", 0))
        band = int(st.get("band", 0))
    except Exception:
        return
    color = BAND_COLOR.get(band, 109)
    sys.stdout.write(f"\033[38;5;{color}m[ASTRAL {pct:.0f}%]\033[0m")


main()
