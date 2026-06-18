# Astral

[![GitHub stars](https://img.shields.io/github/stars/sourikduttanyu/astral?style=flat&logo=github)](https://github.com/sourikduttanyu/astral/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/sourikduttanyu/astral)](https://github.com/sourikduttanyu/astral/commits/master)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d77757)](https://github.com/sourikduttanyu/astral)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A context-budget manager for Claude Code.** Astral watches how full your context
window is, warns you before auto-compact silently rewrites your session, and helps
you decide what to drop — so you stay in control and your results stay accurate.

## What problem this solves

Claude Code (and Cursor) can only hold so much in context at once — a fixed
**context window**. When it fills up, the tool auto-compacts: it crams your whole
session into a summary on its own, with no warning and no say in what gets cut,
and often drops something you still needed.

Hitting the cap isn't the only problem. **Accuracy degrades long before the window
is full** — the more you stuff in, the more the model misses, confuses, or
hallucinates ("context rot"). A bigger window doesn't fix that; it just lets you
fill it with more noise. Keeping the working set lean is about *quality*, not only
about dodging auto-compact.

Astral's job: **tell you before context gets heavy, and let you choose what to
drop** — instead of letting the tool blindly flatten everything.

---

## What it does

Five pieces, each a concrete outcome, plus a status command:

- **No surprise compactions.** A **Watcher** checks your context on every prompt
  and warns you at 40% / 55% / 70% full — while you can still act, not after the
  session was already compacted.
- **Drop finished work, keep the live thread.** At a **Checkpoint**, you
  multi-select the work that's already done. Astral writes a resume-ready note and
  hands you a `/compact` line steered to shed that work — instead of flattening the
  whole conversation.
- **Big file reads don't eat your memory.** Before a large `Read`, a **Read-gate**
  offers to hand the file to a subagent, so a 10K-token dump stays out of your main
  session.
- **Get nudged to start clean.** A **Switch-guard** notices when your new prompt is
  unrelated to the current session and suggests `/clear` first.
- **Stop paying rent on dead tooling.** An **Audit** scans your installed agents and
  skills against real usage, flags the never-used or stale ones that load every
  session, and gives you reversible commands to prune them.
- **Get evicted context back.** Before compaction, a **Recall** store snapshots the
  about-to-be-dropped turns; a `recall(query)` tool lets Claude re-fetch the right
  slice on demand — see [Recall](#recall-re-fetch-evicted-context).

Plus `/astral:status` to see your current level and what's done at any time.

| Piece | Trigger | Behavior |
|---|---|---|
| **Watcher** | every prompt (`UserPromptSubmit`) | Reads real context usage from the transcript. Crossing a band (40% / 55% / 70% by default) tells you what work is **done** and offers `/astral:checkpoint` — *before* auto-compact. |
| **Checkpoint** | `/astral:checkpoint` | Lists completed work-units, lets you **pick which to shed** (multi-select), writes a resume-ready summary to `.astral/checkpoint-<ts>.md`, then hands you a **steered `/compact` line** that drops the done work but keeps the live thread. |
| **Read-gate** | before any `Read` (`PreToolUse: Read`) | If the target file is large (>~8000 est. tokens) and unbounded, **asks** before reading and offers **subagent options** (Explore / general-purpose) so a big dump never lands in your main context. Allow the direct read, or it delegates. |
| **Switch-guard** | every prompt | If your prompt starts work unrelated to the current session, suggests `/clear` first; if you decline, offers a checkpoint of what's droppable. |
| **Status** | `/astral:status` | Shows current context level + completed vs in-flight work. |
| **Audit** | `/astral:audit` | Scans every installed agent/skill against real usage in your transcripts. Flags ones **never used** or **stale** (>60d) — dead weight loaded into *every* session — and hands you reversible `mv … .disabled/` commands. Reports tokens reclaimed. |
| **Recall** | `PreCompact` + `recall()` tool | Snapshots about-to-be-evicted turns to `.astral/store/` and indexes them; the `recall(query)` MCP tool re-fetches the right slice when a later step needs context that compaction dropped. |

---

## Install

One line, ~10 seconds, idempotent (safe to re-run).

### Prerequisites

- `python3` and `git` — both preinstalled on macOS/Linux. On Windows, install
  [Python](https://www.python.org/downloads/) (check "Add to PATH") and
  [Git](https://git-scm.com/download/win).
- Claude Code v2.1.132+ for the statusline badge (older versions still get hooks +
  commands; the badge just falls back to per-session state).

### macOS / Linux / WSL / Git Bash

```bash
curl -fsSL https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.sh | bash
```

### Windows (PowerShell 5.1+)

```powershell
irm https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.ps1 | iex
```

### What the installer does

1. Clones the repo to `~/.claude/astral`.
2. Copies the slash commands into `~/.claude/commands/astral/`.
3. Merges the two hooks into `~/.claude/settings.json` — your existing settings and
   hooks are preserved, not overwritten.
4. Wires the statusline badge (chaining after any existing statusline).

### Verify the install

```bash
# 1. Restart Claude Code, or reload hooks in an open session:
/hooks

# 2. Confirm Astral is live:
/astral:status     # current context %, window, model, band
/astral:help       # commands + config at a glance
```

You should also see the badge — `[ASTRAL 23%]` — in your statusline. Warnings fire on
their own from here; nothing else to configure.

### Update

Re-run the same one-line install command for your OS. It `git pull`s the clone,
re-copies commands, and re-merges hooks, then restart Claude Code:

```bash
curl -fsSL https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.sh | bash
```

> A bare `git pull` in `~/.claude/astral` updates the hook scripts (they run from the
> clone) but **not** the commands (those are copied into `~/.claude/commands/astral/`).
> Re-running the installer is the reliable path.

### Uninstall

```bash
# macOS / Linux / WSL / Git Bash
ASTRAL_UNINSTALL=1 bash ~/.claude/astral/install.sh
```

```powershell
# Windows (PowerShell)
$env:ASTRAL_UNINSTALL=1; irm https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.ps1 | iex
```

This removes the hooks, commands, and statusline wiring, and restores any statusline
you had before.

### Manual / as a plugin

The repo is also a valid Claude Code plugin (`.claude-plugin/plugin.json` +
`hooks/hooks.json`, paths use `${CLAUDE_PLUGIN_ROOT}`). Clone anywhere and load it via
the plugin loader:

```bash
git clone https://github.com/sourikduttanyu/astral.git
# then point Claude Code's plugin loader at the cloned directory
```

> `hooks/hooks.json` invokes `python3` (it can't self-detect the interpreter the way
> the installer does). On Windows, where the binary is usually `python`, prefer the
> one-line installer above — it wires the exact interpreter that ran it.

---

## Features — usage & examples

Nothing to learn up front: the **Watcher**, **Read-gate**, **Switch-guard**, and
**Recall** capture run on their own after install. The commands (**Checkpoint**,
**Status**, **Window**, **Audit**) are there for when you want to act. Each feature
below has what it does, how to use it, and a worked example.

**Mental model:** `status` to look, `checkpoint` to shed, `window` to fix the basis,
`audit` to prune. The automatic pieces handle the rest hands-off.

### Watcher — warns before auto-compact

- **Trigger:** automatic, on every prompt (`UserPromptSubmit`). Nothing to run.
- **What it does:** reads real context usage from the transcript and warns when you
  cross a band — `40% / 55% / 70%` of the window by default — naming what work is
  already DONE and offering a checkpoint, *before* auto-compact rewrites your session.
- **How to use it:** just keep working. When a warning fires, decide: keep going,
  `/astral:checkpoint`, or `/clear`.

**Example.** Mid-session your badge ticks past 55%. Astral surfaces:

```text
[ASTRAL] Context at 56% (112K / 200K). Crossed the 55% band.
Done so far: (1) fixed the recall MCP path bug, (2) verified recall end-to-end.
Consider /astral:checkpoint to shed finished work before auto-compact.
```

Tune the bands with `ASTRAL_BUCKETS` (see [Config](#config-env-vars)):

```bash
export ASTRAL_BUCKETS=50,70,85   # warn later, e.g. on a roomy 1M window
```

### Checkpoint — shed finished work, keep the live thread

- **Trigger:** you run `/astral:checkpoint`.
- **What it does:** lists completed, self-contained work-units, lets you multi-select
  which to shed, writes a resume-ready summary to `.astral/checkpoint-<UTC-ts>.md`, and
  hands you a steered `/compact` line that drops the done work but keeps the live thread.
- **How to use it:**

```bash
/astral:checkpoint
```

**Example.** You've finished a bug fix and are starting a new feature. Run the command;
Astral lists the done units, you pick the bug-fix one, and it returns a line to paste:

```text
/compact Keep: the new export-feature work and open files src/export.py, tests/test_export.py.
Drop: completed work — recall MCP path fix (verified), now saved in .astral/checkpoint-20260618T230114Z.md.
```

Paste that `/compact` line yourself — Claude can't run slash commands. The `.md` file is
your durable backup; the steered line shapes what stays in context.

### Read-gate — keep big file reads out of your context

- **Trigger:** automatic, before any `Read` (`PreToolUse: Read`). Nothing to run.
- **What it does:** if the target file is large (over `ASTRAL_READ_TOKENS`, default
  `8000` est. tokens = `bytes / 4`) and the read is unbounded, it asks first and offers
  to delegate the read to a subagent (Explore / general-purpose) that summarizes in its
  own context — so a 50K-token log never lands in your main window.
- **How to use it:** when prompted, allow the direct read or let it delegate. To always
  bypass the gate for certain paths, set `ASTRAL_READ_ALLOW`:

```bash
# Comma-separated globs, matched on full path + basename:
export ASTRAL_READ_ALLOW='*/CHANGELOG.md,*.csv,*/package-lock.json'
```

**Example.** You ask Claude to read a 5,000-line server log. The gate intercepts:
instead of dumping ~40K tokens into your session, a subagent reads it and returns just
the answer ("3 OOM errors at 14:02, 14:09, 14:31"). Your main context stays lean.

### Switch-guard — nudge to start clean on unrelated work

- **Trigger:** automatic, on every prompt (`UserPromptSubmit`). Nothing to run.
- **What it does:** if your new prompt starts work unrelated to the current session, it
  suggests `/clear` first; if you decline, it offers a checkpoint of what's droppable —
  so stale context doesn't bleed into new work.
- **How to use it:** when nudged, run `/clear` to start fresh, or decline and continue.

**Example.** After a long debugging session you type "now help me write release notes."
Astral notices the topic shift:

```text
[ASTRAL] This looks unrelated to the current debugging session.
Consider /clear to start fresh, or /astral:checkpoint to shed the finished debugging work first.
```

### Status & Window — inspect and fix the basis

- **`/astral:status`** — show current context level (percent + token count vs window),
  completed vs in-flight work, and a one-line recommendation.

```bash
/astral:status
```

- **`/astral:window`** — assert the context window the bands measure against, per
  project. Needed when the same model can have different windows (Sonnet 200K vs Opus
  1M) or when using Cursor. Auto-detection usually handles this; override when it's
  genuinely ambiguous.

```bash
/astral:window opus      # 1,000,000-token basis
/astral:window sonnet    # 200,000-token basis
/astral:window 500000    # custom integer (e.g. a Cursor window)
/astral:window auto      # clear the override, back to auto-detect (also: reset)
```

**Example.** You switch from Sonnet to Opus mid-session. Astral asks which window
applies; you confirm Opus and it reports: *"Astral window set to 1,000,000 tokens —
bands now fire at 400K / 550K / 700K."* The setting lives in `.astral/window` and takes
effect on your next prompt.

### Audit — prune tooling you never use

- **Trigger:** you run `/astral:audit`.
- **What it does:** scans every installed agent/skill against real usage in your
  transcripts, buckets them NEVER / STALE (> `ASTRAL_STALE_DAYS`, default 60) / ACTIVE,
  reports tokens reclaimed per session, and hands you reversible `mv … .disabled/`
  commands. Read-only analysis; nothing is deleted.
- **How to use it:**

```bash
/astral:audit                       # default 60-day stale threshold
ASTRAL_STALE_DAYS=90 /astral:audit  # only flag stale after 90 days
```

**Example.** The audit finds 12 agents never used in your transcripts, costing ~9K
tokens loaded every session. You multi-select the never-used set; Astral hands you:

```bash
mv ~/.claude/agents/some-unused-agent.md ~/.claude/agents/.disabled/
```

Run those (or move them back later to re-enable). Restart Claude Code or run `/hooks`
for the change to take effect.

### Recall — re-fetch context that compaction evicted

- **Trigger:** automatic capture on `PreCompact`; on-demand re-fetch via the
  `recall(query, k)` MCP tool that Claude calls itself.
- **What it does:** before compaction, snapshots the about-to-be-evicted turns to
  `.astral/store/` and indexes them; later, when a step needs detail that was dropped,
  Claude calls `recall()` to pull the right slice back — so re-hydration looks automatic.
- **How to use it:** the installer registers the recall MCP server in user scope
  (`~/.claude.json`), so it's available in **every** project; working inside a clone of
  this repo also gets it via the repo's `.mcp.json`. Confirm it's connected, then it's
  hands-off:

```bash
/mcp                 # should list astral-recall as connected
```

You can also nudge Claude explicitly: *"recall the error text from earlier."* Disable
the whole store with `ASTRAL_STORE=0`; tune results with `ASTRAL_RECALL_K`. See
[Recall](#recall-re-fetch-evicted-context) for the mechanics.

**Example.** Forty turns ago Claude saw an exact stack trace; auto-compact has since
dropped it. When you ask "what was that traceback?", Claude calls
`recall(query="traceback OOM", k=5)` and the store returns the original lines from the
snapshot — no need to re-run anything.

---

## How it works

*Mechanics for the curious. Skip to [Config](#config-env-vars) if you just want it
running.*

**Token accounting is real, not guessed.** The context count is read from the
transcript's latest `usage` field — `input + cache_read + cache_creation`, the
model's own accounting (the same numbers the benchmark uses). It tracks reality and
drops after a `/compact`.

**Resolving the context window is the tricky part.** The window isn't something a
hook can read — it's set by the harness and your tier/subscription, and the *same
model* can have *different* windows. Claude Code gives Sonnet 4.6 a 200K window but
Opus 4.8 a 1M window in the same session; Cursor lets you pick. So a model id does
**not** determine the window. Astral resolves it by this precedence:

1. **`ASTRAL_WINDOW` env var** — a hard pin. If set, that's the window.
2. **A user-asserted value in `.astral/window`** — set per-project via the
   `/astral:window` command.
3. **Default of 200000**, raised by an **occupancy floor**: if the live token count
   already exceeds a known tier (200K, 1M) with no compaction, the window is
   provably larger, so Astral snaps it up to the next tier automatically. A 1M
   session is detected without any config (no false alarms), and a 200K tier is
   never under-warned. This is **sticky** for the session: once occupancy proves
   a larger window, a later `/compact` shrinks the token count but never the
   window (the window is a model/tier property, not current usage). A real
   `/clear` starts a fresh session and re-resolves.

The current model id *is* read every prompt (from the transcript). When the model
**changes** and the window is genuinely ambiguous, the Watcher asks you (via Claude's
`AskUserQuestion`) to confirm the window and run `/astral:window`. Bands re-arm
whenever the window changes — so dropping to a smaller window can still warn.

`/astral:window` accepts `opus` (1M), `sonnet` (200K), a bare integer, or
`auto`/`reset` (clear the override). It writes `.astral/window` for the current
project.

**Checkpoint is a durable-`.md` + steered-`/compact` hybrid.** Claude Code has no
native way to compact one region and keep another, so Astral does two things at once:
writes your done work to a durable `.astral/checkpoint-<ts>.md` file *and* generates a
`/compact Keep:… Drop:…` line whose instruction text steers what the compaction sheds.
The durable file is your safety net; the steered line shapes the in-context result.

**Read delegation keeps large dumps out of the main session.** The read-gate measures
a file by `bytes / 4`. Over the `ASTRAL_READ_TOKENS` threshold and unbounded, it routes
the read to a subagent (Explore or general-purpose) that reads and summarizes in its
own context, so your main window only receives the summary.

**Hooks instruct; Claude acts.** Astral ships three hooks — `astral_monitor.py`
(`UserPromptSubmit`: Watcher + Switch-guard), `astral_readgate.py`
(`PreToolUse: Read`), and `astral_precompact.py` (`PreCompact`: the capture store
below). Hooks can't render menus or spawn subagents themselves; they *instruct
Claude*, and Claude drives the `AskUserQuestion` picker and subagent dispatch.

---

## Recall (re-fetch evicted context)

Compaction shrinks what's *in context*, but it doesn't delete the transcript — the
evicted turns still exist on disk. Astral makes them **retrievable** so a later step
can pull the right slice back.

- **Capture (a hook).** `astral_precompact.py` runs on `PreCompact` (auto-compact
  *and* manual `/compact`). It snapshots the about-to-be-evicted turns to readable
  files under `.astral/store/snap-<ts>/` and indexes them. A line **watermark** keeps
  this incremental — repeated compactions only process new turns, never re-copy.
- **Re-fetch (a tool).** Astral ships a small MCP server exposing one tool,
  **`recall(query, k)`**, that searches the store and returns the top matching chunks.
  A hook can't act mid-turn, but a *tool* can: the model calls `recall()` itself when
  it needs detail that's no longer in context, so re-hydration looks automatic.

**Storage is hybrid and dependency-free.** The snapshot files are the durable truth;
the search index is **SQLite FTS5** (`sqlite3` is stdlib — no `pip install`) for BM25
ranking, treated as derived and rebuildable. If a runtime lacks FTS5, it falls back to
a pure-stdlib keyword scan over the same files — so the store works everywhere, only
search speed varies. No embeddings / vector DB in core (that would need third-party
deps or a remote API call); an optional embedding layer is a possible future add-on.

Disable the whole thing with `ASTRAL_STORE=0`. Tune results with `ASTRAL_RECALL_K`.

---

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ASTRAL_WINDOW` | *(unset)* | Hard-pin the context window the bands measure against. The real window can't be read from a hook — it's set by the harness and your tier — so when this is unset Astral defaults to `200000` and **auto-raises** it via the occupancy floor (snaps up to 1M once live usage proves the window is larger). Use `/astral:window` to assert a value per-project; use this env var to force one globally. Not model-detected — see [How it works](#how-it-works). |
| `ASTRAL_BUCKETS` | `40,55,70` | Warn bands, as a percent of the window. Tuned to fire **before accuracy degrades**, not at the cap — see [Why these thresholds](#why-these-thresholds). |
| `ASTRAL_READ_TOKENS` | `8000` | Est-token threshold (bytes/4) that gates an unbounded read. |
| `ASTRAL_READ_ALLOW` | *(empty)* | Comma-separated globs that bypass the read-gate (matched on full path + basename), e.g. `*/CHANGELOG.md,*.csv`. |
| `ASTRAL_STALE_DAYS` | `60` | `/astral:audit`: days since last use before an agent/skill is "stale". |
| `ASTRAL_STORE` | *(on)* | Set to `0`/`off` to disable the PreCompact capture store — see [Recall](#recall-re-fetch-evicted-context). |
| `ASTRAL_RECALL_K` | `5` | Default number of chunks `recall()` returns. |
| `ASTRAL_STORE_DIR` | *(project `.astral/store`)* | Override where the recall store lives (the MCP server reads this). |

### Why these thresholds

The default bands (40 / 55 / 70%) aren't arbitrary — they're set to fire *before*
long-context accuracy falls off, not when you're about to hit auto-compact:

- A stable comprehension region runs to ~**40%** of the window; past ~**50%** accuracy
  drops sharply (~45% degradation in one study) — [arxiv 2601.15300](https://arxiv.org/abs/2601.15300).
- Degradation is **monotonic with length and position-independent** — it shows up within
  7K–30K tokens on smaller models, and the *sheer amount* of context hurts reasoning even
  with perfect retrieval — [arxiv 2510.05381](https://arxiv.org/abs/2510.05381).
- "Context rot" replicates across 18 models including Claude 4; frontier models are more
  robust but still degrade as input grows — [Chroma study (overview)](https://www.understandingai.org/p/context-rot-the-emerging-challenge).

So the first warning lands at the edge of the stable zone (40%), the second past the
cliff (55%), the third when it's clearly time to shed (70%). Tune via `ASTRAL_BUCKETS`.

---

## What this is — and isn't

Read this before you trust it. Nothing here is magic, and nothing happens without you.

- **There is no native selective compaction in Claude Code, and Astral doesn't claim
  to add one.** The only real selectivity is the instruction text in `/compact`. The
  "pick what to compact" UX is really "pick what completed work to shed," delivered via
  the durable-`.md` + steered-`/compact` hybrid described above.
- **Compaction is always user-triggered.** Hooks and Claude can't run slash commands.
  Astral prompts and steers; **you** press the button (`/compact` or `/clear`).
- **The real context window can't be read from a hook.** It's set by the harness and
  your tier/subscription, so Astral can't simply "use your model's window." Instead it
  uses the occupancy-floor heuristic plus the `/astral:window` override (see
  [How it works](#how-it-works)). The token count itself is the model's real `usage`;
  only the *percentage* depends on resolving the window correctly.
- **Hooks can't render UI or spawn subagents.** They instruct Claude to; Claude does it.

---

## Statusline badge

The installer also wires a small statusline badge — `[ASTRAL 32%]` — that shows your
current context level, colored by band (calm → amber → red as you approach
auto-compact). It tracks live: Claude Code hands the statusline command a
`context_window` object on stdin every render (since v2.1.132) with a pre-computed
`used_percentage` against the *real* window size, so the badge reflects reality with
no extra cost and no window guesswork. When that field is absent — older Claude Code,
or the brief gap right after a `/compact` before the next API call — it falls back to
the per-session `.astral/state-<id>.json` the Watcher writes.

If you already have a statusline (e.g. the [caveman](https://github.com/JuliusBrussee/caveman)
badge — another lightweight Claude Code plugin worth a look), the macOS/Linux installer
**chains** Astral's after it — `[CAVEMAN] [ASTRAL 32%]` — and restores yours on
uninstall. On Windows it sets the badge only when you have no statusline; otherwise it
prints the one-liner to chain it yourself.

---

## Benchmark

Does it actually help? A/B it. `bench/astral_bench.py` parses a Claude Code transcript
into real context metrics (autocompacts, peak context, tokens/task). Run the same task
with Astral off vs on, then:

```bash
python3 bench/astral_bench.py --compare off.jsonl on.jsonl --labels off,on
```

See [`bench/README.md`](bench/README.md) for method (arms, 3+ runs, caveats).

---

## Layout

```text
astral/
  .claude-plugin/plugin.json   manifest
  .mcp.json                    recall MCP server wiring
  hooks/hooks.json             hook wiring
  scripts/astral_monitor.py    watcher + switch-guard (UserPromptSubmit)
  scripts/astral_readgate.py   large-read delegation (PreToolUse: Read)
  scripts/astral_precompact.py capture store (PreCompact)
  scripts/astral_audit.py      unused-agent/skill auditor (/astral:audit)
  scripts/astral_statusline.py context-budget badge (statusLine)
  scripts/astral_store.py      snapshot index (FTS5 / scan)
  servers/astral_recall_mcp.py recall(query) MCP server
  commands/checkpoint.md       /astral:checkpoint
  commands/status.md           /astral:status
  commands/audit.md            /astral:audit
  commands/window.md           /astral:window
  commands/help.md             /astral:help
```

State lives in `.astral/` inside whatever project you run Claude in (gitignore it).

---

## Commands

- `/astral:checkpoint` — pick completed work to shed; get a steered `/compact` line.
- `/astral:status` — show current context level and completed work.
- `/astral:window` — assert the context window (`opus`, `sonnet`, an integer, or
  `auto`/`reset`).
- `/astral:audit` — find never-used or stale agents/skills and prune them.
- `/astral:help` — what Astral does and how to use it.
