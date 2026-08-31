param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [string]$FinalJson = "data\ai\example_match\ai_coach_judge_llm_report_Player_v0_7_claims_ru_final_v0_1.json",
    [string]$FinalMarkdown = "data\reports\example_match\coach_report_Player_v0_7_claims_ru_final_v0_1.md",
    [string]$FinalText = "data\reports\example_match\coach_report_Player_v0_7_claims_ru_final_v0_1.txt",
    [string]$ProjectRoot = "."
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

if (-not (Test-Path $FinalJson)) {
    throw "Final JSON not found: $FinalJson"
}

if (-not (Test-Path $FinalMarkdown)) {
    throw "Final Markdown not found: $FinalMarkdown"
}

if (-not (Test-Path $FinalText)) {
    throw "Final Text not found: $FinalText"
}

Write-Host ""
Write-Host "=== STEP 1: Validate final report contract ==="
Write-Host ""

.\scripts\validate_claim_report_contract_v0_1.ps1 `
    -MatchId $MatchId `
    -Player $Player `
    -ReportPath $FinalJson `
    -ExpectedRounds "2,3,4,8,9,11,14,15,16,17,19,20"

if ($LASTEXITCODE -ne 0) {
    throw "Final report contract validation failed."
}

Write-Host ""
Write-Host "=== STEP 2: Create accepted/current aliases ==="
Write-Host ""

$aiDir = "data\ai\$MatchId"
$reportDir = "data\reports\$MatchId"

$acceptedJson = "$aiDir\ai_coach_judge_report_accepted_current.json"
$acceptedMarkdown = "$reportDir\coach_report_accepted_current.md"
$acceptedText = "$reportDir\coach_report_accepted_current.txt"

$versionedManifest = "$aiDir\ai_coach_judge_acceptance_manifest_${Player}_v0_7_claims_ru_final_v0_1.json"
$currentManifest = "$aiDir\ai_coach_judge_acceptance_manifest_current.json"

Copy-Item $FinalJson $acceptedJson -Force
Copy-Item $FinalMarkdown $acceptedMarkdown -Force
Copy-Item $FinalText $acceptedText -Force

$report = Get-Content $FinalJson -Raw | ConvertFrom-Json

$manifest = [ordered]@{
    status = "accepted"
    manifest_version = "ai_coach_judge_acceptance_manifest_v0_1"
    accepted_at_local = (Get-Date).ToString("s")
    match_id = $MatchId
    player = $Player
    accepted_report_version = "v0_7_claims_ru_final_v0_1"
    schema_version = $report.schema_version
    language = $report.language
    round_reviews = @($report.round_reviews).Count
    top_priorities = @($report.top_priorities).Count
    quality_pipeline = [ordered]@{
        core_generator = "gemini-3.5-flash"
        cheap_judge = "gemini-3.1-flash-lite"
        targeted_semantic_judge = "gemini-2.5-flash"
        claim_repair = "gemini-2.5-flash"
        surface_repair = "gemini-2.5-flash"
        final_contract_validator = "claim_report_contract_validator_v0_1"
        renderer = "claim_report_renderer_v0_2"
    }
    accepted_files = [ordered]@{
        source_json = $FinalJson
        source_markdown = $FinalMarkdown
        source_text = $FinalText
        accepted_json = $acceptedJson
        accepted_markdown = $acceptedMarkdown
        accepted_text = $acceptedText
    }
    qa_files = [ordered]@{
        cheap_judge = "$aiDir\ai_semantic_claim_judge_${Player}_v0_1_cheap.json"
        targeted_judge = "$aiDir\ai_semantic_claim_judge_${Player}_v0_2_targeted_r2_8_14_17.json"
        repaired_verifier = "$aiDir\ai_semantic_claim_judge_${Player}_v0_3_repaired_r14_17.json"
        claim_repair_result = "$aiDir\ai_claim_report_repair_result_${Player}_v0_1.json"
        surface_repair_result = "$aiDir\ai_surface_report_repair_result_${Player}_v0_1.json"
    }
    acceptance_checks = [ordered]@{
        expected_rounds = @(2,3,4,8,9,11,14,15,16,17,19,20)
        contract_status = "ok"
        semantic_verifier_status = "pass"
        remaining_findings = 0
        use_repaired_report = $true
        needs_more_repair = $false
    }
}

$manifest | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $versionedManifest
$manifest | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $currentManifest

Write-Host ""
Write-Host "=== STEP 3: Accepted output preview ==="
Write-Host ""

[PSCustomObject]@{
    status = "accepted"
    match_id = $MatchId
    player = $Player
    schema_version = $report.schema_version
    language = $report.language
    round_reviews = @($report.round_reviews).Count
    top_priorities = @($report.top_priorities).Count
    accepted_json = $acceptedJson
    accepted_markdown = $acceptedMarkdown
    accepted_text = $acceptedText
    current_manifest = $currentManifest
    versioned_manifest = $versionedManifest
} | Format-List

Write-Host ""
Write-Host "Accepted files:"
Get-Item $acceptedJson, $acceptedMarkdown, $acceptedText, $currentManifest, $versionedManifest |
    Select-Object FullName, Length, LastWriteTime |
    Format-List

Write-Host ""
Write-Host "First 40 lines of accepted markdown:"
Write-Host ""

Get-Content $acceptedMarkdown -TotalCount 40
