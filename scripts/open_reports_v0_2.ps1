param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location "."
pwd

$Targets = @(
    ".\data\dashboard\dashboard_v0_7.html",
    ".\data\reports\$MatchId\unified_coach_verdict_${Player}_v0_3.html",
    ".\data\reports\$MatchId\round_macro_${Player}_v0_2.html",
    ".\data\reports\$MatchId\macro_coach_verdict_${Player}_v0_1.html",
    ".\data\dashboard\dashboard_v0_4.html",
    ".\data\reports\$MatchId"
)

foreach ($Target in $Targets) {
    if (Test-Path $Target) {
        Start-Process (Resolve-Path $Target)
    } else {
        Write-Host "MISSING: $Target"
    }
}

Write-Host ""
Write-Host "=== Reports opened ==="
