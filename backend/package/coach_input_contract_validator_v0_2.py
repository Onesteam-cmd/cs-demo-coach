import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


VALIDATOR_VERSION = "coach_input_contract_validator_v0_2"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def path_get(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if is_empty(value):
        return []
    return [value]


def flatten_source_files(source_files: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                new_prefix = f"{prefix}.{k}" if prefix else str(k)
                walk(new_prefix, v)
        elif isinstance(value, str) and value.strip():
            out[prefix] = value

    walk("", source_files)
    return out


def source_path_exists(root: Path, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    p = Path(value)
    if p.is_absolute():
        return p.exists()
    return (root / value).exists()


def find_note_like(obj: Any, max_depth: int = 7) -> Any:
    if max_depth < 0:
        return None

    if isinstance(obj, dict):
        for key in ["final_notes", "final_note", "notes", "closing_notes"]:
            value = obj.get(key)
            if not is_empty(value):
                return value
        for value in obj.values():
            found = find_note_like(value, max_depth - 1)
            if not is_empty(found):
                return found

    elif isinstance(obj, list):
        for item in obj[:60]:
            found = find_note_like(item, max_depth - 1)
            if not is_empty(found):
                return found

    return None


def validate(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    pkg_dir = root / "data" / "package" / match_id
    verdict_dir = root / "data" / "verdict" / match_id
    runs_dir = root / "data" / "runs" / match_id
    cases_dir = root / "data" / "cases" / match_id
    layers_dir = root / "data" / "layers" / match_id

    coach_input_path = pkg_dir / "coach_input_package_current.json"
    match_package_current = pkg_dir / "match_package_current.json"
    coach_brief_current = verdict_dir / "coach_brief_current.json"
    health_current = runs_dir / "product_health_current.json"
    round_cases_current = cases_dir / "round_cases_current.json"
    info_state_current = layers_dir / "canonical_info_state_current.json"

    errors: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    required_files = {
        "coach_input_package_current": coach_input_path,
        "match_package_current": match_package_current,
        "coach_brief_current": coach_brief_current,
        "canonical_info_state_current": info_state_current,
    }

    optional_files = {
        "product_health_current": health_current,
        "round_cases_current": round_cases_current,
    }

    for name, path in required_files.items():
        if not path.exists():
            errors.append(f"MISSING required file: {name} => {rel(path, root)}")

    for name, path in optional_files.items():
        if not path.exists():
            warnings.append(f"optional current file missing: {name} => {rel(path, root)}")

    if errors:
        return {
            "status": "fail",
            "validator": VALIDATOR_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "errors": errors,
            "warnings": warnings,
            "notes": notes,
        }

    coach_input = load_json(coach_input_path)
    info_state = load_json(info_state_current)

    required_top_keys = [
        "meta",
        "source_files",
        "contract_health",
        "overview",
        "coach_priorities",
        "review",
        "evidence_sections",
        "ui_contract",
        "ai_contract",
    ]

    for key in required_top_keys:
        if key not in coach_input:
            errors.append(f"MISSING top-level key: {key}")

    meta_match_id = path_get(coach_input, "meta.match_id")
    meta_player = path_get(coach_input, "meta.player")
    meta_version = path_get(coach_input, "meta.version")
    meta_package_type = path_get(coach_input, "meta.package_type")

    if meta_package_type != "coach_input_package":
        errors.append(f"bad meta.package_type: {meta_package_type}")

    if meta_match_id != match_id:
        errors.append(f"bad meta.match_id: expected {match_id}, got {meta_match_id}")

    if meta_player != player:
        errors.append(f"bad meta.player: expected {player}, got {meta_player}")

    if meta_version != "v0_3":
        errors.append(f"bad coach_input version: expected v0_3, got {meta_version}")

    contract_status = path_get(coach_input, "contract_health.status")
    if is_empty(contract_status):
        errors.append("MISSING contract_health.status")
    elif not str(contract_status).startswith("ok"):
        warnings.append(f"contract_health.status is not ok-like: {contract_status}")

    has_info_state = path_get(coach_input, "contract_health.has_info_state")
    if has_info_state is not True:
        errors.append("contract_health.has_info_state is not true")

    source_info_state = path_get(coach_input, "source_files.layers.canonical_info_state")
    if not source_info_state:
        errors.append("MISSING source_files.layers.canonical_info_state")
    elif not source_path_exists(root, source_info_state):
        errors.append(f"source file does not exist: source_files.layers.canonical_info_state => {source_info_state}")

    primary_diagnosis = path_get(coach_input, "overview.primary_diagnosis")
    coach_priorities = as_list(path_get(coach_input, "coach_priorities"))
    review_rounds = as_list(path_get(coach_input, "overview.review_rounds"))
    top_cases = as_list(path_get(coach_input, "review.top_cases"))
    round_cards = as_list(path_get(coach_input, "review.round_cards"))

    if is_empty(primary_diagnosis):
        warnings.append("overview.primary_diagnosis is empty")

    if len(coach_priorities) == 0:
        errors.append("coach_priorities is empty")

    if len(review_rounds) == 0:
        warnings.append("overview.review_rounds is empty")

    if len(top_cases) == 0:
        warnings.append("review.top_cases is empty")

    if len(round_cards) == 0:
        warnings.append("review.round_cards is empty")

    evidence_sections = path_get(coach_input, "evidence_sections")
    if not isinstance(evidence_sections, dict):
        errors.append("evidence_sections is not an object")
        evidence_sections = {}

    expected_sections = [
        "macro_trade_spacing",
        "info_state",
        "round_impact",
        "plant_phase",
        "mechanics",
        "loss_patterns",
        "utility",
        "combat",
        "phase",
        "advantage_state",
        "area_map",
    ]

    present_sections = []
    ok_sections = []
    missing_sections = []
    missing_status_sections = []

    for section in expected_sections:
        value = evidence_sections.get(section)
        if value is None:
            missing_sections.append(section)
            continue

        present_sections.append(section)
        status = value.get("status") if isinstance(value, dict) else None

        if status == "ok":
            ok_sections.append(section)
        elif status == "missing":
            missing_status_sections.append(section)

    if missing_sections:
        errors.append(f"MISSING evidence_sections keys: {', '.join(missing_sections)}")

    if missing_status_sections:
        warnings.append(f"optional analysis sections marked missing: {', '.join(missing_status_sections)}")

    info_state_section = evidence_sections.get("info_state")
    if not isinstance(info_state_section, dict):
        errors.append("evidence_sections.info_state is not an object")
    else:
        if info_state_section.get("status") != "ok":
            errors.append(f"evidence_sections.info_state.status is not ok: {info_state_section.get('status')}")

        info_summary = info_state_section.get("summary", {})
        if info_summary.get("version") != "canonical_info_state_v0_2":
            errors.append(f"info_state summary version is not canonical_info_state_v0_2: {info_summary.get('version')}")

        if not info_summary.get("observations_total"):
            errors.append("info_state observations_total is empty")

        death_counts = path_get(info_state_section, "coach_relevant_summary.death_context_counts")
        if is_empty(death_counts):
            errors.append("info_state death_context_counts is empty")

    raw_info_summary = info_state.get("summary", {})
    if raw_info_summary.get("version") != "canonical_info_state_v0_2":
        errors.append(f"canonical_info_state_current version is not v0_2: {raw_info_summary.get('version')}")

    raw_observations_total = raw_info_summary.get("observations_total")
    if isinstance(raw_observations_total, int) and raw_observations_total > 10000:
        errors.append(f"canonical_info_state observations_total too high, possible trajectory table leak: {raw_observations_total}")

    ai_layers = as_list(path_get(coach_input, "ai_contract.required_future_layers"))
    if "canonical_info_state_v0_2" not in ai_layers:
        errors.append("ai_contract.required_future_layers lacks canonical_info_state_v0_2")

    if "canonical_info_state_v0_1" in ai_layers:
        warnings.append("ai_contract.required_future_layers still contains old canonical_info_state_v0_1")

    judge_tasks = as_list(path_get(coach_input, "ai_contract.judge_tasks_v0_1"))
    has_info_task = any(
        isinstance(x, dict) and x.get("task_id") == "info_state_review"
        for x in judge_tasks
    )
    if not has_info_task:
        errors.append("ai_contract.judge_tasks_v0_1 lacks info_state_review")

    ui_order = as_list(path_get(coach_input, "ui_contract.recommended_screen_order"))
    if "evidence_sections.info_state" not in ui_order:
        errors.append("ui_contract.recommended_screen_order lacks evidence_sections.info_state")

    flat_sources = flatten_source_files(path_get(coach_input, "source_files"))
    important_sources = [
        "match_package",
        "coach_brief",
        "aliases.match_package_current",
        "aliases.coach_brief_current",
        "layers.canonical_info_state",
    ]

    for source_key in important_sources:
        source_value = flat_sources.get(source_key)
        if not source_value:
            errors.append(f"MISSING source_files.{source_key}")
        elif not source_path_exists(root, source_value):
            errors.append(f"source file does not exist: source_files.{source_key} => {source_value}")

    coach_brief = load_json(coach_brief_current)
    final_notes_value = find_note_like(coach_brief)
    final_notes_text = json.dumps(final_notes_value, ensure_ascii=False) if final_notes_value is not None else ""

    if re.search(r"главн(ый|ая|ое)[^\n\r]{0,240}player_kill_swing", final_notes_text, re.IGNORECASE):
        errors.append("BAD_FINAL_NOTE: final notes still seem to use player_kill_swing as main problem")

    if re.search(r"player_kill_swing\s*=\s*20", final_notes_text, re.IGNORECASE):
        errors.append("BAD_FINAL_NOTE: found player_kill_swing = 20 pattern in final notes")

    notes.append(f"coach_priorities_count={len(coach_priorities)}")
    notes.append(f"review_rounds_count={len(review_rounds)}")
    notes.append(f"top_cases_count={len(top_cases)}")
    notes.append(f"round_cards_count={len(round_cards)}")
    notes.append(f"ok_evidence_sections={len(ok_sections)}/{len(expected_sections)}")
    notes.append(f"info_state_observations_total={raw_info_summary.get('observations_total')}")
    notes.append(f"info_state_death_snapshots_total={raw_info_summary.get('player_death_snapshots_total')}")

    status = "ok" if not errors else "fail"
    if status == "ok" and warnings:
        status = "ok_with_warnings"

    return {
        "status": status,
        "validator": VALIDATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "match_id": match_id,
        "player": player,
        "checked_file": rel(coach_input_path, root),
        "meta_version": meta_version,
        "counts": {
            "coach_priorities": len(coach_priorities),
            "review_rounds": len(review_rounds),
            "top_cases": len(top_cases),
            "round_cards": len(round_cards),
            "expected_sections": len(expected_sections),
            "ok_evidence_sections": len(ok_sections),
            "info_state_observations_total": raw_info_summary.get("observations_total"),
            "info_state_focus_snapshots_total": raw_info_summary.get("focus_snapshots_total"),
            "info_state_player_death_snapshots_total": raw_info_summary.get("player_death_snapshots_total"),
        },
        "sections": {
            "expected": expected_sections,
            "present": present_sections,
            "ok": ok_sections,
            "missing_status": missing_status_sections,
            "missing_keys": missing_sections,
        },
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    root = project_root()
    result = validate(args)

    out_dir = root / "data" / "package" / args.match_id
    out_json = out_dir / f"coach_input_contract_validation_{args.player}_v0_2.json"
    out_current = out_dir / "coach_input_contract_validation_current.json"
    out_csv = out_dir / f"coach_input_contract_validation_{args.player}_v0_2.csv"

    write_json(out_json, result)
    write_json(out_current, result)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": result.get("status")})
        writer.writerow({"key": "match_id", "value": result.get("match_id")})
        writer.writerow({"key": "player", "value": result.get("player")})
        writer.writerow({"key": "meta_version", "value": result.get("meta_version")})
        for k, v in result.get("counts", {}).items():
            writer.writerow({"key": k, "value": str(v)})
        writer.writerow({"key": "errors", "value": " | ".join(result.get("errors", []))})
        writer.writerow({"key": "warnings", "value": " | ".join(result.get("warnings", []))})

    print(json.dumps({
        "status": result.get("status"),
        "validator": VALIDATOR_VERSION,
        "match_id": result.get("match_id"),
        "player": result.get("player"),
        "meta_version": result.get("meta_version"),
        "counts": result.get("counts"),
        "errors": result.get("errors"),
        "warnings": result.get("warnings"),
        "created": {
            "validation_json": rel(out_json, root),
            "validation_current": rel(out_current, root),
            "validation_csv": rel(out_csv, root),
        }
    }, ensure_ascii=False, indent=2))

    if result.get("errors"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
