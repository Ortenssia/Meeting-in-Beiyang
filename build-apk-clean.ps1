$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CleanRoot = Join-Path $ProjectRoot ".apk-build-clean"
$StageOutput = Join-Path $ProjectRoot ".apk-output-clean"
$OutputDir = Join-Path $ProjectRoot "build\apk"
$LegacyFlutterBuild = Join-Path $ProjectRoot "build\flutter"
$ImageTag = "beiyang-builder:latest"

function Assert-UnderProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    if (-not $pathFull.StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove or write outside project: $Path"
    }
}

function Invoke-RobocopyChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [string[]]$ExtraArgs = @()
    )

    $args = @($Source, $Destination, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP") + $ExtraArgs
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with exit code ${LASTEXITCODE}: $Source -> $Destination"
    }
}

Write-Host "[1/5] Preparing clean Flet app directory..."
Assert-UnderProject $CleanRoot
Assert-UnderProject $OutputDir
Assert-UnderProject $LegacyFlutterBuild
if (Test-Path -LiteralPath $CleanRoot) {
    Remove-Item -LiteralPath $CleanRoot -Recurse -Force
}
if (Test-Path -LiteralPath $OutputDir) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}
if (Test-Path -LiteralPath $LegacyFlutterBuild) {
    Remove-Item -LiteralPath $LegacyFlutterBuild -Recurse -Force
}
New-Item -ItemType Directory -Path $CleanRoot | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

Set-Content -LiteralPath (Join-Path $CleanRoot "main.py") -Value @"
from core.main import main


if __name__ == "__main__":
    main()
"@ -NoNewline
Copy-Item -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -Destination $CleanRoot
Copy-Item -LiteralPath (Join-Path $ProjectRoot "requirements.txt") -Destination $CleanRoot

$projectVersion = (Select-String -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -Pattern '^\s*version\s*=\s*"([^"]+)"').Matches.Groups[1].Value
$cleanVersion = (Select-String -LiteralPath (Join-Path $CleanRoot "pyproject.toml") -Pattern '^\s*version\s*=\s*"([^"]+)"').Matches.Groups[1].Value
if ($projectVersion -ne $cleanVersion) {
    throw "Clean build version mismatch: source=$projectVersion clean=$cleanVersion"
}
Write-Host "  Version: $cleanVersion"

$sourceFiles = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "core") -Recurse -File -Force |
    Where-Object { $_.FullName -notmatch '\\tests\\' -and $_.Extension -eq ".py" } |
    Sort-Object FullName
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    foreach ($file in $sourceFiles) {
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        [void]$sha.TransformBlock($bytes, 0, $bytes.Length, $null, 0)
    }
    $pyprojectBytes = [System.IO.File]::ReadAllBytes((Join-Path $ProjectRoot "pyproject.toml"))
    [void]$sha.TransformBlock($pyprojectBytes, 0, $pyprojectBytes.Length, $null, 0)
    [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
    $sourceSha256 = ([System.BitConverter]::ToString($sha.Hash)).Replace("-", "").ToLowerInvariant()
}
finally {
    $sha.Dispose()
}
$buildId = [guid]::NewGuid().ToString("N")
$buildInfo = [ordered]@{
    product = "meeting-in-beiyang"
    version = $cleanVersion
    build_id = $buildId
    built_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    source_sha256 = $sourceSha256
}
$buildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $CleanRoot "build_info.json") -Encoding UTF8
Write-Host "  Build ID: $buildId"
Write-Host "  Source SHA256: $sourceSha256"

