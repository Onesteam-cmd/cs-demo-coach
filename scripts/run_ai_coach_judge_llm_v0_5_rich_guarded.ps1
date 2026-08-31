param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
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

& $Python ".\backend\ai\ai_coach_judge_llm_runner_v0_5_rich_guarded.py" `
    --match-id $MatchId `
    --player $Player `
    --mode $Mode
