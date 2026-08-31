import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ENRICHER_VERSION = "coach_input_mechanics_deep_enricher_v0_5"


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


def normalize_mechanics_deep(mechanics_deep: Dict[str, Any]) -> Dict[str, Any]:
    summary = mechanics_deep.get("summary", {}) if isinstance(mechanics_deep, dict) else {}
    events = mechanics_deep.get("deep_events", []) if isinstance(mechanics_deep, dict) else []

    high_conf = [
        x for x in events
        if isinstance(x, dict) and x.get("deep_confidence") == "high"
    ]

    actionable = [
        x for x in events
        if isinstance(x, dict)
        and x.get("deep_confidence") in ("medium", "high")
        and x.get("deep_label") != "context_only"
    ]

    movement_events = [
        x for x in events
        if isinstance(x, dict)
        and "movement_risk_at_contact" in (x.get("deep_flags") or [])
    ]

    aim_offset_events = [
        x for x in events
        if isinstance(x, dict)
        and (
            "large_crosshair_offset" in (x.get("deep_flags") or [])
            or "moderate_crosshair_offset" in (x.get("deep_flags") or [])
        )
    ]

    no_response_events = [
        x for x in events
        if isinstance(x, dict)
        and "no_shot_response_near_event" in (x.get("deep_flags") or [])
    ]

    visibility_limited_events = [
        x for x in events
        if isinstance(x, dict)
        and "visibility_flash_context_missing_or_limited" in (x.get("deep_flags") or [])
    ]

    return {
        "status": "ok",
        "section_type": "mechanics_deep_analyzer",
        "summary": compact(summary, limit_list=20),
        "coach_relevant_summary": {
            "purpose": "Контекст aim/reaction/movement по mechanics events: view yaw/pitch, speed, shots, combat link.",
            "events_total": summary.get("events_total"),
            "deep_actionable_events_total": summary.get("deep_actionable_events_total"),
            "deep_label_counts": summary.get("deep_label_counts", {}),
            "deep_confidence_counts": summary.get("deep_confidence_counts", {}),
            "deep_flag_counts": summary.get("deep_flag_counts", {}),
            "speed_band_counts": summary.get("speed_band_counts", {}),
            "yaw_error_band_counts": summary.get("yaw_error_band_counts", {}),
            "critical_caution": (
                "visibility/flash context is limited or missing, so this section should support coach reasoning, "
                "not produce absolute visibility verdicts."
            ),
        },
        "top_examples": compact(summary.get("top_examples", []), limit_list=15, limit_dict_keys=80),
        "actionable_deep_events_sample": compact(actionable, limit_list=20, limit_dict_keys=90),
        "high_confidence_events_sample": compact(high_conf, limit_list=16, limit_dict_keys=90),
        "movement_context_events_sample": compact(movement_events, limit_list=16, limit_dict_keys=90),
        "aim_offset_events_sample": compact(aim_offset_events, limit_list=12, limit_dict_keys=90),
        "no_response_events_sample": compact(no_response_events, limit_list=12, limit_dict_keys=90),
        "visibility_limited_events_sample": compact(visibility_limited_events, limit_list=8, limit_dict_keys=70),
    }


