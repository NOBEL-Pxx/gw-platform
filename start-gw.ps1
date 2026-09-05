# GravitationalWave Platform — One-Click Launcher (v4.15)
# Features: tunnel auto-reconnect, service monitor, db backup reminder
# Run: powershell -ExecutionPolicy Bypass -File start-gw.ps1
#      powershell -ExecutionPolicy Bypass -File start-gw.ps1 -NoTunnel
#      powershell -ExecutionPolicy Bypass -File start-gw.ps1 -Stop

param(
    [switch]$NoTunnel,
    [switch]$Monitor,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$ProjectDir = "D:\AliCPT"
$UrlFile = "C:\Users\28610\public-url.txt"
$PidFile = "$ProjectDir\docker-data\tunnel.pid"

function Write-Banner {
    Write-Host "`n========================================" -ForegroundColor Magenta
    Write-Host "  GravitationalWave Platform Launcher" -ForegroundColor Magenta
    Write-Host "  v4.15 — Windows" -ForegroundColor Magenta
    Write-Host "========================================`n" -ForegroundColor Magenta
}

# ═══════════════════════════════════════════════════════════════════════════
#  STOP
# ═══════════════════════════════════════════════════════════════════════════
if ($Stop) {
    Write-Banner
    Write-Host "[STOP] Stopping all services..." -ForegroundColor Yellow

    # Stop monitor if running
    if (Test-Path "$ProjectDir\docker-data\monitor.pid") {
        $monitorPid = Get-Content "$ProjectDir\docker-data\monitor.pid"
        try { Stop-Process -Id $monitorPid -Force -ErrorAction SilentlyContinue } catch {}
        Remove-Item "$ProjectDir\docker-data\monitor.pid" -Force -ErrorAction SilentlyContinue
    }

    # Kill tunnel jobs
    Get-Job | Where-Object { $_.Name -like "*ssh*tunnel*" -or $_.Name -like "*lhr*" } | Stop-Job -PassThru | Remove-Job -Force
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }

    # Stop containers
    Set-Location $ProjectDir
    docker compose down 2>&1 | Out-Null
    Write-Host "  All services stopped." -ForegroundColor Green
    exit 0
}

# ═══════════════════════════════════════════════════════════════════════════
#  TUNNEL WITH AUTO-RECONNECT
# ═══════════════════════════════════════════════════════════════════════════
function Start-TunnelWithRetry {
    param([int]$MaxRetries = 10)
    $retry = 0
    $backoff = 5

    while ($retry -lt $MaxRetries) {
        $retry++
        Write-Host "  Tunnel attempt $retry/$MaxRetries ..." -ForegroundColor Cyan

        # Start SSH tunnel as background job
        $job = Start-Job -Name "gw-tunnel-lhr" -ScriptBlock {
            ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R 80:localhost:6001 nokey@localhost.run 2>&1
        }

        # Wait and extract URL
        $waited = 0
        while ($waited -lt 30) {
            Start-Sleep -Seconds 1
            $waited++
            $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
            $urlMatch = [regex]::Match($output, 'https://[a-z0-9]+\.lhr\.life')
            if ($urlMatch.Success) {
                $url = $urlMatch.Value
                $url | Out-File -FilePath $UrlFile -Encoding UTF8
                Write-Host "  Tunnel active! Public URL: $url" -ForegroundColor Green
                return $job  # Return the running job
            }
            # Check if job died
            if ($job.State -eq 'Failed' -or $job.State -eq 'Completed') {
                Write-Host "  SSH process died. Retrying..." -ForegroundColor Yellow
                Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
                break
            }
        }

        # If we got here, connection failed this attempt
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        if ($retry -lt $MaxRetries) {
            Write-Host "  Retrying in ${backoff}s..." -ForegroundColor Yellow
            Start-Sleep -Seconds $backoff
            $backoff += 5
        }
    }
    Write-Host "  Failed to establish tunnel after $MaxRetries attempts." -ForegroundColor Red
    return $null
}

# ═══════════════════════════════════════════════════════════════════════════
#  TUNNEL WATCHDOG — auto-reconnect loop
# ═══════════════════════════════════════════════════════════════════════════
function Start-TunnelWatchdog {
    $watchdogJob = Start-Job -Name "gw-tunnel-watchdog" -ScriptBlock {
        $UrlFile = $using:UrlFile
        while ($true) {
            Start-Sleep -Seconds 45
            $job = Get-Job -Name "gw-tunnel-lhr" -ErrorAction SilentlyContinue
            if (-not $job -or $job.State -eq 'Failed' -or $job.State -eq 'Completed') {
                $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Tunnel lost! Reconnecting..."
                Add-Content -Path "D:\AliCPT\docker-data\tunnel-watchdog.log" -Value $msg
                # Restart tunnel
                $newJob = Start-Job -Name "gw-tunnel-lhr" -ScriptBlock {
                    ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R 80:localhost:6001 nokey@localhost.run 2>&1
                }
                Start-Sleep -Seconds 10
                $output = Receive-Job -Job $newJob -ErrorAction SilentlyContinue
                $urlMatch = [regex]::Match($output, 'https://[a-z0-9]+\.lhr\.life')
                if ($urlMatch.Success) {
                    $urlMatch.Value | Out-File -FilePath $UrlFile -Encoding UTF8
                    Add-Content -Path "D:\AliCPT\docker-data\tunnel-watchdog.log" -Value "Tunnel reconnected: $($urlMatch.Value)"
                }
            }
        }
    }
    return $watchdogJob
}

