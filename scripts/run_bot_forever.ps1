# Auto-restart wrapper for the Polyou bot.
#
# Keeps the bot running for unattended multi-day data-collection runs.
# If the Python process exits for ANY reason (crash, OOM, network glitch
# bubbling out of asyncio, etc.), this script sleeps a few seconds and
# relaunches it. Stops only on Ctrl+C in this PowerShell window.
#
# Usage (from repo root):
#     powershell -ExecutionPolicy Bypass -File scripts\run_bot_forever.ps1
#
# All bot stdout/stderr is appended to logs\bot_supervisor.log and also
# echoed to the console. A line is written to that log on each restart
# with timestamp and exit code so you can audit reliability after the week.

$ErrorActionPreference = "Stop"
$repoRoot   = Split-Path -Parent $PSScriptRoot
$python     = Join-Path $repoRoot ".venv\Scripts\python.exe"
$entry      = Join-Path $repoRoot "src\run_polyou_bot.py"
$logDir     = Join-Path $repoRoot "logs"
$superLog   = Join-Path $logDir   "bot_supervisor.log"
$restartGap = 10  # seconds between restarts

if (-not (Test-Path $logDir))   { New-Item -ItemType Directory -Path $logDir | Out-Null }
if (-not (Test-Path $python))   { throw "Python not found at $python" }
if (-not (Test-Path $entry))    { throw "Entry script not found at $entry" }

$env:PYTHONPATH = "src"

# Rotate any log >= 100 MB into logs\archive\<name>.<yyyymmdd-HHmmss>.gz so
# the live files stay small. Runs once before each launch attempt; cheap
# no-op when files are small.
$rotateBytes = 100MB
$archiveDir  = Join-Path $logDir "archive"
if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir | Out-Null }
function Rotate-IfBig($path) {
    if (-not (Test-Path $path)) { return }
    $f = Get-Item $path
    if ($f.Length -lt $rotateBytes) { return }
    $stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
    $target = Join-Path $archiveDir ("{0}.{1}" -f $f.Name, $stamp)
    Move-Item -Path $path -Destination $target -Force
    try {
        $in  = [System.IO.File]::OpenRead($target)
        $out = [System.IO.File]::Create("$target.gz")
        $gz  = New-Object System.IO.Compression.GzipStream($out, [System.IO.Compression.CompressionMode]::Compress)
        $in.CopyTo($gz); $gz.Close(); $out.Close(); $in.Close()
        Remove-Item $target -Force
        Add-Content -Path $superLog -Value "$(Get-Date -Format o)  rotated $($f.Name) -> $target.gz"
    } catch {
        Add-Content -Path $superLog -Value "$(Get-Date -Format o)  rotate FAILED for $($f.Name): $_"
    }
}

Write-Host "[supervisor] starting watch loop. Ctrl+C to stop." -ForegroundColor Cyan
Add-Content -Path $superLog -Value "$(Get-Date -Format o)  supervisor START"

while ($true) {
    Rotate-IfBig (Join-Path $logDir "bot.log")
    Rotate-IfBig $superLog

    $startedAt = Get-Date
    Add-Content -Path $superLog -Value "$($startedAt.ToString('o'))  bot LAUNCH"
    Write-Host "[supervisor] launching bot at $startedAt" -ForegroundColor Cyan

    # Run in foreground so Ctrl+C also stops the child.
    & $python $entry
    $exitCode = $LASTEXITCODE
    $endedAt  = Get-Date
    $ranSecs  = [int]($endedAt - $startedAt).TotalSeconds

    $msg = "$($endedAt.ToString('o'))  bot EXIT  code=$exitCode  ran_secs=$ranSecs"
    Add-Content -Path $superLog -Value $msg
    Write-Host "[supervisor] $msg" -ForegroundColor Yellow

    # Crash-loop guard: if the bot dies in <30s repeatedly, back off harder.
    if ($ranSecs -lt 30) {
        $sleep = [Math]::Min($restartGap * 6, 120)
        Write-Host "[supervisor] short run; sleeping $sleep s before restart" -ForegroundColor Red
        Start-Sleep -Seconds $sleep
    } else {
        Start-Sleep -Seconds $restartGap
    }
}
