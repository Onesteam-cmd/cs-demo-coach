from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPECTED_ROUNDS = [2, 3, 4, 8, 9, 11, 14, 15, 16, 17, 19, 20]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def add_issue(issues: List[Dict[str, Any]], severity: str, code: str, message: str, path: str = "") -> None:
    issues.append({
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
    })


def as_int_list(value: Any) -> List[int]:
    result: List[int] = []
    if not isinstance(value, list):
        return result

    for item in value:
        try:
            result.append(int(item))
        except Exception:
            pass

    return result


def validate_claim(
    claim: Any,
    round_num: int,
    claim_ids: Set[str],
    issues: List[Dict[str, Any]],
    claim_index: int,
) -> None:
    path = f"round_reviews[{round_num}].claims[{claim_index}]"

    if not isinstance(claim, dict):
        add_issue(issues, "error", "claim_not_object", "Claim must be an object.", path)
        return

    required_fields = [
        "claim_id",
        "claim_type",
        "claim_text",
        "claim_strength",
        "evidence_refs",
        "evidence_summary",
        "limitations",
        "alternative_explanations",
        "actionability",
        "should_show_to_user",
    ]

    for field in required_fields:
        if field not in claim:
            add_issue(issues, "error", "claim_missing_field", f"Missing field: {field}", f"{path}.{field}")

    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        add_issue(issues, "error", "claim_id_empty", "claim_id must be a non-empty string.", f"{path}.claim_id")
    else:
        if claim_id in claim_ids:
            add_issue(issues, "error", "duplicate_claim_id", f"Duplicate claim_id: {claim_id}", f"{path}.claim_id")
        claim_ids.add(claim_id)

    claim_type = claim.get("claim_type")
    allowed_types = {
        "mechanics",
        "decision",
        "info_state",
        "enemy_intent",
        "trade_spacing",
        "round_impact",
        "training",
    }
    if claim_type not in allowed_types:
        add_issue(issues, "error", "invalid_claim_type", f"Invalid claim_type: {claim_type}", f"{path}.claim_type")

    strength = claim.get("claim_strength")
    allowed_strengths = {
        "supported",
        "limited",
        "hypothesis",
        "unsupported_avoided",
    }
    if strength not in allowed_strengths:
        add_issue(issues, "error", "invalid_claim_strength", f"Invalid claim_strength: {strength}", f"{path}.claim_strength")

    evidence_refs = claim.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        add_issue(issues, "error", "evidence_refs_not_list", "evidence_refs must be a list.", f"{path}.evidence_refs")
    elif strength == "supported" and len(evidence_refs) == 0:
        add_issue(
            issues,
            "error",
            "supported_claim_without_evidence_refs",
            "Supported claim must have non-empty evidence_refs.",
            f"{path}.evidence_refs",
        )

    for list_field in ["evidence_summary", "limitations", "alternative_explanations"]:
        value = claim.get(list_field)
        if not isinstance(value, list):
            add_issue(issues, "error", "claim_list_field_not_list", f"{list_field} must be a list.", f"{path}.{list_field}")
        elif list_field in {"limitations", "alternative_explanations"} and len(value) == 0:
            add_issue(issues, "warning", "claim_list_field_empty", f"{list_field} should not be empty.", f"{path}.{list_field}")

    text = claim.get("claim_text")
    if not isinstance(text, str) or len(text.strip()) < 20:
        add_issue(issues, "warning", "claim_text_too_short", "claim_text looks too short.", f"{path}.claim_text")

    actionability = claim.get("actionability")
    if not isinstance(actionability, str) or len(actionability.strip()) < 20:
        add_issue(issues, "warning", "actionability_too_short", "actionability looks too short.", f"{path}.actionability")

    if not isinstance(claim.get("should_show_to_user"), bool):
        add_issue(issues, "error", "should_show_to_user_not_bool", "should_show_to_user must be boolean.", f"{path}.should_show_to_user")


