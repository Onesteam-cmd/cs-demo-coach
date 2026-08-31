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


VERSION = "advantage_profile_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_rows(state_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    for r in state_payload.get("rows", []):
        if not bool(r.get("player_event")):
            continue

        role = safe_str(r.get("player_role"))
        before = safe_str(r.get("player_team_state_before"))
        after = safe_str(r.get("player_team_state_after"))
        result = safe_str(r.get("round_result"))

        risk_score = 0
        value_score = 0
        tags = []
        reasons = []

        if role == "kill":
            value_score += 10
            tags.append("player_kill_swing")
            reasons.append("player made kill")

            if before in {"player_team_disadvantage", "player_team_big_disadvantage"}:
                value_score += 8
                tags.append("kill_from_disadvantage")
                reasons.append("kill improved bad state")

            if before == "even":
                value_score += 4
                tags.append("kill_from_even")
                reasons.append("kill created advantage from even state")

            if result == "loss":
                risk_score += 4
                tags.append("kill_not_converted_to_round")
                reasons.append("kill happened in lost round")

        elif role == "death":
            risk_score += 10
            tags.append("player_death_swing")
            reasons.append("player died")

            if before in {"player_team_advantage", "player_team_big_advantage"}:
                risk_score += 10
                tags.append("death_while_team_ahead")
                reasons.append("death reduced or lost team advantage")

            if before == "even":
                risk_score += 7
                tags.append("death_from_even")
                reasons.append("death gave enemy advantage from even state")

            if result == "loss":
                risk_score += 4
                tags.append("death_in_lost_round")
                reasons.append("death occurred in lost round")

            if bool(r.get("is_opening_kill_event")):
                risk_score += 8
                tags.append("opening_death_swing")
                reasons.append("opening death changed round state")

        swing_label = "neutral"
        if risk_score >= 20:
            swing_label = "major_negative_swing"
        elif risk_score >= 12:
            swing_label = "negative_swing"
        elif value_score >= 18:
            swing_label = "major_positive_swing"
        elif value_score >= 10:
            swing_label = "positive_swing"

        rows.append({
            "round_num": safe_int(r.get("round_num")),
            "tick": safe_int(r.get("tick")),
            "swing_label": swing_label,
            "player_role": role,
            "risk_score": risk_score,
            "value_score": value_score,
            "tags": list(dict.fromkeys(tags)),
            "reasons": list(dict.fromkeys(reasons)),
            "round_result": result,
            "player_side": safe_str(r.get("player_side")),
            "has_plant": bool(r.get("has_plant")),
            "event_phase": safe_str(r.get("event_phase")),
            "state_before": before,
            "state_after": after,
            "diff_before": safe_int(r.get("player_team_diff_before")),
            "diff_after": safe_int(r.get("player_team_diff_after")),
            "swing_delta": safe_int(r.get("swing_delta")),
            "weapon": safe_str(r.get("weapon")),
            "headshot": bool(r.get("headshot")),
            "attacker": safe_str(r.get("attacker")),
            "victim": safe_str(r.get("victim")),
        })

    return sorted(rows, key=lambda x: (-safe_int(x.get("risk_score"), 0), -safe_int(x.get("value_score"), 0), safe_int(x.get("round_num"), 9999) or 9999))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(r.get("swing_label") for r in rows)
    tags = Counter()
    state_before = Counter(r.get("state_before") for r in rows)
    result_counts = Counter(r.get("round_result") for r in rows)

    for r in rows:
        for tag in r.get("tags") or []:
            tags[tag] += 1

    negative = [r for r in rows if safe_int(r.get("risk_score"), 0) > 0]
    positive = [r for r in rows if safe_int(r.get("value_score"), 0) > 0]

    return {
        "version": VERSION,
        "player_swing_events_total": len(rows),
        "swing_label_counts": dict(labels),
        "tag_counts": dict(tags),
        "state_before_counts": dict(state_before),
        "round_result_counts": dict(result_counts),
        "top_negative_swings": [
            {
                "round_num": r.get("round_num"),
                "tick": r.get("tick"),
                "risk_score": r.get("risk_score"),
                "swing_label": r.get("swing_label"),
                "tags": r.get("tags"),
                "state_before": r.get("state_before"),
                "state_after": r.get("state_after"),
                "round_result": r.get("round_result"),
            }
            for r in negative[:10]
        ],
        "top_positive_swings": [
            {
                "round_num": r.get("round_num"),
                "tick": r.get("tick"),
                "value_score": r.get("value_score"),
                "swing_label": r.get("swing_label"),
                "tags": r.get("tags"),
                "state_before": r.get("state_before"),
                "state_after": r.get("state_after"),
                "round_result": r.get("round_result"),
            }
            for r in sorted(positive, key=lambda x: (-safe_int(x.get("value_score"), 0), safe_int(x.get("round_num"), 9999) or 9999))[:10]
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

    state_json = data_root / "layers" / args.match_id / f"canonical_round_state_{args.player}_v0_1.json"

    print("=== Advantage Profile Analyzer v0.1 ===")
    print(f"Round state layer: {state_json} exists={state_json.exists()}")

    state_payload = load_json(state_json)

    rows = build_rows(state_payload)
    summary = summarize(rows)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_state": str(state_json),
        },
        "summary": summary,
        "rows": rows,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"advantage_profile_{args.player}_v0_1.json"
    csv_path = out_dir / f"advantage_profile_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== ADVANTAGE PROFILE ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
