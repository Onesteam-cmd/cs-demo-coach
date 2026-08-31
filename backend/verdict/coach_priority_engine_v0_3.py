from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_csv, write_json, print_json
from backend.verdict.coach_priority_engine_v0_2 import build_clusters, build_training_blocks, summarize, rows_for_csv


VERSION = "coach_priority_engine_v0_3"


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

    evidence_json = data_root / "verdict" / args.match_id / f"evidence_priority_{args.player}_v0_2.json"

    print("=== Coach Priority Engine v0.3 ===")
    print(f"Evidence priority v0.2: {evidence_json} exists={evidence_json.exists()}")

    evidence = load_json(evidence_json)

    clusters = build_clusters(evidence)
    training_blocks = build_training_blocks(clusters)
    summary = summarize(clusters, training_blocks)
    summary["version"] = VERSION

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "evidence_priority": str(evidence_json),
        },
        "summary": summary,
        "clusters": clusters,
        "training_blocks": training_blocks,
    }

    out_dir = data_root / "verdict" / args.match_id
    json_path = out_dir / f"coach_priority_{args.player}_v0_3.json"
    csv_path = out_dir / f"coach_priority_{args.player}_v0_3.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows_for_csv(clusters))

    print("")
    print("=== COACH PRIORITY ENGINE v0.3 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
