#!/usr/bin/env python3
"""Astral audit - find unused / stale agents and skills. Read-only.

Joins what's INSTALLED (~/.claude/agents/*.md, ~/.claude/skills/*/SKILL.md)
against what's been USED (Task subagent_type + Skill calls in every transcript
~/.claude/projects/*/*.jsonl), then buckets each into:

  NEVER   never invoked in any recorded session
  STALE   last used > ASTRAL_STALE_DAYS ago (default 60)
  ACTIVE  used within the window

Every loaded agent/skill costs context tokens on EVERY session (its name +
description sit in the picker). Pruning dead ones reclaims that budget.

This script only REPORTS and prints ready-to-run move commands. It deletes
nothing. Cleanup moves files to a `.disabled/` sibling dir - reversible.

Usage:
  astral_audit.py                 # full report
  astral_audit.py --json          # machine-readable
  ASTRAL_STALE_DAYS=90 astral_audit.py
"""
import json, os, glob, sys, argparse
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
CLAUDE = os.environ.get("CLAUDE_HOME", os.path.join(HOME, ".claude"))
STALE_DAYS = int(os.environ.get("ASTRAL_STALE_DAYS", "60"))
NOW = datetime.now(timezone.utc)


def _frontmatter(path):
    """Return (name, description) from a markdown frontmatter block."""
    name = desc = None
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return None, ""
    if not lines or lines[0].strip() != "---":
        return None, ""
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        if ln.startswith("name:"):
            name = ln[5:].strip().strip('"').strip("'")
        elif ln.startswith("description:"):
            desc = ln[12:].strip().strip('"').strip("'")
    return name, (desc or "")


