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
number drops and warnings re-arm correctly.

The context WINDOW can't be read from a hook — the harness/tier/subscription
sets it (Claude Code gives Sonnet 4.6 a 200K window but Opus 4.8 a 1M one for
the same session; Cursor lets users pick), and a model id alone doesn't imply a
size. So Astral resolves the window in this precedence:
  1. ASTRAL_WINDOW env (hard pin), else
  2. the user-asserted value in `.astral/window` (set by `/astral:window`), else
  3. 200000 — but raised by the occupancy floor: if current tokens already
     exceed a tier without a compact, the window is provably larger, so it jumps
     to the next known tier automatically.
The model id is still read each prompt: when it CHANGES and the window is
ambiguous, the hook asks Claude to confirm the new window (`/astral:window`).
Tune bands with:
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

# Known context-window tiers, smallest first. The occupancy floor snaps the
# window up to the smallest tier that current usage proves it must be.
TIERS = (200000, 1000000)


def floor_window(tokens):
    """Smallest known tier that can hold `tokens`. Past 200K with no compact
    means the window is really 1M; past 1M means a custom/huge window."""
    for t in TIERS:
        if tokens <= t:
            return t
    return tokens


def user_window(cwd):
    """User-asserted window from `.astral/window` (set by /astral:window), or None."""
    try:
        with open(os.path.join(cwd, ".astral", "window")) as f:
            v = int(f.read().strip())
        return v if v > 0 else None
    except Exception:
        return None


def resolve_window(tokens, cwd):
    """(window, source) by precedence: env > .astral/window > 200000 — each
    raised by the occupancy floor so we never claim a window smaller than what
    the live token count already disproves."""
    env = os.environ.get("ASTRAL_WINDOW")
    if env:
        try:
            return max(int(env), 1), "env"
        except ValueError:
            pass
    u = user_window(cwd)
    if u:
        return max(u, floor_window(tokens)), "user"
    return floor_window(tokens), "auto"


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


def state_name(session_id):
    """Per-session state filename so two terminals in one project don't clobber
    each other's badge. Falls back to the shared name when no session id."""
    sid = "".join(c for c in (session_id or "") if c.isalnum() or c in "-_")
    return f"state-{sid}.json" if sid else "state.json"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    transcript = data.get("transcript_path", "")
    cwd = data.get("cwd") or os.getcwd()

    tokens, model = scan(transcript) if transcript and os.path.exists(transcript) else (0, None)
    window, source = resolve_window(tokens, cwd)
    pct = round(tokens / window * 100, 1) if window else 0.0

    state_dir = os.path.join(cwd, ".astral")
    state_path = os.path.join(state_dir, state_name(data.get("session_id")))
    prev = {}
    try:
        with open(state_path) as f:
            prev = json.load(f)
    except Exception:
        pass
    # Re-arm bands when the window changes (e.g. a switch to a smaller window
    # must be able to fire even if a higher band already fired at the larger one).
    last = prev.get("band", 0) if prev.get("window") == window else 0

    cur = band(pct)
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(state_path, "w") as f:
            json.dump({"tokens": tokens, "pct": pct, "window": window,
                       "model": model, "source": source, "band": cur}, f)
    except OSError:
        pass

    guard = (
        "Astral active. If this prompt starts work unrelated to the session so far, "
        "suggest `/clear` first; if the user declines, offer `/astral:checkpoint` to "
        "summarize and shed completed work before continuing."
    )
    out = guard

    # Model changed and the window is genuinely ambiguous (occupancy hasn't
    # proven a tier, and the user hasn't pinned it) -> ask which window applies.
    model_changed = bool(model and prev.get("model") and model != prev.get("model"))
    if model_changed and source != "env" and tokens <= TIERS[0]:
        out += (
            f"\n[Astral] Model changed ({prev.get('model')} -> {model}). Its context "
            f"window depends on your tier/subscription (e.g. 200K or 1M), which Astral "
            "can't read. Ask the user via AskUserQuestion which window applies "
            "(200K / 1M / keep current), then run `/astral:window <200000|1000000>` so "
            "the bands and badge match. Do this before continuing."
        )
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
