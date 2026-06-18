# Astral bench

Measure whether Astral actually does its job: **fewer autocompacts, leaner
context, fewer tokens per task.** Reads *real* token usage from the transcript
JSONL — not Astral's bytes/4 proxy.

## The claim being tested

Astral ON should, vs OFF, lower:
- **autocompacts** (primary — target `0`)
- **peak_ctx** (peak context window used)
- **in_tok / out_tok** per task

…while NOT increasing turns/wall-time (guards against "leaner but dumber").
`subagents` going *up* is good — large reads offloaded out of main context.

## Method

1. Pick ONE fixed, replayable long task that reliably blows context (e.g.
   multi-file refactor across several 1500+ line files, or a scripted N-step job).
2. Run it in **two arms**, identical model + repo commit + prompt sequence:
   - **off** — Astral uninstalled (`ASTRAL_UNINSTALL=1 bash install.sh`), vanilla autocompact.
   - **on** — Astral installed.
3. **3+ runs per arm.** LLM variance is high; one run lies. Report spread.
4. After each run, grab the transcript and analyze.

## Find the transcript

```bash
ls -t ~/.claude/projects/*/*.jsonl | head    # most recent session first
```

## Run

```bash
# single run
python3 bench/astral_bench.py ~/.claude/projects/<slug>/<session>.jsonl --label on

# A/B compare
python3 bench/astral_bench.py --compare off.jsonl on.jsonl --labels off,on
```

Example compare output:

```
  metric             off        on   delta
  -----------------------------------------------
  autocompacts         2         0   -2 (-100%)
  peak_ctx       195,000   148,200   -46,800 (-24%)
  in_tok          88,400    61,900   -26,500 (-30%)
  out_tok         41,200    39,800   -1,400 (-3%)
  turns               54        52   -2 (-4%)
  reads               19        12   -7 (-37%)
  subagents            0         3   +3
```

## Caveats (read these)

- **Compaction detection is best-effort** — the marker shape varies across Claude
  Code versions (`isCompactSummary`, `type:summary`, or a summary text). If
  `autocompacts` looks wrong, eyeball the transcript and adjust `_is_compact()`.
- **peak_ctx** = max per-turn prompt size (`input + cache_read + cache_creation`).
  That's the true context-window high-water mark, the thing Astral tries to cap.
- `in_tok` excludes cache reads (cheap); it's *new* context paid for each turn.
- N=3+ and report the spread. A single A/B pair is an anecdote, not a result.
