# Round 8a (ablation) on the same diagnostic suite and settings as round 8 (training/rounds/round8a_plan.md).
# Run after quill-editor-v8a has been created in Ollama; v7 and v8 results from run_round8_eval.ps1 are reused.
#   powershell -File training\writing_eval\run_round8a_eval.ps1
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:PYTHONIOENCODING = "utf-8"
foreach ($line in Get-Content (Join-Path $root "quill.env")) {
    if ($line -match '^\s*(QUILL_[A-Z_]+)\s*=\s*(.*)$' -and $Matches[1] -ne "QUILL_PASSCODE") { Set-Item "Env:$($Matches[1])" $Matches[2].Trim() }
}
$progress = Join-Path $logs "progress-r8a.log"
Remove-Item $progress -ErrorAction SilentlyContinue
function Step($name, [scriptblock]$body) {
    "[$(Get-Date -Format HH:mm:ss)] start $name" | Out-File -Append $progress
    & $body *> (Join-Path $logs "$name.log")
    "[$(Get-Date -Format HH:mm:ss)] end $name (exit $LASTEXITCODE)" | Out-File -Append $progress
}
$human = Join-Path $root "data\human_corpus\_all"
foreach ($v in @("v8a")) {
    $model = "quill-editor-$v"
    $env:QUILL_MODEL = $model
    $env:QUILL_RUN_TAG = "@$v"
    Step "r8a-reliability-heldout-$v" { Remove-Item Env:QUILL_TESTSET -ErrorAction SilentlyContinue; & $py training\reliability.py $model }
    Step "r8a-reliability-confirm-$v" { $env:QUILL_TESTSET = "confirm"; & $py training\reliability.py $model; Remove-Item Env:QUILL_TESTSET }
    Step "r8a-eval-$v" { & $py training\eval.py $model }
    Step "r8a-revise-$v" { & $py training\compare_writing.py revise original }
    Step "r8a-human-$v" { & $py training\compare_writing.py human original $human }
    Step "r8a-pipeline-$v" { & $py training\compare_writing.py pipeline original improved }
}
"[$(Get-Date -Format HH:mm:ss)] all done" | Out-File -Append $progress
