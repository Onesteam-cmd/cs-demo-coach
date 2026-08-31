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

Write-Host ""
Write-Host "=== CS Demo Coach Product Pipeline v0.1 ==="
Write-Host "MatchId: $MatchId"
Write-Host "Player:  $Player"

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
    Write-Host "=== 1) Run base parser/report pipeline ==="
    & ".\scripts\analyze_demo.ps1" -Demo $Demo -MatchId $MatchId -Player $Player
} else {
    Write-Host ""
    Write-Host "=== 1) Skip base parser/report pipeline ==="
    Write-Host "Using existing parsed data."
}

Write-Host ""
Write-Host "=== 2) Build full coach brief / match package v0.8 ==="
& ".\scripts\build_coach_brief_v0_1.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 3) Product health check ==="
& $Py ".\backend\pipeline\product_health_check_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Final product files ==="
$Files = @(
    ".\data\package\$MatchId\match_package_${Player}_v0_8.json",
    ".\data\package\$MatchId\match_package_index_${Player}_v0_8.csv",
    ".\data\verdict\$MatchId\coach_brief_${Player}_v0_1.json",
    ".\data\verdict\$MatchId\coach_brief_${Player}_v0_1.csv",
    ".\data\runs\$MatchId\product_health_${Player}_v0_1.json"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
        throw "Missing final product output: $File"
    }
}

Write-Host ""
Write-Host "=== PRODUCT ANALYSIS v0.1 COMPLETE ==="
Write-Host "Main package:"
Write-Host "  .\data\package\$MatchId\match_package_${Player}_v0_8.json"
Write-Host ""
Write-Host "Coach brief:"
Write-Host "  .\data\verdict\$MatchId\coach_brief_${Player}_v0_1.json"
Write-Host ""
Write-Host "Health:"
Write-Host "  .\data\runs\$MatchId\product_health_${Player}_v0_1.json"
