from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import write_json, print_json


VERSION = "structured_analysis_manifest_v0_1"


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
        "modified": path.stat().st_mtime if path.exists() else None,
    }


def add_entry(entries: list[dict[str, Any]], name: str, kind: str, path: Path, summary_path: list[str] | None = None) -> None:
    payload = load_json_optional(path) if path.suffix.lower() == ".json" else {}
    summary: Any = payload

    if summary_path:
        cur: Any = payload
        for key in summary_path:
            if isinstance(cur, dict):
                cur = cur.get(key, {})
            else:
                cur = {}
                break
        summary = cur

    entries.append({
        "name": name,
        "kind": kind,
        "file": file_info(path),
        "summary": summary if isinstance(summary, dict) else {},
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    layers = data_root / "layers" / args.match_id
    analysis = data_root / "analysis" / args.match_id
    verdict = data_root / "verdict" / args.match_id
    reviews = data_root / "reviews" / args.match_id
    reports = data_root / "reports" / args.match_id

    entries: list[dict[str, Any]] = []

    add_entry(entries, "canonical_round_timeline", "layer", layers / f"canonical_round_timeline_{args.player}_v0_1.json", ["summary"])
    add_entry(entries, "canonical_trade_layer", "layer", layers / f"canonical_trade_layer_{args.player}_v0_1.json", ["summary"])
    add_entry(entries, "canonical_utility_timeline", "layer", layers / "canonical_utility_timeline_v0_1.json", ["summary"])

    add_entry(entries, "trade_spacing", "analysis", analysis / f"trade_spacing_{args.player}_v0_1.json", ["summary"])
    add_entry(entries, "round_impact", "analysis", analysis / f"round_impact_{args.player}_v0_1.json", ["summary"])
    add_entry(entries, "postplant_retake", "analysis", analysis / f"postplant_retake_{args.player}_v0_1.json", ["summary"])

    add_entry(entries, "evidence_priority", "verdict", verdict / f"evidence_priority_{args.player}_v0_1.json", ["summary"])
    add_entry(entries, "coach_priority", "verdict", verdict / f"coach_priority_{args.player}_v0_2.json", ["summary"])
    add_entry(entries, "coach_action_plan", "verdict", verdict / f"coach_action_plan_{args.player}_v0_1.json", ["summary"])

    add_entry(entries, "coach_round_review_queue", "review_queue", reviews / f"coach_round_review_queue_{args.player}_v0_1.csv")
    add_entry(entries, "legacy_unified_coach_verdict", "legacy_report", reports / f"unified_coach_verdict_{args.player}_v0_3.json", ["diagnoses"])

    missing = [e for e in entries if not e["file"]["exists"]]

    action_plan = load_json_optional(verdict / f"coach_action_plan_{args.player}_v0_1.json")
    coach_priority = load_json_optional(verdict / f"coach_priority_{args.player}_v0_2.json")

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "status": "ok" if not missing else "missing_outputs",
        "missing_count": len(missing),
        "missing": [
            {
                "name": e["name"],
                "path": e["file"]["path"],
            }
            for e in missing
        ],
        "outputs": entries,
        "main_outputs": {
            "coach_action_plan_json": str(verdict / f"coach_action_plan_{args.player}_v0_1.json"),
            "coach_action_plan_csv": str(verdict / f"coach_action_plan_{args.player}_v0_1.csv"),
            "coach_round_review_queue_csv": str(reviews / f"coach_round_review_queue_{args.player}_v0_1.csv"),
            "coach_priority_json": str(verdict / f"coach_priority_{args.player}_v0_2.json"),
            "evidence_priority_json": str(verdict / f"evidence_priority_{args.player}_v0_1.json"),
        },
        "quick_summary": {
            "action_plan": action_plan.get("summary", {}),
            "coach_priority": coach_priority.get("summary", {}),
        },
    }

    out_dir = data_root / "runs" / args.match_id
    out_path = out_dir / f"structured_analysis_manifest_{args.player}_v0_1.json"
    write_json(out_path, payload)

    print("")
    print("=== STRUCTURED ANALYSIS MANIFEST v0.1 COMPLETE ===")
    print(f"Manifest: {out_path}")
    print("")
    print_json({
        "status": payload["status"],
        "missing_count": payload["missing_count"],
        "main_outputs": payload["main_outputs"],
        "quick_summary": payload["quick_summary"],
    })

    if missing:
        raise SystemExit("Some structured analysis outputs are missing.")


if __name__ == "__main__":
    main()
