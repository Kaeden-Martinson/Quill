# Opens a Cloudflare quick tunnel to Quill and prints the public link.
# The link changes every time this runs; see README for a permanent address.
#   powershell -File scripts\start-tunnel.ps1
# Close the tunnel with Ctrl+C (or by closing this window).

param([int]$StatusPort = 20241)  # cloudflared's local status page, which reports the tunnel's address
$metrics = "127.0.0.1:$StatusPort"
# Test-NetConnection draws a progress banner over the top of the window, which hid the link.
$ProgressPreference = "SilentlyContinue"

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

$log = Join-Path $env:TEMP "quill-tunnel.log"
$cf = Start-Process cloudflared -PassThru -NoNewWindow -RedirectStandardError $log `
    -ArgumentList "tunnel", "--no-autoupdate", "--protocol", "http2", "--metrics", $metrics, "--url", "http://127.0.0.1:8000"
try {
    Write-Host "Opening the tunnel..."
    # The address comes from cloudflared's status page, not its log, so nothing on screen can hide it.
    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url -and -not $cf.HasExited; $i++) {
        try { $url = "https://" + (Invoke-RestMethod "http://$metrics/quicktunnel" -TimeoutSec 2).hostname } catch {}
        if ($url -eq "https://") { $url = $null }
        if (-not $url) { Start-Sleep 1 }
    }
    if (-not $url) {
        Write-Host "The tunnel didn't start. Its log is in $log" -ForegroundColor Red
        exit 1
    }
    # Wait until Cloudflare can actually reach it, so the link works when it's printed.
    for ($i = 0; $i -lt 30; $i++) {
        try { Invoke-RestMethod "$url/api/status" -TimeoutSec 5 | Out-Null; break } catch { Start-Sleep 2 }
    }
    Write-Host ""
    Write-Host "  Quill is live at:  $url" -ForegroundColor Green
    Write-Host "  Share it with the invite code from quill.env. Keep this window open; Ctrl+C closes the tunnel."
    Write-Host ""
    $cf.WaitForExit()
}
finally {
    if (-not $cf.HasExited) { Stop-Process -Id $cf.Id -Force }
}
