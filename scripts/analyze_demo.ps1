param(
    [Parameter(Mandatory=$true)]
    [string]$Demo,

    [string]$MatchId = "",

    [string]$Player = "Player",

    [switch]$Force,

    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not (Test-Path $Demo)) {
    throw "Demo file not found: $Demo"
}

if ([string]::IsNullOrWhiteSpace($MatchId)) {
    $MatchId = [System.IO.Path]::GetFileNameWithoutExtension($Demo)
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pipeline = Join-Path $Root "backend\pipeline\run_full_pipeline_v0_3.py"

if (-not (Test-Path $Python)) {
    throw "Python venv not found: $Python"
}

if (-not (Test-Path $Pipeline)) {
    throw "Pipeline not found: $Pipeline"
}

Write-Host "=== CS Demo Coach Launcher ==="
Write-Host "Root:    $Root"
Write-Host "Demo:    $Demo"
Write-Host "MatchId: $MatchId"
Write-Host "Player:  $Player"
Write-Host "Force:   $Force"
Write-Host "NoOpen:  $NoOpen"
Write-Host ""

$argsList = @(
    $Pipeline,
    $Demo,
    "--match-id",
    $MatchId,
    "--player",
    $Player
)

if ($Force) {
    $argsList += "--force"
}

if ($NoOpen) {
    $argsList += "--no-open"
}

& $Python @argsList

Write-Host ""
Write-Host "=== Launcher complete ==="
Write-Host "Dashboard:"
Write-Host "  $Root\data\dashboard\dashboard_v0_4.html"
Write-Host ""
Write-Host "Reports:"
Write-Host "  $Root\data\reports\$MatchId"
Write-Host ""
Write-Host "Reviews:"
Write-Host "  $Root\data\reviews\$MatchId"

