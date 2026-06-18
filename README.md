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
| **Read-gate (Courier)** | before any `Read` | If the target file is large (>1500 lines) and unbounded, blocks the read and has Claude offer you **subagent options** (Explore / general-purpose) so a big dump never lands in your main context. |
| **Switch-guard** | every prompt | If your prompt starts work unrelated to the current session, Claude suggests `/clear` first; if you decline, it offers a checkpoint of what's droppable. |
| **Status** | `/astral:status` | Shows current context level + completed vs in-flight work. |

## Honest limits

- **No native selective/verbatim compaction exists in Claude Code.** Astral can't
  compact one region and keep another. The only real selectivity is `/compact`'s
  instruction text. `/astral:checkpoint` uses a **hybrid** flow: write done-work
  to a durable `.md` *and* generate a steered `/compact Keep:… Drop:…` line. The
  "pick what to compact" UX is "pick what completed work to shed."
- **Compaction is always user-triggered.** Hooks and Claude cannot run slash
  commands; Astral prompts and steers, you run `/compact` (or `/clear`).
- **Token count is an estimate** (transcript bytes ÷ 4), biased to warn early.
  It is not the model's exact accounting. Tune the window/bands if it's off.
- Hooks can't render menus or spawn subagents themselves — they *instruct Claude*
  to, and Claude drives the `AskUserQuestion` picker and the subagent dispatch.

## Install

Astral is a standard Claude Code plugin (manifest + hooks + commands).

```bash
git clone <this-repo> ~/astral
```

Then add it to your Claude Code config (`~/.claude/settings.json`):

```json
{
  "plugins": ["~/astral"]
}
```

Or, to wire just the hooks manually, point your settings `hooks` at
`~/astral/hooks/hooks.json` style entries (paths use `${CLAUDE_PLUGIN_ROOT}`).

Requires `python3` (preinstalled on macOS/Linux). Restart your session after
installing.

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ASTRAL_WINDOW` | `200000` | Assumed context window, tokens |
| `ASTRAL_BUCKETS` | `50,65,80` | Warn bands (percent) |
| `ASTRAL_READ_LINES` | `1500` | Line threshold for read delegation |

## Layout

```
astral/
  .claude-plugin/plugin.json   manifest
  hooks/hooks.json             hook wiring
  scripts/astral_monitor.py    watcher + switch-guard (UserPromptSubmit)
  scripts/astral_readgate.py   large-read delegation (PreToolUse: Read)
  commands/checkpoint.md       /astral:checkpoint
  commands/status.md           /astral:status
```

State lives in `.astral/` inside whatever project you run Claude in (gitignore it).

## License

MIT
