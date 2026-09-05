# ═══════════════════════════════════════════════════════════════════════════
# GravitationalWave Platform — Scheduled Database Backup (v4.16)
# ═══════════════════════════════════════════════════════════════════════════
# Usage:
#   powershell -Exec Bypass -File backup-schedule.ps1 -Install       # Install scheduled task
#   powershell -Exec Bypass -File backup-schedule.ps1 -Uninstall     # Remove scheduled task
#   powershell -Exec Bypass -File backup-schedule.ps1 -BackupNow     # Run backup immediately
#   powershell -Exec Bypass -File backup-schedule.ps1 -Status        # Show status + recent backups
#
# Schedule: Daily at 03:00 (full backup MongoDB + ES), auto-clean old backups
# ═══════════════════════════════════════════════════════════════════════════
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$BackupNow,
    [switch]$Status
)

$TaskName = "GW-DB-Backup"
$ProjectDir = "D:\AliCPT"
$BackupScript = "$ProjectDir\scripts\backup-db.sh"
$LogDir = "$ProjectDir\docker-data\backup-logs"
$KeepBackups = 7  # Keep last 7 daily backups

# ── Ensure log directory exists ────────────────────────────────────────────
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-BackupLog($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    $logFile = Join-Path $LogDir "backup-$(Get-Date -Format 'yyyyMMdd').log"
    Add-Content -Path $logFile -Value $line
}

# ── Run backup (called by both -Install's action and -BackupNow) ───────────
function Invoke-Backup {
    Write-BackupLog "===== Starting scheduled backup ====="

    # Check Docker is running
    $dockerOk = docker ps --format '{{.Names}}' 2>$null | Select-String "gw-mongodb" -Quiet
    if (-not $dockerOk) {
        Write-BackupLog "ERROR: Docker/gw-mongodb not running. Aborting."
        return 1
    }

    # Run the bash backup script via Git Bash
    $bashPath = "C:\Program Files\Git\bin\bash.exe"
    if (-not (Test-Path $bashPath)) {
        $bashPath = "bash"  # fallback to PATH
    }

    Write-BackupLog "Running: $bashPath $BackupScript backup"
    $result = & $bashPath $BackupScript backup 2>&1
    $exitCode = $LASTEXITCODE

    # Log output
    foreach ($line in $result) {
        Write-BackupLog $line
    }

    if ($exitCode -eq 0) {
        Write-BackupLog "Backup SUCCESS"
        # Clean old backups — keep last N
        Write-BackupLog "Cleaning old backups (keep=$KeepBackups)..."
        & $bashPath $BackupScript clean --keep $KeepBackups 2>&1 | ForEach-Object {
            Write-BackupLog $_
        }
    } else {
        Write-BackupLog "Backup FAILED (exit code: $exitCode)"
    }

    Write-BackupLog "===== Scheduled backup complete ====="
    return $exitCode
}

# ── Status ─────────────────────────────────────────────────────────────────
if ($Status) {
    Write-Host ""
    Write-Host "=== GW Platform — Backup Status (v4.16) ===" -ForegroundColor Cyan
    Write-Host ""

    # Check scheduled task
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Scheduled Task: $($task.State)" -ForegroundColor Green
        Write-Host "  Next run: $($task.NextRunTime)"
        Write-Host "  Last run: $($task.LastRunTime)"
        Write-Host "  Last result: $($task.LastTaskResult)"
    } else {
        Write-Host "Scheduled Task: NOT INSTALLED. Run with -Install." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Backup directory: $ProjectDir\docker-data\backups"
    if (Test-Path "$ProjectDir\docker-data\backups") {
        Get-ChildItem "$ProjectDir\docker-data\backups" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 10 | ForEach-Object {
            $size = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object -Property Length -Sum).Sum
            $sizeMB = [math]::Round($size / 1MB, 1)
            Write-Host "  $($_.Name)  (${sizeMB}MB)  $($_.LastWriteTime)"
        }
    }

    Write-Host ""
    Write-Host "Recent backup logs:"
    if (Test-Path $LogDir) {
        Get-ChildItem $LogDir -Filter "backup-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object {
            Write-Host "  --- $($_.Name) ---"
            Get-Content $_.FullName -Tail 3 | ForEach-Object { Write-Host "    $_" }
        }
    }
    exit 0
}

# ── Uninstall ──────────────────────────────────────────────────────────────
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled Task '$TaskName' removed."
    Write-Host "Backup files at $ProjectDir\docker-data\backups are NOT deleted."
    exit 0
}

# ── Backup Now ─────────────────────────────────────────────────────────────
if ($BackupNow) {
    Write-BackupLog "Manual backup triggered"
    Invoke-Backup
    exit $LASTEXITCODE
}

# ── Install ────────────────────────────────────────────────────────────────
if ($Install) {
    Write-Host ""
    Write-Host "=== Installing GW Database Backup Scheduled Task ===" -ForegroundColor Cyan
    Write-Host ""

    # Remove old task if exists
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    # The action: run this script with -BackupNow flag
    $ScriptPath = (Resolve-Path -Path $MyInvocation.MyCommand.Path).Path
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`" -BackupNow"

    # Daily at 03:00
    $trigger = New-ScheduledTaskTrigger -Daily -At "03:00"

    # Settings: retry on failure, don't run if missed (run next day instead)
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 5) `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Highest

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description "GW Platform daily database backup: MongoDB + Elasticsearch. Runs at 03:00." | Out-Null

    Write-Host "Scheduled Task '$TaskName' installed." -ForegroundColor Green
    Write-Host "  Schedule: Daily at 03:00"
    Write-Host "  Action:   Full backup (MongoDB + ES) + auto-clean old backups"
    Write-Host "  Keep:     Last $KeepBackups backups"
    Write-Host "  Logs:     $LogDir"
    Write-Host ""

    # Ask if user wants to run first backup now
    Write-Host "Run first backup now? (Recommended)"
    $response = Read-Host "  [Y/n]"
    if ($response -eq '' -or $response -eq 'y' -or $response -eq 'Y') {
        Write-Host ""
        Invoke-Backup
    } else {
        Write-Host "Skipped. First backup will run at next scheduled time (03:00)."
    }

    Write-Host ""
    Write-Host "Done. Use 'powershell -Exec Bypass -File backup-schedule.ps1 -Status' to check."
    exit 0
}

# ── No flag → show help ────────────────────────────────────────────────────
Write-Host @"
GW Platform — Scheduled Database Backup (v4.16)

Usage:
  powershell -Exec Bypass -File backup-schedule.ps1 -Install      Install daily backup task
  powershell -Exec Bypass -File backup-schedule.ps1 -Uninstall    Remove scheduled task
  powershell -Exec Bypass -File backup-schedule.ps1 -BackupNow    Run backup immediately
  powershell -Exec Bypass -File backup-schedule.ps1 -Status       Show status

Schedule: Daily at 03:00
  - Full MongoDB dump (mongodump --gzip)
  - Full Elasticsearch snapshot
  - Metadata YAML (docker images, git commit)
  - Auto-clean: keeps last $KeepBackups backups
  - Logs: $LogDir
"@
