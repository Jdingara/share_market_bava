# Daily history push (owner, 2026-10-08; per strategy branch since 2026-10-19). Run by Windows Task Scheduler at
# 15:10, Mon-Fri. For each strategy folder (git worktree) it commits that strategy's history/ files and pushes them to
# the strategy's own branch on GitHub. Code is not touched.
$ErrorActionPreference = "Continue"
$main = $PSScriptRoot
$today = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $main "data\paper_trades\daily_push_$today.txt"
function Note($text) { $line = "$(Get-Date -Format HH:mm:ss) $text"; Write-Output $line; Add-Content -Path $log -Value $line -Encoding UTF8 }

$bots_root = Join-Path (Split-Path $main -Parent) "bots"
$failed = $false
foreach ($s in "sniper", "hlc", "orb", "lalitha") {
  $dir = Join-Path $bots_root $s
  if (-not (Test-Path $dir)) { Note "${s}: folder missing"; continue }
  git -C $dir add history 2>&1 | ForEach-Object { Note "git ${s}: $_" }
  git -C $dir diff --cached --quiet
  if ($LASTEXITCODE -eq 0) { Note "${s}: no history changes today"; continue }
  $msg = "$today $s history (paper, auto push)`n`nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  git -C $dir commit -m $msg 2>&1 | ForEach-Object { Note "git ${s}: $_" }
  $ok = $false
  for ($i = 0; $i -lt 3; $i++) {
    git -C $dir push origin $s 2>&1 | ForEach-Object { Note "git ${s}: $_" }
    if ($LASTEXITCODE -eq 0) { $ok = $true; Note "${s}: pushed"; break }
    Start-Sleep -Seconds 60
  }
  if (-not $ok) { $failed = $true; Note "${s}: push failed - will go with the next push" }
}
if ($failed) { exit 1 }
