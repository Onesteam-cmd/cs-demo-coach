import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BUILDER_VERSION = "coach_input_package_builder_v0_1"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def version_key(path: Path) -> Tuple[Tuple[int, ...], float, str]:
    name = path.name
    m = re.search(r"_v(\d+)(?:_(\d+))?", name)
    if m:
        parts = [int(x) for x in m.groups() if x is not None]
        version = tuple(parts)
    else:
        version = (-1,)
    return version, path.stat().st_mtime, name


def latest_file(directory: Path, pattern: str) -> Optional[Path]:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    if not files:
        return None
    return max(files, key=version_key)


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Optional[Path]) -> Optional[Any]:
    if not path or not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def copy_alias(src: Optional[Path], dst: Path, warnings: List[str]) -> bool:
    if not src or not src.exists():
        warnings.append(f"alias skipped: source missing for {dst.name}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return True


def path_get(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def first_path(obj: Any, paths: List[str]) -> Any:
    for p in paths:
        value = path_get(obj, p)
        if value not in (None, "", [], {}):
            return value
    return None


def find_first_key(obj: Any, names: List[str], max_depth: int = 6) -> Any:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] not in (None, "", [], {}):
                return obj[name]
        for value in obj.values():
            found = find_first_key(value, names, max_depth - 1)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(obj, list):
        for item in obj[:40]:
            found = find_first_key(item, names, max_depth - 1)
            if found not in (None, "", [], {}):
                return found
    return None


def find_first_list(obj: Any, preferred_keys: List[str], max_depth: int = 5) -> Optional[List[Any]]:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for key in preferred_keys:
            value = obj.get(key)
            if isinstance(value, list) and value:
                return value
        for value in obj.values():
            found = find_first_list(value, preferred_keys, max_depth - 1)
            if found:
                return found
    elif isinstance(obj, list) and obj:
        return obj
    return None


def compact(value: Any, limit_list: int = 20, limit_dict_keys: int = 80) -> Any:
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


def compact_analysis(name: str, obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {
            "status": "missing",
            "note": "optional section not found yet"
        }

    summary = find_first_key(obj, ["summary", "health", "meta", "totals"], max_depth=4)
    items = find_first_list(
        obj,
        [
            "top_items",
            "top_cases",
            "priorities",
            "issues",
            "patterns",
            "areas",
            "phases",
            "rounds",
            "events",
            "records",
            "player_focus",
        ],
        max_depth=5,
    )

    return {
        "status": "ok",
        "summary": compact(summary, limit_list=12) if summary is not None else None,
        "sample_or_top_items": compact(items, limit_list=20) if items is not None else None,
    }


def extract_round_cards(round_cases: Any, match_pkg: Any) -> List[Any]:
    candidates = None

    if isinstance(round_cases, dict):
        candidates = first_path(round_cases, [
            "round_cases",
            "cases",
            "rounds",
            "data.round_cases",
            "data.cases",
            "data.rounds",
        ])

    if not isinstance(candidates, list):
        candidates = find_first_list(round_cases, ["round_cases", "cases", "rounds"], max_depth=6)

    if not isinstance(candidates, list) and isinstance(match_pkg, dict):
        candidates = first_path(match_pkg, [
            "rounds.top_cases",
            "top_cases",
            "cases.top_cases",
            "round_cases",
        ])

    if not isinstance(candidates, list):
        return []

    return compact(candidates, limit_list=32)


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    pkg_dir = root / "data" / "package" / match_id
    verdict_dir = root / "data" / "verdict" / match_id
    runs_dir = root / "data" / "runs" / match_id
    cases_dir = root / "data" / "cases" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    warnings: List[str] = []

    package_path = latest_file(pkg_dir, f"match_package_{player}_v*.json")
    brief_path = latest_file(verdict_dir, f"coach_brief_{player}_v*.json")
    health_path = latest_file(runs_dir, f"product_health_{player}_v*.json")
    round_cases_path = latest_file(cases_dir, f"round_cases_{player}_v*.json")

    analysis_specs = {
        "trade_spacing": f"trade_spacing_{player}_v*.json",
        "round_impact": f"round_impact_{player}_v*.json",
        "postplant_retake": f"postplant_retake_{player}_v*.json",
        "mechanics": f"mechanics_problem_{player}_v*.json",
        "loss_patterns": f"loss_patterns_{player}_v*.json",
        "utility": f"utility_value_{player}_v*.json",
        "combat": f"combat_profile_{player}_v*.json",
        "phase": f"phase_profile_{player}_v*.json",
        "advantage": f"advantage_profile_{player}_v*.json",
        "area": f"area_profile_{player}_v*.json",
    }
    analysis_paths = {name: latest_file(analysis_dir, pattern) for name, pattern in analysis_specs.items()}

    required = {
        "match_package": package_path,
        "coach_brief": brief_path,
    }
    for name, path in required.items():
        if path is None:
            raise FileNotFoundError(f"MISSING required source: {name}")

    match_pkg = load_json(package_path)
    coach_brief = load_json(brief_path)
    health = load_json(health_path)
    round_cases = load_json(round_cases_path)
    analysis = {name: load_json(path) for name, path in analysis_paths.items()}

    aliases = {
        "match_package_current": pkg_dir / "match_package_current.json",
        "coach_brief_current": verdict_dir / "coach_brief_current.json",
        "product_health_current": runs_dir / "product_health_current.json",
        "round_cases_current": cases_dir / "round_cases_current.json",
    }

    alias_results = {
        "match_package_current": copy_alias(package_path, aliases["match_package_current"], warnings),
        "coach_brief_current": copy_alias(brief_path, aliases["coach_brief_current"], warnings),
        "product_health_current": copy_alias(health_path, aliases["product_health_current"], warnings),
        "round_cases_current": copy_alias(round_cases_path, aliases["round_cases_current"], warnings),
    }

    diagnosis = first_path(coach_brief, [
        "primary_diagnosis",
        "diagnosis.primary",
        "diagnosis.text",
        "summary.primary_diagnosis",
        "brief.primary_diagnosis",
    ]) or find_first_key(coach_brief, ["primary_diagnosis", "diagnosis"])

    priorities = first_path(coach_brief, [
        "top_priorities",
        "priorities",
        "coach_priorities",
        "summary.top_priorities",
    ]) or find_first_key(coach_brief, ["top_priorities", "priorities", "coach_priorities"])

    review_rounds = first_path(coach_brief, [
        "review_rounds",
        "rounds.review_rounds",
        "summary.review_rounds",
    ]) or find_first_key(coach_brief, ["review_rounds"])

    top_cases = first_path(match_pkg, [
        "rounds.top_cases",
        "top_cases",
        "cases.top_cases",
    ]) or find_first_key(match_pkg, ["top_cases"])

    round_cards = extract_round_cards(round_cases, match_pkg)

    sections = {
        name: compact_analysis(name, obj)
        for name, obj in analysis.items()
    }

    source_files = {
        "match_package": rel(package_path, root),
        "coach_brief": rel(brief_path, root),
        "product_health": rel(health_path, root),
        "round_cases": rel(round_cases_path, root),
        "analysis": {name: rel(path, root) for name, path in analysis_paths.items()},
        "aliases": {name: rel(path, root) for name, path in aliases.items()},
    }

    coach_input = {
        "meta": {
            "package_type": "coach_input_package",
            "version": "v0_1",
            "builder": BUILDER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "purpose": "stable input contract for future UI and AI coach judge",
            "status": "experimental_but_stable_path_names",
        },
        "source_files": source_files,
        "current_aliases_created": alias_results,
        "health": compact(health, limit_list=30) if health is not None else None,
        "header": {
            "match_id": match_id,
            "player": player,
            "latest_match_package": rel(package_path, root),
            "latest_coach_brief": rel(brief_path, root),
        },
        "diagnosis": compact(diagnosis, limit_list=12),
        "priorities": compact(priorities, limit_list=12),
        "review_rounds": compact(review_rounds, limit_list=40),
        "top_cases": compact(top_cases, limit_list=20),
        "round_cards": round_cards,
        "sections": sections,
        "ai_contract": {
            "role": "This package is evidence input for a future AI coach layer, not final model judgement.",
            "model_should_do": [
                "explain practical mistakes using only provided evidence",
                "separate mechanics, macro, utility, phase, area and advantage-state causes",
                "state uncertainty when evidence is incomplete",
                "produce actionable training priorities and review notes"
            ],
            "model_must_not_do": [
                "invent enemy positions, comms, intentions or player knowledge not present in evidence",
                "treat inferred areas/phases as exact truth when confidence is absent",
                "call a mechanics issue real if visibility, flash state or context contradicts it"
            ],
            "future_required_layers": [
                "canonical_info_state_v0_1",
                "enemy_intent_inference_v0_1",
                "mechanics_deep_analyzer_v0_1",
                "decision_context_v0_1",
                "aim_context_v0_1",
                "round_narrative_v0_1",
                "ai_coach_judge_v0_1",
                "ai_judgement_validator_v0_1"
            ],
            "known_gaps_v0_1": [
                "player information state is not fully reconstructed yet",
                "enemy plan/intent is not inferred yet",
                "deep aim/reaction context still depends on available raw view/shot/movement data",
                "area inference can be approximate for mechanics/trade events"
            ]
        }
    }

    out_versioned = pkg_dir / f"coach_input_package_{player}_v0_1.json"
    out_current = pkg_dir / "coach_input_package_current.json"

    write_json(out_versioned, coach_input)
    write_json(out_current, coach_input)

    index_path = pkg_dir / f"coach_input_package_index_{player}_v0_1.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "versioned_package", "value": rel(out_versioned, root)})
        writer.writerow({"key": "current_package", "value": rel(out_current, root)})
        writer.writerow({"key": "warnings_count", "value": str(len(warnings))})
        writer.writerow({"key": "round_cards_count", "value": str(len(round_cards))})
        writer.writerow({"key": "sections_count", "value": str(len(sections))})

    result = {
        "status": "ok",
        "builder": BUILDER_VERSION,
        "match_id": match_id,
        "player": player,
        "created": {
            "coach_input_package": rel(out_versioned, root),
            "coach_input_package_current": rel(out_current, root),
            "coach_input_package_index": rel(index_path, root),
            "match_package_current": rel(aliases["match_package_current"], root),
            "coach_brief_current": rel(aliases["coach_brief_current"], root)
        },
        "source_files": source_files,
        "warnings": warnings,
        "round_cards_count": len(round_cards),
        "sections": list(sections.keys())
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
