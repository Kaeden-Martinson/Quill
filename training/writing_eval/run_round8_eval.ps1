# Round 7 vs round 8 on the same diagnostic suite, same day, same settings (training/rounds/round8_plan.md).
# Run after round 8's training finishes and quill-editor-v8 has been created in Ollama.
#   powershell -File training\writing_eval\run_round8_eval.ps1
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:PYTHONIOENCODING = "utf-8"
foreach ($line in Get-Content (Join-Path $root "quill.env")) {
    if ($line -match '^\s*(QUILL_[A-Z_]+)\s*=\s*(.*)$' -and $Matches[1] -ne "QUILL_PASSCODE") { Set-Item "Env:$($Matches[1])" $Matches[2].Trim() }
}
$progress = Join-Path $logs "progress-r8.log"
Remove-Item $progress -ErrorAction SilentlyContinue
function Step($name, [scriptblock]$body) {
    "[$(Get-Date -Format HH:mm:ss)] start $name" | Out-File -Append $progress
    & $body *> (Join-Path $logs "$name.log")
    "[$(Get-Date -Format HH:mm:ss)] end $name (exit $LASTEXITCODE)" | Out-File -Append $progress
}
$human = Join-Path $root "data\human_corpus\_all"
foreach ($v in "v7", "v8") {
    $model = "quill-editor-$v"
    $env:QUILL_MODEL = $model
    $env:QUILL_RUN_TAG = "@$v"
    Step "r8-reliability-heldout-$v" { Remove-Item Env:QUILL_TESTSET -ErrorAction SilentlyContinue; & $py training\reliability.py $model }
    Step "r8-reliability-confirm-$v" { $env:QUILL_TESTSET = "confirm"; & $py training\reliability.py $model; Remove-Item Env:QUILL_TESTSET }
    Step "r8-eval-$v" { & $py training\eval.py $model }
    Step "r8-revise-$v" { & $py training\compare_writing.py revise original }
    Step "r8-human-$v" { & $py training\compare_writing.py human original $human }
    Step "r8-pipeline-$v" { & $py training\compare_writing.py pipeline original improved }
}
"[$(Get-Date -Format HH:mm:ss)] all done" | Out-File -Append $progress
