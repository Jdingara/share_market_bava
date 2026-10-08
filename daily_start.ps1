# Daily paper-bot start (owner, 2026-10-08). Run by Windows Task Scheduler at 08:40, Mon-Fri.
# Syncs the code from GitHub, opens the Zerodha login (you log in; no copy-paste), then starts the
# 4 paper bots hidden in the background. Dashboards: :8050 :8051 :8052 :8053. PAPER MODE - no real orders.
$ErrorActionPreference = "Continue"
$repo = $PSScriptRoot
Set-Location $repo
$today = Get-Date -Format "yyyy-MM-dd"
$out = Join-Path $repo "data\paper_trades"
New-Item -ItemType Directory -Force $out | Out-Null
$log = Join-Path $out "daily_start_$today.txt"
function Note($text) { "$(Get-Date -Format HH:mm:ss) $text" | Tee-Object -FilePath $log -Append }

Note "daily start"
git pull --ff-only 2>&1 | ForEach-Object { Note "git: $_" }

py src\auto_login.py 2>&1 | ForEach-Object { Note "login: $_" }
if ($LASTEXITCODE -ne 0) { Note "login failed - bots not started"; exit 1 }

# already running (e.g. started by hand)? then leave them alone
$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '(sniper|hlc)_live\.py' -and $_.Name -eq 'python.exe' }
if ($running) { Note "bots already running - not starting again"; exit 0 }

$bots = @(
  @{ n = "sniper_NIFTY";  a = "src\sniper_live.py --market NIFTY --no-browser" },
  @{ n = "sniper_SENSEX"; a = "src\sniper_live.py --market SENSEX --no-browser" },
  @{ n = "hlc_NIFTY";     a = "src\hlc_live.py --market NIFTY --no-browser" },
  @{ n = "hlc_SENSEX";    a = "src\hlc_live.py --market SENSEX --no-browser" }
)
foreach ($b in $bots) {
  Start-Process py -WorkingDirectory $repo -ArgumentList $b.a -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $out "console_$($b.n)_$today.txt") `
    -RedirectStandardError (Join-Path $out "console_$($b.n)_$today.err.txt")
  Note "started $($b.n)"
}
Start-Process "http://127.0.0.1:8050"
