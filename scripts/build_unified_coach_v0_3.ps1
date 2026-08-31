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
Write-Host "=== 1) Ensure Macro Layer v0.2 exists ==="
& ".\scripts\build_macro_layer_v0_2.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build Unified Coach Verdict v0.3 ==="
& $Py ".\backend\reports\unified_coach_verdict_v0_3.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Build Dashboard v0.7 ==="
& $Py ".\backend\dashboard\build_dashboard_v0_7.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Open Dashboard v0.7 ==="
$Dashboard = ".\data\dashboard\dashboard_v0_7.html"
if (Test-Path $Dashboard) {
    Start-Process (Resolve-Path $Dashboard)
}

Write-Host ""
Write-Host "=== 5) Check generated files ==="
$Files = @(
    ".\data\reports\$MatchId\unified_coach_verdict_${Player}_v0_3.html",
    ".\data\reports\$MatchId\unified_coach_verdict_${Player}_v0_3.json",
    ".\data\dashboard\dashboard_v0_7.html",
    ".\data\reports\$MatchId\round_macro_${Player}_v0_2.html",
    ".\data\reports\$MatchId\macro_coach_verdict_${Player}_v0_1.html"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
    }
}

Write-Host ""
Write-Host "=== Unified coach layer complete ==="
Write-Host "Dashboard:"
Write-Host "  .\data\dashboard\dashboard_v0_7.html"
Write-Host ""
Write-Host "Unified coach verdict:"
Write-Host "  .\data\reports\$MatchId\unified_coach_verdict_${Player}_v0_3.html"
