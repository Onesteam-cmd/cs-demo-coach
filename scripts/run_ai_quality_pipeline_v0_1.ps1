param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$QualityProfile = "balanced",
    [switch]$PreflightOnly,
    [switch]$SkipCoreGeneration,
    [switch]$SkipSurfaceRepair,
    [switch]$KeepGoing
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$pythonCmd = $null
foreach ($candidate in @("python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        $pythonCmd = $candidate
        break
    }
}

if (-not $pythonCmd) {
    throw "Python не найден в PATH. Нужен python или py."
}

$argsList = @(
    ".\backend\ai\ai_quality_pipeline_runner_v0_1.py",
    "--match-id", $MatchId,
    "--player", $Player,
    "--quality-profile", $QualityProfile
)

if ($PreflightOnly) {
    $argsList += "--preflight-only"
}

if ($SkipCoreGeneration) {
    $argsList += "--skip-core-generation"
}

if ($SkipSurfaceRepair) {
    $argsList += "--skip-surface-repair"
}

if ($KeepGoing) {
    $argsList += "--keep-going"
}

& $pythonCmd @argsList

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
