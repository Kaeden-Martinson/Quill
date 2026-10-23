# Second batch: every editor test, re-run under the same conditions after an Ollama outage made
# the first batch's editor results invalid; then the ablations (editor on generated drafts, the
# full pipeline, and the editor on human-written text). Waits for run_all.ps1 to finish first so
# the two never share the GPU.
#   powershell -File training\writing_eval\run_editor.ps1
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $PSScriptRoot "logs"
$env:PYTHONIOENCODING = "utf-8"
foreach ($line in Get-Content (Join-Path $root "quill.env")) {
    if ($line -match '^\s*(QUILL_[A-Z_]+)\s*=\s*(.*)$' -and $Matches[1] -ne "QUILL_PASSCODE") { Set-Item "Env:$($Matches[1])" $Matches[2].Trim() }
}
while (-not (Select-String -Path (Join-Path $logs "progress.log") -Pattern "all done" -Quiet)) { Start-Sleep -Seconds 60 }

$progress = Join-Path $logs "progress2.log"
function Step($name, [scriptblock]$body) {
    "[$(Get-Date -Format HH:mm:ss)] start $name" | Out-File -Append $progress
    & $body *> (Join-Path $logs "$name.log")
    "[$(Get-Date -Format HH:mm:ss)] end $name (exit $LASTEXITCODE)" | Out-File -Append $progress
}
Remove-Item $progress -ErrorAction SilentlyContinue
foreach ($c in "original", "v2-proofread", "v2-clarity") {
    Step "revise-$c" { & $py training\compare_writing.py revise $c }
    Step "eval-$c" { $env:QUILL_PROMPT_CONFIG = $c; & $py training\eval.py $env:QUILL_MODEL; Remove-Item Env:QUILL_PROMPT_CONFIG }
    Step "reliability-$c" { $env:QUILL_PROMPT_CONFIG = $c; $env:QUILL_TESTSET = "confirm"; & $py training\reliability.py $env:QUILL_MODEL; Remove-Item Env:QUILL_PROMPT_CONFIG, Env:QUILL_TESTSET }
}
# Editor on generated drafts and the full pipeline: live drafter + live editor, candidate drafter
# + candidate editor, and the two crossings, so each stage's effect can be separated.
foreach ($pair in @("original original", "original v2-clarity", "improved original", "improved v2-clarity")) {
    $d, $e = $pair.Split(" ")
    Step "pipeline-$d+$e" { & $py training\compare_writing.py pipeline $e $d }
}
# Editor on human-written text (data\human_corpus, all four sources in one folder view).
$human = Join-Path $root "data\human_corpus\_all"
New-Item -ItemType Directory -Force $human | Out-Null
Get-ChildItem (Join-Path $root "data\human_corpus") -Directory | Where-Object { $_.Name -notlike "_*" } | ForEach-Object {
    $src = $_.Name; Get-ChildItem $_.FullName -Filter *.txt | ForEach-Object { Copy-Item $_.FullName (Join-Path $human "$src--$($_.Name)") }
}
foreach ($c in "original", "v2-clarity") { Step "human-$c" { & $py training\compare_writing.py human $c $human } }
"[$(Get-Date -Format HH:mm:ss)] all done" | Out-File -Append $progress
