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
json.dump(s,open(p,"w"),indent=2)
'@
  Say "removed. Restart Claude Code."; exit 0
}

if (Test-Path "$Dir\.git") { Say "updating $Dir..."; git -C $Dir pull --ff-only -q }
else { Say "cloning into $Dir..."; New-Item -ItemType Directory -Force -Path (Split-Path $Dir) | Out-Null; git clone -q $Repo $Dir }

New-Item -ItemType Directory -Force -Path $CmdDst | Out-Null
Copy-Item "$Dir\commands\*.md" $CmdDst -Force
Say "commands -> $CmdDst (/astral:checkpoint, /astral:status)"

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
ups=strip("UserPromptSubmit"); ups.append({"hooks":[{"type":"command","command":f'"{py}" "{mon}"'}]})
pre=strip("PreToolUse");       pre.append({"matcher":"Read","hooks":[{"type":"command","command":f'"{py}" "{gate}"'}]})
h["UserPromptSubmit"]=ups; h["PreToolUse"]=pre; s["hooks"]=h
os.makedirs(os.path.dirname(settings),exist_ok=True)
json.dump(s,open(settings,"w"),indent=2)
print("[astral] hooks merged into",settings)
'@

Say "done. Restart Claude Code (or /hooks to reload)."
