param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportPath = "",
    [string]$InputPath = "",
    [switch]$RequirePermissionGate,
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

$pythonCandidates = @(
    ".\.venv\Scripts\python.exe",
    ".\venv\Scripts\python.exe",
    "python",
    "py"
)

$pythonExe = $null

foreach ($candidate in $pythonCandidates) {
    if ($candidate -like ".\*") {
        if (Test-Path $candidate) {
            $pythonExe = $candidate
            break
        }
    } else {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $cmd) {
            $pythonExe = $candidate
            break
        }
    }
}

if ($null -eq $pythonExe) {
    throw "Python executable not found."
}

$argsList = @(
    "backend\ai\claim_permission_report_validator_v0_1.py",
    "--match-id", $MatchId,
    "--player", $Player
)

if ($ReportPath -and $ReportPath.Trim().Length -gt 0) {
    $argsList += @("--report-path", $ReportPath)
}

if ($InputPath -and $InputPath.Trim().Length -gt 0) {
    $argsList += @("--input-path", $InputPath)
}

if ($RequirePermissionGate) {
    $argsList += "--require-permission-gate"
}

& $pythonExe @argsList

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
