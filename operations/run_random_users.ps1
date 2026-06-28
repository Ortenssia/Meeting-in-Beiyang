param(
    [int]$Count = 6,
    [int]$BaseTcpPort = 7780,
    [int]$BaseUdpPort = 8890,
    [string]$NamePrefix = "",
    [string]$Python = "python",
    [switch]$NoWindow = $true,
    [int]$Delay = 3
)

<#
.SYNOPSIS
  Launch N randomly-named instances for multi-user stability stress testing.

.DESCRIPTION
  Each instance gets:
    - A unique random name (or -NamePrefix based sequential names)
    - An isolated --instance directory (.runtime/<name>)
    - Incrementing, non-conflicting TCP / UDP ports

  All instances discover each other via UDP on the same LAN.  Useful for
  stress-testing:
    - Discovery performance with many online users
    - Friend request / message relay stability
    - TCP connection pool and heartbeat under load

.PARAMETER Count
  Number of instances to launch (default 6).

.PARAMETER BaseTcpPort
  Starting TCP port (default 7780).  Each instance gets +1.

.PARAMETER BaseUdpPort
  Starting UDP port (default 8890).  Each instance gets +1.

.PARAMETER NamePrefix
  Uniform name prefix, e.g. "Test" produces Test-1, Test-2, ...
  When omitted, names are randomly drawn from the built-in pool.

.PARAMETER Python
  Python interpreter path (default "python").

.PARAMETER NoWindow
  Hide all instance windows (default $true).  Only PID + port info is
  printed to the console.

.EXAMPLE
  # Launch 10 random users
  powershell -ExecutionPolicy Bypass -File operations/run_random_users.ps1 -Count 10

.EXAMPLE
  # Launch 4 prefixed users with visible windows
  powershell -ExecutionPolicy Bypass -File operations/run_random_users.ps1 -Count 4 -NamePrefix "QA" -NoWindow:$false

.EXAMPLE
  # Use a specific Python (e.g. venv)
  powershell -ExecutionPolicy Bypass -File operations/run_random_users.ps1 -Python ".venv\Scripts\python.exe"
#>

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $projectRoot "core\main.py"

# ------------------------------------------------------------------ #
#  Random name pool (Pinyin — ASCII-safe for all PowerShell versions)
# ------------------------------------------------------------------ #
$namePool = @(
    "Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi",
    "Ivan", "Judy", "Kevin", "Lena", "Mallory", "Nia", "Oscar", "Peggy",
    "Quinn", "Rudy", "Sybil", "Trudy", "Uma", "Victor", "Wendy", "Xena",
    "Yara", "Zack", "Atlas", "Blake", "Cyan", "Drew", "Ellis", "Finley",
    "Gale", "Harper", "Indigo", "Joss", "Kai", "Lane", "Morgan", "Nico",
    "Ollie", "Pax", "Quincy", "Reese", "Sage", "Tate", "Val", "Wren"
)

function Get-RandomName {
    param([int]$Index)
    if ($NamePrefix) {
        return "$NamePrefix-$Index"
    }
    return $namePool | Get-Random
}

# ------------------------------------------------------------------ #
#  Launch instances
# ------------------------------------------------------------------ #
$instances = @()
$usedNames = [System.Collections.Generic.HashSet[string]]::new()

for ($i = 0; $i -lt $Count; $i++) {
    # Generate a unique random name
    $name = Get-RandomName -Index ($i + 1)
    $attempt = 0
    while ($usedNames.Contains($name) -and $attempt -lt 200) {
        $name = Get-RandomName -Index ($i + 1)
        $attempt++
    }
    $usedNames.Add($name) | Out-Null

    $tcpPort  = $BaseTcpPort + $i
    $udpPort  = $BaseUdpPort + $i
    $instance = $name

    $args = @(
        $entryPoint,
        "--instance", $instance,
        "--name", $name,
        "--port", $tcpPort,
        "--udp-port", $udpPort
    )

    $windowStyle = if ($NoWindow) { "Hidden" } else { "Normal" }

    $proc = Start-Process -FilePath $Python -ArgumentList $args `
        -WorkingDirectory $projectRoot `
        -WindowStyle $windowStyle `
        -PassThru

    $instances += [PSCustomObject]@{
        Index    = $i + 1
        Name     = $name
        PID      = $proc.Id
        TcpPort  = $tcpPort
        UdpPort  = $udpPort
        Instance = $instance
    }

    Write-Host "  [$($i+1)/$Count] $name started (PID $($proc.Id))" -ForegroundColor Green

    # Stagger launches so each instance has time to bind its ports and
    # start broadcasting before the next one arrives.
    if ($i -lt $Count - 1) {
        Start-Sleep -Seconds $Delay
    }
}

# ------------------------------------------------------------------ #
#  Output
# ------------------------------------------------------------------ #
Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Random-User Stress Test -- $Count instances" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$instances | Format-Table -Property Index, Name, PID, TcpPort, UdpPort

Write-Host "Runtime data dir : $projectRoot\.runtime\" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Tips:" -ForegroundColor Yellow
Write-Host "  - All instances discover each other via UDP broadcast (same LAN)"
Write-Host "  - Each instance has isolated DB and received-files dir"
Write-Host "  - Inspect a process : Get-Process -Id <PID>"
Write-Host "  - Stop all          : Get-Process python | Stop-Process"
Write-Host "  - Clean runtime data: Remove-Item -Recurse .runtime"
Write-Host ""
