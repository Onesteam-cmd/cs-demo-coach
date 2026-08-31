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
    try {
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
    } catch {}
}

if (-not $Py) {
    throw "Python не найден. Запусти из того же окружения, где работает analyze_demo.ps1."
}

Write-Host ""
Write-Host "=== 1) Build Round Macro Analyzer v0.1 ==="
& $Py ".\backend\analyzers\round_macro_analyzer_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 2) Build Dashboard v0.5 ==="
& $Py ".\backend\dashboard\build_dashboard_v0_5.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Open Dashboard v0.5 ==="
$Dashboard = ".\data\dashboard\dashboard_v0_5.html"
if (Test-Path $Dashboard) {
    Start-Process (Resolve-Path $Dashboard)
}

Write-Host ""
Write-Host "=== 4) Check generated files ==="
Get-ChildItem `
    ".\data\reports\$MatchId\round_macro_${Player}_v0_1.html", `
    ".\data\reports\$MatchId\round_macro_${Player}_v0_1.json", `
    ".\data\reviews\$MatchId\macro_review_${Player}_v0_1.csv", `
    ".\data\dashboard\dashboard_v0_5.html" |
    Select-Object FullName, Length, LastWriteTime

Write-Host ""
Write-Host "=== Macro layer complete ==="
Write-Host "Dashboard:"
Write-Host "  .\data\dashboard\dashboard_v0_5.html"
Write-Host ""
Write-Host "Macro report:"
Write-Host "  .\data\reports\$MatchId\round_macro_${Player}_v0_1.html"
Write-Host ""
Write-Host "Manual macro queue:"
Write-Host "  .\data\reviews\$MatchId\macro_review_${Player}_v0_1.csv"
