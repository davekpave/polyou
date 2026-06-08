# Aliveness check for the unattended Polyou bot.
#
# Exits 0 when everything looks healthy, 1 when something is off, and
# prints a one-line summary either way. Designed for ad-hoc invocation
# or a Windows Task Scheduler job.
#
# Healthy means:
#   - At least one python.exe process is alive
#   - logs\bot.log was written within $StaleMinutes
#   - The drive that holds the repo has > $MinFreeGb free
#
# Usage:
#     powershell -ExecutionPolicy Bypass -File scripts\aliveness_check.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\aliveness_check.ps1 -StaleMinutes 5

param(
    [int]$StaleMinutes = 10,
    [int]$MinFreeGb    = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$botLog   = Join-Path $repoRoot "logs\bot.log"

$problems = @()

# 1. python process alive?
$procs = Get-Process python -ErrorAction SilentlyContinue
if (-not $procs) { $problems += "no python.exe process" }

# 2. bot.log fresh?
if (-not (Test-Path $botLog)) {
    $problems += "logs\bot.log missing"
} else {
    $lastWrite = (Get-Item $botLog).LastWriteTime
    $ageMin = [int]((Get-Date) - $lastWrite).TotalMinutes
    if ($ageMin -gt $StaleMinutes) { $problems += "bot.log stale ${ageMin}m" }
}

# 3. disk space?
$drive = (Get-Item $repoRoot).PSDrive
$freeGb = [math]::Round($drive.Free / 1GB, 1)
if ($freeGb -lt $MinFreeGb) { $problems += "low disk ${freeGb}GB" }

$nProc = if ($procs) { $procs.Count } else { 0 }
$now   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

if ($problems.Count -eq 0) {
    Write-Host "$now OK   procs=$nProc disk=${freeGb}GB"
    exit 0
} else {
    $msg = ($problems -join "; ")
    Write-Host "$now FAIL procs=$nProc disk=${freeGb}GB  -- $msg" -ForegroundColor Red
    exit 1
}
