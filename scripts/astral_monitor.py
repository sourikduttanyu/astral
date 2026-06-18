#!/usr/bin/env python3
"""Astral monitor — runs on every UserPromptSubmit.

Two jobs:
1. Estimate context usage from the transcript and warn when it crosses a band,
   so the user is told what's DONE and offered a checkpoint BEFORE autocompact.
2. Always inject a tiny standing rule so Claude guards against unrelated
   context switches (suggest /clear first).

Context size is read from the transcript's most recent turn `usage` block
(input_tokens + cache_read + cache_creation) - the same real accounting the
bench uses, NOT a bytes proxy. So it tracks reality: after a /compact the
number drops and warnings re-arm correctly. Tune with env vars:
  ASTRAL_WINDOW   assumed context window in tokens (default 200000)
  ASTRAL_BUCKETS  warn bands, comma list of percents (default 50,65,80)
"""
import sys, os, json

WINDOW = int(os.environ.get("ASTRAL_WINDOW", "200000"))
BUCKETS = sorted(int(x) for x in os.environ.get("ASTRAL_BUCKETS", "50,65,80").split(","))
TAIL_BYTES = 512 * 1024


def band(pct):
    b = 0
    for t in BUCKETS:
        if pct >= t:
            b = t
    return b


def real_tokens(path):
    """Most recent turn's real context size from its `usage` block.

    Reads only the tail of the transcript (latest turns live at the end), parses
    each line's usage, and returns the LAST one found = current context
    occupancy. Returns 0 if no usage is present yet.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read()
    except OSError:
        return 0
    ctx = 0
    for raw in tail.split(b"\n"):
        if b'"usage"' not in raw:
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            continue  # partial first line from the tail cut, or non-JSON
        u = (o.get("message") or {}).get("usage") or {}
        cur = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
            + (u.get("cache_creation_input_tokens") or 0)
        if cur:
            ctx = cur  # later lines overwrite -> ends on most recent turn
    return ctx


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    transcript = data.get("transcript_path", "")
    cwd = data.get("cwd") or os.getcwd()

    tokens = real_tokens(transcript) if transcript and os.path.exists(transcript) else 0
    pct = round(tokens / WINDOW * 100, 1) if WINDOW else 0.0

    state_dir = os.path.join(cwd, ".astral")
    state_path = os.path.join(state_dir, "state.json")
    last = 0
    try:
        with open(state_path) as f:
            last = json.load(f).get("band", 0)
    except Exception:
        pass

    cur = band(pct)
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(state_path, "w") as f:
            json.dump({"tokens": tokens, "pct": pct, "window": WINDOW, "band": cur}, f)
    except OSError:
        pass

    guard = (
        "Astral active. If this prompt starts work unrelated to the session so far, "
        "suggest `/clear` first; if the user declines, offer `/astral:checkpoint` to "
        "summarize and shed completed work before continuing."
    )
    out = guard
    if cur > last and cur > 0:
        out += (
            f"\n[Astral] Context ~{pct}% (~{tokens} tok / {WINDOW}). "
            "Tell the user what work is DONE, then offer `/astral:checkpoint` to "
            "summarize + drop finished work so you never hit autocompact."
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": out,
        }
    }))


if __name__ == "__main__":
    main()
