# Astral

**A context-budget manager for Claude Code.**

> Spend your context like mana — don't get caught empty mid-fight.

Claude Code only remembers so much at once — a fixed **context window**. Depending
on the model that's 200K tokens (e.g. Haiku) up to **1M** (Opus 4.x, Sonnet 4.6,
Fable 5). When it fills up, Claude Code auto-compacts: it silently crams your whole
session into a summary on its own — no warning, no say in what gets cut — and
usually drops something you needed right when you needed it.

But hitting the cap isn't the only problem. **Accuracy degrades long before the
window is full** — the more you stuff into context, the more the model misses,
confuses, or hallucinates ("context rot"). A 1M window doesn't fix that; it just
lets you fill it with more noise. Keeping the working set lean is about *quality*,
not only about dodging auto-compact.

Astral's job: **tell you before context gets heavy, and let you choose what to drop**
instead of letting Claude blindly flatten everything.

Think of your context window as a mana pool. Auto-compact is running dry mid-fight;
context rot is your spells getting weaker as the pool fills with sludge. Astral
watches the meter and helps you spend deliberately. (That's where the analogy
ends — nothing below depends on it.)

---

## What it does

Five pieces, each a concrete outcome:

- **No surprise wipes.** A *Watcher* checks your context on every prompt and warns
  you at 50% / 65% / 80% full — while you can still act, not after Claude already
  compacted.
- **Drop finished work, keep the live thread.** At a *Checkpoint*, you multi-select
  the work that's already done. Astral writes a resume-ready note and hands you a
  `/compact` line steered to shed that work — instead of flattening the whole
  conversation.
- **Big file reads don't eat your memory.** Before a large `Read`, a *Read-gate*
  offers to hand the file to a subagent, so a 10k-token dump stays out of your main
  session.
- **Get nudged to start clean.** A *Switch-guard* notices when your new prompt is
  unrelated to the current session and suggests `/clear` first.
- **Stop paying rent on dead tooling.** An *Audit* scans your installed agents and
  skills against real usage, flags the never-used or stale ones that load every
  session, and gives you reversible commands to prune them.

Plus `/astral:status` to see your current level and what's done at any time.

| Piece | Trigger | Behavior |
|---|---|---|
| **Watcher** | every prompt (`UserPromptSubmit`) | Estimates context usage from the transcript. Crossing a band (50% / 65% / 80% by default) tells you what work is **done** and offers `/astral:checkpoint` — *before* auto-compact. |
| **Checkpoint** | `/astral:checkpoint` | Lists completed work-units, lets you **pick which to shed** (multi-select), writes a resume-ready summary to `.astral/checkpoint-<ts>.md`, then hands you a **steered `/compact` line** that drops the done work but keeps the live thread. |
| **Read-gate ("Courier")** | before any `Read` (`PreToolUse: Read`) | If the target file is large (>~8000 est. tokens) and unbounded, **asks** before reading and offers **subagent options** (Explore / general-purpose) so a big dump never lands in your main context. Allow the direct read, or it delegates. |
| **Switch-guard** | every prompt | If your prompt starts work unrelated to the current session, suggests `/clear` first; if you decline, offers a checkpoint of what's droppable. |
| **Status** | `/astral:status` | Shows current context level + completed vs in-flight work. |
| **Audit ("Sanity's Eclipse")** | `/astral:audit` | Scans every installed agent/skill against real usage in your transcripts. Flags ones **never used** or **stale** (>60d) — dead weight loaded into *every* session — and hands you reversible `mv … .disabled/` commands. Reports tokens reclaimed. |

---

## How it works

