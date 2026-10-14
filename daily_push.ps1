# Daily history push (owner, 2026-10-08). Run by Windows Task Scheduler at 15:10, Mon-Fri.
# Commits the bots' history/ files for today and pushes them to GitHub. Code is not touched.
$ErrorActionPreference = "Continue"
$repo = $PSScriptRoot
Set-Location $repo
$today = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $repo "data\paper_trades\daily_push_$today.txt"
function Note($text) { $line = "$(Get-Date -Format HH:mm:ss) $text"; Write-Output $line; Add-Content -Path $log -Value $line -Encoding UTF8 }

git add history 2>&1 | ForEach-Object { Note "git: $_" }
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Note "no history changes today"; exit 0 }
$msg = "$today history (paper, auto push)`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git commit -m $msg 2>&1 | ForEach-Object { Note "git: $_" }
for ($i = 0; $i -lt 3; $i++) {
  git push origin main 2>&1 | ForEach-Object { Note "git: $_" }
  if ($LASTEXITCODE -eq 0) { Note "pushed"; exit 0 }
  Start-Sleep -Seconds 60
}
Note "push failed - will go with the next push"
exit 1
