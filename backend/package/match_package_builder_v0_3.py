from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_csv, write_json, print_json
from backend.package.match_package_builder_v0_2 import rows_for_csv
from backend.package.match_package_builder_v0_2 import load_json as load_required
from backend.package.match_package_builder_v0_1 import build_package, file_entry


VERSION = "match_package_builder_v0_3"


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

    print("=== Match Package Builder v0.3 ===")
    print(f"MatchId: {args.match_id}")
    print(f"Player:  {args.player}")

    package = build_package(data_root, args.match_id, args.player)
    package["version"] = VERSION

    loss_json = data_root / "analysis" / args.match_id / f"loss_patterns_{args.player}_v0_1.json"
    loss_csv = data_root / "analysis" / args.match_id / f"loss_patterns_{args.player}_v0_1.csv"
    utility_json = data_root / "analysis" / args.match_id / f"utility_value_{args.player}_v0_1.json"
    utility_csv = data_root / "analysis" / args.match_id / f"utility_value_{args.player}_v0_1.csv"

    loss_patterns = load_json(loss_json)
    utility_value = load_json(utility_json)

    package["summaries"]["loss_patterns"] = loss_patterns.get("summary", {})
    package["summaries"]["utility_value"] = utility_value.get("summary", {})

    package["coach"]["loss_patterns"] = loss_patterns.get("summary", {}).get("top_loss_patterns", [])
    package["coach"]["utility_value"] = utility_value.get("summary", {}).get("top_utility_problem_rounds", [])

    package["files"]["loss_patterns"] = file_entry(loss_json)
    package["files"]["loss_patterns_csv"] = file_entry(loss_csv)
    package["files"]["utility_value"] = file_entry(utility_json)
    package["files"]["utility_value_csv"] = file_entry(utility_csv)

    package["health"]["checks"]["loss_rounds_total"] = loss_patterns.get("summary", {}).get("loss_rounds_total")
    package["health"]["checks"]["utility_problem_rounds_total"] = utility_value.get("summary", {}).get("problem_rounds_total")

    out_dir = data_root / "package" / args.match_id
    json_path = out_dir / f"match_package_{args.player}_v0_3.json"
    csv_path = out_dir / f"match_package_index_{args.player}_v0_3.csv"

    write_json(json_path, package)
    write_csv(csv_path, rows_for_csv(package))

    print("")
    print("=== MATCH PACKAGE v0.3 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json({
        "health": package.get("health"),
        "utility_value": package.get("summaries", {}).get("utility_value", {}),
        "loss_patterns": package.get("summaries", {}).get("loss_patterns", {}),
    })


if __name__ == "__main__":
    main()
