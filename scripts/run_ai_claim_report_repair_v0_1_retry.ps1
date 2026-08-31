param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [ValidateSet("check", "llm")]
    [string]$Mode = "llm",
    [int]$Retries = 3,
    [int]$SleepSeconds = 25,
    [int]$MaxTokens = 5000,
    [double]$Temperature = 0.0,
    [int]$TimeoutSec = 1800,
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

if ($Mode -eq "check") {
    & ".\scripts\run_ai_claim_report_repair_v0_1.ps1" `
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
    Write-Host "Claim report repair v0.1 attempt $attempt / $($Retries + 1)"
    Write-Host ""

    & ".\scripts\run_ai_claim_report_repair_v0_1.ps1" `
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
