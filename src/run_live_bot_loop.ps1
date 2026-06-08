param(
    [string]$Whitelist = "0xa3d043b2da34f58045c6485d3f89b798b2b0ec04,0x01b739b360d3c2f6cc8ec84cda900d48650e2eca,0x08ec01051d8f8d298b2cd81b65fa5669b8ebc20b,0xeebde7a0e019a63e6b476eb425505b7b3e6eba30,0x14774b671287348daa324e8404e5f608e3acbe50,0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82",
    [string]$TradeSize = "1.0"
)

$env:COPY_WHITELIST     = $Whitelist
$env:COPY_ONLY_DOWN     = "true"
$env:COPY_TRADE_SIZE    = $TradeSize
$env:EXECUTION_ENABLED  = "true"
$env:READ_ONLY_MODE     = "false"
$env:SHADOW_EXITS_FILE  = "logs/live_shadow_exits.csv"
$env:PYTHONPATH         = "src"

$restartDelay = 10

while ($true) {
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [LOOP] Starting live bot..." -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe src\run_live_bot.py
    $exit = $LASTEXITCODE
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [LOOP] Bot exited (code=$exit). Restarting in ${restartDelay}s..." -ForegroundColor Yellow
    # Clean up stale lock file if present
    Remove-Item -ErrorAction SilentlyContinue logs\polyou_live_bot.lock
    Start-Sleep -Seconds $restartDelay
}
