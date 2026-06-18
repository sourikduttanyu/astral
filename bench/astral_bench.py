#!/usr/bin/env python3
"""Astral bench - turn a Claude Code transcript into REAL context metrics.

Reads the per-message `usage` block from the transcript JSONL (actual token
accounting, NOT Astral's bytes/4 proxy) and reports the numbers that matter for
A/B-ing Astral on vs off.

Usage:
  astral_bench.py TRANSCRIPT.jsonl [--label NAME]
  astral_bench.py --compare BASE.jsonl ASTRAL.jsonl [--labels off,on]

Find transcripts at:  ~/.claude/projects/<project-slug>/<session-id>.jsonl
(tip: `ls -t ~/.claude/projects/*/*.jsonl | head` for the most recent)

Metrics:
  autocompacts  forced/auto compaction events  (PRIMARY - target 0)
  peak_ctx      max prompt size of any turn = peak context window used
  in_tok        new (non-cache) input tokens, summed
  out_tok       output tokens, summed
  turns         assistant turns
  reads         Read tool calls (attempts)
  subagents     Task/Agent dispatches (large-read offloads)
"""
import json, sys, argparse


def _is_compact(o):
    """Best-effort compaction detection across Claude Code versions."""
    for k in ("isCompactSummary", "isCompact"):
        if o.get(k):
            return True
    if o.get("type") == "summary":
        return True
    if (o.get("subtype") or "") == "compact":
        return True
    msg = o.get("message") or {}
    c = msg.get("content")
    txt = c if isinstance(c, str) else ""
    if isinstance(c, list):
        txt = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
    low = txt.lower()
    return ("conversation compacted" in low) or ("session is being continued" in low
            and "summary" in low)


def analyze(path):
    m = dict(turns=0, in_tok=0, out_tok=0, peak_ctx=0,
             autocompacts=0, reads=0, subagents=0)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if _is_compact(o):
                m["autocompacts"] += 1
            msg = o.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        n = b.get("name", "")
                        if n == "Read":
                            m["reads"] += 1
                        elif n in ("Task", "Agent"):
                            m["subagents"] += 1
            u = msg.get("usage")
            if u:
                i = u.get("input_tokens", 0) or 0
                ot = u.get("output_tokens", 0) or 0
                cr = u.get("cache_read_input_tokens", 0) or 0
                cc = u.get("cache_creation_input_tokens", 0) or 0
                m["turns"] += 1
                m["in_tok"] += i
                m["out_tok"] += ot
                ctx = i + cr + cc
                if ctx > m["peak_ctx"]:
                    m["peak_ctx"] = ctx
    return m


ORDER = ["autocompacts", "peak_ctx", "in_tok", "out_tok", "turns", "reads", "subagents"]


def _fmt(n):
    return f"{n:,}"


def print_one(label, m):
    print(f"\n== {label} ==")
    for k in ORDER:
        print(f"  {k:<13} {_fmt(m[k])}")


def print_compare(la, ma, lb, mb):
    w = max(len(la), len(lb), 8)
    print(f"\n  {'metric':<13} {la:>{w}} {lb:>{w}}   delta")
    print("  " + "-" * (13 + 2 * w + 12))
    for k in ORDER:
        a, b = ma[k], mb[k]
        d = b - a
        pct = f" ({d/a*100:+.0f}%)" if a else ""
        print(f"  {k:<13} {_fmt(a):>{w}} {_fmt(b):>{w}}   {d:+,}{pct}")
    print("\n  lower is better for every metric except subagents (offload = good).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", nargs="?")
    ap.add_argument("--label", default="run")
    ap.add_argument("--compare", nargs=2, metavar=("BASE", "ASTRAL"))
    ap.add_argument("--labels", default="off,on")
    a = ap.parse_args()

    if a.compare:
        la, lb = (a.labels.split(",") + ["off", "on"])[:2]
        print_compare(la, analyze(a.compare[0]), lb, analyze(a.compare[1]))
        return
    if not a.transcript:
        ap.error("give a TRANSCRIPT.jsonl or use --compare BASE ASTRAL")
    print_one(a.label, analyze(a.transcript))


if __name__ == "__main__":
    main()
