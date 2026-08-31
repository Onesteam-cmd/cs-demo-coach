param(
    [string]$Demo = "",
    [string]$MatchId = "example_match",
    [string]$Player = "Player",
    [switch]$SkipBasePipeline
)

$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")
pwd

Write-Host ""
Write-Host "=== Product pipeline ==="

$pipelineParams = @{
    MatchId = $MatchId
    Player = $Player
}

if ($Demo -and $Demo.Trim().Length -gt 0) {
    $pipelineParams["Demo"] = $Demo
}

if ($SkipBasePipeline) {
    $pipelineParams["SkipBasePipeline"] = $true
}

& ".\scripts\run_product_analysis_v0_1.ps1" @pipelineParams
if (-not $?) { throw "run_product_analysis_v0_1.ps1 failed" }

Write-Host ""
Write-Host "=== Current / coach input package v0.2 ==="
& ".\scripts\build_current_coach_input_v0_2.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "build_current_coach_input_v0_2.ps1 failed" }

Write-Host ""
Write-Host "=== Canonical info state v0.2 ==="
& ".\scripts\build_canonical_info_state_v0_2.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "build_canonical_info_state_v0_2.ps1 failed" }

Write-Host ""
Write-Host "=== Enrich coach input with info state v0.3 ==="
& ".\scripts\enrich_coach_input_info_state_v0_3.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "enrich_coach_input_info_state_v0_3.ps1 failed" }

Write-Host ""
Write-Host "=== Enemy intent inference v0.2 ==="
& ".\scripts\build_enemy_intent_v0_2.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "build_enemy_intent_v0_2.ps1 failed" }

Write-Host ""
Write-Host "=== Enrich coach input with enemy intent v0.4 ==="
& ".\scripts\enrich_coach_input_enemy_intent_v0_4.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "enrich_coach_input_enemy_intent_v0_4.ps1 failed" }

Write-Host ""
Write-Host "=== Mechanics deep analyzer v0.1 ==="
& ".\scripts\build_mechanics_deep_v0_1.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "build_mechanics_deep_v0_1.ps1 failed" }

Write-Host ""
Write-Host "=== Enrich coach input with mechanics deep v0.5 ==="
& ".\scripts\enrich_coach_input_mechanics_deep_v0_5.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "enrich_coach_input_mechanics_deep_v0_5.ps1 failed" }

Write-Host ""
Write-Host "=== Decision context v0.1 ==="
& ".\scripts\build_decision_context_v0_1.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "build_decision_context_v0_1.ps1 failed" }

Write-Host ""
Write-Host "=== Enrich coach input with decision context v0.6 ==="
& ".\scripts\enrich_coach_input_decision_context_v0_6.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "enrich_coach_input_decision_context_v0_6.ps1 failed" }

Write-Host ""
Write-Host "=== AI coach judge input v0.1 ==="
& ".\scripts\build_ai_coach_judge_input_v0_1.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "build_ai_coach_judge_input_v0_1.ps1 failed" }

Write-Host ""
Write-Host "=== Enrich coach input with AI judge input v0.7 ==="
& ".\scripts\enrich_coach_input_ai_judge_input_v0_7.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "enrich_coach_input_ai_judge_input_v0_7.ps1 failed" }

Write-Host ""
Write-Host "=== AI coach judge dry-run v0.1 ==="
& ".\scripts\run_ai_coach_judge_dry_run_v0_1.ps1" -MatchId $MatchId -Player $Player
if (-not $?) { throw "run_ai_coach_judge_dry_run_v0_1.ps1 failed" }

Write-Host ""
Write-Host "=== Final smoke check v0.7 + dry-run ==="

$coachInputPath = ".\data\package\$MatchId\coach_input_package_current.json"
$decisionContextPath = ".\data\analysis\$MatchId\decision_context_current.json"
$aiInputPath = ".\data\ai\$MatchId\ai_coach_judge_input_current.json"
$dryRunPath = ".\data\ai\$MatchId\ai_coach_judge_dry_run_current.json"
$dryRunTxtPath = ".\data\ai\$MatchId\ai_coach_judge_dry_run_${Player}_v0_1.txt"
$acceptedJsonPath = ".\data\ai\$MatchId\ai_coach_judge_report_accepted_current.json"
$acceptedMarkdownPath = ".\data\reports\$MatchId\coach_report_accepted_current.md"
$acceptedTextPath = ".\data\reports\$MatchId\coach_report_accepted_current.txt"
$acceptedManifestPath = ".\data\ai\$MatchId\ai_coach_judge_acceptance_manifest_current.json"

$required = @(
    $coachInputPath,
    $decisionContextPath,
    $aiInputPath,
    $dryRunPath,
    $dryRunTxtPath,
    $acceptedJsonPath,
    $acceptedMarkdownPath,
    $acceptedTextPath,
    $acceptedManifestPath
)

foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        throw "MISSING required current file: $path"
    }
}

