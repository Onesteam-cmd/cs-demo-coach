import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ENRICHER_VERSION = "coach_input_enemy_intent_enricher_v0_4"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


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


def compact(value: Any, limit_list: int = 24, limit_dict_keys: int = 90) -> Any:
    if isinstance(value, list):
        return [compact(x, limit_list, limit_dict_keys) for x in value[:limit_list]]
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= limit_dict_keys:
                out["_truncated_keys"] = len(value) - limit_dict_keys
                break
            out[k] = compact(v, limit_list, limit_dict_keys)
        return out
    return value


def insert_after(items: List[str], after_value: str, new_value: str) -> List[str]:
    if new_value in items:
        return items
    out = []
    inserted = False
    for item in items:
        out.append(item)
        if item == after_value:
            out.append(new_value)
            inserted = True
    if not inserted:
        out.append(new_value)
    return out


def normalize_enemy_intent(enemy_intent: Dict[str, Any]) -> Dict[str, Any]:
    summary = enemy_intent.get("summary", {}) if isinstance(enemy_intent, dict) else {}
    round_intents = enemy_intent.get("round_intents", []) if isinstance(enemy_intent, dict) else []

    low_conf = [
        x for x in round_intents
        if isinstance(x, dict) and x.get("confidence") == "low"
    ]

    medium_high = [
        x for x in round_intents
        if isinstance(x, dict) and x.get("confidence") in ("medium", "high")
    ]

    flagged = [
        x for x in round_intents
        if isinstance(x, dict) and x.get("reasoning_quality_flags")
    ]

    review_sorted = sorted(
        [x for x in round_intents if isinstance(x, dict)],
        key=lambda x: (x.get("review_weight") or 0, x.get("metrics", {}).get("events_total") or 0),
        reverse=True
    )

    return {
        "status": "ok",
        "section_type": "enemy_intent_inference",
        "summary": compact(summary, limit_list=20),
        "coach_relevant_summary": {
            "purpose": "Гипотеза о плане врагов по observable demo events: plant, контакты, utility, зоны, фазы.",
            "rounds_total": summary.get("rounds_total"),
            "plan_counts": summary.get("plan_counts", {}),
            "plan_family_counts": summary.get("plan_family_counts", {}),
            "confidence_counts": summary.get("confidence_counts", {}),
            "quality_flag_counts": summary.get("quality_flag_counts", {}),
            "medium_or_high_confidence_rounds": summary.get("medium_or_high_confidence_rounds", []),
            "interpretation": (
                "Это не знание реальных мыслей/коллов врагов. "
                "Это conservative hypothesis layer, который должен помогать ИИ-тренеру объяснять контекст раунда."
            )
        },
        "top_review_rounds": compact(summary.get("top_review_rounds", []), limit_list=12, limit_dict_keys=70),
        "round_intents_sample": compact(review_sorted, limit_list=22, limit_dict_keys=80),
        "flagged_low_quality_rounds": compact(flagged, limit_list=12, limit_dict_keys=70),
        "low_confidence_rounds": compact(low_conf, limit_list=12, limit_dict_keys=70),
        "medium_or_high_confidence_rounds_sample": compact(medium_high, limit_list=18, limit_dict_keys=70),
    }


