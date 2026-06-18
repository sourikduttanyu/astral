---
description: Show Astral context level and completed work
---

Astral status.

1. Read `.astral/state.json` in the current working dir (if present). Report the
   estimated context usage: percent and token count vs the assumed window.
   If the file is missing, say monitoring hasn't run yet this session.
2. List the session's completed work-units and what's still in-flight.
3. End with a one-line recommendation: keep going / consider `/astral:checkpoint`
   / consider `/clear`.

Keep it short.
