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


VERSION = "phase_profile_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def by_phase(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        out[safe_str(e.get("phase")) or "unknown"].append(e)
    return out


def by_round(events: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        rn = safe_int(e.get("round_num"))
        if rn is not None:
            out[rn].append(e)
    return out


def phase_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for phase, items in by_phase(events).items():
        negative = [e for e in items if e.get("value_type") == "negative"]
        positive = [e for e in items if e.get("value_type") == "positive"]
        utility = [e for e in items if e.get("event_source") == "utility"]
        mechanics = [e for e in items if e.get("event_source") == "mechanics" and e.get("value_type") == "negative"]
        trade = [e for e in items if e.get("event_source") == "trade_spacing" and e.get("value_type") == "negative"]

        problem_score = len(negative) * 4 + len(mechanics) * 4 + len(trade) * 5
        value_score = len(positive) * 3 + len(utility) * 1

        rows.append({
            "phase": phase,
            "events_total": len(items),
            "positive_events": len(positive),
            "negative_events": len(negative),
            "utility_events": len(utility),
            "mechanics_problem_events": len(mechanics),
            "trade_problem_events": len(trade),
            "problem_score": problem_score,
            "value_score": value_score,
            "event_type_counts": dict(Counter(e.get("event_type") for e in items)),
            "source_counts": dict(Counter(e.get("event_source") for e in items)),
        })

    return sorted(rows, key=lambda r: (-safe_float(r.get("problem_score")), safe_str(r.get("phase"))))


def round_phase_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for rn, items in by_round(events).items():
        phase_counts = Counter(e.get("phase") for e in items)
        negative_by_phase = Counter(e.get("phase") for e in items if e.get("value_type") == "negative")
        positive_by_phase = Counter(e.get("phase") for e in items if e.get("value_type") == "positive")
        utility_by_phase = Counter(e.get("phase") for e in items if e.get("event_source") == "utility")

        negative = [e for e in items if e.get("value_type") == "negative"]
        top_negative = sorted(negative, key=lambda e: -safe_float(e.get("priority_score")))[:5]

        main_problem_phase = ""
        if negative_by_phase:
            main_problem_phase = negative_by_phase.most_common(1)[0][0]

        rows.append({
            "round_num": rn,
            "main_problem_phase": main_problem_phase,
            "events_total": len(items),
            "phase_counts": dict(phase_counts),
            "negative_by_phase": dict(negative_by_phase),
            "positive_by_phase": dict(positive_by_phase),
            "utility_by_phase": dict(utility_by_phase),
            "problem_event_count": len(negative),
            "top_negative_events": [
                {
                    "event_source": e.get("event_source"),
                    "event_type": e.get("event_type"),
                    "phase": e.get("phase"),
                    "tick": e.get("tick"),
                    "priority_score": e.get("priority_score"),
                }
                for e in top_negative
            ],
        })

    return sorted(rows, key=lambda r: (-safe_int(r.get("problem_event_count"), 0), safe_int(r.get("round_num"), 9999) or 9999))


def summarize(phases: list[dict[str, Any]], rounds: list[dict[str, Any]]) -> dict[str, Any]:
    main_phase = phases[0].get("phase") if phases else ""

    problem_rounds = [r for r in rounds if safe_int(r.get("problem_event_count"), 0) > 0]
    main_problem_phase_counts = Counter(r.get("main_problem_phase") for r in problem_rounds if r.get("main_problem_phase"))

    return {
        "version": VERSION,
        "phases_total": len(phases),
        "rounds_total": len(rounds),
        "problem_rounds_total": len(problem_rounds),
        "main_problem_phase": main_phase,
        "main_problem_phase_counts_by_round": dict(main_problem_phase_counts),
        "phase_problem_scores": [
            {
                "phase": p.get("phase"),
                "problem_score": p.get("problem_score"),
                "negative_events": p.get("negative_events"),
                "mechanics_problem_events": p.get("mechanics_problem_events"),
                "trade_problem_events": p.get("trade_problem_events"),
            }
            for p in phases
        ],
        "top_problem_rounds": [
            {
                "round_num": r.get("round_num"),
                "main_problem_phase": r.get("main_problem_phase"),
                "problem_event_count": r.get("problem_event_count"),
                "negative_by_phase": r.get("negative_by_phase"),
            }
            for r in problem_rounds[:10]
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

    phase_json = data_root / "layers" / args.match_id / f"canonical_phase_timeline_{args.player}_v0_1.json"

    print("=== Phase Profile Analyzer v0.1 ===")
    print(f"Phase timeline: {phase_json} exists={phase_json.exists()}")

    phase_payload = load_json(phase_json)
    events = phase_payload.get("events", [])

    phases = phase_rows(events)
    rounds = round_phase_rows(events)
    summary = summarize(phases, rounds)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "phase_timeline": str(phase_json),
        },
        "summary": summary,
        "phases": phases,
        "rounds": rounds,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"phase_profile_{args.player}_v0_1.json"
    phase_csv = out_dir / f"phase_profile_phases_{args.player}_v0_1.csv"
    round_csv = out_dir / f"phase_profile_rounds_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(phase_csv, phases)
    write_csv(round_csv, rounds)

    print("")
    print("=== PHASE PROFILE ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"Phases CSV: {phase_csv}")
    print(f"Rounds CSV: {round_csv}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