$coachInput = Get-Content $coachInputPath -Raw -Encoding UTF8 | ConvertFrom-Json
$decisionContext = Get-Content $decisionContextPath -Raw -Encoding UTF8 | ConvertFrom-Json
$aiInput = Get-Content $aiInputPath -Raw -Encoding UTF8 | ConvertFrom-Json
$dryRun = Get-Content $dryRunPath -Raw -Encoding UTF8 | ConvertFrom-Json
$acceptedReport = Get-Content $acceptedJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
$acceptedManifest = Get-Content $acceptedManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($coachInput.meta.version -ne "v0_7") {
    throw "BAD_COACH_INPUT_VERSION: expected v0_7, got $($coachInput.meta.version)"
}

if ($aiInput.meta.version -ne "ai_coach_judge_input_v0_1") {
    throw "BAD_AI_JUDGE_INPUT_VERSION: expected ai_coach_judge_input_v0_1, got $($aiInput.meta.version)"
}

if ($dryRun.meta.version -ne "ai_coach_judge_dry_run_v0_1") {
    throw "BAD_DRY_RUN_VERSION: expected ai_coach_judge_dry_run_v0_1, got $($dryRun.meta.version)"
}

if (@($aiInput.round_cards_for_model).Count -lt 5) {
    throw "AI_JUDGE_INPUT_TOO_SMALL: round_cards_for_model < 5"
}

if (@($dryRun.coach_review.round_reviews).Count -lt 5) {
    throw "DRY_RUN_TOO_SMALL: round_reviews < 5"
}

if ($acceptedManifest.status -ne "accepted") {
    throw "BAD_ACCEPTED_REPORT_STATUS: expected accepted, got $($acceptedManifest.status)"
}

if ($acceptedManifest.accepted_report_version -ne "v0_7_claims_ru_final_v0_1") {
    throw "BAD_ACCEPTED_REPORT_VERSION: expected v0_7_claims_ru_final_v0_1, got $($acceptedManifest.accepted_report_version)"
}

if ($acceptedReport.schema_version -ne "ai_coach_judge_report_v0_7_claims_ru") {
    throw "BAD_ACCEPTED_REPORT_SCHEMA: expected ai_coach_judge_report_v0_7_claims_ru, got $($acceptedReport.schema_version)"
}

if (@($acceptedReport.round_reviews).Count -ne 12) {
    throw "BAD_ACCEPTED_REPORT_ROUND_COUNT: expected 12, got $(@($acceptedReport.round_reviews).Count)"
}

if ($acceptedManifest.acceptance_checks.contract_status -ne "ok") {
    throw "BAD_ACCEPTED_REPORT_CONTRACT_STATUS: expected ok, got $($acceptedManifest.acceptance_checks.contract_status)"
}

if ($acceptedManifest.acceptance_checks.semantic_verifier_status -ne "pass") {
    throw "BAD_ACCEPTED_REPORT_SEMANTIC_STATUS: expected pass, got $($acceptedManifest.acceptance_checks.semantic_verifier_status)"
}

if ($acceptedManifest.acceptance_checks.needs_more_repair -ne $false) {
    throw "BAD_ACCEPTED_REPORT_REPAIR_STATE: needs_more_repair is not false"
}

[pscustomobject]@{
    status = "ok"
    match_id = $coachInput.meta.match_id
    player = $coachInput.meta.player
    coach_input_version = $coachInput.meta.version
    coach_input_current = $coachInputPath
    decision_context_current = $decisionContextPath
    ai_coach_judge_input_current = $aiInputPath
    ai_coach_judge_dry_run_current = $dryRunPath
    ai_coach_judge_dry_run_txt = $dryRunTxtPath
    ai_coach_judge_accepted_json = $acceptedJsonPath
    ai_coach_judge_accepted_markdown = $acceptedMarkdownPath
    ai_coach_judge_accepted_text = $acceptedTextPath
    ai_coach_judge_acceptance_manifest = $acceptedManifestPath
    accepted_report_version = $acceptedManifest.accepted_report_version
    accepted_report_round_reviews = @($acceptedReport.round_reviews).Count
    accepted_report_semantic_status = $acceptedManifest.acceptance_checks.semantic_verifier_status
    evidence_sections_count = @($coachInput.evidence_sections.PSObject.Properties).Count
    decision_context_rounds_total = $decisionContext.summary.rounds_total
    ai_round_cards_for_model = @($aiInput.round_cards_for_model).Count
    dry_run_round_reviews = @($dryRun.coach_review.round_reviews).Count
    dry_run_decision_label_counts = ($dryRun.debug_summary.decision_label_counts | ConvertTo-Json -Compress)
    dry_run_enemy_plan_counts = ($dryRun.debug_summary.enemy_plan_counts | ConvertTo-Json -Compress)
    dry_run_mechanics_flags_total = ($dryRun.debug_summary.mechanics_flags_total | ConvertTo-Json -Compress)
    final_contract = "ok_v0_7_with_ai_judge_input_dry_run_and_accepted_claims_ru_report"
} | Format-List

