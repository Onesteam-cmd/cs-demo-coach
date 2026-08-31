param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location "."
pwd

$PythonCandidates = @(
    ".\.venv\Scripts\python.exe",
    ".\venv\Scripts\python.exe",
    "python"
)

$Py = $null
foreach ($Candidate in $PythonCandidates) {
    if ($Candidate -eq "python") {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) {
            $Py = "python"
            break
        }
    } elseif (Test-Path $Candidate) {
        $Py = $Candidate
        break
    }
}

if (-not $Py) {
    throw "Python не найден. Запусти из того же окружения, где работает analyze_demo.ps1."
}

Write-Host ""
Write-Host "=== 1) Ensure structured analysis v0.2 ==="
& ".\scripts\run_structured_analysis_v0_2.ps1" -MatchId $MatchId -Player $Player -SkipBasePipeline

Write-Host ""
Write-Host "=== 2) Build round casebook ==="
& $Py ".\backend\cases\round_casebook_builder_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Check files ==="
$Files = @(
    ".\data\cases\$MatchId\round_cases_${Player}_v0_1.json",
    ".\data\cases\$MatchId\round_cases_${Player}_v0_1.csv",
    ".\data\reviews\$MatchId\unified_round_review_queue_${Player}_v0_1.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
        throw "Missing output: $File"
    }
}

Write-Host ""
Write-Host "=== ROUND CASEBOOK LAYER COMPLETE ==="
