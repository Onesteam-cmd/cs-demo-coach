param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")
pwd

$PythonCmd = "python"
try {
    & $PythonCmd --version | Out-Null
}
catch {
    $PythonCmd = "py"
}

& $PythonCmd ".\backend\package\coach_input_contract_validator_v0_1.py" --match-id $MatchId --player $Player

if (-not $?) {
    throw "coach_input_contract_validator_v0_1 failed"
}