*(Mechanics for the curious. Skip to [Install](#install) if you just want it running.)*

**Token accounting is real, not guessed for the meter.** The context count is read
from the transcript's latest `usage` field — `input + cache_read + cache_creation`,
the model's own accounting (the same numbers the bench uses). It tracks reality and
drops after a `/compact`. The one assumption is `ASTRAL_WINDOW`, the context limit it
measures against — set it to your model's window.

**Checkpoint is a durable-`.md` + steered-`/compact` hybrid.** Claude Code has no
native way to compact one region and keep another, so Astral does two things at once:
writes your done work to a durable `.astral/checkpoint-<ts>.md` file *and* generates a
`/compact Keep:… Drop:…` line whose instruction text steers what the compaction sheds.
The durable file is your safety net; the steered line shapes the in-context result.

**Read delegation keeps large dumps out of the main session.** The read-gate measures
a file by `bytes / 4`. Over the `ASTRAL_READ_TOKENS` threshold and unbounded, it routes
the read to a subagent (Explore or general-purpose) that reads and summarizes in its own
context, so your main window only receives the summary.

**Hooks instruct; Claude acts.** Astral ships two hooks — `astral_monitor.py`
(`UserPromptSubmit`: Watcher + Switch-guard) and `astral_readgate.py`
(`PreToolUse: Read`). Hooks can't render menus or spawn subagents themselves; they
*instruct Claude*, and Claude drives the `AskUserQuestion` picker and subagent dispatch.

---

## Honest limits

Read this before you trust it. Nothing here is magic, and nothing happens without you.

- **There is no native selective compaction in Claude Code, and Astral doesn't claim
  to add one.** The only real selectivity is the instruction text in `/compact`. The
  "pick what to compact" UX is really "pick what completed work to shed," delivered via
  the durable-`.md` + steered-`/compact` hybrid above.
- **Compaction is always user-triggered.** Hooks and Claude can't run slash commands.
  Astral prompts and steers; **you** press the button (`/compact` or `/clear`).
- **The Watcher estimates against `ASTRAL_WINDOW`.** The token count itself is the
  model's real `usage`, but the *percentage* depends on the window you configure. Set
  it correctly for your model or the bands will be off.
- **Hooks can't render UI or spawn subagents.** They instruct Claude to; Claude does it.

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

Takes ~10 seconds. Needs `python3` + `git` (both preinstalled on macOS/Linux). It clones
to `~/.claude/astral`, drops the commands into `~/.claude/commands/astral/`, and merges
the two hooks into `~/.claude/settings.json` (your other settings/hooks are preserved).
**Restart Claude Code** (or run `/hooks`) afterward.

Then type **`/astral:help`** to get started. Warnings fire on their own.

**Update:** re-run the same one-line install command. It `git pull`s the clone, re-copies
commands, and re-merges hooks — so fixes actually reach your live setup. (The hooks run
from the clone; commands are copied, so a bare `git pull` updates scripts but not
commands — re-running the installer is the reliable path.) Restart Claude Code afterward.

**Uninstall:** `ASTRAL_UNINSTALL=1 bash install.sh` (or `$env:ASTRAL_UNINSTALL=1` on Windows).

### Manual / as a plugin

Prefer the plugin loader? Clone anywhere and reference it; the repo is also a valid Claude
Code plugin (`.claude-plugin/plugin.json` + `hooks/hooks.json`, paths use
`${CLAUDE_PLUGIN_ROOT}`). Note: `hooks.json` invokes `python3` (can't self-detect the
interpreter the way the installer does). On Windows, where the binary is usually `python`,
prefer the one-line installer above — it wires the exact interpreter that ran it.

---

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ASTRAL_WINDOW` | `200000` | Token budget the bands are measured against. **Not necessarily your model's full window** — most current models are 1M, but you don't want to ride context to 800K (that's deep in the accuracy-rot zone). Treat this as your *quality* budget: the point past which you'd rather shed work than keep piling on. Raise it if you genuinely want later warnings. |
| `ASTRAL_BUCKETS` | `50,65,80` | Warn bands, as a percent of `ASTRAL_WINDOW` |
| `ASTRAL_READ_TOKENS` | `8000` | Est-token threshold (bytes/4) that gates an unbounded read |
| `ASTRAL_READ_ALLOW` | *(empty)* | Comma-separated globs that bypass the read-gate (matched on full path + basename), e.g. `*/CHANGELOG.md,*.csv` |
| `ASTRAL_STALE_DAYS` | `60` | `/astral:audit`: days since last use before an agent/skill is "stale" |

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
  commands/help.md             /astral:help
```

State lives in `.astral/` inside whatever project you run Claude in (gitignore it).

### Statusline badge

The installer also wires a small statusline badge — `[ASTRAL 32%]` — that shows
your current context level, colored by band (calm → amber → red as you approach
auto-compact). It reads the same `.astral/state.json` the Watcher writes, so it
costs nothing extra.

If you already have a statusline (e.g. the caveman badge), the macOS/Linux
installer **chains** Astral's after it — `[CAVEMAN] [ASTRAL 32%]` — and restores
yours on uninstall. On Windows it sets the badge only when you have no statusline;
otherwise it prints the one-liner to chain it yourself.

---

## Benchmark

Does it actually help? A/B it. `bench/astral_bench.py` parses a Claude Code transcript
into real context metrics (autocompacts, peak context, tokens/task). Run the same task
with Astral off vs on, then:

```bash
python3 bench/astral_bench.py --compare off.jsonl on.jsonl --labels off,on
```

See [`bench/README.md`](bench/README.md) for method (arms, 3+ runs, caveats).
