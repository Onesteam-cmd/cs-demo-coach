param(
    [Parameter(Mandatory = $true)]
    [string]$Demo,

    [string]$MatchId = "",

    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location "."
pwd

if (-not (Test-Path $Demo)) {
    throw "Demo file not found: $Demo"
}

if ([string]::IsNullOrWhiteSpace($MatchId)) {
    $MatchId = [System.IO.Path]::GetFileNameWithoutExtension($Demo)
}

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
    throw "Python не найден. Запусти из того же окружения, где работает старый analyze_demo.ps1."
}

Write-Host ""
Write-Host "=== CS Demo Coach full launcher v0.4 ==="
Write-Host "Demo:    $Demo"
Write-Host "MatchId: $MatchId"
Write-Host "Player:  $Player"

Write-Host ""
Write-Host "=== 1) Run stable base pipeline ==="
& ".\scripts\analyze_demo.ps1" -Demo $Demo -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build Round Macro Analyzer v0.2 ==="
& $Py ".\backend\analyzers\round_macro_analyzer_v0_2.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Build Macro Coach Verdict v0.1 ==="
& $Py ".\backend\reports\macro_coach_verdict_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Build Unified Coach Verdict v0.3 ==="
& $Py ".\backend\reports\unified_coach_verdict_v0_3.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 5) Build Dashboard v0.6/v0.7 ==="
& $Py ".\backend\dashboard\build_dashboard_v0_6.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

& $Py ".\backend\dashboard\build_dashboard_v0_7.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 6) Open Dashboard v0.7 ==="
$Dashboard = ".\data\dashboard\dashboard_v0_7.html"
if (Test-Path $Dashboard) {
    Start-Process (Resolve-Path $Dashboard)
}

Write-Host ""
Write-Host "=== 7) Check final files ==="
$Files = @(
    ".\data\dashboard\dashboard_v0_7.html",
    ".\data\reports\$MatchId\unified_coach_verdict_${Player}_v0_3.html",
    ".\data\reports\$MatchId\round_macro_${Player}_v0_2.html",
    ".\data\reports\$MatchId\macro_coach_verdict_${Player}_v0_1.html",
    ".\data\reviews\$MatchId\macro_review_${Player}_v0_2.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
    }
}

Write-Host ""
Write-Host "=== FULL LAUNCHER v0.4 COMPLETE ==="
Write-Host "Dashboard:"
Write-Host "  .\data\dashboard\dashboard_v0_7.html"
Write-Host ""
Write-Host "Unified coach verdict:"
Write-Host "  .\data\reports\$MatchId\unified_coach_verdict_${Player}_v0_3.html"
Write-Host ""
Write-Host "Round macro:"
Write-Host "  .\data\reports\$MatchId\round_macro_${Player}_v0_2.html"