# ═══════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK with progress
# ═══════════════════════════════════════════════════════════════════════════
function Wait-ForHealthy {
    $maxWait = 180
    $waited = 0
    Write-Host "[Wait]" -NoNewline -ForegroundColor Yellow
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 5
        $waited += 5
        $healthy = (docker compose -f "$ProjectDir\docker-compose.yml" ps 2>&1 | Select-String "healthy").Count
        Write-Host "." -NoNewline
        if ($healthy -ge 7) {
            Write-Host "`n  All 7 services healthy! (${waited}s)" -ForegroundColor Green
            return $true
        }
    }
    Write-Host "`n"
    Write-Host "  Timeout: only $healthy/7 healthy after ${maxWait}s" -ForegroundColor Red
    return $false
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
Write-Banner

# Step 1: Start Docker
Write-Host "[1/4] Starting Docker containers..." -ForegroundColor Yellow
Set-Location $ProjectDir
docker compose up -d 2>&1 | Out-Null

# Step 2: Wait for healthy
Write-Host "[2/4] Waiting for all 7 services to be healthy..." -ForegroundColor Yellow
if (-not (Wait-ForHealthy)) {
    Write-Host "  Some services failed. Check: docker compose ps" -ForegroundColor Red
    docker compose ps
    exit 1
}

# Step 3: Monitor (optional)
if ($Monitor) {
    Write-Host "[3/4] Starting service monitor..." -ForegroundColor Yellow
    # Start monitor as background job
    $monitorJob = Start-Job -Name "gw-monitor" -ScriptBlock {
        $ProjectDir = $using:ProjectDir
        while ($true) {
            Start-Sleep -Seconds 30
            $containers = docker compose -f "$ProjectDir\docker-compose.yml" ps -q 2>&1
            foreach ($cid in $containers) {
                $status = docker inspect --format '{{.State.Status}}' $cid 2>&1
                $health = docker inspect --format '{{.State.Health.Status}}' $cid 2>&1
                $cname = (docker inspect --format '{{.Name}}' $cid).TrimStart('/')
                if ($status -ne "running" -or $health -eq "unhealthy") {
                    $msg = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] RESTART: $cname (status=$status, health=$health)"
                    Add-Content -Path "$ProjectDir\docker-data\monitor.log" -Value $msg
                    docker compose -f "$ProjectDir\docker-compose.yml" restart $cname 2>&1 | Out-Null
                }
            }
        }
    }
    Write-Host "  Monitor started." -ForegroundColor Green
} else {
    Write-Host "[3/4] Service monitor skipped (use -Monitor to enable)." -ForegroundColor Cyan
}

# Step 4: Tunnel
if (-not $NoTunnel) {
    Write-Host "[4/4] Starting public tunnel with auto-reconnect..." -ForegroundColor Yellow
    $tunnelJob = Start-TunnelWithRetry

    if ($tunnelJob) {
        # Start watchdog for auto-reconnect
        $watchdog = Start-TunnelWatchdog
        Write-Host "  Watchdog started (auto-reconnect on disconnect)." -ForegroundColor Green
    }
} else {
    Write-Host "[4/4] Public tunnel skipped (-NoTunnel)." -ForegroundColor Cyan
}

# ── Final Summary ───────────────────────────────────────────────────────────
$publicUrl = ""
if (Test-Path $UrlFile) { $publicUrl = Get-Content $UrlFile }

Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  LOCAL   : https://localhost:6002" -ForegroundColor Cyan
if ($publicUrl) {
    Write-Host "  PUBLIC  : $publicUrl" -ForegroundColor Green
}
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "`nCommands:"
Write-Host "  powershell -File start-gw.ps1 -Stop      Stop everything"
Write-Host "  bash scripts/monitor.sh status           Health check"
Write-Host "  bash scripts/backup-db.sh backup          Backup databases"
Write-Host "  bash scripts/log-mgmt.sh status           Log status"
Write-Host ""
Write-Host "Press Ctrl+C to stop the tunnel and exit.`n" -ForegroundColor Yellow

# Keep script alive; wait on tunnel job
try {
    Wait-Job -Name "gw-tunnel-lhr" -ErrorAction SilentlyContinue | Out-Null
} catch {
    Write-Host "`nShutting down..." -ForegroundColor Yellow
}
