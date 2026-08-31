from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "match_package_builder_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def file_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else None,
    }


def compact_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "round_num": case.get("round_num"),
        "case_label": case.get("case_label"),
        "case_priority_score": case.get("case_priority_score"),
        "case_reasons": case.get("case_reasons"),
        "round_result": case.get("round_result"),
        "player_side": case.get("player_side"),
        "has_plant": case.get("has_plant"),
        "bombsite": case.get("bombsite"),
        "opening_role": case.get("opening_role"),
        "death_phase": case.get("death_phase"),
        "kd_damage": f"{case.get('player_kills')}/{case.get('player_deaths')}/{case.get('player_damage')}",
        "mechanics": {
            "actionable_count": case.get("mechanics", {}).get("actionable_count"),
            "root_counts": case.get("mechanics", {}).get("actionable_root_cause_counts"),
            "top_events": case.get("mechanics", {}).get("top_events"),
        },
        "trade_spacing": {
            "problem_events_total": case.get("trade_spacing", {}).get("problem_events_total"),
            "problem_category_counts": case.get("trade_spacing", {}).get("problem_category_counts"),
            "top_events": case.get("trade_spacing", {}).get("top_events"),
        },
        "utility": case.get("utility", {}),
        "round_impact": {
            "round_label": case.get("round_impact", {}).get("round_label"),
            "impact_score": case.get("round_impact", {}).get("impact_score"),
            "problem_score": case.get("round_impact", {}).get("problem_score"),
            "problem_categories": case.get("round_impact", {}).get("problem_categories"),
        },
        "plant_phase": {
            "plant_phase_label": case.get("plant_phase", {}).get("plant_phase_label"),
            "plant_phase_score": case.get("plant_phase", {}).get("plant_phase_score"),
            "categories": case.get("plant_phase", {}).get("categories"),
        },
    }


def compact_priority(cluster: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": cluster.get("rank"),
        "cluster_id": cluster.get("cluster_id"),
        "area": cluster.get("area"),
        "title": cluster.get("title"),
        "priority_tier": cluster.get("priority_tier"),
        "priority_score": cluster.get("priority_score"),
        "severity": cluster.get("severity"),
        "confidence": cluster.get("confidence"),
        "evidence_count": cluster.get("evidence_count"),
        "top_rounds": cluster.get("top_rounds"),
        "why_it_matters": cluster.get("why_it_matters"),
        "training_focus": cluster.get("training_focus"),
    }


