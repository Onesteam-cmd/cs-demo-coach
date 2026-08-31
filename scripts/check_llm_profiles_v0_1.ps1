param(
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

$pythonCandidates = @(
    ".\.venv\Scripts\python.exe",
    ".\venv\Scripts\python.exe",
    "python",
    "py"
)

$pythonExe = $null

foreach ($candidate in $pythonCandidates) {
    try {
        if ($candidate -like ".\*") {
            if (Test-Path $candidate) {
                $pythonExe = $candidate
                break
            }
        } else {
            $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($null -ne $cmd) {
                $pythonExe = $candidate
                break
            }
        }
    } catch {
        continue
    }
}

if ($null -eq $pythonExe) {
    throw "Python executable not found. Checked: $($pythonCandidates -join ', ')"
}

& $pythonExe "backend\ai\llm_profiles_checker_v0_1.py"
