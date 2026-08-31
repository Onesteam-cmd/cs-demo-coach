param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$TargetRounds = "14,17",
    [string]$ReportPath = "",
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
    & ".\scripts\run_ai_semantic_claim_judge_v0_3_repaired_verify.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -TargetRounds $TargetRounds `
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
    Write-Host "Repaired targeted verifier v0.3 attempt $attempt / $($Retries + 1)"
    Write-Host ""

    & ".\scripts\run_ai_semantic_claim_judge_v0_3_repaired_verify.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -TargetRounds $TargetRounds `
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
