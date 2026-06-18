# Astral

A context-budget manager for Claude Code. Named for Outworld Destroyer's
**Astral Imprison** — banish context, recall it later.

Context window = your **mana pool**. Autocompact = running out of mana mid-fight.
Astral's job: **never let you hit autocompact**, and when you're getting close,
shed work that's already done instead of letting Claude blindly summarize
everything.

## What it does

| Piece | Trigger | Behavior |
|---|---|---|
| **Watcher** | every prompt | Estimates context usage from the transcript. When it crosses a band (50% / 65% / 80% by default), tells you what work is **done** and offers `/astral:checkpoint` — *before* autocompact, not after. |
| **Checkpoint** | `/astral:checkpoint` | Lists completed work-units, lets you **pick which to shed** (multi-select), writes a resume-ready summary to `.astral/checkpoint-<ts>.md`, then hands you a **steered `/compact` line** that drops the done work but keeps the live thread. |
| **Read-gate (Courier)** | before any `Read` | If the target file is large (>~8000 est. tokens) and unbounded, **asks** before the read and has Claude offer you **subagent options** (Explore / general-purpose) so a big dump never lands in your main context. Allow it to read directly, or it delegates. |
| **Switch-guard** | every prompt | If your prompt starts work unrelated to the current session, Claude suggests `/clear` first; if you decline, it offers a checkpoint of what's droppable. |
| **Status** | `/astral:status` | Shows current context level + completed vs in-flight work. |
| **Audit (Sanity's Eclipse)** | `/astral:audit` | Scans every installed agent/skill against real usage in your transcripts. Flags the ones **never used** or **stale** (>60d) — the dead weight that loads into *every* session — and hands you reversible `mv … .disabled/` commands to prune them. Reports tokens reclaimed. |

## Honest limits

- **No native selective/verbatim compaction exists in Claude Code.** Astral can't
  compact one region and keep another. The only real selectivity is `/compact`'s
  instruction text. `/astral:checkpoint` uses a **hybrid** flow: write done-work
  to a durable `.md` *and* generate a steered `/compact Keep:… Drop:…` line. The
  "pick what to compact" UX is "pick what completed work to shed."
- **Compaction is always user-triggered.** Hooks and Claude cannot run slash
  commands; Astral prompts and steers, you run `/compact` (or `/clear`).
- **Token count is read from the transcript's latest `usage`** (input + cache_read
  + cache_creation) — the model's real accounting, the same the bench uses. It
  tracks reality and drops after a `/compact`. The one assumption is `ASTRAL_WINDOW`
  (the context limit it's measured against); set it to your model's window.
- Hooks can't render menus or spawn subagents themselves — they *instruct Claude*
  to, and Claude drives the `AskUserQuestion` picker and the subagent dispatch.

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

~10 seconds. Needs `python3` + `git` (both preinstalled on macOS/Linux). It clones
to `~/.claude/astral`, drops the commands into `~/.claude/commands/astral/`, and
merges the two hooks into `~/.claude/settings.json` (your other settings/hooks are
preserved). **Restart Claude Code** (or run `/hooks`) after install.

Then type **`/astral:help`** to get started. Warnings fire on their own.

**Uninstall:** `ASTRAL_UNINSTALL=1 bash install.sh` (or `$env:ASTRAL_UNINSTALL=1` on Windows).

### Manual / as a plugin

Prefer the plugin loader? Clone anywhere and reference it; the repo is also a valid
Claude Code plugin (`.claude-plugin/plugin.json` + `hooks/hooks.json`, paths use
`${CLAUDE_PLUGIN_ROOT}`). Note: `hooks.json` invokes `python3` (can't self-detect
the interpreter the way the installer does). On Windows, where the binary is
usually `python`, prefer the one-line installer above — it wires the exact
interpreter that ran it.

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ASTRAL_WINDOW` | `200000` | Assumed context window, tokens |
| `ASTRAL_BUCKETS` | `50,65,80` | Warn bands (percent) |
| `ASTRAL_READ_TOKENS` | `8000` | Est-token threshold (bytes/4) that gates an unbounded read |
| `ASTRAL_STALE_DAYS` | `60` | `/astral:audit`: days since last use before an agent/skill is "stale" |

## Layout

```
astral/
  .claude-plugin/plugin.json   manifest
  hooks/hooks.json             hook wiring
  scripts/astral_monitor.py    watcher + switch-guard (UserPromptSubmit)
  scripts/astral_readgate.py   large-read delegation (PreToolUse: Read)
  scripts/astral_audit.py      unused-agent/skill auditor (/astral:audit)
  commands/checkpoint.md       /astral:checkpoint
  commands/status.md           /astral:status
  commands/audit.md            /astral:audit
```

State lives in `.astral/` inside whatever project you run Claude in (gitignore it).

## Benchmark

Does it actually help? A/B it. `bench/astral_bench.py` parses a Claude Code
transcript into real context metrics (autocompacts, peak context, tokens/task).
Run the same task with Astral off vs on, then:

```bash
python3 bench/astral_bench.py --compare off.jsonl on.jsonl --labels off,on
```

See [`bench/README.md`](bench/README.md) for method (arms, 3+ runs, caveats).

## License

MIT
