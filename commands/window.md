---
description: Set the context window Astral measures against (200K / 1M / custom / auto)
---

Astral `/astral:window` — assert the context window for this project so the warn
bands and the statusline badge match your actual model/tier. Astral can't read
the real window from a hook (the harness/subscription sets it), so this records
your choice.

Argument: `$ARGUMENTS` — interpret it as:
- `opus` or `1m` or `1000000` → **1000000**
- `sonnet` or `200k` or `200000` → **200000**
- a bare integer → that exact token count
- `auto` / `reset` / empty → clear the override (Astral falls back to its
  occupancy-floor auto-detection)

Steps:
1. Resolve the argument to an integer (or "clear" for auto/reset/empty). If it's
   empty and you're acting on an Astral model-change prompt, ask the user which
   window applies (200K / 1M / keep) via AskUserQuestion first.
2. Write that integer to `.astral/window` in the current working directory
   (create `.astral/` if needed). For auto/reset, delete `.astral/window` if it
   exists.
3. Confirm to the user, e.g. "Astral window set to 1,000,000 tokens — bands now
   fire at 400K / 550K / 700K." (bands are 40/55/70% of the window). For a clear,
   say auto-detection is restored.

Note: this is per-project (lives in `.astral/`). `ASTRAL_WINDOW` env still
overrides it. The change takes effect on your next prompt (when the monitor
re-reads it). Keep it tight.
