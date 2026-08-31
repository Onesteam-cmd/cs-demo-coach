param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportPath = "",
    [switch]$WriteCompatV07,
    [switch]$UpdateTxt,
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
    "backend\ai\normalize_claim_types_v0_8_to_v0_7.py",
    "--match-id", $MatchId,
    "--player", $Player
)

if ($ReportPath -and $ReportPath.Trim().Length -gt 0) {
    $argsList += @("--report-path", $ReportPath)
}

if ($WriteCompatV07) {
    $argsList += "--write-compat-v07"
}

if ($UpdateTxt) {
    $argsList += "--update-txt"
}

& $pythonExe @argsList

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
