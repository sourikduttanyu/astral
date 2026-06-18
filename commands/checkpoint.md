---
description: Summarize completed work to a durable file, then hand the user a steered /compact line
---

Astral checkpoint (hybrid flow). Goal: shed already-finished work from context
without losing it — durable record + keep the live thread.

Note: Claude Code has no native partial/verbatim compaction. The only real
selectivity comes from `/compact`'s instruction text. This command writes a
durable summary AND generates that steered `/compact` line.

1. Scan the session. List each COMPLETED, self-contained work-unit (done +
   verified, not needed for active work) as short bullets.
2. Use AskUserQuestion (multiSelect) so the user picks which units to shed.
3. For the chosen units, write a concise resume-ready summary (key decisions,
   file paths, commands, outcomes) to `.astral/checkpoint-<UTC-timestamp>.md`.
   Append a new section if the file already exists.
4. Identify what must STAY: the active task and any still-relevant open files.
5. Output a ready-to-run steered compaction line for the user to paste, e.g.:

   `/compact Keep: <active task> and open files <...>. Drop: completed work — <units>, now saved in .astral/checkpoint-<ts>.md.`

6. Tell the user: running that `/compact` sheds the done work but keeps the
   thread; the `.md` is the durable backup. Do NOT auto-run it — Claude cannot
   invoke slash commands; the user runs it.

Keep it tight.
