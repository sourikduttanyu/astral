---
description: What Astral does and how to use it
---

Show the user this quick reference (keep it short):

**Astral — context-budget manager.** Never hit autocompact; shed done work instead.

- Runs automatically: warns at ~50/65/80% context with what's DONE.
- `/astral:checkpoint` — pick finished work to shed → writes durable summary + hands you a steered `/compact` line.
- `/astral:status` — current context level + done vs in-flight.
- `/astral:audit` — find never-used / stale agents + skills that bloat every session; prune them (reversible).
- Large reads auto-suggest a subagent (keeps context lean).
- Starting unrelated work → Astral suggests `/clear` first.

Tune via env: `ASTRAL_WINDOW`, `ASTRAL_BUCKETS`, `ASTRAL_READ_LINES`.
Repo: https://github.com/sourikduttanyu/astral
