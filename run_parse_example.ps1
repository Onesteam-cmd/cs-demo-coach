param(
    [Parameter(Mandatory=$true)]
    [string]$DemoPath
)

$ErrorActionPreference = "Stop"
Set-Location "."
.\.venv\Scripts\python.exe .\backend\parser_core\parse_demo.py "$DemoPath"
