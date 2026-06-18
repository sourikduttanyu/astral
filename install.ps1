# Astral installer - Windows (PowerShell 5.1+)
# One line:
#   irm https://raw.githubusercontent.com/sourikduttanyu/astral/master/install.ps1 | iex
# Safe to re-run. Uninstall: $env:ASTRAL_UNINSTALL=1; irm ... | iex
$ErrorActionPreference = "Stop"

$Repo     = "https://github.com/sourikduttanyu/astral.git"
$Dir      = if ($env:ASTRAL_DIR) { $env:ASTRAL_DIR } else { "$HOME\.claude\astral" }
$Claude   = "$HOME\.claude"
$Settings = "$Claude\settings.json"
$CmdDst   = "$Claude\commands\astral"

function Say($m) { Write-Host "[astral] $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "[astral] $m" -ForegroundColor Red; exit 1 }

$py = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $py)  { Die "python required (python.org)." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "git required." }
$PY = $py.Source

if ($env:ASTRAL_UNINSTALL -eq "1") {
  Say "uninstalling..."
  if (Test-Path $CmdDst) { Remove-Item -Recurse -Force $CmdDst }
  & $PY - $Settings @'
import json,sys,os
p=sys.argv[1]
try: s=json.load(open(p))
except Exception: sys.exit(0)
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
    s.pop("statusLine",None)
json.dump(s,open(p,"w"),indent=2)
'@
  & $PY - "$HOME\.claude.json" @'
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
'@
  Say "removed (incl. recall MCP). Restart Claude Code."; exit 0
}

# Managed mirror: if a plain ff-only pull fails (dirty/diverged clone), sync hard
# to origin instead of leaving the install half-done.
if (Test-Path "$Dir\.git") {
  Say "updating $Dir..."
  git -C $Dir pull --ff-only -q 2>$null
  if ($LASTEXITCODE -ne 0) {
    Say "fast-forward failed (clone dirty or diverged); resetting to origin..."
    git -C $Dir fetch -q origin
    git -C $Dir reset --hard -q '@{u}'
  }
}
else { Say "cloning into $Dir..."; New-Item -ItemType Directory -Force -Path (Split-Path $Dir) | Out-Null; git clone -q $Repo $Dir }

New-Item -ItemType Directory -Force -Path $CmdDst | Out-Null
Copy-Item "$Dir\commands\*.md" $CmdDst -Force
Say "commands -> $CmdDst (/astral:checkpoint, /astral:status, /astral:audit, /astral:help)"

& $PY - $Settings "$Dir\scripts" @'
import json,sys,os
settings, scripts = sys.argv[1], sys.argv[2]
py   = sys.executable or "python"   # wire the exact interpreter that ran install
mon  = os.path.join(scripts,"astral_monitor.py")
gate = os.path.join(scripts,"astral_readgate.py")
try: s=json.load(open(settings))
except Exception: s={}
h=s.get("hooks",{})
def strip(evt):
    out=[]
    for e in h.get(evt,[]):
        hs=[x for x in e.get("hooks",[]) if "astral_" not in x.get("command","")]
        if hs: e["hooks"]=hs; out.append(e)
    return out
prec = os.path.join(scripts,"astral_precompact.py")
ups=strip("UserPromptSubmit"); ups.append({"hooks":[{"type":"command","command":f'"{py}" "{mon}"'}]})
pre=strip("PreToolUse");       pre.append({"matcher":"Read","hooks":[{"type":"command","command":f'"{py}" "{gate}"'}]})
pc=strip("PreCompact")
for trig in ("auto","manual"):
    pc.append({"matcher":trig,"hooks":[{"type":"command","command":f'"{py}" "{prec}"'}]})
h["UserPromptSubmit"]=ups; h["PreToolUse"]=pre; h["PreCompact"]=pc; s["hooks"]=h

# statusline: set the Astral badge only if no statusline exists. Cross-shell
# chaining isn't safe to auto-generate on Windows, so if one's already set we
# leave it and print how to chain manually.
SL=os.path.join(scripts,"astral_statusline.py"); acmd=f'"{py}" "{SL}"'
cur=s.get("statusLine")
if cur is None:
    s["statusLine"]={"type":"command","command":acmd}
    print("[astral] statusline -> Astral context badge")
elif "astral_statusline" not in (cur.get("command","") if isinstance(cur,dict) else ""):
    print("[astral] existing statusline left as-is. To add the badge, chain it after yours:")
    print("[astral]   "+acmd)

os.makedirs(os.path.dirname(settings),exist_ok=True)
json.dump(s,open(settings,"w"),indent=2)
print("[astral] hooks merged into",settings)
'@

# Register the recall MCP server (user scope). Machine-independent interpreter:
# "python" on PATH, not an absolute install-machine path.
& $PY - "$HOME\.claude.json" "$Dir\servers\astral_recall_mcp.py" @'
import json,sys,os
cfg, server = sys.argv[1], sys.argv[2]
try: d=json.load(open(cfg))
except Exception: d={}
m=d.get("mcpServers") or {}
want={"command":"python","args":[server]}
if m.get("astral-recall")!=want:
    m["astral-recall"]=want; d["mcpServers"]=m
    os.makedirs(os.path.dirname(cfg) or ".",exist_ok=True)
    json.dump(d,open(cfg,"w"),indent=2)
    print("[astral] recall MCP server registered in",cfg)
else:
    print("[astral] recall MCP server already registered")
'@

Say "done. Restart Claude Code (or /hooks to reload)."
