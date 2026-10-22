# #5 Vengat BEP daily record (owner, 2026-10-22: "idhai daily pathivu seiyyavum"). Run by Windows Task Scheduler at
# 15:40, Mon-Fri (after the close). From the bep folder (branch bep): records how the index treated today's BEP levels
# into history/bep/ and pushes that to the bep branch. Uses the Zerodha session daily_start.ps1 copied there.
$ErrorActionPreference = "Continue"
$main = $PSScriptRoot
$today = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $main "data\paper_trades\bep_daily_$today.txt"
function Note($text) { $line = "$(Get-Date -Format HH:mm:ss) $text"; Write-Output $line; Add-Content -Path $log -Value $line -Encoding UTF8 }

$bep = Join-Path (Split-Path $main -Parent) "bots\bep"
if (-not (Test-Path $bep)) { Note "bep folder missing"; exit 1 }
Copy-Item (Join-Path $main ".cache\kite_session.json") (Join-Path $bep ".cache\kite_session.json") -Force
Push-Location $bep
py src\bep_review.py 2>&1 | ForEach-Object { Note "bep: $_" }
Pop-Location
git -C $bep add history 2>&1 | ForEach-Object { Note "git bep: $_" }
git -C $bep diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Note "bep: no history changes today"; exit 0 }
git -C $bep commit -m "$today bep levels record (auto)`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" 2>&1 | ForEach-Object { Note "git bep: $_" }
for ($i = 0; $i -lt 3; $i++) {
  git -C $bep push origin bep 2>&1 | ForEach-Object { Note "git bep: $_" }
  if ($LASTEXITCODE -eq 0) { Note "bep: pushed"; exit 0 }
  Start-Sleep -Seconds 60
}
Note "bep: push failed"; exit 1
