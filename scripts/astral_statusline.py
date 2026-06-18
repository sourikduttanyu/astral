#!/usr/bin/env python3
"""Astral statusline badge.

Prints a context-budget badge ``[ASTRAL <pct>%]`` colored by warn band
(calm -> amber -> red as you approach auto-compact).

Claude Code hands the statusLine command a JSON payload on stdin. Since
v2.1.132 that payload carries a `context_window` object the harness computes
live every render -- `used_percentage` and the real `context_window_size`
(200000, or 1000000 for extended context). That's the authoritative number and
it tracks reality without any state file, so it's the primary source here.

Two fallbacks keep it working everywhere:
  * `context_window.used_percentage` is `null` before the first API call and
    again right after a `/compact` (until the next call repopulates it), and is
    absent entirely on Claude Code < 2.1.132. When it's missing we fall back to
    `.astral/state-<sid>.json`, which astral_monitor.py writes each prompt
    (with the session's sticky window).
  * If neither is available (fresh project, no state yet) we print nothing --
    safe to chain after another statusline command (e.g. caveman's badge).
"""
import json, os, sys

# Warn bands (% of window); same default as astral_monitor.py.
BUCKETS = sorted(int(x) for x in os.environ.get("ASTRAL_BUCKETS", "40,55,70").split(","))
# 256-color codes: blue-grey (calm) -> amber -> red (danger), by band crossed.
COLORS = (109, 179, 167)


def color_for(pct):
    """Color by how many warn bands `pct` has crossed (0 = calm)."""
    level = sum(1 for t in BUCKETS if pct >= t)
    return COLORS[min(level, len(COLORS) - 1)]


def pct_from_stdin(data):
    """Live context % from the harness-provided `context_window`, or None when
    it's absent/null (pre-first-call, just after /compact, or old Claude Code)."""
    cw = data.get("context_window") or {}
    p = cw.get("used_percentage")
    if p is None:
        return None
    try:
        return float(p)
    except (TypeError, ValueError):
        return None


def pct_from_state(data):
    """Fallback: the percent astral_monitor.py wrote to this session's state."""
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or os.getcwd()
    sid = "".join(c for c in (data.get("session_id") or "") if c.isalnum() or c in "-_")
    fname = f"state-{sid}.json" if sid else "state.json"
    path = os.path.join(cwd, ".astral", fname)
    # Refuse symlinks (a planted link could feed attacker-controlled bytes).
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return float(json.load(f).get("pct", 0))
    except Exception:
        return None


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    pct = pct_from_stdin(data)
    if pct is None:
        pct = pct_from_state(data)
    if pct is None:
        return
    sys.stdout.write(f"\033[38;5;{color_for(pct)}m[ASTRAL {pct:.0f}%]\033[0m")


if __name__ == "__main__":
    main()
