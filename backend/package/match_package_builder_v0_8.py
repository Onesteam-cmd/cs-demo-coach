from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_csv, write_json, print_json
from backend.package.match_package_builder_v0_7 import rows_for_csv
from backend.package.match_package_builder_v0_1 import file_entry


VERSION = "match_package_builder_v0_8"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    print("=== Match Package Builder v0.8 ===")

    package_v7 = data_root / "package" / args.match_id / f"match_package_{args.player}_v0_7.json"
    brief_json = data_root / "verdict" / args.match_id / f"coach_brief_{args.player}_v0_1.json"
    brief_csv = data_root / "verdict" / args.match_id / f"coach_brief_{args.player}_v0_1.csv"

    package = load_json(package_v7)
    brief = load_json(brief_json)

    package["version"] = VERSION
    package["coach"]["brief"] = brief
    package["summaries"]["coach_brief"] = {
        "primary_title": brief.get("diagnosis", {}).get("primary_title"),
        "short_diagnosis": brief.get("diagnosis", {}).get("short_diagnosis"),
        "final_notes": brief.get("final_notes", []),
        "review_rounds": brief.get("sections", {}).get("review_rounds", []),
    }
    package["files"]["coach_brief"] = file_entry(brief_json)
    package["files"]["coach_brief_csv"] = file_entry(brief_csv)
    package["health"]["checks"]["coach_brief_exists"] = brief_json.exists()

    out_dir = data_root / "package" / args.match_id
    json_path = out_dir / f"match_package_{args.player}_v0_8.json"
    csv_path = out_dir / f"match_package_index_{args.player}_v0_8.csv"

    write_json(json_path, package)
    write_csv(csv_path, rows_for_csv(package))

    print("")
    print("=== MATCH PACKAGE v0.8 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json({
        "health": package.get("health"),
        "coach_brief": package.get("summaries", {}).get("coach_brief", {}),
    })


if __name__ == "__main__":
    main()
