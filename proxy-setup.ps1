# GravitationalWave Docker Proxy Auto-Detect Script
# Detects active Clash proxy port and configures Docker Desktop

Write-Host "Scanning for active proxy..." -ForegroundColor Cyan

$ports = @(7890, 7891, 1080, 1081, 8088, 8888, 9090, 10809)
$activePort = $null

foreach ($port in $ports) {
    try {
        $result = Invoke-WebRequest -Uri "https://httpbin.org/ip" -Proxy "http://127.0.0.1:$port" -TimeoutSec 3 -ErrorAction Stop
        Write-Host "  Port $port : OK" -ForegroundColor Green
        $activePort = $port
        break
    } catch {
        Write-Host "  Port $port : -"
    }
}

if (-not $activePort) {
    Write-Host "No active proxy found. Start Clash first." -ForegroundColor Red
    exit 1
}

Write-Host "Configuring Docker Desktop to use proxy 127.0.0.1:$activePort" -ForegroundColor Yellow

$settingsPath = "$env:APPDATA\Docker\settings.json"
if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath | ConvertFrom-Json
    $settings | Add-Member -NotePropertyName "proxies" -NotePropertyValue @{
        "default" = "http://127.0.0.1:${activePort}"
    } -Force
    $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath
    Write-Host "Docker Desktop settings updated. Restart Docker Desktop." -ForegroundColor Green
} else {
    Write-Host "Docker settings.json not found. Configure manually in Docker Desktop → Settings → Resources → Proxies" -ForegroundColor Yellow
    Write-Host "  HTTP: http://127.0.0.1:$activePort"
    Write-Host "  HTTPS: http://127.0.0.1:$activePort"
}

Write-Host ""
Write-Host "For docker pull, set env vars:" -ForegroundColor Cyan
Write-Host "  `$env:HTTP_PROXY='http://127.0.0.1:$activePort'"
Write-Host "  `$env:HTTPS_PROXY='http://127.0.0.1:$activePort'"
