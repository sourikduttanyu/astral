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
number drops and warnings re-arm correctly. The context window is auto-detected from the current model in the transcript
(re-read every prompt, so mid-session model switches are tracked). Tune with:
  ASTRAL_WINDOW   override the detected window, in tokens (else: Haiku/unknown
                  200000, Opus 4.x / Sonnet 4.6 / Fable 5 1000000)
  ASTRAL_BUCKETS  warn bands, comma list of percents (default 40,55,70 -
                  set to fire before accuracy degrades, not at the cap)
"""
import sys, os, json

# Warn bands default to 40/55/70 (% of window). Research on long-context
# accuracy ("context rot") finds a stable region to ~40% of the window, then a
# sharp accuracy drop past ~50% — degradation is monotonic with length and
# hits well before the cap. So warn before the cliff, not at 80%.
#   arxiv 2601.15300 (stable 0-40%, ~45% drop at 50%), arxiv 2510.05381
#   (degradation within 7k-30k tokens, position-independent), Chroma "context rot".
BUCKETS = sorted(int(x) for x in os.environ.get("ASTRAL_BUCKETS", "40,55,70").split(","))
TAIL_BYTES = 512 * 1024

# Detected context windows by model family. ASTRAL_WINDOW overrides everything;
# otherwise we read the current model from the transcript and map it. Unknown /
# synthetic / older models fall back to 200000 (conservative -> warns earlier).
_WINDOWS_1M = ("opus-4-5", "opus-4-6", "opus-4-7", "opus-4-8",
               "sonnet-4-6", "fable-5", "mythos-5")


def window_for(model):
    """Token budget the bands are measured against, for the current model.

    ASTRAL_WINDOW wins if set. Else map the detected model id; Haiku and unknown
    models -> 200000. Re-evaluated every prompt, so mid-session model switches
    (Opus<->Sonnet<->Haiku) are tracked automatically.
    """
    env = os.environ.get("ASTRAL_WINDOW")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    if not model:
        return 200000
    m = model.lower()
    if "haiku" in m:
        return 200000
    if any(tag in m for tag in _WINDOWS_1M):
        return 1000000
    return 200000


def band(pct):
    b = 0
    for t in BUCKETS:
        if pct >= t:
            b = t
    return b


def scan(path):
    """(current context tokens, current model id) from the transcript tail.

    Reads only the tail (latest turns live at the end). Each assistant turn
    carries `usage` and `model` on the same JSON line, so one pass gets both;
    the LAST values win = the most recent turn = the model you're on right now.
    Returns (0, None) if nothing usable is present yet. Synthetic / non-claude
    model strings are ignored so an injected `<synthetic>` turn can't skew the
    detected window.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read()
    except OSError:
        return 0, None
    ctx, model = 0, None
    for raw in tail.split(b"\n"):
        if b'"usage"' not in raw:
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            continue  # partial first line from the tail cut, or non-JSON
        msg = o.get("message") or {}
        u = msg.get("usage") or {}
        cur = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
            + (u.get("cache_creation_input_tokens") or 0)
        if cur:
            ctx = cur  # later lines overwrite -> ends on most recent turn
        mdl = msg.get("model") or o.get("model")
        if isinstance(mdl, str) and mdl.startswith("claude-"):
            model = mdl
    return ctx, model


def real_tokens(path):
    """Current context size in tokens (back-compat wrapper around scan)."""
    return scan(path)[0]


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    transcript = data.get("transcript_path", "")
    cwd = data.get("cwd") or os.getcwd()

    tokens, model = scan(transcript) if transcript and os.path.exists(transcript) else (0, None)
    window = window_for(model)
    pct = round(tokens / window * 100, 1) if window else 0.0

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
            json.dump({"tokens": tokens, "pct": pct, "window": window,
                       "model": model, "band": cur}, f)
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
            f"\n[Astral] Context ~{pct}% (~{tokens} tok / {window}). "
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
