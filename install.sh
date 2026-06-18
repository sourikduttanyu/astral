#!/usr/bin/env bash
# Astral installer — macOS / Linux / WSL / Git Bash
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
  say "uninstalling…"
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
json.dump(s,open(p,"w"),indent=2)
PY
  say "removed hooks + commands. Repo left at $DIR (rm -rf to delete). Restart Claude Code."
  exit 0
fi

# ---- fetch / update repo ----
if [ -d "$DIR/.git" ]; then
  say "updating $DIR…"; git -C "$DIR" pull --ff-only -q || die "git pull failed."
else
  say "cloning into $DIR…"; mkdir -p "$(dirname "$DIR")"; git clone -q "$REPO" "$DIR"
fi
chmod +x "$DIR"/scripts/*.py 2>/dev/null || true

# ---- install commands ----
mkdir -p "$CMDDST"
cp "$DIR"/commands/*.md "$CMDDST"/
say "commands → $CMDDST (/astral:checkpoint, /astral:status)"

# ---- merge hooks into settings.json ----
python3 - "$SETTINGS" "$DIR/scripts" <<'PY'
import json,sys,os
settings, scripts = sys.argv[1], sys.argv[2]
mon  = os.path.join(scripts,"astral_monitor.py")
gate = os.path.join(scripts,"astral_readgate.py")
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
ups.append({"hooks":[{"type":"command","command":f'python3 "{mon}"'}]})
pre=strip("PreToolUse")
pre.append({"matcher":"Read","hooks":[{"type":"command","command":f'python3 "{gate}"'}]})
h["UserPromptSubmit"]=ups
h["PreToolUse"]=pre
s["hooks"]=h
os.makedirs(os.path.dirname(settings),exist_ok=True)
json.dump(s,open(settings,"w"),indent=2)
print("[astral] hooks merged into",settings)
PY

say "done. Restart Claude Code (or run /hooks to reload)."
say "warns before autocompact · /astral:checkpoint to shed done work · /astral:status for level"
