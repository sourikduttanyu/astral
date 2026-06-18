#!/usr/bin/env bash
# Astral installer - macOS / Linux / WSL / Git Bash
# One line:
#   curl -fsSL https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.sh | bash
# Safe to re-run (idempotent). Uninstall: ASTRAL_UNINSTALL=1 bash install.sh
set -euo pipefail

REPO="https://github.com/sourikduttanyu/astral.git"
DIR="${ASTRAL_DIR:-$HOME/.claude/astral}"
CLAUDE="$HOME/.claude"
SETTINGS="$CLAUDE/settings.json"
CMDDST="$CLAUDE/commands/astral"

say() { printf '\033[1;36m[astral]\033[0m %s\n' "$1"; }
die() { printf '\033[1;31m[astral] %s\033[0m\n' "$1" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 required (preinstalled on macOS/Linux)."
command -v git     >/dev/null 2>&1 || die "git required."

# ---- uninstall ----
if [ "${ASTRAL_UNINSTALL:-0}" = "1" ]; then
  say "uninstalling..."
  rm -rf "$CMDDST"
  python3 - "$SETTINGS" <<'PY'
import json,sys,os
p=sys.argv[1]
try:
    s=json.load(open(p))
except Exception:
    sys.exit(0)
h=s.get("hooks",{})
for evt in list(h):
    out=[]
    for e in h[evt]:
        hs=[x for x in e.get("hooks",[]) if "astral_" not in x.get("command","")]
        if hs: e["hooks"]=hs; out.append(e)
    if out: h[evt]=out
    else: h.pop(evt,None)
s["hooks"]=h
sl=s.get("statusLine")
if isinstance(sl,dict) and "astral_statusline" in sl.get("command",""):
    prev=s.pop("_astralPrevStatusLine",None)
    if prev is not None:
        s["statusLine"]=prev               # restore the badge we chained after
    else:
        c=sl.get("command",""); base=""
        for sep in (" </dev/null; printf ' '; ", "; printf ' '; "):
            if sep in c: base=c.split(sep,1)[0]; break
        if base: s["statusLine"]={"type":"command","command":base}
        else: s.pop("statusLine",None)
s.pop("_astralPrevStatusLine",None)
json.dump(s,open(p,"w"),indent=2)
PY
  python3 - "$HOME/.claude.json" <<'PY'
import json,sys
p=sys.argv[1]
try: d=json.load(open(p))
except Exception: sys.exit(0)
m=d.get("mcpServers")
if isinstance(m,dict) and "astral-recall" in m:
    m.pop("astral-recall")
    if m: d["mcpServers"]=m
    else: d.pop("mcpServers",None)
    json.dump(d,open(p,"w"),indent=2)
PY
  say "removed hooks + commands + statusline + recall MCP. Repo left at $DIR (rm -rf to delete). Restart Claude Code."
  exit 0
fi

# ---- fetch / update repo ----
# The clone is a managed mirror, not a dev workspace. A plain ff-only pull dies
# if it ever ends up dirty or diverged (local edits, an interrupted update), so
# fall back to syncing it hard to origin instead of failing the whole install.
if [ -d "$DIR/.git" ]; then
  say "updating $DIR..."
  git -C "$DIR" pull --ff-only -q 2>/dev/null || {
    say "fast-forward failed (clone dirty or diverged); resetting to origin..."
    git -C "$DIR" fetch -q origin || die "git fetch failed."
    git -C "$DIR" reset --hard -q '@{u}' || die "git reset failed."
  }
else
  say "cloning into $DIR..."; mkdir -p "$(dirname "$DIR")"; git clone -q "$REPO" "$DIR"
fi
chmod +x "$DIR"/scripts/*.py 2>/dev/null || true

# ---- install commands ----
mkdir -p "$CMDDST"
cp "$DIR"/commands/*.md "$CMDDST"/
say "commands -> $CMDDST (/astral:checkpoint, /astral:status, /astral:audit, /astral:help)"

# ---- merge hooks into settings.json ----
python3 - "$SETTINGS" "$DIR/scripts" <<'PY'
import json,sys,os
settings, scripts = sys.argv[1], sys.argv[2]
py   = sys.executable or "python3"   # wire the exact interpreter that ran install
mon  = os.path.join(scripts,"astral_monitor.py")
gate = os.path.join(scripts,"astral_readgate.py")
prec = os.path.join(scripts,"astral_precompact.py")
try:
    s=json.load(open(settings))
except Exception:
    s={}
h=s.get("hooks",{})
def strip(evt):
    out=[]
    for e in h.get(evt,[]):
        hs=[x for x in e.get("hooks",[]) if "astral_" not in x.get("command","")]
        if hs: e["hooks"]=hs; out.append(e)
    return out
ups=strip("UserPromptSubmit")
ups.append({"hooks":[{"type":"command","command":f'"{py}" "{mon}"'}]})
pre=strip("PreToolUse")
pre.append({"matcher":"Read","hooks":[{"type":"command","command":f'"{py}" "{gate}"'}]})
pc=strip("PreCompact")
for trig in ("auto","manual"):
    pc.append({"matcher":trig,"hooks":[{"type":"command","command":f'"{py}" "{prec}"'}]})
h["UserPromptSubmit"]=ups
h["PreToolUse"]=pre
h["PreCompact"]=pc
s["hooks"]=h

# ---- statusline: Astral context badge, chained after any existing one ----
SL=os.path.join(scripts,"astral_statusline.py")
acmd='"%s" "%s"'%(py,SL)
def _cmd(x): return x.get("command","") if isinstance(x,dict) else (x or "")
cur=s.get("statusLine"); prevsl=s.get("_astralPrevStatusLine")
if prevsl is not None:                 # re-run: rebuild from the base we saved
    base=_cmd(prevsl)
elif cur is None:
    base=""
elif "astral_statusline" in _cmd(cur): # legacy/manual chain, no saved base: recover it
    c=_cmd(cur); base=""
    for sep in (" </dev/null; printf ' '; ", "; printf ' '; printf", "; printf ' '; "):
        if sep in c: base=c.split(sep,1)[0]; break
else:
    base=_cmd(cur)                     # someone else's badge (e.g. caveman): chain after it
if base:
    s["_astralPrevStatusLine"]={"type":"command","command":base}
    q='"$__d"'                          # tee stdin to both so neither starves for the JSON
    s["statusLine"]={"type":"command","command":
        "__d=$(cat); printf '%s' "+q+" | "+base+"; printf ' '; printf '%s' "+q+" | "+acmd}
    print("[astral] statusline chained after existing badge")
else:
    s["statusLine"]={"type":"command","command":acmd}
    s.pop("_astralPrevStatusLine",None)
    print("[astral] statusline -> Astral context badge")

os.makedirs(os.path.dirname(settings),exist_ok=True)
json.dump(s,open(settings,"w"),indent=2)
print("[astral] hooks merged into",settings)
PY

# ---- register recall MCP server (~/.claude.json, user scope) ----
# Machine-independent: interpreter is "python3" on PATH (not an absolute
# install-machine path), and the server is referenced via ${HOME} expansion so
# the same entry resolves on any machine with the standard clone location.
python3 - "$HOME/.claude.json" "$DIR/servers/astral_recall_mcp.py" <<'PY'
import json,sys,os
cfg, server = sys.argv[1], sys.argv[2]
home=os.path.expanduser("~")
# Reference the server portably when it lives under $HOME (the default clone
# path); fall back to the literal path for a custom ASTRAL_DIR outside $HOME.
if server.startswith(home + os.sep):
    server="${HOME}" + server[len(home):]
try:
    d=json.load(open(cfg))
except Exception:
    d={}
m=d.get("mcpServers") or {}
want={"command":"python3","args":[server]}
if m.get("astral-recall")!=want:        # idempotent: only rewrite if it changed
    m["astral-recall"]=want
    d["mcpServers"]=m
    os.makedirs(os.path.dirname(cfg) or ".",exist_ok=True)
    json.dump(d,open(cfg,"w"),indent=2)
    print("[astral] recall MCP server registered in",cfg)
else:
    print("[astral] recall MCP server already registered")
PY

say "done. Restart Claude Code (or run /hooks to reload)."
say "warns before autocompact - /astral:checkpoint to shed done work - recall() re-fetches evicted context"
