# Starts Quill with settings from quill.env (KEY=value per line) in the project root.
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "quill.env"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*)$') {
            Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2].Trim()
        }
    }
}
# 127.0.0.1 is enough for Cloudflare Tunnel. Set QUILL_HOST=0.0.0.0 in quill.env for Wi-Fi or Tailscale.
$hostAddr = if ($env:QUILL_HOST) { $env:QUILL_HOST } else { "127.0.0.1" }
$logDir = Join-Path $root "data"
New-Item -ItemType Directory -Force $logDir | Out-Null

& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn app:app `
    --app-dir (Join-Path $root "backend") --host $hostAddr --port 8000 `
    *>> (Join-Path $logDir "server.log")
