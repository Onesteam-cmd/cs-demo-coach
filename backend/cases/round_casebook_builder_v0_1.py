from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, norm, write_csv, write_json, print_json


VERSION = "round_casebook_builder_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def rows_by_round(payload: dict[str, Any], round_key: str = "round_num") -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in payload.get("rows", []):
        rn = safe_int(row.get(round_key))
        if rn is not None:
            out[rn].append(row)
    return out


def single_by_round(payload: dict[str, Any], round_key: str = "round_num") -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in payload.get("rows", []):
        rn = safe_int(row.get(round_key))
        if rn is not None:
            out[rn] = row
    return out


def utility_summary(rows: list[dict[str, Any]], player: str) -> dict[str, Any]:
    p = norm(player)
    focus_rows = [r for r in rows if norm(r.get("player")) == p]

    type_counts = Counter()
    role_counts = Counter()
    kind_counts = Counter()

    for r in focus_rows:
        kind_counts[safe_str(r.get("event_kind"))] += 1
        if safe_str(r.get("event_kind")) == "grenade_throw":
            type_counts[safe_str(r.get("utility_type"))] += 1
            role_counts[safe_str(r.get("role"))] += 1

    return {
        "events_total": len(focus_rows),
        "event_kind_counts": dict(kind_counts),
        "throw_type_counts": dict(type_counts),
        "throw_role_counts": dict(role_counts),
    }


def mechanics_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = [r for r in rows if bool(r.get("is_actionable"))]
    clean = [r for r in rows if bool(r.get("is_clean_training_example"))]
    noise = [r for r in rows if bool(r.get("is_noise_or_not_real"))]

    return {
        "events_total": len(rows),
        "actionable_count": len(actionable),
        "clean_training_examples": len(clean),
        "noise_or_not_real_count": len(noise),
        "root_cause_counts": dict(Counter(safe_str(r.get("root_cause")) or "unknown" for r in rows)),
        "actionable_root_cause_counts": dict(Counter(safe_str(r.get("root_cause")) or "unknown" for r in actionable)),
        "top_events": [
            {
                "event_id": r.get("event_id"),
                "tick": r.get("tick"),
                "root_cause": r.get("root_cause"),
                "real_issue": r.get("real_issue"),
                "priority_score": r.get("priority_score"),
            }
            for r in sorted(actionable, key=lambda x: -safe_float(x.get("priority_score")))[:5]
        ],
    }


def trade_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    problems = [r for r in rows if bool(r.get("is_problem"))]

    return {
        "events_total": len(rows),
        "problem_events_total": len(problems),
        "category_counts": dict(Counter(safe_str(r.get("category")) for r in rows)),
        "problem_category_counts": dict(Counter(safe_str(r.get("category")) for r in problems)),
        "top_events": [
            {
                "kill_tick": r.get("kill_tick"),
                "category": r.get("category"),
                "severity": r.get("severity"),
                "priority_score": r.get("priority_score"),
                "reasons": r.get("reasons"),
            }
            for r in sorted(problems, key=lambda x: -safe_float(x.get("priority_score")))[:5]
        ],
    }


