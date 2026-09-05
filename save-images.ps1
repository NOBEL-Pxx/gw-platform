# Save current Docker images to D drive (run after successful docker compose build)
$AliCPT = "D:\AliCPT"
$imagesDir = "$AliCPT\docker-images"
New-Item -ItemType Directory -Force -Path $imagesDir | Out-Null

$images = @(
    "alicpt-gw-backend:latest",
    "alicpt-gw-frontend:latest",
    "alicpt-gw-mcp-server:latest",
    "alicpt-gw-pipeline:latest"
)

foreach ($img in $images) {
    $name = $img.Split(":")[0]
    $file = "$imagesDir\$name.tar"
    Write-Host "Saving $img ..."
    docker save -o $file $img
    $size = (Get-Item $file).Length / 1MB
    Write-Host "  $file ($([math]::Round($size,1)) MB)"
}
Write-Host "Done. Run start.ps1 to load and start."
