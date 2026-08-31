import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ENRICHER_VERSION = "coach_input_decision_context_enricher_v0_6"


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


def normalize_decision_context(decision_context: Dict[str, Any]) -> Dict[str, Any]:
    summary = decision_context.get("summary", {}) if isinstance(decision_context, dict) else {}
    rounds = decision_context.get("decision_rounds", []) if isinstance(decision_context, dict) else []

    top_review = summary.get("top_review_rounds", [])
    high_conf = [x for x in rounds if isinstance(x, dict) and x.get("decision_confidence") == "high"]
    medium_conf = [x for x in rounds if isinstance(x, dict) and x.get("decision_confidence") == "medium"]

    return {
        "status": "ok",
        "section_type": "decision_context",
        "summary": compact(summary, limit_list=20),
        "coach_relevant_summary": {
            "purpose": "Раундовый мост между info_state, enemy_intent, mechanics_deep и round review.",
            "rounds_total": summary.get("rounds_total"),
            "decision_label_counts": summary.get("decision_label_counts", {}),
            "decision_confidence_counts": summary.get("decision_confidence_counts", {}),
            "interpretation": (
                "Это главный вход для будущего AI coach judge: он связывает, что игрок мог знать, "
                "какой был вероятный план врага, что произошло механически и почему раунд важен для review."
            )
        },
        "top_review_rounds": compact(top_review, limit_list=12, limit_dict_keys=90),
        "high_confidence_rounds_sample": compact(high_conf, limit_list=12, limit_dict_keys=90),
        "medium_confidence_rounds_sample": compact(medium_conf, limit_list=16, limit_dict_keys=90),
        "decision_rounds_sample": compact(rounds, limit_list=22, limit_dict_keys=90),
    }


def enrich(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    pkg_dir = root / "data" / "package" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    coach_input_current = pkg_dir / "coach_input_package_current.json"
    decision_context_current = analysis_dir / "decision_context_current.json"

    if not coach_input_current.exists():
        raise FileNotFoundError(f"MISSING coach input package: {coach_input_current}")

    if not decision_context_current.exists():
        raise FileNotFoundError(f"MISSING decision context current: {decision_context_current}")

    coach_input = load_json(coach_input_current)
    decision_context = load_json(decision_context_current)

    backup_path = pkg_dir / "coach_input_package_before_decision_context_v0_6_backup.json"
    shutil.copyfile(coach_input_current, backup_path)

    meta = coach_input.setdefault("meta", {})
    meta["version"] = "v0_6"
    meta["last_enriched_by"] = ENRICHER_VERSION
    meta["last_enriched_at_utc"] = datetime.now(timezone.utc).isoformat()

    source_files = coach_input.setdefault("source_files", {})
    analysis_sources = source_files.setdefault("analysis", {})
    analysis_sources["decision_context"] = rel(decision_context_current, root)

    evidence_sections = coach_input.setdefault("evidence_sections", {})
    evidence_sections["decision_context"] = normalize_decision_context(decision_context)

    contract_health = coach_input.setdefault("contract_health", {})
    contract_health["decision_context_status"] = "ok"
    contract_health["has_decision_context"] = True
    contract_health["sections_count"] = len(evidence_sections)

    ai_contract = coach_input.setdefault("ai_contract", {})
    layers = ai_contract.get("required_future_layers", [])
    if isinstance(layers, list) and "decision_context_v0_1" not in layers:
        layers.insert(3, "decision_context_v0_1")
        ai_contract["required_future_layers"] = layers

    tasks = ai_contract.get("judge_tasks_v0_1", [])
    if isinstance(tasks, list):
        has_task = any(isinstance(x, dict) and x.get("task_id") == "decision_context_review" for x in tasks)
        if not has_task:
            tasks.append({
                "task_id": "decision_context_review",
                "input_sections": [
                    "evidence_sections.decision_context",
                    "evidence_sections.info_state",
                    "evidence_sections.enemy_intent",
                    "evidence_sections.mechanics_deep",
                    "review.round_cards"
                ],
                "output": "produce grounded round-level coach explanations without inventing comms, visibility, or enemy intent beyond evidence"
            })
        ai_contract["judge_tasks_v0_1"] = tasks

    known_gaps = ai_contract.get("known_gaps_v0_5", [])
    if isinstance(known_gaps, list):
        known_gaps.append(
            "decision_context_v0_1 exists, but it still depends on inferred enemy intent and limited visibility/flash data"
        )
        ai_contract["known_gaps_v0_6"] = known_gaps

    ui_contract = coach_input.setdefault("ui_contract", {})
    order = ui_contract.get("recommended_screen_order", [])
    if isinstance(order, list):
        order = insert_after(order, "evidence_sections.enemy_intent", "evidence_sections.decision_context")
        ui_contract["recommended_screen_order"] = order

    out_versioned = pkg_dir / f"coach_input_package_{player}_v0_6.json"
    out_current = pkg_dir / "coach_input_package_current.json"
    write_json(out_versioned, coach_input)
    write_json(out_current, coach_input)

    index_path = pkg_dir / f"coach_input_package_index_{player}_v0_6.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "version", "value": "v0_6"})
        writer.writerow({"key": "enricher", "value": ENRICHER_VERSION})
        writer.writerow({"key": "versioned_package", "value": rel(out_versioned, root)})
        writer.writerow({"key": "current_package", "value": rel(out_current, root)})
        writer.writerow({"key": "decision_context_source", "value": rel(decision_context_current, root)})
        writer.writerow({"key": "sections_count", "value": str(len(evidence_sections))})

    summary = decision_context.get("summary", {}) if isinstance(decision_context, dict) else {}

    return {
        "status": "ok",
        "enricher": ENRICHER_VERSION,
        "match_id": match_id,
        "player": player,
        "coach_input_version": "v0_6",
        "decision_context_summary": {
            "version": summary.get("version"),
            "rounds_total": summary.get("rounds_total"),
            "decision_label_counts": summary.get("decision_label_counts"),
            "decision_confidence_counts": summary.get("decision_confidence_counts"),
        },
        "created": {
            "versioned_package": rel(out_versioned, root),
            "current_package": rel(out_current, root),
            "index": rel(index_path, root),
            "backup": rel(backup_path, root),
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = enrich(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
