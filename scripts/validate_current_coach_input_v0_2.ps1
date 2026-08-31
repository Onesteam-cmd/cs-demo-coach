param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")
pwd

$candidates = @(
    ".\.venv\Scripts\python.exe",
    ".\venv\Scripts\python.exe",
    ".\backend\.venv\Scripts\python.exe",
    "python",
    "py"
)

$PythonCmd = $null

foreach ($candidate in $candidates) {
    try {
        if ($candidate.EndsWith(".exe")) {
            if (-not (Test-Path $candidate)) {
                continue
            }
        }

        & $candidate --version | Out-Null
        $PythonCmd = $candidate
        break
    }
    catch {
        continue
    }
}

if (-not $PythonCmd) {
    throw "MISSING Python"
}

& $PythonCmd ".\backend\package\coach_input_contract_validator_v0_2.py" --match-id $MatchId --player $Player

if (-not $?) {
    throw "coach_input_contract_validator_v0_2 failed"
}
