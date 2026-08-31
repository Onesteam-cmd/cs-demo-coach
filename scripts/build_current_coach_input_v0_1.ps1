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

& $PythonCmd ".\backend\package\coach_input_package_builder_v0_1.py" --match-id $MatchId --player $Player

if ($LASTEXITCODE -ne 0) {
    throw "coach_input_package_builder_v0_1 failed"
}
