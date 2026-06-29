$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CleanRoot = Join-Path $ProjectRoot ".windows-build-clean"
$OutputDir = Join-Path $ProjectRoot "build\windows"
$ReleaseDir = Join-Path $ProjectRoot "build\release"

function Assert-UnderProject {
    param([Parameter(Mandatory = $true)][string]$Path)

    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    if (-not $pathFull.StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove or write outside project: $Path"
    }
}

function Invoke-RobocopyChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    $args = @($Source, $Destination, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP") + $ExtraArgs
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with exit code ${LASTEXITCODE}: $Source -> $Destination"
    }
}

Write-Host "[1/4] Preparing clean Windows app directory..."
foreach ($path in @($CleanRoot, $OutputDir, $ReleaseDir)) {
    Assert-UnderProject $path
}
if (Test-Path -LiteralPath $CleanRoot) {
    Remove-Item -LiteralPath $CleanRoot -Recurse -Force
}
if (Test-Path -LiteralPath $OutputDir) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}
New-Item -ItemType Directory -Path $CleanRoot | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

Set-Content -LiteralPath (Join-Path $CleanRoot "main.py") -Value @"
from core.main import main


if __name__ == "__main__":
    main()
"@ -NoNewline
Copy-Item -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -Destination $CleanRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "requirements.txt") -Destination $CleanRoot

Invoke-RobocopyChecked `
    -Source (Join-Path $ProjectRoot "core") `
    -Destination (Join-Path $CleanRoot "core") `
    -ExtraArgs @("/XD", "__pycache__", "tests", "/XF", "*.pyc", "*.pyo")
Invoke-RobocopyChecked `
    -Source (Join-Path $ProjectRoot "assets") `
    -Destination (Join-Path $CleanRoot "assets") `
    -ExtraArgs @("/XD", "data", "received_avatars", "received_files", "tmp")

$version = (Select-String -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -Pattern '^\s*version\s*=\s*"([^"]+)"').Matches.Groups[1].Value
$buildInfo = [ordered]@{
    product = "meeting-in-beiyang"
    version = $version
    build_id = [guid]::NewGuid().ToString("N")
    built_at_utc = (Get-Date).ToUniversalTime().ToString("o")
}
$buildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $CleanRoot "build_info.json") -Encoding UTF8
Write-Host "  Version: $version"
Write-Host "  Build ID: $($buildInfo.build_id)"

Write-Host "[2/4] Building Windows package..."
& flet build windows $CleanRoot `
    --output $OutputDir `
    --yes `
    --no-rich-output `
    --cleanup-app `
    --module-name main
if ($LASTEXITCODE -ne 0) {
    throw "Flet Windows build failed with exit code $LASTEXITCODE"
}

Write-Host "[3/4] Verifying executable..."
$exe = Get-ChildItem -LiteralPath $OutputDir -Filter "*.exe" -File -Recurse |
    Sort-Object Length -Descending |
    Select-Object -First 1
if (-not $exe) {
    throw "No Windows executable was produced under $OutputDir"
}
$sha256 = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "[4/4] Creating distributable ZIP..."
$releaseZip = Join-Path $ReleaseDir "meeting-in-beiyang-windows-$version.zip"
if (Test-Path -LiteralPath $releaseZip) {
    Remove-Item -LiteralPath $releaseZip -Force
}
Compress-Archive -Path (Join-Path $OutputDir "*") -DestinationPath $releaseZip -CompressionLevel Optimal
Set-Content -LiteralPath "$releaseZip.sha256" -Value ((Get-FileHash -LiteralPath $releaseZip -Algorithm SHA256).Hash.ToLowerInvariant()) -NoNewline

Write-Host "DONE: $($exe.FullName)"
Write-Host "EXE SHA256: $sha256"
Write-Host "RELEASE ZIP: $releaseZip"
