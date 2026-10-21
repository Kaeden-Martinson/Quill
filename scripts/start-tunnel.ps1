# Opens a Cloudflare quick tunnel to Quill and prints the public link.
# The link changes every time this runs; see README for a permanent address.
#   powershell -File scripts\start-tunnel.ps1

$port = Test-NetConnection region1.v2.argotunnel.com -Port 7844 -WarningAction SilentlyContinue
if (-not $port.TcpTestSucceeded) {
    Write-Host "This network blocks port 7844, which Cloudflare tunnels need. Try another network (home Wi-Fi usually works)." -ForegroundColor Red
    exit 1
}
try { Invoke-RestMethod http://127.0.0.1:8000/api/status -TimeoutSec 3 | Out-Null }
catch {
    Write-Host "Quill isn't running on port 8000. Start it first: Start-ScheduledTask -TaskName Quill" -ForegroundColor Red
    exit 1
}

Write-Host "Opening tunnel. The public link appears below as https://....trycloudflare.com. Press Ctrl+C to close it."
cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8000 2>&1 | ForEach-Object {
    $line = "$_"
    if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') { Write-Host "`nQuill is live at: $($Matches[0])`n" -ForegroundColor Green }
    elseif ($line -match 'Registered tunnel connection') { Write-Host "Connected to Cloudflare." }
    elseif ($line -match ' ERR ') { Write-Host $line -ForegroundColor Yellow }
}
