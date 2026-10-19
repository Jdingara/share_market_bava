# Daily paper-bot start (owner, 2026-10-08; one branch per strategy since 2026-10-19). Run by Windows Task Scheduler
# at 08:40, Mon-Fri. Each strategy lives on its own git branch, checked out in its own folder (git worktree):
#   #1 Sniper      E:\BOT\Share_BOT\bots\sniper   (branch sniper)   dashboards :8050 :8051
#   #2 HLC         E:\BOT\Share_BOT\bots\hlc      (branch hlc)      dashboards :8052 :8053
#   #3 Vengat ORB  E:\BOT\Share_BOT\bots\orb      (branch orb)      dashboards :8054 :8055
#   #4 Lalitha     E:\BOT\Share_BOT\bots\lalitha  (branch lalitha)  dashboards :8056 :8057
# Syncs every folder from GitHub, opens the Zerodha login once (you log in), shares that session with every folder,
# then starts each strategy's bots hidden FROM ITS OWN FOLDER. PAPER MODE - no real orders.
$ErrorActionPreference = "Continue"
$main = $PSScriptRoot
Set-Location $main
$today = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $main "data\paper_trades"
New-Item -ItemType Directory -Force $out | Out-Null
$log = Join-Path $out "daily_start_$today.txt"
function Note($text) { $line = "$(Get-Date -Format HH:mm:ss) $text"; Write-Output $line; Add-Content -Path $log -Value $line -Encoding UTF8 }

$bots_root = Join-Path (Split-Path $main -Parent) "bots"
$strategies = [ordered]@{
  sniper  = @(@("sniper_NIFTY", "src\sniper_live.py --market NIFTY --no-browser"), @("sniper_SENSEX", "src\sniper_live.py --market SENSEX --no-browser"))
  hlc     = @(@("hlc_NIFTY", "src\hlc_live.py --market NIFTY --no-browser"), @("hlc_SENSEX", "src\hlc_live.py --market SENSEX --no-browser"))
  orb     = @(@("orb_NIFTY", "src\orb_live.py --market NIFTY --no-browser"), @("orb_SENSEX", "src\orb_live.py --market SENSEX --no-browser"))
  lalitha = @(@("lalitha_NIFTY", "src\lalitha_live.py --market NIFTY --no-browser"), @("lalitha_SENSEX", "src\lalitha_live.py --market SENSEX --no-browser"))
}

Note "daily start"
git -C $main pull --ff-only 2>&1 | ForEach-Object { Note "git main: $_" }
foreach ($s in $strategies.Keys) {
  git -C (Join-Path $bots_root $s) pull --ff-only 2>&1 | ForEach-Object { Note "git ${s}: $_" }
}

py src\auto_login.py 2>&1 | ForEach-Object { Note "login: $_" }
if ($LASTEXITCODE -ne 0) { Note "login failed - bots not started"; exit 1 }

# one login for all: copy today's session (and .env) into every strategy folder
foreach ($s in $strategies.Keys) {
  $dir = Join-Path $bots_root $s
  New-Item -ItemType Directory -Force (Join-Path $dir ".cache") | Out-Null
  Copy-Item (Join-Path $main ".cache\kite_session.json") (Join-Path $dir ".cache\kite_session.json") -Force
  Copy-Item (Join-Path $main ".env") (Join-Path $dir ".env") -Force
}

# already running (e.g. started by hand)? then leave them alone
$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '_live\.py' -and $_.Name -eq 'python.exe' }
if ($running) { Note "bots already running - not starting again"; exit 0 }

foreach ($s in $strategies.Keys) {
  $dir = Join-Path $bots_root $s
  $logs = Join-Path $dir "data\paper_trades"
  New-Item -ItemType Directory -Force $logs | Out-Null
  foreach ($b in $strategies[$s]) {
    Start-Process py -WorkingDirectory $dir -ArgumentList $b[1] -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $logs "console_$($b[0])_$today.txt") `
      -RedirectStandardError (Join-Path $logs "console_$($b[0])_$today.err.txt")
    Note "started $($b[0]) from $dir"
  }
}
Start-Process (Join-Path $main "all_bots.html")
