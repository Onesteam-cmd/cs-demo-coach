import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ENRICHER_VERSION = "coach_input_info_state_enricher_v0_3"


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


def normalize_info_state(info_state: Dict[str, Any]) -> Dict[str, Any]:
    summary = info_state.get("summary", {}) if isinstance(info_state, dict) else {}
    snapshots = info_state.get("focus_snapshots", []) if isinstance(info_state, dict) else []
    observations = info_state.get("observations", []) if isinstance(info_state, dict) else []

    death_snapshots = [
        s for s in snapshots
        if isinstance(s, dict) and s.get("focus_event_kind") == "player_death"
    ]

    problem_death_snapshots = [
        s for s in death_snapshots
        if s.get("opponent_info_context") in ("stale", "expired", "no_prior_info")
    ]

    actionable_death_snapshots = [
        s for s in death_snapshots
        if s.get("opponent_info_context") in ("fresh", "recent")
    ]

    return {
        "status": "ok",
        "section_type": "canonical_info_state",
        "summary": compact(summary, limit_list=20),
        "coach_relevant_summary": {
            "purpose": "Оценка того, была ли prior-инфа по противнику до ключевого события игрока.",
            "player_death_snapshots_total": len(death_snapshots),
            "death_with_actionable_prior_info": len(actionable_death_snapshots),
            "death_with_stale_or_missing_prior_info": len(problem_death_snapshots),
            "death_context_counts": summary.get("death_opponent_info_context_counts", {}),
            "all_focus_context_counts": summary.get("opponent_info_context_counts", {}),
            "interpretation": (
                "Этот слой не доказывает, что игрок реально услышал/получил колл. "
                "Он показывает, какая инфа могла быть восстановлена из demo events до события."
            )
        },
        "top_death_context_examples": compact(death_snapshots, limit_list=14, limit_dict_keys=70),
        "stale_or_missing_info_death_examples": compact(problem_death_snapshots, limit_list=10, limit_dict_keys=70),
        "actionable_prior_info_death_examples": compact(actionable_death_snapshots, limit_list=10, limit_dict_keys=70),
        "sample_focus_snapshots": compact(snapshots, limit_list=20, limit_dict_keys=70),
        "raw_observations_sample": compact(observations, limit_list=20, limit_dict_keys=50),
    }


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


def enrich(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    pkg_dir = root / "data" / "package" / match_id
    layer_dir = root / "data" / "layers" / match_id

    coach_input_current = pkg_dir / "coach_input_package_current.json"
    info_state_current = layer_dir / "canonical_info_state_current.json"

    if not coach_input_current.exists():
        raise FileNotFoundError(f"MISSING coach input package: {coach_input_current}")

    if not info_state_current.exists():
        raise FileNotFoundError(f"MISSING canonical info state: {info_state_current}")

    coach_input = load_json(coach_input_current)
    info_state = load_json(info_state_current)

    backup_path = pkg_dir / "coach_input_package_before_info_state_v0_3_backup.json"
    shutil.copyfile(coach_input_current, backup_path)

    meta = coach_input.setdefault("meta", {})
    meta["version"] = "v0_3"
    meta["last_enriched_by"] = ENRICHER_VERSION
    meta["last_enriched_at_utc"] = datetime.now(timezone.utc).isoformat()

    source_files = coach_input.setdefault("source_files", {})
    layers = source_files.setdefault("layers", {})
    layers["canonical_info_state"] = rel(info_state_current, root)

    evidence_sections = coach_input.setdefault("evidence_sections", {})
    evidence_sections["info_state"] = normalize_info_state(info_state)

    contract_health = coach_input.setdefault("contract_health", {})
    contract_health["info_state_status"] = "ok"
    contract_health["sections_count"] = len(evidence_sections)
    contract_health["has_info_state"] = True

    ai_contract = coach_input.setdefault("ai_contract", {})

    required_future_layers = ai_contract.get("required_future_layers", [])
    if isinstance(required_future_layers, list):
        required_future_layers = [
            x for x in required_future_layers
            if x != "canonical_info_state_v0_1"
        ]
        if "canonical_info_state_v0_2" not in required_future_layers:
            required_future_layers.insert(0, "canonical_info_state_v0_2")
        ai_contract["required_future_layers"] = required_future_layers

    known_gaps = ai_contract.get("known_gaps_v0_2", [])
    if isinstance(known_gaps, list):
        filtered = [
            x for x in known_gaps
            if "information state is not fully reconstructed" not in str(x).lower()
            and "player information state" not in str(x).lower()
        ]
        filtered.append(
            "canonical_info_state_v0_2 exists, but sound/voice comms are still unavailable and utility is only a low-confidence proxy"
        )
        ai_contract["known_gaps_v0_3"] = filtered

    judge_tasks = ai_contract.get("judge_tasks_v0_1", [])
    if isinstance(judge_tasks, list):
        has_info_task = any(
            isinstance(x, dict) and x.get("task_id") == "info_state_review"
            for x in judge_tasks
        )
        if not has_info_task:
            judge_tasks.append({
                "task_id": "info_state_review",
                "input_sections": [
                    "evidence_sections.info_state",
                    "review.round_cards",
                    "evidence_sections.advantage_state",
                    "evidence_sections.macro_trade_spacing"
                ],
                "output": "explain whether deaths/duels happened with fresh, stale, expired or missing prior info"
            })
        ai_contract["judge_tasks_v0_1"] = judge_tasks

    ui_contract = coach_input.setdefault("ui_contract", {})
    order = ui_contract.get("recommended_screen_order", [])
    if isinstance(order, list):
        order = insert_after(order, "evidence_sections.macro_trade_spacing", "evidence_sections.info_state")
        ui_contract["recommended_screen_order"] = order

    out_versioned = pkg_dir / f"coach_input_package_{player}_v0_3.json"
    out_current = pkg_dir / "coach_input_package_current.json"

    write_json(out_versioned, coach_input)
    write_json(out_current, coach_input)

    index_path = pkg_dir / f"coach_input_package_index_{player}_v0_3.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "version", "value": "v0_3"})
        writer.writerow({"key": "enricher", "value": ENRICHER_VERSION})
        writer.writerow({"key": "versioned_package", "value": rel(out_versioned, root)})
        writer.writerow({"key": "current_package", "value": rel(out_current, root)})
        writer.writerow({"key": "info_state_source", "value": rel(info_state_current, root)})
        writer.writerow({"key": "sections_count", "value": str(len(evidence_sections))})

    info_summary = info_state.get("summary", {}) if isinstance(info_state, dict) else {}

    result = {
        "status": "ok",
        "enricher": ENRICHER_VERSION,
        "match_id": match_id,
        "player": player,
        "coach_input_version": "v0_3",
        "info_state_summary": {
            "version": info_summary.get("version"),
            "observations_total": info_summary.get("observations_total"),
            "focus_snapshots_total": info_summary.get("focus_snapshots_total"),
            "player_death_snapshots_total": info_summary.get("player_death_snapshots_total"),
            "death_opponent_info_context_counts": info_summary.get("death_opponent_info_context_counts"),
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
