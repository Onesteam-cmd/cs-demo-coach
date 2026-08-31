param(
    [string]$Demo = "",
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [switch]$SkipBasePipeline
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

if (-not $SkipBasePipeline) {
    if ([string]::IsNullOrWhiteSpace($Demo)) {
        throw "Demo is required when SkipBasePipeline is not set."
    }

    if (-not (Test-Path $Demo)) {
        throw "Demo file not found: $Demo"
    }

    if ([string]::IsNullOrWhiteSpace($MatchId)) {
        $MatchId = [System.IO.Path]::GetFileNameWithoutExtension($Demo)
    }

    Write-Host ""
    Write-Host "=== 1) Run legacy stable base pipeline ==="
    & ".\scripts\analyze_demo.ps1" -Demo $Demo -MatchId $MatchId -Player $Player
} else {
    Write-Host ""
    Write-Host "=== 1) Skip legacy base pipeline ==="
    Write-Host "Using existing parsed/reported data for MatchId=$MatchId Player=$Player"
}

Write-Host ""
Write-Host "=== 2) Build coach action plan v0.2 ==="
& ".\scripts\build_coach_action_plan_v0_2.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 3) Build structured analysis manifest v0.2 ==="
& $Py ".\backend\pipeline\structured_analysis_manifest_v0_2.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Final check ==="
$Files = @(
    ".\data\runs\$MatchId\structured_analysis_manifest_${Player}_v0_2.json",
    ".\data\layers\$MatchId\canonical_mechanics_events_${Player}_v0_1.json",
    ".\data\analysis\$MatchId\mechanics_problem_${Player}_v0_1.json",
    ".\data\verdict\$MatchId\evidence_priority_${Player}_v0_2.json",
    ".\data\verdict\$MatchId\coach_priority_${Player}_v0_3.json",
    ".\data\verdict\$MatchId\coach_action_plan_${Player}_v0_2.json",
    ".\data\reviews\$MatchId\coach_round_review_queue_${Player}_v0_2.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
        throw "Missing final output: $File"
    }
}

Write-Host ""
Write-Host "=== STRUCTURED ANALYSIS v0.2 COMPLETE ==="
Write-Host "Manifest:"
Write-Host "  .\data\runs\$MatchId\structured_analysis_manifest_${Player}_v0_2.json"
Write-Host ""
Write-Host "Coach action plan:"
Write-Host "  .\data\verdict\$MatchId\coach_action_plan_${Player}_v0_2.json"
Write-Host ""
Write-Host "Round review queue:"
Write-Host "  .\data\reviews\$MatchId\coach_round_review_queue_${Player}_v0_2.csv"
