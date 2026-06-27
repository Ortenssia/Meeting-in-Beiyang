param(
    [string]$Python = "python"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$entryPoint = Join-Path $projectRoot "core\main.py"

$aliceArgs = @(
    $entryPoint,
    "--instance", "alice",
    "--name", "Alice",
    "--port", "7779",
    "--udp-port", "8890"
)
$bobArgs = @(
    $entryPoint,
    "--instance", "bob",
    "--name", "Bob",
    "--port", "7780",
    "--udp-port", "8891"
)

$alice = Start-Process -FilePath $Python -ArgumentList $aliceArgs `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
$bob = Start-Process -FilePath $Python -ArgumentList $bobArgs `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru

Write-Host "Alice started: PID $($alice.Id), TCP 7779, UDP 8890"
Write-Host "Bob started:   PID $($bob.Id), TCP 7780, UDP 8891"
Write-Host "Runtime data:  $projectRoot\.runtime\alice and $projectRoot\.runtime\bob"
