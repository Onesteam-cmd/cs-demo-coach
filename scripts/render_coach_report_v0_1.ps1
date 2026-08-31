param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportVersion = "v0_5"
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = ".\.venv\Scripts\python.exe"
} else {
    $Python = "python"
}

& $Python ".\backend\ai\coach_report_renderer_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --report-version $ReportVersion

Write-Host "`n=== RENDERED REPORT PREVIEW ===`n"
Get-Content ".\data\reports\$MatchId\coach_report_${Player}_${ReportVersion}_rendered_v0_1.md" -TotalCount 180
