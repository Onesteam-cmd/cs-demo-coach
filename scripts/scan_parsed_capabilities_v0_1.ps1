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

        $check = & $candidate -c "import sys; print(sys.executable); import pandas, pyarrow; print('PARQUET_OK')" 2>$null

        if ($check -match "PARQUET_OK") {
            $PythonCmd = $candidate
            break
        }
    }
    catch {
        continue
    }
}

if (-not $PythonCmd) {
    throw "MISSING parquet-capable Python. Need project venv with pandas + pyarrow."
}

Write-Host "Using Python:"
& $PythonCmd -c "import sys; print(sys.executable); import pandas, pyarrow; print('pandas/pyarrow ok')"

& $PythonCmd ".\backend\pipeline\parsed_data_capabilities_scanner_v0_1.py" --match-id $MatchId --player $Player

if (-not $?) {
    throw "parsed_data_capabilities_scanner_v0_1 failed"
}
