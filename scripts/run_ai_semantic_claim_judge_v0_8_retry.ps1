param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [ValidateSet("check", "llm")]
    [string]$Mode = "llm",
    [int]$MaxTokens = 12000,
    [double]$Temperature = 0.0,
    [int]$TimeoutSec = 1800,
    [int]$Attempts = 2,
    [int]$SleepSec = 8,
    [switch]$PreferCompatV07,
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$lastError = $null

for ($i = 1; $i -le $Attempts; $i++) {
    try {
        if ($PreferCompatV07) {
            & "$PSScriptRoot\run_ai_semantic_claim_judge_v0_8.ps1" `
                -MatchId $MatchId `
                -Player $Player `
                -Mode $Mode `
                -MaxTokens $MaxTokens `
                -Temperature $Temperature `
                -TimeoutSec $TimeoutSec `
                -PreferCompatV07 `
                -ProjectRoot $ProjectRoot
        } else {
            & "$PSScriptRoot\run_ai_semantic_claim_judge_v0_8.ps1" `
                -MatchId $MatchId `
                -Player $Player `
                -Mode $Mode `
                -MaxTokens $MaxTokens `
                -Temperature $Temperature `
                -TimeoutSec $TimeoutSec `
                -ProjectRoot $ProjectRoot
        }

        if ($LASTEXITCODE -eq 0) {
            exit 0
        }

        $lastError = "Exit code $LASTEXITCODE"
    } catch {
        $lastError = $_.Exception.Message
    }

    if ($i -lt $Attempts) {
        Start-Sleep -Seconds $SleepSec
    }
}

throw "v0.8 semantic claim judge failed after $Attempts attempt(s): $lastError"
