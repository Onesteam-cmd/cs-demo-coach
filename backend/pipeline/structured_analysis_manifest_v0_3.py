from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_json, print_json


VERSION = "structured_analysis_manifest_v0_3"


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    package_json = data_root / "package" / args.match_id / f"match_package_{args.player}_v0_1.json"
    package = load_json_optional(package_json)

    files = {
        "match_package": package_json,
        "match_package_index": data_root / "package" / args.match_id / f"match_package_index_{args.player}_v0_1.csv",
        "round_cases": data_root / "cases" / args.match_id / f"round_cases_{args.player}_v0_1.json",
        "coach_action_plan": data_root / "verdict" / args.match_id / f"coach_action_plan_{args.player}_v0_2.json",
        "coach_priority": data_root / "verdict" / args.match_id / f"coach_priority_{args.player}_v0_3.json",
        "evidence_priority": data_root / "verdict" / args.match_id / f"evidence_priority_{args.player}_v0_2.json",
        "unified_round_review_queue": data_root / "reviews" / args.match_id / f"unified_round_review_queue_{args.player}_v0_1.csv",
    }

    missing = [name for name, path in files.items() if not path.exists()]

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "status": "ok" if not missing and package.get("health", {}).get("status") in {"ok", "ok_with_warnings"} else "check_required",
        "missing": missing,
        "health": package.get("health", {}),
        "main_outputs": {name: str(path) for name, path in files.items()},
        "file_info": {name: file_info(path) for name, path in files.items()},
        "quick_summary": {
            "coach_priority": package.get("summaries", {}).get("coach_priority", {}),
            "coach_action_plan": package.get("summaries", {}).get("coach_action_plan", {}),
            "round_cases": package.get("summaries", {}).get("round_cases", {}),
        },
    }

    out_dir = data_root / "runs" / args.match_id
    out_path = out_dir / f"structured_analysis_manifest_{args.player}_v0_3.json"
    write_json(out_path, payload)

    print("")
    print("=== STRUCTURED ANALYSIS MANIFEST v0.3 COMPLETE ===")
    print(f"Manifest: {out_path}")
    print("")
    print_json({
        "status": payload["status"],
        "missing": payload["missing"],
        "health": payload["health"],
        "main_outputs": payload["main_outputs"],
    })

    if missing:
        raise SystemExit("Some package outputs are missing.")


if __name__ == "__main__":
    main()
