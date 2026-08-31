param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$paths = @(
    ".\data\dashboard\dashboard_v0_4.html",
    ".\data\reports\$MatchId\coach_verdict_${Player}_v0_2.html",
    ".\data\reports\$MatchId\coach_verdict_${Player}_v0_1.html",
    ".\data\reports\$MatchId\moments_review_v0_2.html",
    ".\data\reports\$MatchId\utility_analyzer_v0_2.html",
    ".\data\reports\$MatchId\utility_map_review_v0_1.html",
    ".\data\reports\$MatchId\utility_map_summary_v0_1.html",
    ".\data\reviews\$MatchId\manual_review_summary_${Player}_v0_1.html",
    ".\data\reviews\$MatchId\manual_review_${Player}_v0_1.html",
    ".\data\progress\progress_${Player}_v0_2.html"
)

Write-Host "=== Opening CS Demo Coach reports ==="
Write-Host "MatchId: $MatchId"
Write-Host "Player:  $Player"
Write-Host ""

foreach ($path in $paths) {
    if (Test-Path $path) {
        Write-Host "OPEN: $path"
        Start-Process $path
    } else {
        Write-Host "MISS: $path"
    }
}