def inventory():
    """key (kind, name) -> {file, desc, tok}. tok = rough picker cost."""
    items = {}
    for p in glob.glob(os.path.join(CLAUDE, "agents", "*.md")):
        name, desc = _frontmatter(p)
        if not name:
            name = os.path.basename(p)[:-3]
        items[("agent", name)] = {"file": p, "desc": desc,
                                  "tok": (len(name) + len(desc)) // 4}
    for p in glob.glob(os.path.join(CLAUDE, "skills", "*", "SKILL.md")):
        name, desc = _frontmatter(p)
        if not name:
            name = os.path.basename(os.path.dirname(p))
        items[("skill", name)] = {"file": os.path.dirname(p), "desc": desc,
                                  "tok": (len(name) + len(desc)) // 4}
    return items


def _count_components(install_path):
    """(n_agents, n_skills, n_commands, token_estimate) a plugin provides."""
    na = ns = nc = tok = 0
    for p in glob.glob(os.path.join(install_path, "agents", "*.md")):
        na += 1
        n, d = _frontmatter(p)
        tok += (len(n or "") + len(d)) // 4
    for p in glob.glob(os.path.join(install_path, "skills", "*", "SKILL.md")):
        ns += 1
        n, d = _frontmatter(p)
        tok += (len(n or "") + len(d)) // 4
    for p in glob.glob(os.path.join(install_path, "commands", "*.md")):
        nc += 1
        n, d = _frontmatter(p)
        tok += (len(n or "") + len(d)) // 4
    return na, ns, nc, tok


def _plugin_flags(ipath):
    """(has_hooks, is_opaque) - hooks => passive/active; opaque => MCP-like."""
    has_hooks = os.path.isdir(os.path.join(ipath, "hooks"))
    is_mcp = os.path.exists(os.path.join(ipath, ".mcp.json"))
    pj = os.path.join(ipath, ".claude-plugin", "plugin.json")
    try:
        with open(pj, encoding="utf-8") as f:
            man = json.load(f)
        if man.get("hooks"):
            has_hooks = True
        if man.get("mcpServers"):
            is_mcp = True
    except (OSError, ValueError):
        pass
    return has_hooks, is_mcp


def plugins():
    """short-name -> {id, install_path, agents, skills, commands, tok, hooks, opaque}."""
    out = {}
    manifest = os.path.join(CLAUDE, "plugins", "installed_plugins.json")
    try:
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    for pid, recs in (data.get("plugins") or {}).items():
        rec = (recs or [{}])[0]
        ipath = rec.get("installPath", "")
        short = pid.split("@")[0]
        na, ns, nc, tok = _count_components(ipath)
        has_hooks, is_mcp = _plugin_flags(ipath)
        # opaque = nothing we can attribute by name (MCP-only / config-only plugin)
        opaque = is_mcp or (na + ns + nc == 0 and not has_hooks)
        out[short] = {"id": pid, "install_path": ipath, "agents": na,
                      "skills": ns, "commands": nc, "tok": tok,
                      "hooks": has_hooks, "opaque": opaque}
    return out


def usage():
    """key (kind, name) -> {count, last} from all transcripts."""
    used = {}

    def bump(key, ts):
        c, last = used.get(key, (0, None))
        if ts and (last is None or ts > last):
            last = ts
        used[key] = (c + 1, last)

    for p in glob.glob(os.path.join(CLAUDE, "projects", "*", "*.jsonl")):
        try:
            f = open(p, encoding="utf-8")
        except OSError:
            continue
        with f:
            for line in f:
                if ('"subagent_type"' not in line and '"skill"' not in line
                        and '"mcp__' not in line):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ts = o.get("timestamp")
                content = (o.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    name = b.get("name", "")
                    if name.startswith("mcp__"):
                        bump(("mcp", name), ts)
                    inp = b.get("input") or {}
                    if inp.get("subagent_type"):
                        bump(("agent", inp["subagent_type"]), ts)
                    if inp.get("skill"):
                        bump(("skill", inp["skill"]), ts)
    return {k: {"count": c, "last": l} for k, (c, l) in used.items()}


def _days_since(ts):
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (NOW - d).days


def build():
    inv, use = inventory(), usage()
    rows = []
    for key, meta in inv.items():
        kind, name = key
        u = use.get(key)
        if not u:
            bucket, days, cnt = "NEVER", None, 0
        else:
            cnt = u["count"]
            days = _days_since(u["last"])
            bucket = "STALE" if (days is not None and days > STALE_DAYS) else "ACTIVE"
        rows.append({"kind": kind, "name": name, "bucket": bucket,
                     "count": cnt, "days": days, "tok": meta["tok"],
                     "file": meta["file"]})
    rows.sort(key=lambda r: (r["kind"], {"NEVER": 0, "STALE": 1, "ACTIVE": 2}[r["bucket"]],
                             -(r["days"] or 0), r["name"]))
    return rows, plugin_rows(use)


def plugin_rows(use):
    """Attribute usage to plugins. Namespace (plugin:component) for agents/skills,
    mcp__ tool calls for MCP plugins, and ship-time hooks for passive plugins."""
    plug = plugins()

    def agg(match):
        c, last = 0, None
        for (kind, name), u in use.items():
            if not match(kind, name):
                continue
            c += u["count"]
            if u["last"] and (last is None or u["last"] > last):
                last = u["last"]
        return c, last

    prows = []
    for short, meta in plug.items():
        us = short.replace("-", "_")
        if meta["opaque"]:
            # MCP / config-only: measure by mcp__ calls, not namespace
            c, last = agg(lambda k, n: k == "mcp" and us in n)
            prunable = False  # can't confidently auto-recommend; flag instead
        else:
            c, last = agg(lambda k, n: ":" in n and n.split(":", 1)[0] == short)
            prunable = True

        if meta["hooks"]:
            bucket = "HOOK"          # passive/active via hooks - never prunable
            prunable = False
        elif c:
            days = _days_since(last)
            bucket = "STALE" if (days is not None and days > STALE_DAYS) else "ACTIVE"
            prunable = prunable and bucket == "STALE"
        elif meta["opaque"]:
            bucket = "MCP?"          # opaque + unseen: flag, don't auto-prune
        else:
            bucket = "NEVER"

        days = _days_since(last) if c else None
        prows.append({"plugin": short, "id": meta["id"], "bucket": bucket,
                      "count": c, "days": days, "tok": meta["tok"],
                      "prunable": prunable, "agents": meta["agents"],
                      "skills": meta["skills"], "commands": meta["commands"]})
    order = {"NEVER": 0, "STALE": 1, "MCP?": 2, "HOOK": 3, "ACTIVE": 4}
    prows.sort(key=lambda r: (order[r["bucket"]], -(r["days"] or 0), r["plugin"]))
    return prows


TAGS = {"NEVER": "x NEVER", "STALE": "~ STALE", "ACTIVE": "+ active",
        "HOOK": "= hook  ", "MCP?": "? mcp   "}


def _when(r):
    if r["bucket"] in ("NEVER", "MCP?"):
        return "never"
    return f"{r['days']}d ago" if r["days"] is not None else "?"


def report(rows, prows):
    inst = len(rows)
    dead = [r for r in rows if r["bucket"] in ("NEVER", "STALE")]
    pdead = [r for r in prows if r["prunable"]]
    reclaim = sum(r["tok"] for r in dead) + sum(r["tok"] for r in pdead)
    print(f"\nASTRAL AUDIT  ({CLAUDE})")
    print(f"installed: {inst} agents/skills + {len(prows)} plugins   "
          f"prunable: {len(dead)} agents/skills + {len(pdead)} plugins "
          f"(NEVER {sum(r['bucket']=='NEVER' for r in rows)}, "
          f"STALE>{STALE_DAYS}d {sum(r['bucket']=='STALE' for r in rows)})   "
          f"reclaim ~{reclaim:,} tok/session")

    for kind in ("agent", "skill"):
        krows = [r for r in rows if r["kind"] == kind]
        if not krows:
            continue
        print(f"\n  {kind.upper()}S")
        for r in krows:
            print(f"    {TAGS[r['bucket']]:9} {r['name'][:38]:38} used {r['count']:>3}  "
                  f"last {_when(r):9} ~{r['tok']}t")

    if prows:
        print(f"\n  PLUGINS   (= hook & ? mcp = NOT auto-prunable, usage unmeasurable)")
        for r in prows:
            provides = f"{r['agents']}a/{r['skills']}s/{r['commands']}c"
            print(f"    {TAGS[r['bucket']]:9} {r['plugin'][:28]:28} used {r['count']:>3}  "
                  f"last {_when(r):9} {provides:9} ~{r['tok']}t")
        print("    = hook: runs via session hooks (caveman, astral). ? mcp: MCP/opaque")
        print("      plugin - measured by mcp__ calls. Both flagged, never auto-pruned.")

    if dead:
        print(f"\n  CLEANUP agents/skills (reversible - moves to .disabled/, deletes nothing):")
        for kind in ("agent", "skill"):
            kd = [r for r in dead if r["kind"] == kind]
            if not kd:
                continue
            disabled = os.path.join(CLAUDE, f"{kind}s.disabled")
            print(f"    mkdir -p {disabled}")
            print(f"    # move all {len(kd)} prunable {kind}s:")
            for r in kd[:6]:
                print(f"    mv {r['file']!r} {disabled}/")
            if len(kd) > 6:
                print(f"    # ... and {len(kd)-6} more (see --json for full list)")
        print(f"    restore any: mv back from .disabled/.")
    if pdead:
        print(f"\n  CLEANUP plugins (managed - uninstall via Claude Code):")
        for r in pdead:
            tok = f"~{r['tok']}t" if r["tok"] else ""
            print(f"    /plugin uninstall {r['id']}   # {r['plugin']}, unused {tok}")
    if not dead and not pdead:
        print("\n  clean - nothing prunable.")
    else:
        print(f"\n    Restart Claude Code (or /hooks) after pruning.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows, prows = build()
    if a.json:
        print(json.dumps({"items": rows, "plugins": prows}, indent=2))
    else:
        report(rows, prows)


if __name__ == "__main__":
    main()
