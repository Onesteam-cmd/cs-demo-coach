param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportVersion = "v0_5"
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$Report = "data/ai/$MatchId/ai_coach_judge_llm_report_${Player}_${ReportVersion}.json"
$Manual = "data/manual_review/$MatchId/manual_review_notes_${Player}_v0_1.json"
$OutJson = "data/validation/$MatchId/ai_judgement_validation_${Player}_${ReportVersion}_v0_2.json"
$OutTxt = "data/validation/$MatchId/ai_judgement_validation_${Player}_${ReportVersion}_v0_2.txt"

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = ".\.venv\Scripts\python.exe"
} else {
    $Python = "python"
}

& $Python ".\backend\ai\ai_judgement_validator_v0_2.py" `
    --report $Report `
    --manual-notes $Manual `
    --out-json $OutJson `
    --out-txt $OutTxt

Write-Host "`n=== VALIDATION REPORT V0.2 ===`n"
Get-Content $OutTxt -Raw
