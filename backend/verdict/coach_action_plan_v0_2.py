from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_csv, write_json, print_json
from backend.verdict.coach_action_plan_v0_1 import (
    build_action_blocks,
    build_round_review_queue,
    build_session_plan,
    build_summary,
    csv_action_rows,
)


VERSION = "coach_action_plan_v0_2"


def load_json(path: Path) -> dict:
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

    priority_json = data_root / "verdict" / args.match_id / f"coach_priority_{args.player}_v0_3.json"

    print("=== Coach Action Plan v0.2 ===")
    print(f"Coach priority v0.3: {priority_json} exists={priority_json.exists()}")

    priority = load_json(priority_json)

    action_blocks = build_action_blocks(priority)
    round_queue = build_round_review_queue(priority)
    session_plan = build_session_plan(action_blocks)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "coach_priority": str(priority_json),
        },
        "summary": build_summary(priority, action_blocks, round_queue),
        "session_plan": session_plan,
        "action_blocks": action_blocks,
        "round_review_queue": round_queue,
    }

    verdict_dir = data_root / "verdict" / args.match_id
    review_dir = data_root / "reviews" / args.match_id

    json_path = verdict_dir / f"coach_action_plan_{args.player}_v0_2.json"
    csv_path = verdict_dir / f"coach_action_plan_{args.player}_v0_2.csv"
    review_csv_path = review_dir / f"coach_round_review_queue_{args.player}_v0_2.csv"

    write_json(json_path, payload)
    write_csv(csv_path, csv_action_rows(action_blocks))
    write_csv(review_csv_path, round_queue)

    print("")
    print("=== COACH ACTION PLAN v0.2 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"Round review queue: {review_csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
