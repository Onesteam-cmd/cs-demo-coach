from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

EXPECTED_VERSION = "ai_coach_judge_input_v0_8"
REQUIRED_PERMISSION_TYPES = [
    "bad_duel_choice",
    "info_mistake",
    "mechanical_issue",
    "spacing_issue",
    "postplant_issue",
    "c4_safety_issue",
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_round(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def validate(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    path = root / "data" / "ai" / args.match_id / "ai_coach_judge_input_v0_8_current.json"
    if not path.exists():
        return {
            "status": "error",
            "reason": "missing_v0_8_current_input",
            "expected_path": rel(path, root),
        }

    data = load_json(path)
    issues: List[Dict[str, Any]] = []

    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        issues.append({"path": "meta", "issue": "missing_or_not_object"})
    elif meta.get("version") != EXPECTED_VERSION:
        issues.append({"path": "meta.version", "expected": EXPECTED_VERSION, "actual": meta.get("version")})

    source_files = data.get("source_files") if isinstance(data, dict) else None
    if not isinstance(source_files, dict):
        issues.append({"path": "source_files", "issue": "missing_or_not_object"})
    else:
        for key in ["base_ai_input_current", "tactical_context_current", "claim_permissions_current"]:
            if not source_files.get(key):
                issues.append({"path": f"source_files.{key}", "issue": "missing"})

    model_contract = data.get("model_contract") if isinstance(data, dict) else None
    if not isinstance(model_contract, dict):
        issues.append({"path": "model_contract", "issue": "missing_or_not_object"})
    else:
        for key in ["tactical_context_layer_v0_8", "claim_permission_layer_v0_8"]:
            if key not in model_contract:
                issues.append({"path": f"model_contract.{key}", "issue": "missing"})

    match_context = data.get("match_context") if isinstance(data, dict) else None
    if not isinstance(match_context, dict):
        issues.append({"path": "match_context", "issue": "missing_or_not_object"})
    else:
        for key in ["tactical_context_summary_v0_8", "claim_permissions_summary_v0_8"]:
            if key not in match_context:
                issues.append({"path": f"match_context.{key}", "issue": "missing"})

    cards = data.get("round_cards_for_model") if isinstance(data, dict) else None
    if not isinstance(cards, list) or not cards:
        issues.append({"path": "round_cards_for_model", "issue": "missing_or_empty"})
        cards = []

    expected_rounds = []
    bad_duel_counts: Dict[str, int] = {}
    permission_status_counts: Dict[str, Dict[str, int]] = {k: {} for k in REQUIRED_PERMISSION_TYPES}

    for idx, card in enumerate(cards):
        if not isinstance(card, dict):
            issues.append({"path": f"round_cards_for_model[{idx}]", "issue": "not_object"})
            continue

        rn = safe_round(card.get("round_num"))
        expected_rounds.append(rn)

        if "tactical_context_v0_8" not in card:
            issues.append({"path": f"round_cards_for_model[{idx}].tactical_context_v0_8", "round_num": rn, "issue": "missing"})
        if "claim_permissions_v0_8" not in card:
            issues.append({"path": f"round_cards_for_model[{idx}].claim_permissions_v0_8", "round_num": rn, "issue": "missing"})
            continue

        perms = card.get("claim_permissions_v0_8")
        if not isinstance(perms, dict):
            issues.append({"path": f"round_cards_for_model[{idx}].claim_permissions_v0_8", "round_num": rn, "issue": "not_object"})
            continue

        for claim_type in REQUIRED_PERMISSION_TYPES:
            item = perms.get(claim_type)
            if not isinstance(item, dict):
                issues.append({"path": f"round_cards_for_model[{idx}].claim_permissions_v0_8.{claim_type}", "round_num": rn, "issue": "missing_or_not_object"})
                continue
            status = str(item.get("status") or "missing")
            permission_status_counts[claim_type][status] = permission_status_counts[claim_type].get(status, 0) + 1
            if not item.get("max_claim_strength"):
                issues.append({"path": f"round_cards_for_model[{idx}].claim_permissions_v0_8.{claim_type}.max_claim_strength", "round_num": rn, "issue": "missing"})

        bad_status = str((perms.get("bad_duel_choice") or {}).get("status") or "missing")
        bad_duel_counts[bad_status] = bad_duel_counts.get(bad_status, 0) + 1

        instruction_text = "\n".join(str(x) for x in card.get("required_model_behavior_for_this_round", []))
        if "claim_permissions_v0_8" not in instruction_text:
            issues.append({"path": f"round_cards_for_model[{idx}].required_model_behavior_for_this_round", "round_num": rn, "issue": "missing_v0_8_instruction"})

    if len(cards) != 12:
        issues.append({"path": "round_cards_for_model", "expected_count": 12, "actual_count": len(cards)})

    return {
        "status": "ok" if not issues else "error",
        "validator": "ai_coach_judge_input_contract_validator_v0_8",
        "match_id": args.match_id,
        "player": args.player,
        "input_path": rel(path, root),
        "input_version": (meta or {}).get("version") if isinstance(meta, dict) else None,
        "round_cards_for_model": len(cards),
        "expected_rounds": expected_rounds,
        "issues_total": len(issues),
        "issues": issues,
        "bad_duel_choice_permission_counts": bad_duel_counts,
        "permission_status_counts": permission_status_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = validate(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
