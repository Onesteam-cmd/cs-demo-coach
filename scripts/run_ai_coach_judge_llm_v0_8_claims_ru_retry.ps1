param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [int]$MaxTokens = 18000,
    [double]$Temperature = 0.12,
    [int]$TimeoutSec = 1800,
    [switch]$WriteCompatV07,
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

try {
    & ".\scripts\run_ai_coach_judge_llm_v0_8_claims_ru.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -Mode "llm" `
        -MaxTokens $MaxTokens `
        -Temperature $Temperature `
        -TimeoutSec $TimeoutSec `
        -ProjectRoot $ProjectRoot `
        -WriteCompatV07:$WriteCompatV07

    if ($LASTEXITCODE -eq 0) {
        if (Test-Path ".\scripts\normalize_claim_types_v0_8_to_v0_7.ps1") {
            & ".\scripts\normalize_claim_types_v0_8_to_v0_7.ps1" `
                -MatchId $MatchId `
                -Player $Player `
                -ProjectRoot $ProjectRoot `
                -WriteCompatV07:$WriteCompatV07 `
                -UpdateTxt

            if ($LASTEXITCODE -ne 0) {
                exit $LASTEXITCODE
            }
        }
        exit 0
    }
} catch {
    Write-Host "First v0.8 LLM attempt failed: $($_.Exception.Message)"
}

Start-Sleep -Seconds 8

& ".\scripts\run_ai_coach_judge_llm_v0_8_claims_ru.ps1" `
    -MatchId $MatchId `
    -Player $Player `
    -Mode "llm" `
    -MaxTokens $MaxTokens `
    -Temperature $Temperature `
    -TimeoutSec $TimeoutSec `
    -ProjectRoot $ProjectRoot `
    -WriteCompatV07:$WriteCompatV07

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}


if (Test-Path ".\scripts\normalize_claim_types_v0_8_to_v0_7.ps1") {
    & ".\scripts\normalize_claim_types_v0_8_to_v0_7.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -ProjectRoot $ProjectRoot `
        -WriteCompatV07:$WriteCompatV07 `
        -UpdateTxt

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
