from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_int, safe_str, write_json, print_json


VERSION = "product_health_check_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else None,
    }


def check_package(package: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    health = package.get("health", {})
    summaries = package.get("summaries", {})
    coach = package.get("coach", {})
    rounds = package.get("rounds", {})
    files = package.get("files", {})

    if not isinstance(health, dict):
        errors.append("health_missing_or_invalid")

    if not coach.get("brief"):
        errors.append("coach_brief_missing")

    if not coach.get("priorities"):
        errors.append("coach_priorities_missing")

    if not coach.get("action_blocks"):
        errors.append("coach_action_blocks_missing")

    if not rounds.get("top_cases"):
        errors.append("top_round_cases_missing")

    if not summaries.get("round_cases"):
        errors.append("round_cases_summary_missing")

    if not summaries.get("coach_brief"):
        errors.append("coach_brief_summary_missing")

    if not summaries.get("combat_profile"):
        warnings.append("combat_profile_summary_missing")

    if not summaries.get("phase_profile"):
        warnings.append("phase_profile_summary_missing")

    if not summaries.get("area_profile"):
        warnings.append("area_profile_summary_missing")

    if not summaries.get("advantage_profile"):
        warnings.append("advantage_profile_summary_missing")

    required_files = [
        "coach_brief",
        "round_cases",
        "coach_action_plan",
        "coach_priority",
        "evidence_priority",
    ]

    for name in required_files:
        entry = files.get(name)
        if not isinstance(entry, dict) or not entry.get("exists"):
            errors.append(f"file_missing:{name}")

    checks = health.get("checks", {})
    if isinstance(checks, dict):
        if safe_int(checks.get("cases_total"), 0) <= 0:
            errors.append("cases_total_zero")

        if safe_int(checks.get("clusters_total"), 0) <= 0:
            errors.append("clusters_total_zero")

        if safe_int(checks.get("actions_total"), 0) <= 0:
            errors.append("actions_total_zero")

        if safe_int(checks.get("coach_brief_exists"), 0) == 0 and checks.get("coach_brief_exists") is not True:
            errors.append("coach_brief_exists_false")
    else:
        warnings.append("health_checks_missing")

    return errors, warnings


def compact_summary(package: dict[str, Any], errors: list[str], warnings: list[str]) -> dict[str, Any]:
    coach = package.get("coach", {})
    brief = coach.get("brief", {})
    diagnosis = brief.get("diagnosis", {})
    sections = brief.get("sections", {})

    priorities = coach.get("priorities", [])
    top_priority = priorities[0] if priorities else {}

    top_cases = package.get("rounds", {}).get("top_cases", [])
    top_case = top_cases[0] if top_cases else {}

    return {
        "version": VERSION,
        "package_version": package.get("version"),
        "status": "ok" if not errors else "error",
        "errors": errors,
        "warnings": warnings,
        "primary_diagnosis": diagnosis.get("short_diagnosis"),
        "primary_priority": {
            "title": top_priority.get("title"),
            "area": top_priority.get("area"),
            "score": top_priority.get("priority_score"),
            "confidence": top_priority.get("confidence"),
        },
        "review_rounds": sections.get("review_rounds", []),
        "top_case": {
            "round_num": top_case.get("round_num"),
            "label": top_case.get("case_label"),
            "score": top_case.get("case_priority_score"),
            "result": top_case.get("round_result"),
        },
        "health_checks": package.get("health", {}).get("checks", {}),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    package_path = data_root / "package" / args.match_id / f"match_package_{args.player}_v0_8.json"
    brief_path = data_root / "verdict" / args.match_id / f"coach_brief_{args.player}_v0_1.json"

    print("=== Product Health Check v0.1 ===")
    print(f"Package: {package_path} exists={package_path.exists()}")
    print(f"Brief:   {brief_path} exists={brief_path.exists()}")

    package = load_json(package_path)
    errors, warnings = check_package(package)

    summary = compact_summary(package, errors, warnings)

    out_dir = data_root / "runs" / args.match_id
    out_path = out_dir / f"product_health_{args.player}_v0_1.json"
    write_json(out_path, {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "package": file_info(package_path),
        "brief": file_info(brief_path),
        "summary": summary,
    })

    print("")
    print("=== PRODUCT HEALTH CHECK v0.1 COMPLETE ===")
    print(f"JSON: {out_path}")
    print("")
    print_json(summary)

    if errors:
        raise SystemExit("Product health check failed.")


if __name__ == "__main__":
    main()