def validate_report(report: Any, expected_rounds_override: List[int]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    if isinstance(report, dict) and "report" in report and isinstance(report["report"], dict):
        report = report["report"]

    if not isinstance(report, dict):
        add_issue(issues, "error", "report_not_object", "Report root must be an object.")
        return build_result(issues)

    schema_version = report.get("schema_version")
    if schema_version != "ai_coach_judge_report_v0_7_claims_ru":
        add_issue(
            issues,
            "error",
            "invalid_schema_version",
            f"Expected ai_coach_judge_report_v0_7_claims_ru, got {schema_version}",
            "schema_version",
        )

    expected_rounds = expected_rounds_override or as_int_list(report.get("expected_rounds")) or DEFAULT_EXPECTED_ROUNDS

    report_expected_rounds = as_int_list(report.get("expected_rounds"))
    if report_expected_rounds != expected_rounds:
        add_issue(
            issues,
            "error",
            "expected_rounds_mismatch",
            f"expected_rounds mismatch. Expected {expected_rounds}, got {report_expected_rounds}",
            "expected_rounds",
        )

    round_reviews = report.get("round_reviews")
    if not isinstance(round_reviews, list):
        add_issue(issues, "error", "round_reviews_not_list", "round_reviews must be a list.", "round_reviews")
        round_reviews = []

    actual_rounds: List[int] = []

    for idx, rr in enumerate(round_reviews):
        if not isinstance(rr, dict):
            add_issue(issues, "error", "round_review_not_object", "Round review must be an object.", f"round_reviews[{idx}]")
            continue

        try:
            round_num = int(rr.get("round_num"))
            actual_rounds.append(round_num)
        except Exception:
            add_issue(issues, "error", "round_num_invalid", "round_num must be integer.", f"round_reviews[{idx}].round_num")
            continue

        claims = rr.get("claims")
        if not isinstance(claims, list):
            add_issue(issues, "error", "claims_not_list", "claims must be a list.", f"round_reviews[{idx}].claims")
            claims = []

        if len(claims) == 0:
            add_issue(issues, "error", "round_without_claims", "Every round review must have at least one claim.", f"round_reviews[{idx}].claims")

        claim_ids: Set[str] = set()
        for cidx, claim in enumerate(claims):
            validate_claim(claim, round_num, claim_ids, issues, cidx)

        training_note = rr.get("training_note")
        if not isinstance(training_note, str) or len(training_note.strip()) < 20:
            add_issue(issues, "warning", "training_note_too_short", "training_note looks too short.", f"round_reviews[{idx}].training_note")

    duplicate_rounds = sorted({num for num in actual_rounds if actual_rounds.count(num) > 1})
    if duplicate_rounds:
        add_issue(issues, "error", "duplicate_round_reviews", f"Duplicate round_reviews: {duplicate_rounds}", "round_reviews")

    missing_rounds = [num for num in expected_rounds if num not in actual_rounds]
    extra_rounds = [num for num in actual_rounds if num not in expected_rounds]

    if missing_rounds:
        add_issue(issues, "error", "missing_round_reviews", f"Missing round_reviews: {missing_rounds}", "round_reviews")
    if extra_rounds:
        add_issue(issues, "error", "extra_round_reviews", f"Extra round_reviews: {extra_rounds}", "round_reviews")

    coverage = report.get("rounds_coverage")
    if not isinstance(coverage, dict):
        add_issue(issues, "error", "rounds_coverage_missing", "rounds_coverage must be an object.", "rounds_coverage")
    else:
        if int(coverage.get("expected_count", -1)) != len(expected_rounds):
            add_issue(issues, "error", "coverage_expected_count_wrong", "rounds_coverage.expected_count is wrong.", "rounds_coverage.expected_count")
        if int(coverage.get("actual_count", -1)) != len(actual_rounds):
            add_issue(issues, "error", "coverage_actual_count_wrong", "rounds_coverage.actual_count is wrong.", "rounds_coverage.actual_count")
        if as_int_list(coverage.get("missing_rounds")) != missing_rounds:
            add_issue(issues, "error", "coverage_missing_rounds_wrong", "rounds_coverage.missing_rounds is wrong.", "rounds_coverage.missing_rounds")
        if as_int_list(coverage.get("extra_rounds")) != extra_rounds:
            add_issue(issues, "error", "coverage_extra_rounds_wrong", "rounds_coverage.extra_rounds is wrong.", "rounds_coverage.extra_rounds")

    top_priorities = report.get("top_priorities")
    if not isinstance(top_priorities, list) or len(top_priorities) == 0:
        add_issue(issues, "error", "top_priorities_empty", "top_priorities must be a non-empty list.", "top_priorities")

    training_plan = report.get("training_plan")
    if not isinstance(training_plan, dict) or len(training_plan) == 0:
        add_issue(issues, "error", "training_plan_empty", "training_plan must be a non-empty object.", "training_plan")

    uncertainties = report.get("uncertainties")
    if not isinstance(uncertainties, list):
        add_issue(issues, "warning", "uncertainties_not_list", "uncertainties should be a list.", "uncertainties")

    return build_result(issues, expected_rounds=expected_rounds, actual_rounds=actual_rounds)


def build_result(
    issues: List[Dict[str, Any]],
    expected_rounds: List[int] | None = None,
    actual_rounds: List[int] | None = None,
) -> Dict[str, Any]:
    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    info_count = sum(1 for issue in issues if issue["severity"] == "info")

    status = "fail" if error_count else ("warn" if warning_count else "ok")

    return {
        "status": status,
        "validator": "claim_report_contract_validator_v0_1",
        "expected_rounds": expected_rounds or [],
        "actual_rounds": actual_rounds or [],
        "issues_total": len(issues),
        "issues_by_severity": {
            "error": error_count,
            "warning": warning_count,
            "info": info_count,
        },
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--report-path", default="")
    parser.add_argument("--expected-rounds", default="")
    args = parser.parse_args()

    if args.report_path:
        report_path = Path(args.report_path)
        if not report_path.is_absolute():
            report_path = PROJECT_ROOT / report_path
    else:
        report_path = (
            PROJECT_ROOT
            / "data"
            / "ai"
            / args.match_id
            / f"ai_coach_judge_llm_report_{args.player}_v0_7_claims_ru.json"
        )

    if args.expected_rounds.strip():
        expected_rounds = [int(x.strip()) for x in args.expected_rounds.split(",") if x.strip()]
    else:
        expected_rounds = DEFAULT_EXPECTED_ROUNDS

    if not report_path.exists():
        result = build_result([
            {
                "severity": "error",
                "code": "report_file_missing",
                "message": f"Report file not found: {report_path}",
                "path": str(report_path),
            }
        ], expected_rounds=expected_rounds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    report = load_json(report_path)
    result = validate_report(report, expected_rounds)
    result["report_path"] = str(report_path.relative_to(PROJECT_ROOT))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"ok", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
