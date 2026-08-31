param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [ValidateSet("llm")]
    [string]$Mode = "llm",
    [int]$Retries = 3
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$RetryableStatusCodes = @(429, 500, 502, 503, 504)
$Attempts = @()
$LastJson = $null
$LastRaw = $null

for ($Attempt = 1; $Attempt -le ($Retries + 1); $Attempt++) {
    Write-Host "`n=== v0.6 RU LLM attempt $Attempt / $($Retries + 1) ===`n"

    $Raw = & ".\scripts\run_ai_coach_judge_llm_v0_6_ru.ps1" `
        -MatchId $MatchId `
        -Player $Player `
        -Mode $Mode 2>&1 | Out-String

    $LastRaw = $Raw

    try {
        $JsonStart = $Raw.IndexOf("{")
        if ($JsonStart -lt 0) {
            throw "No JSON object found in runner output."
        }

        $JsonText = $Raw.Substring($JsonStart)
        $Parsed = $JsonText | ConvertFrom-Json
        $LastJson = $Parsed

        $StatusCode = $null
        if ($Parsed.call -and $null -ne $Parsed.call.status_code) {
            $StatusCode = [int]$Parsed.call.status_code
        }

        $Ok = $Parsed.status -eq "ok" -and $Parsed.call.ok -eq $true

        $Attempts += [pscustomobject]@{
            attempt = $Attempt
            status = $Parsed.status
            status_code = $StatusCode
            ok = $Ok
            retryable = $RetryableStatusCodes -contains $StatusCode
        }

        if ($Ok) {
            Write-Host "`n=== RETRY WRAPPER RESULT ===`n"
            [pscustomobject]@{
                status = "ok"
                wrapper = "run_ai_coach_judge_llm_v0_6_ru_retry"
                attempts = $Attempts
                final = $Parsed
            } | ConvertTo-Json -Depth 20
            exit 0
        }

        if (-not ($RetryableStatusCodes -contains $StatusCode)) {
            Write-Host "`n=== RETRY WRAPPER RESULT ===`n"
            [pscustomobject]@{
                status = "error_non_retryable"
                wrapper = "run_ai_coach_judge_llm_v0_6_ru_retry"
                attempts = $Attempts
                final = $Parsed
                raw_tail = $Raw.Substring([Math]::Max(0, $Raw.Length - 1500))
            } | ConvertTo-Json -Depth 20
            exit 1
        }

        if ($Attempt -le $Retries) {
            $Delay = [Math]::Min(3 * $Attempt, 12)
            Write-Host "Retryable error $StatusCode. Waiting $Delay seconds..."
            Start-Sleep -Seconds $Delay
        }
    }
    catch {
        $Attempts += [pscustomobject]@{
            attempt = $Attempt
            status = "parse_error"
            status_code = $null
            ok = $false
            retryable = $true
            error = $_.Exception.Message
        }

        if ($Attempt -le $Retries) {
            Start-Sleep -Seconds ([Math]::Min(3 * $Attempt, 12))
        }
    }
}

Write-Host "`n=== RETRY WRAPPER RESULT ===`n"
[pscustomobject]@{
    status = "error_retry_exhausted"
    wrapper = "run_ai_coach_judge_llm_v0_6_ru_retry"
    attempts = $Attempts
    final = $LastJson
    raw_tail = if ($LastRaw) { $LastRaw.Substring([Math]::Max(0, $LastRaw.Length - 1500)) } else { $null }
} | ConvertTo-Json -Depth 20

exit 1
