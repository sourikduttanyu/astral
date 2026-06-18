---
description: Summarize completed work, pick what to shed, write a checkpoint file before clearing
---

Astral checkpoint. Goal: shed already-finished work from context without losing it.

Note: Claude Code has no native partial/selective compaction. The real lever is
summarize-to-file + `/clear`. This command does the summarize half and lets the
user choose scope.

1. Scan the session. List each COMPLETED, self-contained work-unit (done +
   verified, not needed for active work) as short bullets.
2. Use AskUserQuestion (multiSelect) so the user picks which units to checkpoint
   and drop.
3. For the chosen units, write a concise resume-ready summary (key decisions,
   file paths, commands, outcomes) to `.astral/checkpoint-<UTC-timestamp>.md`.
   Append a new section if the file already exists.
4. Tell the user the file path and that running `/clear` now reclaims context;
   the checkpoint file + any still-open files reload what's actually needed.
5. Do NOT auto-clear. Leave `/clear` to the user.

Keep it tight.
