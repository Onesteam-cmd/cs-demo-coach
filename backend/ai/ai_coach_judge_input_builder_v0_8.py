from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BUILDER_VERSION = "ai_coach_judge_input_builder_v0_8"
INPUT_VERSION = "ai_coach_judge_input_v0_8"
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def safe_round(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def compact(value: Any, limit_list: int = 8, limit_dict_keys: int = 35, depth: int = 5) -> Any:
    if depth <= 0:
        if isinstance(value, dict):
            return {"_truncated_depth": True, "keys": list(value.keys())[:8]}
        if isinstance(value, list):
            return {"_truncated_depth": True, "items_count": len(value)}
        return value

    if isinstance(value, list):
        out = [compact(x, limit_list, limit_dict_keys, depth - 1) for x in value[:limit_list]]
        if len(value) > limit_list:
            out.append({"_truncated_items": len(value) - limit_list})
        return out

    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= limit_dict_keys:
                out["_truncated_keys"] = len(value) - limit_dict_keys
                break
            out[str(k)] = compact(v, limit_list, limit_dict_keys, depth - 1)
        return out

    return value


def one_by_round(items: List[Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_round(item.get("round_num") or item.get("round") or item.get("round_number"))
        if rn is None:
            continue
        out[rn] = item
    return out


def permission_status_group(permission: Dict[str, Any]) -> str:
    status = str(permission.get("status") or "unknown")
    if status == "allowed":
        return "allowed"
    if status in {"allowed_limited", "allowed_as_hypothesis", "cap_to_limited_or_hypothesis"}:
        return "restricted"
    if status in {"blocked", "limited_or_blocked"}:
        return "blocked_or_weak"
    return "unknown"


def build_permission_summary(permissions: Dict[str, Any]) -> Dict[str, Any]:
    allowed: List[str] = []
    restricted: List[str] = []
    blocked_or_weak: List[str] = []
    missing: List[str] = []

    for claim_type in REQUIRED_PERMISSION_TYPES:
        raw = permissions.get(claim_type)
        if not isinstance(raw, dict):
            missing.append(claim_type)
            continue

        group = permission_status_group(raw)
        if group == "allowed":
            allowed.append(claim_type)
        elif group == "restricted":
            restricted.append(claim_type)
        elif group == "blocked_or_weak":
            blocked_or_weak.append(claim_type)
        else:
            restricted.append(claim_type)

    return {
        "allowed_claim_types": allowed,
        "restricted_claim_types": restricted,
        "blocked_or_weak_claim_types": blocked_or_weak,
        "missing_permission_types": missing,
    }


def extract_claim_permissions(tactical: Dict[str, Any], permission_row: Dict[str, Any]) -> Dict[str, Any]:
    # Prefer dedicated permission file for stable flat schema; fall back to embedded tactical permissions.
    out: Dict[str, Any] = {}

    for claim_type in REQUIRED_PERMISSION_TYPES:
        source = permission_row.get(claim_type)
        if not isinstance(source, dict):
            source = (tactical.get("claim_permissions") or {}).get(claim_type)

        if isinstance(source, dict):
            out[claim_type] = {
                "status": source.get("status"),
                "max_claim_strength": source.get("max_claim_strength"),
                "reason": source.get("reason"),
                "limitations": as_list(source.get("limitations")),
            }
        else:
            out[claim_type] = {
                "status": "missing",
                "max_claim_strength": "unsupported_avoided",
                "reason": "permission source missing for this claim type",
                "limitations": ["do not make this claim unless another explicit evidence section supports it"],
            }

    # Additional tactical permission caps from embedded tactical context.
    embedded = tactical.get("claim_permissions") if isinstance(tactical.get("claim_permissions"), dict) else {}
    for extra_type in ["enemy_intent_claim", "tactical_task_claim", "decision_error_strength_cap"]:
        source = embedded.get(extra_type)
        if isinstance(source, dict):
            out[extra_type] = {
                "status": source.get("status"),
                "max_claim_strength": source.get("max_claim_strength"),
                "reason": source.get("reason"),
                "limitations": as_list(source.get("limitations")),
            }

    return out


def make_tactical_context_for_model(tactical: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "round_phase": compact(tactical.get("round_phase"), limit_list=6, limit_dict_keys=20, depth=4),
        "player_task": compact(tactical.get("player_task"), limit_list=6, limit_dict_keys=20, depth=4),
        "pressure": compact(tactical.get("pressure"), limit_list=8, limit_dict_keys=25, depth=4),
        "alive_state_before_focus": compact(tactical.get("alive_state_before_focus"), limit_list=8, limit_dict_keys=25, depth=4),
        "likely_enemy_zones": compact(tactical.get("likely_enemy_zones", []), limit_list=8, limit_dict_keys=20, depth=4),
        "safe_fallback": compact(tactical.get("safe_fallback"), limit_list=8, limit_dict_keys=25, depth=4),
        "trade_support": compact(tactical.get("trade_support"), limit_list=3, limit_dict_keys=25, depth=4),
        "active_weapon_context": compact(tactical.get("active_weapon_context"), limit_list=6, limit_dict_keys=25, depth=4),
        "postplant_context": compact(tactical.get("postplant_context"), limit_list=6, limit_dict_keys=25, depth=4),
        "limitations": as_list(tactical.get("limitations_v0_1")),
    }


def make_round_instruction(permissions: Dict[str, Any]) -> List[str]:
    instruction = [
        "Перед созданием claim сначала смотри claim_permissions_v0_8.",
        "Если claim type имеет status=blocked, не делай такой вывод как факт; максимум укажи unsupported_avoided/limitation, если это нужно для честности отчёта.",
        "Если max_claim_strength=limited или hypothesis, не повышай claim_strength до supported.",
        "bad_duel_choice можно писать только если permission явно allowed и safe_fallback_confidence поддержан evidence.",
        "trade/spacing issue можно писать limited, если trade layer не доказывает реальный угол или возможность размена.",
        "enemy_intent и tactical_task всегда формулируй как гипотезу, а не как знание мыслей врагов/тиммейтов.",
    ]

    bad_duel = permissions.get("bad_duel_choice") if isinstance(permissions, dict) else None
    if isinstance(bad_duel, dict) and bad_duel.get("status") == "blocked":
        instruction.append("В этом раунде запрещено писать 'плохой выбор дуэли', 'невыгодная дуэль', 'бесплатная смерть' как факт.")

    info = permissions.get("info_mistake") if isinstance(permissions, dict) else None
    if isinstance(info, dict) and info.get("status") == "blocked":
        instruction.append("В этом раунде не называй эпизод ошибкой отсутствия информации, если info_state показывает fresh/recent prior info.")

    return instruction


def add_v08_to_round_card(card: Dict[str, Any], tactical_map: Dict[int, Dict[str, Any]], permission_map: Dict[int, Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    rn = safe_round(card.get("round_num"))
    tactical = tactical_map.get(rn or -1, {})
    permission_row = permission_map.get(rn or -1, {})
    permissions = extract_claim_permissions(tactical, permission_row)
    permission_summary = build_permission_summary(permissions)

    new_card = dict(card)
    new_card["tactical_context_v0_8"] = make_tactical_context_for_model(tactical)
    new_card["claim_permissions_v0_8"] = permissions
    new_card["claim_permission_summary_v0_8"] = permission_summary

    existing = as_list(new_card.get("required_model_behavior_for_this_round"))
    merged = existing + [x for x in make_round_instruction(permissions) if x not in existing]
    new_card["required_model_behavior_for_this_round"] = merged

    row = {
        "round_num": rn,
        "round_phase": permission_row.get("round_phase") or ((tactical.get("round_phase") or {}).get("phase")),
        "pressure_level": permission_row.get("pressure_level") or ((tactical.get("pressure") or {}).get("pressure_level")),
        "player_task_hypothesis": permission_row.get("player_task_hypothesis") or ((tactical.get("player_task") or {}).get("player_task_hypothesis")),
        "safe_fallback_confidence": permission_row.get("safe_fallback_confidence") or ((tactical.get("safe_fallback") or {}).get("safe_fallback_confidence")),
        "trade_support_status": permission_row.get("trade_support_status") or ((tactical.get("trade_support") or {}).get("trade_support_status")),
        "allowed_claim_types": ";".join(permission_summary["allowed_claim_types"]),
        "restricted_claim_types": ";".join(permission_summary["restricted_claim_types"]),
        "blocked_or_weak_claim_types": ";".join(permission_summary["blocked_or_weak_claim_types"]),
        "bad_duel_choice_status": (permissions.get("bad_duel_choice") or {}).get("status"),
        "info_mistake_status": (permissions.get("info_mistake") or {}).get("status"),
        "mechanical_issue_status": (permissions.get("mechanical_issue") or {}).get("status"),
        "spacing_issue_status": (permissions.get("spacing_issue") or {}).get("status"),
        "postplant_issue_status": (permissions.get("postplant_issue") or {}).get("status"),
        "c4_safety_issue_status": (permissions.get("c4_safety_issue") or {}).get("status"),
    }

    return new_card, row


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    ai_dir = root / "data" / "ai" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    base_input_path = ai_dir / "ai_coach_judge_input_current.json"
    tactical_path = analysis_dir / "tactical_context_current.json"
    permissions_path = analysis_dir / "claim_permissions_current.json"

    if not base_input_path.exists():
        raise FileNotFoundError(f"MISSING base AI input: {base_input_path}")
    if not tactical_path.exists():
        raise FileNotFoundError(f"MISSING tactical context: {tactical_path}")
    if not permissions_path.exists():
        raise FileNotFoundError(f"MISSING claim permissions: {permissions_path}")

    base_input = load_json(base_input_path)
    tactical = load_json(tactical_path)
    permissions = load_json(permissions_path)

    round_cards = as_list(base_input.get("round_cards_for_model"))
    if not round_cards:
        raise ValueError("base AI input has no round_cards_for_model")

    tactical_map = one_by_round(as_list(tactical.get("round_contexts")))
    permission_map = one_by_round(as_list(permissions.get("round_permissions")))

    out = dict(base_input)
    out["meta"] = dict(base_input.get("meta") or {})
    out["meta"].update({
        "version": INPUT_VERSION,
        "base_input_version": (base_input.get("meta") or {}).get("version"),
        "builder": BUILDER_VERSION,
        "created_at": utc_now(),
        "match_id": match_id,
        "player": player,
    })

    out["source_files"] = dict(base_input.get("source_files") or {})
    out["source_files"].update({
        "base_ai_input_current": rel(base_input_path, root),
        "tactical_context_current": rel(tactical_path, root),
        "claim_permissions_current": rel(permissions_path, root),
    })

    model_contract = dict(base_input.get("model_contract") or {})
    must_do = as_list(model_contract.get("must_do"))
    must_not_do = as_list(model_contract.get("must_not_do"))

    for item in [
        "перед каждым round claim учитывать tactical_context_v0_8 и claim_permissions_v0_8",
        "соблюдать max_claim_strength из claim_permissions_v0_8",
        "если permission blocked — не делать этот claim как user-facing факт",
        "safe_fallback использовать только как weak proxy, если нет explicit permission",
    ]:
        if item not in must_do:
            must_do.append(item)

    for item in [
        "не писать bad duel choice / невыгодная дуэль / бесплатная смерть без allowed permission и safe fallback evidence",
        "не повышать limited/hypothesis permission до supported claim_strength",
        "не превращать tactical_task_hypothesis в фактическую роль игрока",
    ]:
        if item not in must_not_do:
            must_not_do.append(item)

    model_contract["must_do"] = must_do
    model_contract["must_not_do"] = must_not_do
    model_contract["tactical_context_layer_v0_8"] = {
        "purpose": "adds round phase, inferred player task, pressure, likely enemy zones, safe fallback proxy, and trade support proxy",
        "limits": [
            "no raycast/visibility proof",
            "no voice comms or real player intention",
            "safe fallback is a weak proxy unless permission explicitly allows the claim",
            "trade support does not prove a teammate had a realistic angle",
        ],
    }
    model_contract["claim_permission_layer_v0_8"] = {
        "purpose": "explicitly allow, cap, or block claim types before model generation",
        "required_permission_types": REQUIRED_PERMISSION_TYPES,
        "rule": "permission status and max_claim_strength are binding for the generated report",
    }
    out["model_contract"] = model_contract

    match_context = dict(base_input.get("match_context") or {})
    match_context["tactical_context_summary_v0_8"] = compact(tactical.get("summary"), limit_list=12, limit_dict_keys=50, depth=4)
    match_context["claim_permissions_summary_v0_8"] = compact(permissions.get("summary"), limit_list=12, limit_dict_keys=50, depth=4)
    out["match_context"] = match_context

    new_cards: List[Dict[str, Any]] = []
    index_rows: List[Dict[str, Any]] = []
    missing_tactical_rounds: List[int] = []
    missing_permission_rounds: List[int] = []

    for card in round_cards:
        if not isinstance(card, dict):
            continue
        rn = safe_round(card.get("round_num"))
        if rn is not None and rn not in tactical_map:
            missing_tactical_rounds.append(rn)
        if rn is not None and rn not in permission_map:
            missing_permission_rounds.append(rn)
        new_card, row = add_v08_to_round_card(card, tactical_map, permission_map)
        new_cards.append(new_card)
        index_rows.append(row)

    out["round_cards_for_model"] = new_cards
    out["expected_rounds"] = [safe_round(c.get("round_num")) for c in new_cards if isinstance(c, dict) and safe_round(c.get("round_num")) is not None]
    out["final_instruction"] = (
        str(base_input.get("final_instruction") or "").rstrip()
        + "\n\nV0.8 tactical rule: перед написанием каждого claim проверь tactical_context_v0_8, "
          "claim_permissions_v0_8 и claim_permission_summary_v0_8. "
          "Если claim permission blocked, не формулируй этот вывод как факт. "
          "Если max_claim_strength ограничен limited/hypothesis, не повышай его до supported."
    ).strip()

    out_versioned = ai_dir / f"ai_coach_judge_input_{player}_v0_8.json"
    out_current = ai_dir / "ai_coach_judge_input_v0_8_current.json"
    prompt_preview = ai_dir / f"ai_coach_judge_prompt_preview_{player}_v0_8.txt"
    index_path = ai_dir / f"ai_coach_judge_input_index_{player}_v0_8.csv"

    if out_current.exists():
        backup = ai_dir / f"ai_coach_judge_input_v0_8_current.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(out_current, backup)
    else:
        backup = None

    write_json(out_versioned, out)
    write_json(out_current, out)

    preview = {
        "meta": out.get("meta"),
        "model_contract": out.get("model_contract"),
        "match_context": out.get("match_context"),
        "round_cards_for_model_sample": new_cards[:2],
        "final_instruction": out.get("final_instruction"),
    }
    prompt_preview.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    with index_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "round_num",
            "round_phase",
            "pressure_level",
            "player_task_hypothesis",
            "safe_fallback_confidence",
            "trade_support_status",
            "allowed_claim_types",
            "restricted_claim_types",
            "blocked_or_weak_claim_types",
            "bad_duel_choice_status",
            "info_mistake_status",
            "mechanical_issue_status",
            "spacing_issue_status",
            "postplant_issue_status",
            "c4_safety_issue_status",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(index_rows)

    bad_duel_counts: Dict[str, int] = {}
    claim_type_counts: Dict[str, Dict[str, int]] = {k: {} for k in REQUIRED_PERMISSION_TYPES}
    for row in index_rows:
        bad_status = str(row.get("bad_duel_choice_status") or "missing")
        bad_duel_counts[bad_status] = bad_duel_counts.get(bad_status, 0) + 1
        for claim_type in REQUIRED_PERMISSION_TYPES:
            status = str(row.get(f"{claim_type}_status") or "missing")
            claim_type_counts[claim_type][status] = claim_type_counts[claim_type].get(status, 0) + 1

    return {
        "status": "ok",
        "builder": BUILDER_VERSION,
        "match_id": match_id,
        "player": player,
        "input_version": INPUT_VERSION,
        "round_cards_for_model": len(new_cards),
        "expected_rounds": out["expected_rounds"],
        "missing_tactical_rounds": missing_tactical_rounds,
        "missing_permission_rounds": missing_permission_rounds,
        "bad_duel_choice_permission_counts": bad_duel_counts,
        "claim_type_status_counts": claim_type_counts,
        "created": {
            "versioned_input": rel(out_versioned, root),
            "current_input": rel(out_current, root),
            "prompt_preview": rel(prompt_preview, root),
            "index_csv": rel(index_path, root),
            "backup": rel(backup, root) if backup else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