def enrich(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    pkg_dir = root / "data" / "package" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    coach_input_current = pkg_dir / "coach_input_package_current.json"
    mechanics_deep_current = analysis_dir / "mechanics_deep_current.json"

    if not coach_input_current.exists():
        raise FileNotFoundError(f"MISSING coach input package: {coach_input_current}")

    if not mechanics_deep_current.exists():
        raise FileNotFoundError(f"MISSING mechanics deep current: {mechanics_deep_current}")

    coach_input = load_json(coach_input_current)
    mechanics_deep = load_json(mechanics_deep_current)

    backup_path = pkg_dir / "coach_input_package_before_mechanics_deep_v0_5_backup.json"
    shutil.copyfile(coach_input_current, backup_path)

    meta = coach_input.setdefault("meta", {})
    meta["version"] = "v0_5"
    meta["last_enriched_by"] = ENRICHER_VERSION
    meta["last_enriched_at_utc"] = datetime.now(timezone.utc).isoformat()

    source_files = coach_input.setdefault("source_files", {})
    analysis_sources = source_files.setdefault("analysis", {})
    analysis_sources["mechanics_deep"] = rel(mechanics_deep_current, root)

    evidence_sections = coach_input.setdefault("evidence_sections", {})
    evidence_sections["mechanics_deep"] = normalize_mechanics_deep(mechanics_deep)

    contract_health = coach_input.setdefault("contract_health", {})
    contract_health["mechanics_deep_status"] = "ok"
    contract_health["has_mechanics_deep"] = True
    contract_health["sections_count"] = len(evidence_sections)

    ai_contract = coach_input.setdefault("ai_contract", {})

    required_future_layers = ai_contract.get("required_future_layers", [])
    if isinstance(required_future_layers, list):
        required_future_layers = [
            x for x in required_future_layers
            if x != "mechanics_deep_analyzer_v0_1"
        ]
        if "mechanics_deep_analyzer_v0_1" not in required_future_layers:
            required_future_layers.insert(2, "mechanics_deep_analyzer_v0_1")
        ai_contract["required_future_layers"] = required_future_layers

    known_gaps = ai_contract.get("known_gaps_v0_4", ai_contract.get("known_gaps_v0_3", ai_contract.get("known_gaps_v0_2", [])))
    if isinstance(known_gaps, list):
        filtered = [
            x for x in known_gaps
            if "deep aim/reaction context still depends" not in str(x).lower()
        ]
        filtered.append(
            "mechanics_deep_analyzer_v0_1 exists, but full visibility/raycast and reliable flash/blind context are not available yet"
        )
        ai_contract["known_gaps_v0_5"] = filtered

    judge_tasks = ai_contract.get("judge_tasks_v0_1", [])
    if isinstance(judge_tasks, list):
        has_task = any(
            isinstance(x, dict) and x.get("task_id") == "mechanics_deep_review"
            for x in judge_tasks
        )
        if not has_task:
            judge_tasks.append({
                "task_id": "mechanics_deep_review",
                "input_sections": [
                    "evidence_sections.mechanics_deep",
                    "evidence_sections.mechanics",
                    "evidence_sections.info_state",
                    "review.round_cards"
                ],
                "output": "separate aim, movement, reaction/no-response and timing context while respecting visibility limitations"
            })
        ai_contract["judge_tasks_v0_1"] = judge_tasks

    ui_contract = coach_input.setdefault("ui_contract", {})
    order = ui_contract.get("recommended_screen_order", [])
    if isinstance(order, list):
        order = insert_after(order, "evidence_sections.mechanics", "evidence_sections.mechanics_deep")
        ui_contract["recommended_screen_order"] = order

    out_versioned = pkg_dir / f"coach_input_package_{player}_v0_5.json"
    out_current = pkg_dir / "coach_input_package_current.json"

    write_json(out_versioned, coach_input)
    write_json(out_current, coach_input)

    index_path = pkg_dir / f"coach_input_package_index_{player}_v0_5.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "version", "value": "v0_5"})
        writer.writerow({"key": "enricher", "value": ENRICHER_VERSION})
        writer.writerow({"key": "versioned_package", "value": rel(out_versioned, root)})
        writer.writerow({"key": "current_package", "value": rel(out_current, root)})
        writer.writerow({"key": "mechanics_deep_source", "value": rel(mechanics_deep_current, root)})
        writer.writerow({"key": "sections_count", "value": str(len(evidence_sections))})

    summary = mechanics_deep.get("summary", {}) if isinstance(mechanics_deep, dict) else {}

    result = {
        "status": "ok",
        "enricher": ENRICHER_VERSION,
        "match_id": match_id,
        "player": player,
        "coach_input_version": "v0_5",
        "mechanics_deep_summary": {
            "version": summary.get("version"),
            "events_total": summary.get("events_total"),
            "deep_actionable_events_total": summary.get("deep_actionable_events_total"),
            "deep_label_counts": summary.get("deep_label_counts"),
            "deep_confidence_counts": summary.get("deep_confidence_counts"),
            "speed_band_counts": summary.get("speed_band_counts"),
            "yaw_error_band_counts": summary.get("yaw_error_band_counts"),
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
