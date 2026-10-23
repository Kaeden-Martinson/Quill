# Runs the whole writing experiment: drafts and revisions under each configuration, then the
# editor's accuracy tests under each editor prompt. Same inputs, seeds and models for every
# configuration. Each step logs to writing_eval\logs; a failed step is logged and the rest go on.
#   powershell -File training\writing_eval\run_all.ps1
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:PYTHONIOENCODING = "utf-8"
# The editor model and settings come from quill.env, like the live app.
foreach ($line in Get-Content (Join-Path $root "quill.env")) {
    if ($line -match '^\s*(QUILL_[A-Z_]+)\s*=\s*(.*)$' -and $Matches[1] -ne "QUILL_PASSCODE") { Set-Item "Env:$($Matches[1])" $Matches[2].Trim() }
}

function Step($name, [scriptblock]$body) {
    $log = Join-Path $logs "$name.log"
    "[$(Get-Date -Format HH:mm:ss)] start $name" | Out-File -Append (Join-Path $logs "progress.log")
    & $body *> $log
    "[$(Get-Date -Format HH:mm:ss)] end $name (exit $LASTEXITCODE)" | Out-File -Append (Join-Path $logs "progress.log")
}

Remove-Item (Join-Path $logs "progress.log") -ErrorAction SilentlyContinue
foreach ($c in "original", "v2-proofread", "v2-clarity") {
    Step "revise-$c" { & $py training\compare_writing.py revise $c }
    Step "eval-$c" { $env:QUILL_PROMPT_CONFIG = $c; & $py training\eval.py $env:QUILL_MODEL; Remove-Item Env:QUILL_PROMPT_CONFIG }
    Step "reliability-$c" { $env:QUILL_PROMPT_CONFIG = $c; $env:QUILL_TESTSET = "confirm"; & $py training\reliability.py $env:QUILL_MODEL; Remove-Item Env:QUILL_PROMPT_CONFIG, Env:QUILL_TESTSET }
}
foreach ($c in "original", "prompt-only", "improved") {
    Step "draft-$c" { & $py training\compare_writing.py draft $c }
}
"[$(Get-Date -Format HH:mm:ss)] all done" | Out-File -Append (Join-Path $logs "progress.log")
