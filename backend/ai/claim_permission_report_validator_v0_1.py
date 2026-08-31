from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_PERMISSION_TYPES = [
    "bad_duel_choice",
    "info_mistake",
    "mechanical_issue",
    "spacing_issue",
    "postplant_issue",
    "c4_safety_issue",
]
STRENGTH_ORDER = {
    "unsupported_avoided": 0,
    "hypothesis": 1,
    "limited": 2,
    "supported": 3,
}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def add_issue(issues: List[Dict[str, Any]], severity: str, code: str, message: str, path: str = "", details: Optional[Dict[str, Any]] = None) -> None:
    item: Dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
    }
    if details:
        item["details"] = details
    issues.append(item)


def safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def build_permission_map(input_payload: Any) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    if not isinstance(input_payload, dict):
        return out

    cards = input_payload.get("round_cards_for_model")
    if not isinstance(cards, list):
        return out

    for card in cards:
        if not isinstance(card, dict):
            continue
        rn = safe_int(card.get("round_num"))
        if rn is None:
            continue
        permissions = card.get("claim_permissions_v0_8")
        if not isinstance(permissions, dict):
            permissions = {}
        out[rn] = permissions

    return out


def max_strength_allowed(max_claim_strength: Any) -> str:
    value = str(max_claim_strength or "").strip()
    if value in STRENGTH_ORDER:
        return value
    if value in {"allowed", "not_applicable"}:
        return "supported"
    return "unsupported_avoided"


def validate_report_against_permissions(report: Any, permission_map: Dict[int, Dict[str, Any]], require_permission_gate: bool) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    if isinstance(report, dict) and "report" in report and isinstance(report["report"], dict):
        report = report["report"]

    if not isinstance(report, dict):
        add_issue(issues, "error", "report_not_object", "Report root must be an object.")
        return build_result(issues)

    round_reviews = report.get("round_reviews")
    if not isinstance(round_reviews, list):
        add_issue(issues, "error", "round_reviews_not_list", "round_reviews must be a list.", "round_reviews")
        return build_result(issues)

    claims_total = 0
    claims_with_permission_gate = 0
    blocked_permission_claims_total = 0
    cap_violations_total = 0

    for rr_idx, rr in enumerate(round_reviews):
        if not isinstance(rr, dict):
            continue
        rn = safe_int(rr.get("round_num"))
        claims = rr.get("claims")
        if rn is None or not isinstance(claims, list):
            continue

        round_permissions = permission_map.get(rn, {})

        for cidx, claim in enumerate(claims):
            claims_total += 1
            path = f"round_reviews[{rr_idx}].claims[{cidx}]"
            if not isinstance(claim, dict):
                continue

            gate = claim.get("permission_gate")
            if not isinstance(gate, dict):
                if require_permission_gate:
                    add_issue(
                        issues,
                        "error",
                        "missing_permission_gate",
                        "Every v0.8 claim must include permission_gate.",
                        f"{path}.permission_gate",
                    )
                else:
                    add_issue(
                        issues,
                        "warning",
                        "missing_permission_gate",
                        "Claim does not include permission_gate.",
                        f"{path}.permission_gate",
                    )
                continue

            claims_with_permission_gate += 1
            permission_key = str(gate.get("permission_key") or "")
            permission_status = str(gate.get("permission_status") or "")
            claim_strength = str(claim.get("claim_strength") or "")
            should_show = claim.get("should_show_to_user")

            if permission_key == "not_applicable":
                continue

            if permission_key not in REQUIRED_PERMISSION_TYPES:
                add_issue(
                    issues,
                    "error",
                    "invalid_permission_key",
                    f"Invalid permission_key: {permission_key}",
                    f"{path}.permission_gate.permission_key",
                )
                continue

            source_perm = round_permissions.get(permission_key)
            if not isinstance(source_perm, dict):
                add_issue(
                    issues,
                    "error",
                    "permission_key_missing_in_input",
                    f"permission_key {permission_key} is not present in v0.8 input for round {rn}.",
                    f"{path}.permission_gate.permission_key",
                )
                continue

            source_status = str(source_perm.get("status") or "missing")
            source_max = max_strength_allowed(source_perm.get("max_claim_strength"))
            gate_max = max_strength_allowed(gate.get("max_claim_strength"))

            if permission_status and permission_status != source_status:
                add_issue(
                    issues,
                    "error",
                    "permission_status_mismatch",
                    "permission_gate.permission_status must match v0.8 input permission status.",
                    f"{path}.permission_gate.permission_status",
                    {
                        "round_num": rn,
                        "permission_key": permission_key,
                        "gate_status": permission_status,
                        "input_status": source_status,
                    },
                )

            if gate_max != source_max:
                add_issue(
                    issues,
                    "warning",
                    "permission_max_strength_mismatch",
                    "permission_gate.max_claim_strength should match v0.8 input max_claim_strength.",
                    f"{path}.permission_gate.max_claim_strength",
                    {
                        "round_num": rn,
                        "permission_key": permission_key,
                        "gate_max": gate_max,
                        "input_max": source_max,
                    },
                )

            if source_status == "blocked":
                blocked_permission_claims_total += 1
                if claim_strength != "unsupported_avoided" or should_show is not False:
                    add_issue(
                        issues,
                        "error",
                        "blocked_permission_used_as_visible_claim",
                        "Blocked permission cannot be used as visible factual claim.",
                        path,
                        {
                            "round_num": rn,
                            "permission_key": permission_key,
                            "claim_strength": claim_strength,
                            "should_show_to_user": should_show,
                        },
                    )

            if claim_strength not in STRENGTH_ORDER:
                add_issue(
                    issues,
                    "error",
                    "invalid_claim_strength_for_permission_check",
                    f"Invalid claim_strength: {claim_strength}",
                    f"{path}.claim_strength",
                )
                continue

            if STRENGTH_ORDER[claim_strength] > STRENGTH_ORDER[source_max]:
                cap_violations_total += 1
                add_issue(
                    issues,
                    "error",
                    "claim_strength_exceeds_permission_cap",
                    "claim_strength exceeds v0.8 permission max_claim_strength.",
                    f"{path}.claim_strength",
                    {
                        "round_num": rn,
                        "permission_key": permission_key,
                        "claim_strength": claim_strength,
                        "max_claim_strength": source_max,
                    },
                )

            obeyed = gate.get("obeyed")
            if obeyed is not True:
                add_issue(
                    issues,
                    "error",
                    "permission_gate_not_obeyed",
                    "permission_gate.obeyed must be true for accepted v0.8 report.",
                    f"{path}.permission_gate.obeyed",
                )

    result = build_result(issues)
    result.update({
        "claims_total": claims_total,
        "claims_with_permission_gate": claims_with_permission_gate,
        "blocked_permission_claims_total": blocked_permission_claims_total,
        "cap_violations_total": cap_violations_total,
    })
    return result


