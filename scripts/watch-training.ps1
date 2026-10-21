# Live view of a training run: progress, loss, and GPU load, refreshed every few seconds.
#   powershell -File scripts\watch-training.ps1 -Log <path to the training output log>
param(
    [Parameter(Mandatory = $true)][string]$Log,
    [string]$Checkpoints = "",
    [int]$Every = 5
)
# Windows PowerShell 5.1 hasn't set $PSScriptRoot yet while reading param defaults.
if (-not $Checkpoints) { $Checkpoints = Join-Path (Split-Path -Parent $PSScriptRoot) "training\out\checkpoints" }

while ($true) {
    $text = if (Test-Path $Log) { Get-Content -Raw $Log } else { "" }
    $progress = ($text -split "`r|`n" | Where-Object { $_ -match '(\d+)/(\d+) \[([^\]]*)\]' } | Select-Object -Last 1)
    # Losses come from the newest checkpoint's records: Python buffers printed output when it
    # goes to a file, so the log can lag by many minutes, but checkpoints are always complete.
    $latest = Get-ChildItem $Checkpoints -Directory -Filter "checkpoint-*" -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Name -replace '\D') } | Select-Object -Last 1
    $history = @()
    if ($latest -and (Test-Path (Join-Path $latest.FullName "trainer_state.json"))) {
        $history = (Get-Content -Raw (Join-Path $latest.FullName "trainer_state.json") | ConvertFrom-Json).log_history
    }
    $losses = $history | Where-Object { $_.loss } | Select-Object -Last 5 | ForEach-Object { "{0:n3}" -f $_.loss }
    $evals = $history | Where-Object { $_.eval_loss } | ForEach-Object { "{0:n3} (step {1})" -f $_.eval_loss, $_.step }
    $gpu = (nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw --format=csv,noheader 2>$null) -split ", "

    Clear-Host
    Write-Host "Quill training  ($(Get-Date -Format 'h:mm:ss tt'))" -ForegroundColor Cyan
    Write-Host ""
    if ($progress -match '(\d+)%\|.*?(\d+)/(\d+) \[([^<]*)<([^,]*),\s*([^\]]*)\]') {
        $pct = [int]$Matches[1]; $bar = ('#' * [math]::Floor($pct / 4)).PadRight(25, '.')
        Write-Host ("  Step      {0} of {1}  [{2}] {3}%" -f $Matches[2], $Matches[3], $bar, $pct)
        Write-Host ("  Elapsed   {0}    Left: {1}    Speed: {2}" -f $Matches[4], $Matches[5], $Matches[6])
    } elseif ($text -match "All GGUF conversions completed") {
        Write-Host "  Finished: model exported." -ForegroundColor Green
    } elseif ($text -match "Converting|Merging|GGUF") {
        Write-Host "  Training done. Exporting the model for Ollama (about 15 minutes)..." -ForegroundColor Yellow
    } else {
        Write-Host "  Starting up (loading the model and data)..."
    }
    Write-Host ""
    Write-Host ("  Training loss (latest):    " + ($(if ($losses) { $losses -join "  " } else { "after the first checkpoint" })))
    Write-Host ("  Validation loss (checks):  " + ($(if ($evals) { $evals -join "  ->  " } else { "first check at step 120" })))
    Write-Host ("  As of:                     " + ($(if ($latest) { "$($latest.Name -replace 'checkpoint-', 'checkpoint at step ')" } else { "no checkpoint yet" })))
    Write-Host "  Lower is better; it should mostly go down."
    Write-Host ""
    if ($gpu.Count -ge 4) {
        Write-Host ("  GPU       {0} busy, {1} memory, {2} C, {3}" -f $gpu[0], $gpu[1], $gpu[2], $gpu[3])
    }
    $plugged = (Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue).BatteryStatus -ne 1
    if (-not $plugged) { Write-Host "  On battery: plug in, or training slows down about 9x." -ForegroundColor Red }
    Write-Host ""
    Write-Host "  Ctrl+C closes this view. Training keeps running." -ForegroundColor DarkGray
    Start-Sleep -Seconds $Every
}
