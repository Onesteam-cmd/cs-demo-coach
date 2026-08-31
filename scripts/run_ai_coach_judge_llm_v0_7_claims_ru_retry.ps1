param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [ValidateSet("check", "llm")]
    [string]$Mode = "llm",
    [int]$Retries = 3,
    [int]$SleepSeconds = 20,
    [int]$MaxTokens = 16000,
    [double]$Temperature = 0.15,
    [int]$TimeoutSec = 1800,
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

if ($Mode -eq "check") {
    & ".\scripts\run_ai_coach_judge_llm_v0_7_claims_ru.ps1" `
        -MatchId $MatchId `
        -Player $Player `
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
    Write-Host "v0.7_claims_ru LLM attempt $attempt / $($Retries + 1)"
    Write-Host ""

    & ".\scripts\run_ai_coach_judge_llm_v0_7_claims_ru.ps1" `
        -MatchId $MatchId `
        -Player $Player `
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
