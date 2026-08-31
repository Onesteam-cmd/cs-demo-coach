param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$ReportPath = "data\ai\example_match\ai_coach_judge_llm_report_Player_v0_7_claims_ru_repaired_v0_1.json",
    [ValidateSet("check", "llm")]
    [string]$Mode = "llm",
    [int]$Retries = 3,
    [int]$SleepSeconds = 25,
    [int]$MaxTokens = 6000,
    [double]$Temperature = 0.0,
    [int]$TimeoutSec = 1800,
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

if ($Mode -eq "check") {
    & ".\scripts\run_ai_surface_report_repair_v0_1.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -ReportPath $ReportPath `
        -Mode check `
        -MaxTokens $MaxTokens `
        -Temperature $Temperature `
        -TimeoutSec $TimeoutSec `
        -ProjectRoot $ProjectRoot

    exit $LASTEXITCODE
}

$attempt = 0
$lastExit = 1

while ($attempt -le $Retries) {
    $attempt += 1

    Write-Host ""
    Write-Host "Surface report repair v0.1 attempt $attempt / $($Retries + 1)"
    Write-Host ""

    & ".\scripts\run_ai_surface_report_repair_v0_1.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -ReportPath $ReportPath `
        -Mode llm `
        -MaxTokens $MaxTokens `
        -Temperature $Temperature `
        -TimeoutSec $TimeoutSec `
        -ProjectRoot $ProjectRoot

    $lastExit = $LASTEXITCODE

    if ($lastExit -eq 0) {
        exit 0
    }

    if ($attempt -le $Retries) {
        Write-Host ""
        Write-Host "Attempt failed. Sleeping $SleepSeconds seconds before retry..."
        Start-Sleep -Seconds $SleepSeconds
    }
}

exit $lastExit
