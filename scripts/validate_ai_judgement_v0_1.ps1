param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$Report = "data/ai/$MatchId/ai_coach_judge_llm_report_${Player}_v0_2.txt"
$Compact = "data/ai/$MatchId/ai_coach_judge_input_compact_current.json"
$Manual = "data/manual_review/$MatchId/manual_review_notes_${Player}_v0_1.json"
$OutJson = "data/validation/$MatchId/ai_judgement_validation_${Player}_v0_1.json"
$OutTxt = "data/validation/$MatchId/ai_judgement_validation_${Player}_v0_1.txt"

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = ".\.venv\Scripts\python.exe"
} else {
    $Python = "python"
}

& $Python ".\backend\ai\ai_judgement_validator_v0_1.py" `
    --report $Report `
    --compact-input $Compact `
    --manual-notes $Manual `
    --out-json $OutJson `
    --out-txt $OutTxt

Write-Host "`n=== VALIDATION REPORT ===`n"
Get-Content $OutTxt -Raw
