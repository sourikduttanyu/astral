---
description: Audit installed agents/skills - find never-used or stale ones and help prune them
---

Astral audit. Goal: surface agents/skills that load into context every session
but are never (or rarely) used, and help the user shed them to reclaim token
budget. Read-only analysis; cleanup is reversible and user-approved.

1. Run the audit script and show the user its report:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/astral_audit.py
   ```

   (If `CLAUDE_PLUGIN_ROOT` is unset because this was installed via the
   one-line installer, use `~/.claude/astral/scripts/astral_audit.py`.)

   It buckets every installed agent/skill into NEVER / STALE(>`ASTRAL_STALE_DAYS`,
   default 60) / ACTIVE, by parsing real usage from `~/.claude/projects/*/*.jsonl`,
   and prints the reclaimable tokens/session.

2. Summarize: how many prunable, how many tokens reclaimed, name the heaviest
   never-used ones.

3. Use AskUserQuestion (multiSelect) to let the user choose what to shed:
   - all NEVER-used
   - NEVER + STALE
   - pick a specific subset
   - nothing (just wanted the report)

4. For the chosen items, hand the user the ready-to-run `mv ... .disabled/`
   commands from the script output (or `--json` for the full list). These MOVE
   files to a `.disabled/` sibling dir - reversible, nothing deleted.

5. Tell the user: this is reversible (move back from `.disabled/`), and they
   must restart Claude Code (or `/hooks`) for the picker to drop them. Do NOT
   run the `mv` commands yourself unless the user explicitly says to - this
   touches their global `~/.claude` config.

Keep it tight.
