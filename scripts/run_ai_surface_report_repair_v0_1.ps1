param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportPath = "data\ai\example_match\ai_coach_judge_llm_report_Player_v0_7_claims_ru_repaired_v0_1.json",
    [ValidateSet("check", "llm")]
    [string]$Mode = "check",
    [int]$MaxTokens = 6000,
    [double]$Temperature = 0.0,
    [int]$TimeoutSec = 1800,
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

& $pythonExe "backend\ai\ai_surface_report_repair_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --report-path $ReportPath `
    --mode $Mode `
    --max-tokens $MaxTokens `
    --temperature $Temperature `
    --timeout-sec $TimeoutSec
