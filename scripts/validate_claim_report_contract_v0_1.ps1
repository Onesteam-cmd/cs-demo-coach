param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportPath = "",
    [string]$ExpectedRounds = "2,3,4,8,9,11,14,15,16,17,19,20",
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
    "backend\ai\claim_report_contract_validator_v0_1.py",
    "--match-id", $MatchId,
    "--player", $Player,
    "--expected-rounds", $ExpectedRounds
)

if ($ReportPath -and $ReportPath.Trim().Length -gt 0) {
    $argsList += @("--report-path", $ReportPath)
}

& $pythonExe $argsList