def enrich(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    pkg_dir = root / "data" / "package" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    coach_input_current = pkg_dir / "coach_input_package_current.json"
    enemy_intent_current = analysis_dir / "enemy_intent_current.json"

    if not coach_input_current.exists():
        raise FileNotFoundError(f"MISSING coach input package: {coach_input_current}")

    if not enemy_intent_current.exists():
        raise FileNotFoundError(f"MISSING enemy intent current: {enemy_intent_current}")

    coach_input = load_json(coach_input_current)
    enemy_intent = load_json(enemy_intent_current)

    backup_path = pkg_dir / "coach_input_package_before_enemy_intent_v0_4_backup.json"
    shutil.copyfile(coach_input_current, backup_path)

    meta = coach_input.setdefault("meta", {})
    meta["version"] = "v0_4"
    meta["last_enriched_by"] = ENRICHER_VERSION
    meta["last_enriched_at_utc"] = datetime.now(timezone.utc).isoformat()

    source_files = coach_input.setdefault("source_files", {})
    analysis_sources = source_files.setdefault("analysis", {})
    analysis_sources["enemy_intent"] = rel(enemy_intent_current, root)

    evidence_sections = coach_input.setdefault("evidence_sections", {})
    evidence_sections["enemy_intent"] = normalize_enemy_intent(enemy_intent)

    contract_health = coach_input.setdefault("contract_health", {})
    contract_health["enemy_intent_status"] = "ok"
    contract_health["has_enemy_intent"] = True
    contract_health["sections_count"] = len(evidence_sections)

    ai_contract = coach_input.setdefault("ai_contract", {})

    required_future_layers = ai_contract.get("required_future_layers", [])
    if isinstance(required_future_layers, list):
        required_future_layers = [
            x for x in required_future_layers
            if x != "enemy_intent_inference_v0_1"
        ]
        if "enemy_intent_inference_v0_2" not in required_future_layers:
            required_future_layers.insert(1, "enemy_intent_inference_v0_2")
        ai_contract["required_future_layers"] = required_future_layers

    known_gaps = ai_contract.get("known_gaps_v0_3", ai_contract.get("known_gaps_v0_2", []))
    if isinstance(known_gaps, list):
        filtered = [
            x for x in known_gaps
            if "enemy plan/intent is not inferred" not in str(x).lower()
        ]
        filtered.append(
            "enemy_intent_inference_v0_2 exists, but it is a conservative hypothesis layer and does not know enemy voice comms"
        )
        ai_contract["known_gaps_v0_4"] = filtered

    judge_tasks = ai_contract.get("judge_tasks_v0_1", [])
    if isinstance(judge_tasks, list):
        has_task = any(
            isinstance(x, dict) and x.get("task_id") == "enemy_intent_review"
            for x in judge_tasks
        )
        if not has_task:
            judge_tasks.append({
                "task_id": "enemy_intent_review",
                "input_sections": [
                    "evidence_sections.enemy_intent",
                    "evidence_sections.info_state",
                    "review.round_cards",
                    "evidence_sections.phase",
                    "evidence_sections.area_map",
                    "evidence_sections.utility"
                ],
                "output": "explain the likely enemy plan and how the player's decision fit or failed against that plan"
            })
        ai_contract["judge_tasks_v0_1"] = judge_tasks

    ui_contract = coach_input.setdefault("ui_contract", {})
    order = ui_contract.get("recommended_screen_order", [])
    if isinstance(order, list):
        order = insert_after(order, "evidence_sections.info_state", "evidence_sections.enemy_intent")
        ui_contract["recommended_screen_order"] = order

    out_versioned = pkg_dir / f"coach_input_package_{player}_v0_4.json"
    out_current = pkg_dir / "coach_input_package_current.json"

    write_json(out_versioned, coach_input)
    write_json(out_current, coach_input)

    index_path = pkg_dir / f"coach_input_package_index_{player}_v0_4.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "version", "value": "v0_4"})
        writer.writerow({"key": "enricher", "value": ENRICHER_VERSION})
        writer.writerow({"key": "versioned_package", "value": rel(out_versioned, root)})
        writer.writerow({"key": "current_package", "value": rel(out_current, root)})
        writer.writerow({"key": "enemy_intent_source", "value": rel(enemy_intent_current, root)})
        writer.writerow({"key": "sections_count", "value": str(len(evidence_sections))})

    summary = enemy_intent.get("summary", {}) if isinstance(enemy_intent, dict) else {}

    result = {
        "status": "ok",
        "enricher": ENRICHER_VERSION,
        "match_id": match_id,
        "player": player,
        "coach_input_version": "v0_4",
        "enemy_intent_summary": {
            "version": summary.get("version"),
            "rounds_total": summary.get("rounds_total"),
            "plan_counts": summary.get("plan_counts"),
            "confidence_counts": summary.get("confidence_counts"),
            "quality_flag_counts": summary.get("quality_flag_counts"),
        },
        "created": {
            "versioned_package": rel(out_versioned, root),
            "current_package": rel(out_current, root),
            "index": rel(index_path, root),
            "backup": rel(backup_path, root),
        }
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = enrich(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
