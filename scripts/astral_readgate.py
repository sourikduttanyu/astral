#!/usr/bin/env python3
"""Astral read-gate — runs on PreToolUse for Read.

If a Read targets a large file with no `limit`, deny it and tell Claude to
delegate to a subagent (the "Courier") instead, so a big file dump never lands
in the main context. The user still gets a choice: Claude offers subagent
options; reading directly is allowed if Read is re-run with a `limit`.

Tune with env var:
  ASTRAL_READ_LINES  line threshold to trigger delegation (default 1500)
"""
import sys, os, json

LIMIT = int(os.environ.get("ASTRAL_READ_LINES", "1500"))


def count_lines(path):
    n = 0
    with open(path, "rb") as f:
        for _ in f:
            n += 1
    return n


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Read":
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    if ti.get("limit"):          # user already bounding the read — let it through
        sys.exit(0)

    path = ti.get("file_path", "")
    if not path or not os.path.isfile(path):
        sys.exit(0)

    try:
        lines = count_lines(path)
    except OSError:
        sys.exit(0)

    if lines <= LIMIT:
        sys.exit(0)

    reason = (
        f"Astral: {os.path.basename(path)} is {lines} lines — a full read would bloat "
        "context. Delegate instead: offer the user subagent options via AskUserQuestion "
        "(Explore = locate/search, general-purpose = read + synthesize), then dispatch the "
        "chosen subagent to read it and return only what's needed. To read directly anyway, "
        "re-run Read with a `limit` (and `offset`)."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
