param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportPath = "data\ai\example_match\ai_coach_judge_llm_report_Player_v0_7_claims_ru_repaired_v0_1.json",
    [string]$RepairResultPath = "data\ai\example_match\ai_claim_report_repair_result_Player_v0_1.json",
    [string]$FinalVerdictPath = "data\ai\example_match\ai_semantic_claim_judge_Player_v0_3_repaired_r14_17.json",
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

& $pythonExe "backend\ai\claim_report_renderer_v0_2.py" `
    --match-id $MatchId `
    --player $Player `
    --report-path $ReportPath `
    --repair-result-path $RepairResultPath `
    --final-verdict-path $FinalVerdictPath
