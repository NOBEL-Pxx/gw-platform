# GravitationalWave One-Click Startup
# Loads saved images + starts all services

$ErrorActionPreference = "Stop"
$AliCPT = "D:\AliCPT"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " GravitationalWave Platform Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Docker
Write-Host "[1/3] Checking Docker..." -ForegroundColor Yellow
try {
    docker ps | Out-Null
    Write-Host "  Docker: running" -ForegroundColor Green
} catch {
    Write-Host "  Docker not running. Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "  Waiting for Docker (30s)..."
    Start-Sleep 30
}

# Step 2: Load saved images if needed
Write-Host "[2/3] Loading Docker images..." -ForegroundColor Yellow
$imagesDir = "$AliCPT\docker-images"
if (Test-Path $imagesDir) {
    Get-ChildItem $imagesDir -Filter "*.tar" | ForEach-Object {
        $name = $_.BaseName
        $existing = docker images --format "{{.Repository}}" | Select-String $name
        if (-not $existing) {
            Write-Host "  Loading $name..."
            docker load -i $_.FullName | Out-Null
        } else {
            Write-Host "  $name : already loaded"
        }
    }
}
Write-Host "  Images ready" -ForegroundColor Green

# Step 3: Start services
Write-Host "[3/3] Starting services..." -ForegroundColor Yellow
Set-Location $AliCPT
docker compose up -d

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " All services started!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:  http://localhost:6001" -ForegroundColor Cyan
Write-Host "  Backend:   http://localhost:8093" -ForegroundColor Cyan
Write-Host "  Pipeline:  http://localhost:8200" -ForegroundColor Cyan
Write-Host "  MCP:       http://localhost:8100" -ForegroundColor Cyan
Write-Host "  Firefly:   http://localhost:8080" -ForegroundColor Cyan
Write-Host ""
Write-Host "  docker compose ps   - check status" -ForegroundColor Gray
Write-Host "  docker compose down - stop all" -ForegroundColor Gray