def build_result(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    info_count = sum(1 for issue in issues if issue["severity"] == "info")
    return {
        "status": "fail" if error_count else ("warn" if warning_count else "ok"),
        "validator": "claim_permission_report_validator_v0_1",
        "issues_total": len(issues),
        "issues_by_severity": {
            "error": error_count,
            "warning": warning_count,
            "info": info_count,
        },
        "issues": issues,
    }


def default_report_path(match_id: str, player: str) -> Path:
    v08 = PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_v0_8_claims_ru.json"
    if v08.exists():
        return v08
    return PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--report-path", default="")
    parser.add_argument("--input-path", default="")
    parser.add_argument("--require-permission-gate", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report_path) if args.report_path else default_report_path(args.match_id, args.player)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path

    input_path = Path(args.input_path) if args.input_path else PROJECT_ROOT / "data" / "ai" / args.match_id / "ai_coach_judge_input_v0_8_current.json"
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path

    if not report_path.exists():
        result = build_result([{
            "severity": "error",
            "code": "report_file_missing",
            "message": f"Report file not found: {report_path}",
            "path": str(report_path),
        }])
        result["report_path"] = rel(report_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    if not input_path.exists():
        result = build_result([{
            "severity": "error",
            "code": "input_file_missing",
            "message": f"v0.8 input file not found: {input_path}",
            "path": str(input_path),
        }])
        result["input_path"] = rel(input_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    report = load_json(report_path)
    input_payload = load_json(input_path)
    permission_map = build_permission_map(input_payload)

    result = validate_report_against_permissions(report, permission_map, require_permission_gate=args.require_permission_gate)
    result["match_id"] = args.match_id
    result["player"] = args.player
    result["report_path"] = rel(report_path)
    result["input_path"] = rel(input_path)
    result["permission_rounds_total"] = len(permission_map)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"ok", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