def case_score(
    round_row: dict[str, Any],
    mechanics: dict[str, Any],
    trade: dict[str, Any],
    impact: dict[str, Any] | None,
    plant: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    result = safe_str(round_row.get("player_round_result"))

    mechanics_actionable = safe_int(mechanics.get("actionable_count"), 0) or 0
    if mechanics_actionable > 0:
        score += mechanics_actionable * 8
        reasons.append("mechanics actionable")

    trade_problems = safe_int(trade.get("problem_events_total"), 0) or 0
    if trade_problems > 0:
        score += trade_problems * 10
        reasons.append("trade spacing problem")

    if impact:
        ps = safe_float(impact.get("problem_score"))
        iscore = safe_float(impact.get("impact_score"))
        score += min(35, ps)
        if ps > 0:
            reasons.append("round impact problem")
        if result == "win" and iscore > 0:
            score -= min(8, iscore * 0.3)

    if plant:
        plant_score = safe_float(plant.get("plant_phase_score"))
        score += min(25, plant_score)
        if plant_score > 0:
            reasons.append("plant phase problem")

    if result == "loss":
        score += 3

    return round(max(0.0, score), 1), list(dict.fromkeys(reasons))


def case_label(round_row: dict[str, Any], mechanics: dict[str, Any], trade: dict[str, Any], impact: dict[str, Any] | None, plant: dict[str, Any] | None) -> str:
    if impact and safe_str(impact.get("round_label")):
        label = safe_str(impact.get("round_label"))
        if label in {"major_problem_loss", "problem_loss", "positive_impact_win", "won_but_risky"}:
            return label

    if safe_int(mechanics.get("actionable_count"), 0) > 0:
        return "mechanics_review"

    if safe_int(trade.get("problem_events_total"), 0) > 0:
        return "trade_spacing_review"

    if plant and safe_float(plant.get("plant_phase_score")) > 0:
        return "plant_phase_review"

    if safe_str(round_row.get("player_round_result")) == "win":
        return "neutral_or_positive_win"

    return "low_signal_round"


def build_cases(
    round_payload: dict[str, Any],
    mechanics_payload: dict[str, Any],
    trade_payload: dict[str, Any],
    utility_payload: dict[str, Any],
    impact_payload: dict[str, Any],
    plant_payload: dict[str, Any],
    player: str,
) -> list[dict[str, Any]]:
    mechanics_by_round = rows_by_round(mechanics_payload)
    trade_by_round = rows_by_round(trade_payload)
    utility_by_round = rows_by_round(utility_payload)
    impact_by_round = single_by_round(impact_payload)
    plant_by_round = single_by_round(plant_payload)

    cases = []

    for rr in sorted(round_payload.get("rows", []), key=lambda x: safe_int(x.get("round_num"), 9999) or 9999):
        rn = safe_int(rr.get("round_num"))
        if rn is None:
            continue

        msum = mechanics_summary(mechanics_by_round.get(rn, []))
        tsum = trade_summary(trade_by_round.get(rn, []))
        usum = utility_summary(utility_by_round.get(rn, []), player)

        impact = impact_by_round.get(rn)
        plant = plant_by_round.get(rn)

        score, reasons = case_score(rr, msum, tsum, impact, plant)
        label = case_label(rr, msum, tsum, impact, plant)

        cases.append({
            "case_id": f"{player}_{rn}",
            "round_num": rn,
            "case_label": label,
            "case_priority_score": score,
            "case_reasons": reasons,
            "round_result": safe_str(rr.get("player_round_result")),
            "player_side": safe_str(rr.get("player_side")),
            "winner": safe_str(rr.get("winner")),
            "reason": safe_str(rr.get("reason")),
            "has_plant": bool(rr.get("has_plant")),
            "bombsite": safe_str(rr.get("bombsite")),
            "opening_role": safe_str(rr.get("opening_role")),
            "death_phase": safe_str(rr.get("player_death_phase")),
            "player_kills": safe_int(rr.get("player_kills"), 0),
            "player_deaths": safe_int(rr.get("player_deaths"), 0),
            "player_damage": safe_float(rr.get("player_damage")),
            "player_damage_taken": safe_float(rr.get("player_damage_taken")),
            "mechanics": msum,
            "trade_spacing": tsum,
            "utility": usum,
            "round_impact": impact or {},
            "plant_phase": plant or {},
        })

    return sorted(cases, key=lambda x: (-safe_float(x.get("case_priority_score")), safe_int(x.get("round_num"), 9999) or 9999))


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(c.get("case_label") for c in cases)
    results = Counter(c.get("round_result") for c in cases)

    top = []
    for c in cases[:10]:
        top.append({
            "round_num": c.get("round_num"),
            "case_label": c.get("case_label"),
            "case_priority_score": c.get("case_priority_score"),
            "round_result": c.get("round_result"),
            "kd_damage": f"{c.get('player_kills')}/{c.get('player_deaths')}/{c.get('player_damage')}",
            "reasons": c.get("case_reasons"),
        })

    return {
        "version": VERSION,
        "cases_total": len(cases),
        "case_label_counts": dict(labels),
        "round_result_counts": dict(results),
        "top_cases": top,
    }


def cases_for_csv(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for c in cases:
        rows.append({
            "round_num": c.get("round_num"),
            "case_label": c.get("case_label"),
            "case_priority_score": c.get("case_priority_score"),
            "case_reasons": c.get("case_reasons"),
            "round_result": c.get("round_result"),
            "player_side": c.get("player_side"),
            "has_plant": c.get("has_plant"),
            "bombsite": c.get("bombsite"),
            "opening_role": c.get("opening_role"),
            "death_phase": c.get("death_phase"),
            "player_kills": c.get("player_kills"),
            "player_deaths": c.get("player_deaths"),
            "player_damage": c.get("player_damage"),
            "mechanics_actionable": c.get("mechanics", {}).get("actionable_count"),
            "mechanics_roots": c.get("mechanics", {}).get("actionable_root_cause_counts"),
            "trade_problem_events": c.get("trade_spacing", {}).get("problem_events_total"),
            "trade_problem_categories": c.get("trade_spacing", {}).get("problem_category_counts"),
            "utility_events": c.get("utility", {}).get("events_total"),
            "utility_types": c.get("utility", {}).get("throw_type_counts"),
            "impact_label": c.get("round_impact", {}).get("round_label"),
            "impact_problem_score": c.get("round_impact", {}).get("problem_score"),
            "plant_phase_label": c.get("plant_phase", {}).get("plant_phase_label"),
            "plant_phase_score": c.get("plant_phase", {}).get("plant_phase_score"),
        })
    return rows


def review_queue(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for c in cases:
        score = safe_float(c.get("case_priority_score"))
        if score <= 0:
            continue

        rows.append({
            "round_num": c.get("round_num"),
            "case_label": c.get("case_label"),
            "case_priority_score": score,
            "case_reasons": c.get("case_reasons"),
            "round_result": c.get("round_result"),
            "kd_damage": f"{c.get('player_kills')}/{c.get('player_deaths')}/{c.get('player_damage')}",
            "mechanics_actionable": c.get("mechanics", {}).get("actionable_count"),
            "trade_problem_events": c.get("trade_spacing", {}).get("problem_events_total"),
            "utility_events": c.get("utility", {}).get("events_total"),
            "impact_label": c.get("round_impact", {}).get("round_label"),
            "plant_phase_label": c.get("plant_phase", {}).get("plant_phase_label"),
            "review_status": "todo",
            "real_issue": "",
            "primary_root": "",
            "manual_note": "",
        })

    return rows[:20]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    paths = {
        "round": data_root / "layers" / args.match_id / f"canonical_round_timeline_{args.player}_v0_1.json",
        "mechanics": data_root / "layers" / args.match_id / f"canonical_mechanics_events_{args.player}_v0_1.json",
        "trade": data_root / "analysis" / args.match_id / f"trade_spacing_{args.player}_v0_1.json",
        "utility": data_root / "layers" / args.match_id / "canonical_utility_timeline_v0_1.json",
        "impact": data_root / "analysis" / args.match_id / f"round_impact_{args.player}_v0_1.json",
        "plant": data_root / "analysis" / args.match_id / f"postplant_retake_{args.player}_v0_1.json",
    }

    print("=== Round Casebook Builder v0.1 ===")
    for name, path in paths.items():
        print(f"{name}: {path} exists={path.exists()}")

    round_payload = load_json(paths["round"])
    mechanics_payload = load_json(paths["mechanics"])
    trade_payload = load_json(paths["trade"])
    utility_payload = load_json(paths["utility"])
    impact_payload = load_json(paths["impact"])
    plant_payload = load_json(paths["plant"])

    cases = build_cases(round_payload, mechanics_payload, trade_payload, utility_payload, impact_payload, plant_payload, args.player)
    summary = summarize(cases)
    queue = review_queue(cases)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) for k, v in paths.items()},
        "summary": summary,
        "cases": cases,
    }

    case_dir = data_root / "cases" / args.match_id
    review_dir = data_root / "reviews" / args.match_id

    json_path = case_dir / f"round_cases_{args.player}_v0_1.json"
    csv_path = case_dir / f"round_cases_{args.player}_v0_1.csv"
    queue_path = review_dir / f"unified_round_review_queue_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, cases_for_csv(cases))
    write_csv(queue_path, queue)

    print("")
    print("=== ROUND CASEBOOK v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"Review queue: {queue_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