def health_check(paths: dict[str, Path], payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [name for name, path in paths.items() if not path.exists()]

    warnings: list[str] = []

    round_cases = payloads.get("round_cases", {})
    cases_total = safe_int(round_cases.get("summary", {}).get("cases_total"), 0) or 0
    if cases_total <= 0:
        warnings.append("round_cases_empty")

    coach_priority = payloads.get("coach_priority", {})
    clusters_total = safe_int(coach_priority.get("summary", {}).get("clusters_total"), 0) or 0
    if clusters_total <= 0:
        warnings.append("coach_priority_empty")

    action_plan = payloads.get("coach_action_plan", {})
    actions_total = safe_int(action_plan.get("summary", {}).get("actions_total"), 0) or 0
    if actions_total <= 0:
        warnings.append("coach_action_plan_empty")

    mechanics = payloads.get("mechanics_problem", {})
    mechanics_issues = safe_int(mechanics.get("summary", {}).get("issues_total"), 0) or 0
    if mechanics_issues <= 0:
        warnings.append("mechanics_problem_empty")

    status = "ok"
    if missing:
        status = "missing_required_files"
    elif warnings:
        status = "ok_with_warnings"

    return {
        "status": status,
        "missing": missing,
        "warnings": warnings,
        "checks": {
            "cases_total": cases_total,
            "clusters_total": clusters_total,
            "actions_total": actions_total,
            "mechanics_issues": mechanics_issues,
        },
    }


def build_package(data_root: Path, match_id: str, player: str) -> dict[str, Any]:
    paths = {
        "round_cases": data_root / "cases" / match_id / f"round_cases_{player}_v0_1.json",
        "coach_priority": data_root / "verdict" / match_id / f"coach_priority_{player}_v0_3.json",
        "coach_action_plan": data_root / "verdict" / match_id / f"coach_action_plan_{player}_v0_2.json",
        "evidence_priority": data_root / "verdict" / match_id / f"evidence_priority_{player}_v0_2.json",
        "mechanics_problem": data_root / "analysis" / match_id / f"mechanics_problem_{player}_v0_1.json",
        "trade_spacing": data_root / "analysis" / match_id / f"trade_spacing_{player}_v0_1.json",
        "round_impact": data_root / "analysis" / match_id / f"round_impact_{player}_v0_1.json",
        "postplant_retake": data_root / "analysis" / match_id / f"postplant_retake_{player}_v0_1.json",
        "unified_round_review_queue": data_root / "reviews" / match_id / f"unified_round_review_queue_{player}_v0_1.csv",
        "coach_round_review_queue": data_root / "reviews" / match_id / f"coach_round_review_queue_{player}_v0_2.csv",
        "structured_manifest": data_root / "runs" / match_id / f"structured_analysis_manifest_{player}_v0_2.json",
    }

    required_json = [
        "round_cases",
        "coach_priority",
        "coach_action_plan",
        "evidence_priority",
        "mechanics_problem",
        "trade_spacing",
        "round_impact",
        "postplant_retake",
    ]

    payloads = {}
    for name in required_json:
        payloads[name] = load_json(paths[name])

    payloads["structured_manifest"] = load_json_optional(paths["structured_manifest"])

    round_cases = payloads["round_cases"]
    coach_priority = payloads["coach_priority"]
    action_plan = payloads["coach_action_plan"]
    evidence_priority = payloads["evidence_priority"]

    cases = round_cases.get("cases", [])
    top_cases = [compact_case(c) for c in cases[:12]]

    clusters = [compact_priority(c) for c in coach_priority.get("clusters", [])]
    action_blocks = action_plan.get("action_blocks", [])
    session_plan = action_plan.get("session_plan", [])

    health = health_check(paths, payloads)

    return {
        "version": VERSION,
        "match_id": match_id,
        "player": player,
        "health": health,
        "meta": {
            "package_role": "single_source_for_future_ui",
            "no_dashboard_generated": True,
        },
        "summaries": {
            "round_cases": round_cases.get("summary", {}),
            "coach_priority": coach_priority.get("summary", {}),
            "coach_action_plan": action_plan.get("summary", {}),
            "evidence_priority": evidence_priority.get("summary", {}),
            "mechanics_problem": payloads["mechanics_problem"].get("summary", {}),
            "trade_spacing": payloads["trade_spacing"].get("summary", {}),
            "round_impact": payloads["round_impact"].get("summary", {}),
            "postplant_retake": payloads["postplant_retake"].get("summary", {}),
        },
        "coach": {
            "priorities": clusters,
            "action_blocks": action_blocks,
            "session_plan": session_plan,
        },
        "rounds": {
            "top_cases": top_cases,
            "all_cases_file": str(paths["round_cases"]),
            "unified_review_queue_csv": str(paths["unified_round_review_queue"]),
            "coach_review_queue_csv": str(paths["coach_round_review_queue"]),
        },
        "files": {name: file_entry(path) for name, path in paths.items()},
    }


def rows_for_csv(package: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    for p in package.get("coach", {}).get("priorities", []):
        rows.append({
            "type": "priority",
            "rank": p.get("rank"),
            "id": p.get("cluster_id"),
            "area": p.get("area"),
            "title": p.get("title"),
            "tier": p.get("priority_tier"),
            "score": p.get("priority_score"),
            "confidence": p.get("confidence"),
            "evidence_count": p.get("evidence_count"),
            "rounds": p.get("top_rounds"),
        })

    for c in package.get("rounds", {}).get("top_cases", []):
        rows.append({
            "type": "round_case",
            "rank": "",
            "id": c.get("round_num"),
            "area": "",
            "title": c.get("case_label"),
            "tier": "",
            "score": c.get("case_priority_score"),
            "confidence": "",
            "evidence_count": "",
            "rounds": c.get("round_num"),
        })

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    print("=== Match Package Builder v0.1 ===")
    print(f"MatchId: {args.match_id}")
    print(f"Player:  {args.player}")

    package = build_package(data_root, args.match_id, args.player)

    out_dir = data_root / "package" / args.match_id
    json_path = out_dir / f"match_package_{args.player}_v0_1.json"
    csv_path = out_dir / f"match_package_index_{args.player}_v0_1.csv"

    write_json(json_path, package)
    write_csv(csv_path, rows_for_csv(package))

    print("")
    print("=== MATCH PACKAGE v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json({
        "health": package.get("health"),
        "top_priority": (package.get("coach", {}).get("priorities") or [{}])[0],
        "top_case": (package.get("rounds", {}).get("top_cases") or [{}])[0],
    })


if __name__ == "__main__":
    main()
