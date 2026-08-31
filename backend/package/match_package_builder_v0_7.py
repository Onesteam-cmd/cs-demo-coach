from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_csv, write_json, print_json
from backend.package.match_package_builder_v0_1 import build_package, file_entry, rows_for_csv


VERSION = "match_package_builder_v0_7"


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

    print("=== Match Package Builder v0.7 ===")

    package = build_package(data_root, args.match_id, args.player)
    package["version"] = VERSION

    addon_paths = {
        "loss_patterns": data_root / "analysis" / args.match_id / f"loss_patterns_{args.player}_v0_1.json",
        "utility_value": data_root / "analysis" / args.match_id / f"utility_value_{args.player}_v0_1.json",
        "combat_profile": data_root / "analysis" / args.match_id / f"combat_profile_{args.player}_v0_1.json",
        "combat_layer": data_root / "layers" / args.match_id / f"canonical_combat_events_{args.player}_v0_1.json",
        "phase_profile": data_root / "analysis" / args.match_id / f"phase_profile_{args.player}_v0_1.json",
        "advantage_profile": data_root / "analysis" / args.match_id / f"advantage_profile_{args.player}_v0_1.json",
        "area_layer": data_root / "layers" / args.match_id / f"canonical_area_events_{args.player}_v0_1.json",
        "area_profile": data_root / "analysis" / args.match_id / f"area_profile_{args.player}_v0_1.json",
    }

    addons = {name: load_json(path) for name, path in addon_paths.items()}

    for name, payload in addons.items():
        package["summaries"][name] = payload.get("summary", {})
        package["files"][name] = file_entry(addon_paths[name])

    package["coach"]["loss_patterns"] = addons["loss_patterns"].get("summary", {}).get("top_loss_patterns", [])
    package["coach"]["utility_value"] = addons["utility_value"].get("summary", {}).get("top_utility_problem_rounds", [])
    package["coach"]["combat_profile"] = {
        "top_weapons": addons["combat_profile"].get("summary", {}).get("top_weapons", []),
        "top_combat_rounds": addons["combat_profile"].get("summary", {}).get("top_combat_rounds", []),
        "combat_label_counts": addons["combat_profile"].get("summary", {}).get("combat_label_counts", {}),
    }
    package["coach"]["phase_profile"] = addons["phase_profile"].get("summary", {})
    package["coach"]["advantage_profile"] = addons["advantage_profile"].get("summary", {})
    package["coach"]["area_profile"] = addons["area_profile"].get("summary", {})

    package["health"]["checks"]["area_events_total"] = addons["area_layer"].get("summary", {}).get("area_events_total")
    package["health"]["checks"]["areas_total"] = addons["area_profile"].get("summary", {}).get("areas_total")
    package["health"]["checks"]["top_problem_areas_count"] = len(addons["area_profile"].get("summary", {}).get("top_problem_areas", []))

    out_dir = data_root / "package" / args.match_id
    json_path = out_dir / f"match_package_{args.player}_v0_7.json"
    csv_path = out_dir / f"match_package_index_{args.player}_v0_7.csv"

    write_json(json_path, package)
    write_csv(csv_path, rows_for_csv(package))

    print("")
    print("=== MATCH PACKAGE v0.7 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json({
        "health": package.get("health"),
        "area_profile": package.get("summaries", {}).get("area_profile", {}),
        "top_priority": (package.get("coach", {}).get("priorities") or [{}])[0],
    })


if __name__ == "__main__":
    main()
