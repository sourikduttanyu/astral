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

Plus `/astral:status` to see your current level and what's done at any time.

| Piece | Trigger | Behavior |
|---|---|---|
| **Watcher** | every prompt (`UserPromptSubmit`) | Reads real context usage from the transcript. Crossing a band (40% / 55% / 70% by default) tells you what work is **done** and offers `/astral:checkpoint` — *before* auto-compact. |
| **Checkpoint** | `/astral:checkpoint` | Lists completed work-units, lets you **pick which to shed** (multi-select), writes a resume-ready summary to `.astral/checkpoint-<ts>.md`, then hands you a **steered `/compact` line** that drops the done work but keeps the live thread. |
| **Read-gate** | before any `Read` (`PreToolUse: Read`) | If the target file is large (>~8000 est. tokens) and unbounded, **asks** before reading and offers **subagent options** (Explore / general-purpose) so a big dump never lands in your main context. Allow the direct read, or it delegates. |
| **Switch-guard** | every prompt | If your prompt starts work unrelated to the current session, suggests `/clear` first; if you decline, offers a checkpoint of what's droppable. |
| **Status** | `/astral:status` | Shows current context level + completed vs in-flight work. |
| **Audit** | `/astral:audit` | Scans every installed agent/skill against real usage in your transcripts. Flags ones **never used** or **stale** (>60d) — dead weight loaded into *every* session — and hands you reversible `mv … .disabled/` commands. Reports tokens reclaimed. |

---

## Install

One line. Idempotent — safe to re-run.

```bash
# macOS / Linux / WSL / Git Bash
curl -fsSL https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.sh | bash
```

```powershell
# Windows (PowerShell 5.1+)
irm https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.ps1 | iex
```

Takes ~10 seconds. Needs `python3` + `git` (both preinstalled on macOS/Linux). It
clones to `~/.claude/astral`, drops the commands into `~/.claude/commands/astral/`,
and merges the two hooks into `~/.claude/settings.json` (your other settings and
hooks are preserved). **Restart Claude Code** (or run `/hooks`) afterward.

Then type **`/astral:help`** to get started. Warnings fire on their own.

**Update:** re-run the same one-line install command. It `git pull`s the clone,
re-copies commands, and re-merges hooks — so fixes actually reach your live setup.
(The hooks run from the clone; commands are copied, so a bare `git pull` updates
scripts but not commands — re-running the installer is the reliable path.) Restart
Claude Code afterward.

**Uninstall:** `ASTRAL_UNINSTALL=1 bash install.sh` (or `$env:ASTRAL_UNINSTALL=1` on
Windows).

### Manual / as a plugin

Prefer the plugin loader? Clone anywhere and reference it; the repo is also a valid
Claude Code plugin (`.claude-plugin/plugin.json` + `hooks/hooks.json`, paths use
`${CLAUDE_PLUGIN_ROOT}`). Note: `hooks.json` invokes `python3` (it can't self-detect
the interpreter the way the installer does). On Windows, where the binary is usually
`python`, prefer the one-line installer above — it wires the exact interpreter that
ran it.

---

## Example usage

Nothing to learn up front — the Watcher and Read-gate run on their own after install.
The commands are there for when you want to act.

**First run — confirm it's live:**

```bash
/astral:status   # current context %, window, model, band
/astral:help     # commands + config at a glance
```

You'll also start seeing the badge — `[ASTRAL 23%]` — in your statusline.

### Common use cases

**1. A long session creeping toward auto-compact.**
The badge passes 55%. Astral tells you what's already DONE and offers a checkpoint.
Run it, pick the finished work, paste the `/compact` line it gives you:

```bash
/astral:checkpoint
```

The done work is summarized to a durable `.astral/checkpoint-<ts>.md` and shed from
context — the live thread stays. No surprise compaction mid-task.

**2. Reading a big file or log without flooding context.**
You `Read` a 5,000-line log. The Read-gate intercepts and offers to hand it to a
subagent, so only the answer comes back — not 50K tokens of raw log. Allow the direct
read or let it delegate. Nothing to type.

**3. Switching models mid-session (Opus ↔ Sonnet).**
Different windows (Sonnet 200K, Opus 1M). On a model change Astral asks which window
applies. You can also set it directly:

```bash
/astral:window opus     # 1M basis
/astral:window sonnet   # 200K basis
/astral:window 500000   # custom (e.g. a Cursor window)
/astral:window auto     # back to auto-detect
```

Usually you won't need this — auto-detect locks onto the proven window and keeps it
across compactions.

**4. Pruning tooling you never use.**
Agents and skills load into *every* session. Find and disable the dead weight:

```bash
/astral:audit    # flags never-used or stale (>60d) agents/skills, reports tokens reclaimed
```

**5. Starting something unrelated.**
Type a prompt off-topic from the current session and the Switch-guard suggests
`/clear` first (or a checkpoint of what's droppable) — so old context doesn't bleed
into new work.

**Mental model:** `status` to look, `checkpoint` to shed, `window` to fix the basis,
`audit` to prune. The Watcher and Read-gate handle the rest hands-off.

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

**Hooks instruct; Claude acts.** Astral ships two hooks — `astral_monitor.py`
(`UserPromptSubmit`: Watcher + Switch-guard) and `astral_readgate.py`
(`PreToolUse: Read`). Hooks can't render menus or spawn subagents themselves; they
*instruct Claude*, and Claude drives the `AskUserQuestion` picker and subagent dispatch.

---

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ASTRAL_WINDOW` | *(unset)* | Hard-pin the context window the bands measure against. The real window can't be read from a hook — it's set by the harness and your tier — so when this is unset Astral defaults to `200000` and **auto-raises** it via the occupancy floor (snaps up to 1M once live usage proves the window is larger). Use `/astral:window` to assert a value per-project; use this env var to force one globally. Not model-detected — see [How it works](#how-it-works). |
| `ASTRAL_BUCKETS` | `40,55,70` | Warn bands, as a percent of the window. Tuned to fire **before accuracy degrades**, not at the cap — see [Why these thresholds](#why-these-thresholds). |
| `ASTRAL_READ_TOKENS` | `8000` | Est-token threshold (bytes/4) that gates an unbounded read. |
| `ASTRAL_READ_ALLOW` | *(empty)* | Comma-separated globs that bypass the read-gate (matched on full path + basename), e.g. `*/CHANGELOG.md,*.csv`. |
| `ASTRAL_STALE_DAYS` | `60` | `/astral:audit`: days since last use before an agent/skill is "stale". |

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

```
astral/
  .claude-plugin/plugin.json   manifest
  hooks/hooks.json             hook wiring
  scripts/astral_monitor.py    watcher + switch-guard (UserPromptSubmit)
  scripts/astral_readgate.py   large-read delegation (PreToolUse: Read)
  scripts/astral_audit.py      unused-agent/skill auditor (/astral:audit)
  scripts/astral_statusline.py context-budget badge (statusLine)
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
