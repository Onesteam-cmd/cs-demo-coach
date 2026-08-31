param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportVersion = "v0_5",
    [ValidateSet("build-input", "check", "llm")]
    [string]$Mode = "check"
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = ".\.venv\Scripts\python.exe"
} else {
    $Python = "python"
}

& $Python ".\backend\ai\ai_semantic_judgement_validator_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --report-version $ReportVersion `
    --mode $Mode
