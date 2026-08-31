param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

$pythonCmd = $null
foreach ($candidate in @("python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        $pythonCmd = $candidate
        break
    }
}

if (-not $pythonCmd) {
    throw "Python не найден в PATH. Нужен python или py."
}

& $pythonCmd ".\backend\ai\ai_coach_judge_input_builder_v0_8.py" `
    --match-id $MatchId `
    --player $Player

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
