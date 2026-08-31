from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "area_profile_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_area_rows(area_payload: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for r in area_payload.get("rows", []):
        area = safe_str(r.get("area")) or "unknown"
        grouped[area].append(r)

    rows = []

    for area, items in grouped.items():
        negative = [r for r in items if r.get("value_type") == "negative"]
        positive = [r for r in items if r.get("value_type") == "positive"]
        utility = [r for r in items if r.get("event_source") == "utility"]
        mechanics = [r for r in negative if r.get("event_source") == "mechanics"]
        trade = [r for r in negative if r.get("event_source") == "trade_spacing"]
        deaths = [r for r in negative if r.get("event_type") == "death"]
        kills = [r for r in positive if r.get("event_type") == "kill"]

        problem_score = len(negative) * 3 + len(mechanics) * 5 + len(trade) * 6 + len(deaths) * 4
        value_score = len(positive) * 3 + len(kills) * 4 + len(utility)

        label = "neutral_area"
        if area == "unknown":
            label = "unknown_area"
        elif problem_score >= 35:
            label = "major_problem_area"
        elif problem_score >= 15:
            label = "problem_area"
        elif value_score >= 20 and problem_score < 10:
            label = "positive_area"
        elif len(utility) >= 4:
            label = "utility_area"

        rows.append({
            "area": area,
            "area_label": label,
            "problem_score": problem_score,
            "value_score": value_score,
            "events_total": len(items),
            "negative_events": len(negative),
            "positive_events": len(positive),
            "utility_events": len(utility),
            "mechanics_problem_events": len(mechanics),
            "trade_problem_events": len(trade),
            "death_events": len(deaths),
            "kill_events": len(kills),
            "source_counts": dict(Counter(r.get("event_source") for r in items)),
            "event_type_counts": dict(Counter(r.get("event_type") for r in items)),
            "negative_rounds": sorted(set(safe_int(r.get("round_num")) for r in negative if safe_int(r.get("round_num")) is not None))[:12],
            "positive_rounds": sorted(set(safe_int(r.get("round_num")) for r in positive if safe_int(r.get("round_num")) is not None))[:12],
        })

    return sorted(rows, key=lambda r: (-safe_float(r.get("problem_score")), safe_str(r.get("area"))))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(r.get("area_label") for r in rows)

    problem_areas = [
        r for r in rows
        if r.get("area_label") in {"major_problem_area", "problem_area"}
        and r.get("area") != "unknown"
    ]

    return {
        "version": VERSION,
        "areas_total": len(rows),
        "area_label_counts": dict(labels),
        "top_problem_areas": [
            {
                "area": r.get("area"),
                "area_label": r.get("area_label"),
                "problem_score": r.get("problem_score"),
                "negative_events": r.get("negative_events"),
                "mechanics_problem_events": r.get("mechanics_problem_events"),
                "trade_problem_events": r.get("trade_problem_events"),
                "death_events": r.get("death_events"),
                "negative_rounds": r.get("negative_rounds"),
            }
            for r in problem_areas[:10]
        ],
        "top_value_areas": [
            {
                "area": r.get("area"),
                "value_score": r.get("value_score"),
                "positive_events": r.get("positive_events"),
                "kill_events": r.get("kill_events"),
                "utility_events": r.get("utility_events"),
                "positive_rounds": r.get("positive_rounds"),
            }
            for r in sorted(rows, key=lambda x: (-safe_float(x.get("value_score")), safe_str(x.get("area"))))[:10]
            if r.get("area") != "unknown"
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    area_json = data_root / "layers" / args.match_id / f"canonical_area_events_{args.player}_v0_1.json"

    print("=== Area Profile Analyzer v0.1 ===")
    print(f"Area layer: {area_json} exists={area_json.exists()}")

    area_payload = load_json(area_json)
    rows = build_area_rows(area_payload)
    summary = summarize(rows)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "area_layer": str(area_json),
        },
        "summary": summary,
        "areas": rows,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"area_profile_{args.player}_v0_1.json"
    csv_path = out_dir / f"area_profile_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== AREA PROFILE ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
