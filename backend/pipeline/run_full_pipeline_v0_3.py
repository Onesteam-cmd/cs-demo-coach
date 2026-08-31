from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_step(name: str, cmd: list[str]) -> None:
    print("")
    print(f"=== RUN: {name} ===")
    print(" ".join(str(x) for x in cmd))
    subprocess.run(cmd, check=True)


def load_default_player(root: Path) -> str | None:
    config = read_json(root / "config" / "project_settings.json")

    display = config.get("primary_player_display_name")
    if display:
        return str(display)

    names = config.get("primary_player_names")
    if isinstance(names, list) and names:
        return str(names[0])

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="CS Demo Coach Full Pipeline v0.3")
    parser.add_argument("demo_path", type=Path)
    parser.add_argument("--match-id", default=None, help="Progress/history match id. Default: demo stem.")
    parser.add_argument("--report-id", default=None, help="Report directory under data/reports. Default: demo stem.")
    parser.add_argument("--player", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    os.chdir(root)

    demo_path = args.demo_path
    if not demo_path.is_absolute():
        demo_path = (root / demo_path).resolve()

    if not demo_path.exists():
        raise SystemExit(f"Demo not found: {demo_path}")

    demo_stem = demo_path.stem
    match_id = args.match_id or demo_stem
    report_id = args.report_id or demo_stem
    player = args.player or load_default_player(root)

    if not player:
        raise SystemExit("Player was not provided and config/project_settings.json has no primary player.")

    py = sys.executable

    print("=== CS Demo Coach Full Pipeline v0.3 ===")
    print(f"Demo: {demo_path}")
    print(f"Match ID for progress: {match_id}")
    print(f"Report ID / report dir: {report_id}")
    print(f"Player: {player}")
    print(f"Force: {args.force}")

    v01_cmd = [
        py,
        str(root / "backend" / "pipeline" / "run_full_pipeline_v0_1.py"),
        str(demo_path),
        "--match-id",
        match_id,
        "--player",
        player,
        "--no-open",
    ]

    if args.force:
        v01_cmd.append("--force")

    run_step("Base full pipeline v0.1", v01_cmd)

    run_step(
        "Progress dedup v0.1",
        [
            py,
            str(root / "backend" / "reports" / "progress_dedup_v0_1.py"),
            "--player",
            player,
        ],
    )

    run_step(
        "Progress tracking v0.2",
        [
            py,
            str(root / "backend" / "reports" / "progress_tracking_v0_2.py"),
            "--player",
            player,
        ],
    )

    run_step(
        "Utility Analyzer v0.2",
        [
            py,
            str(root / "backend" / "analyzers" / "utility_analyzer_v0_2.py"),
            str(root / "data" / "parsed" / demo_stem),
            "--match-id",
            report_id,
            "--player",
            player,
        ],
    )

    run_step(
        "Utility Map Review v0.1",
        [
            py,
            str(root / "backend" / "analyzers" / "utility_map_review_v0_1.py"),
            str(root / "data" / "parsed" / demo_stem),
            "--match-id",
            report_id,
            "--player",
            player,
        ],
    )

    utility_map_csv = root / "data" / "reviews" / report_id / f"utility_map_review_{player}_v0_1.csv"
    if utility_map_csv.exists():
        run_step(
            "Utility Map Summary v0.1",
            [
                py,
                str(root / "backend" / "analyzers" / "utility_map_summary_v0_1.py"),
                "--match-id",
                report_id,
                "--player",
                player,
            ],
        )
    else:
        print("")
        print("=== SKIP: Utility Map Summary v0.1 ===")
        print(f"  utility map CSV not found yet: {utility_map_csv}")

    run_step(
        "Moments Review v0.2",
        [
            py,
            str(root / "backend" / "reports" / "moments_review_v0_2.py"),
            "--match-id",
            report_id,
            "--player",
            player,
            "--top-n",
            str(args.top_n),
            "--no-open",
        ],
    )

    dashboard_cmd = [
        py,
        str(root / "backend" / "dashboard" / "build_dashboard_v0_2.py"),
        "--match-id",
        report_id,
        "--player",
        player,
    ]

    if args.no_open:
        dashboard_cmd.append("--no-open")

    run_step(
        "Manual Review Queue v0.1",
        [
            py,
            str(root / "backend" / "reviews" / "manual_review_seed_v0_1.py"),
            "--match-id",
            report_id,
            "--player",
            player,
            "--limit",
            str(args.top_n * 3),
            "--no-open",
        ],
    )

    manual_csv = root / "data" / "reviews" / report_id / f"manual_review_{player}_v0_1.csv"
    if manual_csv.exists():
        run_step(
            "Manual Review Summary v0.1",
            [
                py,
                str(root / "backend" / "reviews" / "manual_review_summary_v0_1.py"),
                "--match-id",
                report_id,
                "--player",
                player,
                "--no-open",
            ],
        )
    else:
        print("")
        print("=== SKIP: Manual Review Summary v0.1 ===")
        print(f"  manual review CSV not found yet: {manual_csv}")

    run_step("Dashboard v0.2", dashboard_cmd)

    dashboard_v03_cmd = [
        py,
        str(root / "backend" / "dashboard" / "build_dashboard_v0_3.py"),
        "--match-id",
        report_id,
        "--player",
        player,
    ]

    if args.no_open:
        dashboard_v03_cmd.append("--no-open")

    run_step("Dashboard v0.3", dashboard_v03_cmd)

    dashboard_v04_cmd = [
        py,
        str(root / "backend" / "dashboard" / "build_dashboard_v0_4.py"),
        "--match-id",
        report_id,
        "--player",
        player,
    ]

    if args.no_open:
        dashboard_v04_cmd.append("--no-open")

    run_step("Dashboard v0.4", dashboard_v04_cmd)

    print("")
    print("=== PIPELINE v0.3 COMPLETE ===")
    print(f"Dashboard v0.2: {root / 'data' / 'dashboard' / 'dashboard_v0_2.html'}")
    print(f"Dashboard v0.3: {root / 'data' / 'dashboard' / 'dashboard_v0_3.html'}")
    print(f"Dashboard v0.4: {root / 'data' / 'dashboard' / 'dashboard_v0_4.html'}")
    print(f"Moments Review: {root / 'data' / 'reports' / report_id / 'moments_review_v0_2.html'}")
    print(f"Progress v0.2: {root / 'data' / 'progress' / ('progress_' + player + '_v0_2.html')}")


if __name__ == "__main__":
    main()