Invoke-RobocopyChecked `
    -Source (Join-Path $ProjectRoot "core") `
    -Destination (Join-Path $CleanRoot "core") `
    -ExtraArgs @("/XD", "__pycache__", "tests", "/XF", "*.pyc", "*.pyo")

$cleanAssets = Join-Path $CleanRoot "assets"
New-Item -ItemType Directory -Path $cleanAssets | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "assets\app_icon.png") -Destination $cleanAssets
Copy-Item -LiteralPath (Join-Path $ProjectRoot "assets\app_icon.ico") -Destination $cleanAssets
$genericIcon = Join-Path $ProjectRoot "assets\icon.png"
$androidIcon = Join-Path $ProjectRoot "assets\icon_android.png"
if (Test-Path -LiteralPath $genericIcon) {
    Copy-Item -LiteralPath $genericIcon -Destination (Join-Path $cleanAssets "icon.png")
} else {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "assets\app_icon.png") -Destination (Join-Path $cleanAssets "icon.png")
}
if (Test-Path -LiteralPath $androidIcon) {
    Copy-Item -LiteralPath $androidIcon -Destination (Join-Path $cleanAssets "icon_android.png")
} else {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "assets\app_icon.png") -Destination (Join-Path $cleanAssets "icon_android.png")
}
foreach ($assetDir in @("avatars", "fonts", "icons")) {
    $source = Join-Path $ProjectRoot "assets\$assetDir"
    if (Test-Path -LiteralPath $source) {
        Invoke-RobocopyChecked -Source $source -Destination (Join-Path $cleanAssets $assetDir)
    }
}

Write-Host "[2/5] Clean directory size:"
$cleanBytes = (Get-ChildItem -LiteralPath $CleanRoot -Recurse -File -Force | Measure-Object Length -Sum).Sum
Write-Host ("  {0:N2} MB" -f ($cleanBytes / 1MB))

Write-Host "[3/5] Checking Docker image $ImageTag..."
& docker image inspect $ImageTag | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker image '$ImageTag' was not found. Build or load it first."
}

Write-Host "[4/5] Building APK in Docker..."
$containerScript = @'
set -uo pipefail
rm -rf /work/app
mkdir -p /work/app
cp -a /src/. /work/app/
cd /work/app
rm -rf build

sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/root/Android/sdk}}"
ndk_dir="$sdk_root/ndk/28.2.13676358"
if [ -d "$ndk_dir" ] && [ ! -f "$ndk_dir/source.properties" ]; then
    echo "Removing incomplete NDK installation: $ndk_dir"
    rm -rf "$ndk_dir"
fi
rm -rf "$sdk_root/.temp"

build_ok=0
for attempt in 1 2 3; do
    echo "Flet APK build attempt $attempt/3"
    if flet build apk --yes --no-rich-output --skip-flutter-doctor --cleanup-app; then
        build_ok=1
        break
    fi
    echo "Build attempt failed; clearing incomplete NDK download before retry."
    rm -rf "$ndk_dir" "$sdk_root/.temp"
    sleep $((attempt * 3))
done
if [ "$build_ok" -ne 1 ]; then
    echo "Flet APK build failed after 3 attempts."
    exit 1
fi
cp build/apk/*.apk /out/
'@
$containerScriptPath = Join-Path $CleanRoot "docker-build.sh"
$containerScriptLf = $containerScript.Replace("`r`n", "`n")
[System.IO.File]::WriteAllText(
    $containerScriptPath,
    $containerScriptLf,
    [System.Text.UTF8Encoding]::new($false)
)
$dockerArgs = @(
    "run", "--rm",
    "-v", "${CleanRoot}:/src:ro",
    "-v", "${OutputDir}:/out",
    "-v", "beiyang-pub-cache:/root/.pub-cache",
    "-v", "beiyang-gradle-cache:/root/.gradle",
    "-v", "beiyang-android-sdk:/root/Android/sdk",
    "-w", "/work",
    $ImageTag,
    "bash", "/src/docker-build.sh"
)
& docker @dockerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Docker APK build failed with exit code $LASTEXITCODE"
}

Write-Host "[5/5] Verifying APK and SHA1..."
$apk = Get-ChildItem -LiteralPath $OutputDir -Filter "*.apk" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $apk) {
    throw "No APK was produced under $OutputDir"
}

$destApk = $apk.FullName
$sha1 = (Get-FileHash -LiteralPath $destApk -Algorithm SHA1).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$destApk.sha1" -Value $sha1 -NoNewline

$verifyScript = @"
import io, json, re, sys, zipfile
from pathlib import Path

apk = Path(sys.argv[1])
expected_version = sys.argv[2]
expected_build_id = sys.argv[3]
with zipfile.ZipFile(apk) as outer:
    app_zip = outer.read("assets/flutter_assets/app/app.zip")
with zipfile.ZipFile(io.BytesIO(app_zip)) as app:
    pyproject = app.read("pyproject.toml").decode("utf-8", errors="replace")
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not version or version.group(1) != expected_version:
        raise SystemExit(f"APK version mismatch: expected {expected_version}, got {version.group(1) if version else '<missing>'}")
    info = json.loads(app.read("build_info.json").decode("utf-8"))
    if info.get("build_id") != expected_build_id:
        raise SystemExit(f"APK build_id mismatch: expected {expected_build_id}, got {info.get('build_id')}")
    required = [
        "core/backend/services/update_service.py",
        "core/backend/services/friend_db.py",
        "core/frontend/app.py",
    ]
    missing = [name for name in required if name not in app.namelist()]
    if missing:
        raise SystemExit(f"APK missing expected source files: {missing}")
print(f"APK verified: version={expected_version} build_id={expected_build_id}")
"@
$verifyScriptPath = Join-Path $CleanRoot "verify_apk.py"
Set-Content -LiteralPath $verifyScriptPath -Value $verifyScript -Encoding UTF8
& python $verifyScriptPath $destApk $cleanVersion $buildId
if ($LASTEXITCODE -ne 0) {
    throw "APK verification failed"
}

$apkSize = (Get-Item -LiteralPath $destApk).Length / 1MB
Write-Host ("DONE: {0}" -f $destApk)
Write-Host ("SIZE: {0:N2} MB" -f $apkSize)
Write-Host ("SHA1: {0}" -f $sha1)
