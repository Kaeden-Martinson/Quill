# Third batch: the "scaffold" drafting configuration (improved + a rule for personal material),
# on the same 32 assignments and seeds. Waits for run_editor.ps1 so the GPU isn't shared.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "logs"
$env:PYTHONIOENCODING = "utf-8"
foreach ($line in Get-Content (Join-Path $root "quill.env")) {
    if ($line -match '^\s*(QUILL_[A-Z_]+)\s*=\s*(.*)$' -and $Matches[1] -ne "QUILL_PASSCODE") { Set-Item "Env:$($Matches[1])" $Matches[2].Trim() }
}
$wait = Join-Path $logs "progress2.log"
while (-not ((Test-Path $wait) -and (Select-String -Path $wait -Pattern "all done" -Quiet))) { Start-Sleep -Seconds 60 }
$progress = Join-Path $logs "progress3.log"
"[$(Get-Date -Format HH:mm:ss)] start draft-scaffold" | Out-File $progress
& $py training\compare_writing.py draft scaffold *> (Join-Path $logs "draft-scaffold.log")
"[$(Get-Date -Format HH:mm:ss)] end draft-scaffold (exit $LASTEXITCODE)" | Out-File -Append $progress
"[$(Get-Date -Format HH:mm:ss)] all done" | Out-File -Append $progress
