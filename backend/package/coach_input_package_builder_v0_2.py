import argparse
import csv
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BUILDER_VERSION = "coach_input_package_builder_v0_2"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def version_key(path: Path) -> Tuple[Tuple[int, ...], float, str]:
    name = path.name
    m = re.search(r"_v(\d+)(?:_(\d+))?", name)
    if m:
        version = tuple(int(x) for x in m.groups() if x is not None)
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


def is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


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
        if not is_empty(value):
            return value
    return None


def find_first_key(obj: Any, names: List[str], max_depth: int = 6) -> Any:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        for name in names:
            if name in obj and not is_empty(obj[name]):
                return obj[name]
        for value in obj.values():
            found = find_first_key(value, names, max_depth - 1)
            if not is_empty(found):
                return found
    elif isinstance(obj, list):
        for item in obj[:60]:
            found = find_first_key(item, names, max_depth - 1)
            if not is_empty(found):
                return found
    return None


def find_first_list(obj: Any, preferred_keys: List[str], max_depth: int = 6) -> Optional[List[Any]]:
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


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if is_empty(value):
        return []
    return [value]


def pick(d: Any, keys: List[str], default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and not is_empty(d[k]):
            return d[k]
    return default


def normalize_priority(item: Any, idx: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "rank": idx + 1,
            "title": str(item),
            "raw": item
        }

    return {
        "rank": idx + 1,
        "title": pick(item, ["title", "name", "priority", "label", "cluster_title"], "untitled_priority"),
        "area": pick(item, ["area", "category", "group", "domain", "section"], "unknown"),
        "tier": pick(item, ["tier", "level"], None),
        "score": pick(item, ["score", "priority_score", "problem_score"], None),
        "confidence": pick(item, ["confidence", "confidence_level"], None),
        "evidence_count": pick(item, ["evidence_count", "evidence_total", "events_count"], None),
        "review_rounds": pick(item, ["review_rounds", "rounds", "round_nums"], []),
        "action": pick(item, ["action", "recommendation", "training_focus", "next_step"], None),
        "raw": compact(item, limit_list=12, limit_dict_keys=40),
    }


def normalize_case(item: Any, idx: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "rank": idx + 1,
            "raw": item
        }

    return {
        "rank": idx + 1,
        "round_num": pick(item, ["round_num", "round", "round_number"], None),
        "label": pick(item, ["label", "case_label", "primary_label"], None),
        "result": pick(item, ["result", "player_round_result", "round_result"], None),
        "score": pick(item, ["score", "case_score", "problem_score", "priority_score"], None),
        "phase": pick(item, ["phase", "main_phase", "problem_phase"], None),
        "area": pick(item, ["area", "place", "main_area", "problem_area"], None),
        "why_review": pick(item, ["why_review", "reason", "review_reason", "summary"], None),
        "raw": compact(item, limit_list=12, limit_dict_keys=55),
    }


def normalize_round_card(item: Any, idx: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "rank": idx + 1,
            "raw": item
        }

    return {
        "rank": idx + 1,
        "round_num": pick(item, ["round_num", "round", "round_number"], None),
        "result": pick(item, ["result", "player_round_result", "round_result"], None),
        "label": pick(item, ["label", "case_label", "primary_label"], None),
        "score": pick(item, ["score", "case_score", "problem_score", "impact_score"], None),
        "main_problem": pick(item, ["main_problem", "primary_problem", "problem", "summary"], None),
        "review_reason": pick(item, ["review_reason", "why_review", "reason"], None),
        "mechanics": pick(item, ["mechanics", "mechanics_summary"], None),
        "macro_trade": pick(item, ["trade_spacing", "trade", "macro"], None),
        "utility": pick(item, ["utility", "utility_summary"], None),
        "plant_phase": pick(item, ["plant_phase", "postplant_retake"], None),
        "raw": compact(item, limit_list=18, limit_dict_keys=70),
    }


def compact_analysis(obj: Any, preferred_keys: List[str]) -> Dict[str, Any]:
    if obj is None:
        return {
            "status": "missing",
            "summary": None,
            "top_items": [],
            "raw_sample": None
        }

    summary = find_first_key(obj, ["summary", "health", "meta", "totals", "overview"], max_depth=5)
    items = find_first_list(obj, preferred_keys, max_depth=6)

    return {
        "status": "ok",
        "summary": compact(summary, limit_list=16) if summary is not None else None,
        "top_items": compact(items, limit_list=24) if items is not None else [],
        "raw_sample": compact(obj, limit_list=6, limit_dict_keys=30),
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

    return [normalize_round_card(x, i) for i, x in enumerate(candidates[:40])]


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
        "macro_trade_spacing": f"trade_spacing_{player}_v*.json",
        "round_impact": f"round_impact_{player}_v*.json",
        "plant_phase": f"postplant_retake_{player}_v*.json",
        "mechanics": f"mechanics_problem_{player}_v*.json",
        "loss_patterns": f"loss_patterns_{player}_v*.json",
        "utility": f"utility_value_{player}_v*.json",
        "combat": f"combat_profile_{player}_v*.json",
        "phase": f"phase_profile_{player}_v*.json",
        "advantage_state": f"advantage_profile_{player}_v*.json",
        "area_map": f"area_profile_{player}_v*.json",
    }

    analysis_paths = {
        name: latest_file(analysis_dir, pattern)
        for name, pattern in analysis_specs.items()
    }

    if package_path is None:
        raise FileNotFoundError("MISSING required source: latest match_package json")
    if brief_path is None:
        raise FileNotFoundError("MISSING required source: latest coach_brief json")

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

    priorities_raw = first_path(coach_brief, [
        "top_priorities",
        "priorities",
        "coach_priorities",
        "summary.top_priorities",
    ]) or find_first_key(coach_brief, ["top_priorities", "priorities", "coach_priorities"])

    priorities = [
        normalize_priority(x, i)
        for i, x in enumerate(as_list(priorities_raw)[:12])
    ]

    review_rounds = first_path(coach_brief, [
        "review_rounds",
        "rounds.review_rounds",
        "summary.review_rounds",
    ]) or find_first_key(coach_brief, ["review_rounds"])

    top_cases_raw = first_path(match_pkg, [
        "rounds.top_cases",
        "top_cases",
        "cases.top_cases",
    ]) or find_first_key(match_pkg, ["top_cases"])

    top_cases = [
        normalize_case(x, i)
        for i, x in enumerate(as_list(top_cases_raw)[:20])
    ]

    round_cards = extract_round_cards(round_cases, match_pkg)

    section_keys = {
        "macro_trade_spacing": ["issues", "events", "player_focus", "rounds", "records"],
        "round_impact": ["rounds", "issues", "top_rounds", "records"],
        "plant_phase": ["rounds", "issues", "plant_rounds", "records"],
        "mechanics": ["issues", "root_causes", "events", "records"],
        "loss_patterns": ["patterns", "loss_patterns", "rounds", "records"],
        "utility": ["issues", "events", "rounds", "records"],
        "combat": ["rounds", "weapons", "events", "records"],
        "phase": ["phases", "rounds", "events", "records"],
        "advantage_state": ["swing_events", "events", "issues", "records"],
        "area_map": ["areas", "events", "problem_areas", "records"],
    }

    sections = {
        name: compact_analysis(obj, section_keys[name])
        for name, obj in analysis.items()
    }

    health_status = None
    if isinstance(health, dict):
        health_status = health.get("status")

    source_files = {
        "match_package": rel(package_path, root),
        "coach_brief": rel(brief_path, root),
        "product_health": rel(health_path, root),
        "round_cases": rel(round_cases_path, root),
        "analysis": {name: rel(path, root) for name, path in analysis_paths.items()},
        "aliases": {name: rel(path, root) for name, path in aliases.items()},
    }

    missing_sections = [
        name for name, value in sections.items()
        if value.get("status") == "missing"
    ]

    coach_input = {
        "meta": {
            "package_type": "coach_input_package",
            "version": "v0_2",
            "builder": BUILDER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "purpose": "stable evidence contract for future UI and AI coach judge",
            "stability": "stable_paths_experimental_schema",
        },
        "source_files": source_files,
        "current_aliases_created": alias_results,
        "contract_health": {
            "status": "ok" if not missing_sections else "ok_with_missing_optional_sections",
            "product_health_status": health_status or "unknown",
            "warnings": warnings,
            "missing_optional_sections": missing_sections,
            "round_cards_count": len(round_cards),
            "priorities_count": len(priorities),
            "top_cases_count": len(top_cases),
            "sections_count": len(sections),
        },
        "overview": {
            "match_id": match_id,
            "player": player,
            "primary_diagnosis": compact(diagnosis, limit_list=12),
            "main_priority": priorities[0] if priorities else None,
            "review_rounds": compact(review_rounds, limit_list=50),
            "top_case": top_cases[0] if top_cases else None,
        },
        "coach_priorities": priorities,
        "review": {
            "review_rounds": compact(review_rounds, limit_list=50),
            "top_cases": top_cases,
            "round_cards": round_cards,
        },
        "evidence_sections": sections,
        "ui_contract": {
            "recommended_screen_order": [
                "overview",
                "coach_priorities",
                "review.top_cases",
                "review.round_cards",
                "evidence_sections.macro_trade_spacing",
                "evidence_sections.mechanics",
                "evidence_sections.round_impact",
                "evidence_sections.plant_phase",
                "evidence_sections.utility",
                "evidence_sections.combat",
                "evidence_sections.phase",
                "evidence_sections.advantage_state",
                "evidence_sections.area_map",
                "evidence_sections.loss_patterns"
            ],
            "do_not_read_versioned_files_directly": True,
            "frontend_entrypoint": f"data/package/{match_id}/coach_input_package_current.json",
        },
        "ai_contract": {
            "role": "Evidence input for a future AI coach layer. This is not final model judgement.",
            "model_input_policy": {
                "allowed": [
                    "use facts, summaries, round cards and evidence sections from this package",
                    "infer likely causes only when evidence supports them",
                    "state uncertainty explicitly",
                    "separate mechanics, macro, utility, phase, area and advantage-state causes"
                ],
                "forbidden": [
                    "invent enemy comms, intentions, exact positions or player knowledge not present in evidence",
                    "treat inferred area/phase as exact truth without confidence",
                    "turn raw counters into problems without negative evidence",
                    "diagnose aim errors without checking visibility, flash, movement and context when available"
                ]
            },
            "judge_tasks_v0_1": [
                {
                    "task_id": "match_diagnosis",
                    "input_sections": ["overview", "coach_priorities", "evidence_sections"],
                    "output": "short practical diagnosis and top training priorities"
                },
                {
                    "task_id": "round_review",
                    "input_sections": ["review.round_cards", "evidence_sections"],
                    "output": "round-by-round coach notes grounded in evidence"
                },
                {
                    "task_id": "mechanics_review",
                    "input_sections": ["evidence_sections.mechanics", "evidence_sections.combat"],
                    "output": "aim/reaction/movement issue separation"
                },
                {
                    "task_id": "macro_decision_review",
                    "input_sections": [
                        "evidence_sections.macro_trade_spacing",
                        "evidence_sections.phase",
                        "evidence_sections.advantage_state",
                        "evidence_sections.area_map"
                    ],
                    "output": "decision, spacing, timing and survival analysis"
                }
            ],
            "required_future_layers": [
                "canonical_info_state_v0_1",
                "enemy_intent_inference_v0_1",
                "mechanics_deep_analyzer_v0_1",
                "decision_context_v0_1",
                "aim_context_v0_1",
                "round_narrative_v0_1",
                "ai_coach_judge_v0_1",
                "ai_judgement_validator_v0_1"
            ],
            "known_gaps_v0_2": [
                "player information state is not fully reconstructed yet",
                "enemy plan/intent is not inferred yet",
                "deep aim/reaction context still depends on available raw view/shot/movement data",
                "area inference can be approximate for mechanics/trade events",
                "AI coach judge is not connected yet"
            ]
        }
    }

    out_versioned = pkg_dir / f"coach_input_package_{player}_v0_2.json"
    out_current = pkg_dir / "coach_input_package_current.json"

    write_json(out_versioned, coach_input)
    write_json(out_current, coach_input)

    index_path = pkg_dir / f"coach_input_package_index_{player}_v0_2.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": coach_input["contract_health"]["status"]})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "versioned_package", "value": rel(out_versioned, root)})
        writer.writerow({"key": "current_package", "value": rel(out_current, root)})
        writer.writerow({"key": "warnings_count", "value": str(len(warnings))})
        writer.writerow({"key": "missing_optional_sections", "value": ",".join(missing_sections)})
        writer.writerow({"key": "round_cards_count", "value": str(len(round_cards))})
        writer.writerow({"key": "priorities_count", "value": str(len(priorities))})
        writer.writerow({"key": "top_cases_count", "value": str(len(top_cases))})
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
        "contract_health": coach_input["contract_health"],
        "overview": coach_input["overview"],
        "ai_future_layers": coach_input["ai_contract"]["required_future_layers"],
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
