#!/usr/bin/env python3
"""Astral read-gate - runs on PreToolUse for Read.

If a Read targets a large TEXT file with no `limit`, ASK the user before the
full dump lands in context - and tell Claude that on a decline it should
delegate to a subagent (the "Courier") instead. Not a hard block: the user can
allow the direct read, or Claude can re-run Read with a `limit`.

Size is judged in estimated TOKENS (file bytes / 4), not line count: a 400-line
minified file is huge, 1500 short lines is tiny. Uses os.path.getsize - no
reading the file on the hot path.

Tune with env var:
  ASTRAL_READ_TOKENS  token estimate that triggers the gate (default 8000)
"""
import sys, os, json

LIMIT = int(os.environ.get("ASTRAL_READ_TOKENS", "8000"))
# Read handles these specially (visual / paged); size-gating them is wrong.
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
            ".pdf", ".ipynb"}


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") != "Read":
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    if ti.get("limit"):          # already bounding the read - let it through
        sys.exit(0)

    path = ti.get("file_path", "")
    if not path or not os.path.isfile(path):
        sys.exit(0)
    if os.path.splitext(path)[1].lower() in SKIP_EXT:
        sys.exit(0)

    try:
        est = os.path.getsize(path) // 4
    except OSError:
        sys.exit(0)

    if est <= LIMIT:
        sys.exit(0)

    reason = (
        f"Astral: {os.path.basename(path)} is ~{est:,} tokens - a full read would "
        "bloat context. Prefer delegating: if the user declines this read, offer "
        "subagent options via AskUserQuestion (Explore = locate/search, "
        "general-purpose = read + synthesize), then dispatch the chosen subagent to "
        "read it and return only what's needed. Or re-run Read with a `limit` "
        "(and `offset`). Allow if a direct full read is genuinely wanted."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
