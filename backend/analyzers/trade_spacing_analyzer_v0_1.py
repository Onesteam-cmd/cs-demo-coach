from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_int, safe_float, safe_str, write_csv, write_json, print_json


VERSION = "trade_spacing_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def round_map(round_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in round_payload.get("rows", []):
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn] = row
    return out


def severity_for_event(event: dict[str, Any], round_row: dict[str, Any]) -> tuple[str, int, list[str]]:
    focus = safe_str(event.get("player_focus"))
    result = safe_str(round_row.get("player_round_result"))
    death_phase = safe_str(round_row.get("player_death_phase"))
    low_impact = bool(round_row.get("player_low_impact_lost_round"))
    trade_delay = safe_int(event.get("trade_delay_ticks"))

    reasons: list[str] = []
    score = 0

    if focus == "player_death_untraded":
        score += 4
        reasons.append("твоя смерть не была быстро разменяна")

        if result == "loss":
            score += 2
            reasons.append("раунд проигран")

        if death_phase == "preplant":
            score += 2
            reasons.append("смерть до plant")
        elif death_phase == "postplant":
            score += 3
            reasons.append("смерть после plant")

        if low_impact:
            score += 2
            reasons.append("низкий impact в проигранном раунде")

    elif focus == "player_kill_traded_by_enemy":
        score += 3
        reasons.append("после твоего kill тебя быстро разменяли")

        if result == "loss":
            score += 2
            reasons.append("раунд проигран")

        if trade_delay is not None:
            if trade_delay <= 96:
                score += 2
                reasons.append("очень быстрый enemy trade")
            elif trade_delay <= 192:
                score += 1
                reasons.append("быстрый enemy trade")

    elif focus == "player_death_traded_by_team":
        score += 1
        reasons.append("смерть была разменяна тиммейтом")

    elif focus == "player_kill_not_traded":
        score += 1
        reasons.append("kill не был быстро разменян соперником")

    if score >= 8:
        return "high", score, reasons
    if score >= 5:
        return "medium", score, reasons
    return "low", score, reasons


def category_for_event(event: dict[str, Any], round_row: dict[str, Any]) -> str:
    focus = safe_str(event.get("player_focus"))
    death_phase = safe_str(round_row.get("player_death_phase"))
    opening_role = safe_str(round_row.get("opening_role"))

    if focus == "player_death_untraded":
        if opening_role == "opening_death":
            return "opening_death_untraded"
        if death_phase == "postplant":
            return "postplant_death_untraded"
        if death_phase == "preplant":
            return "preplant_death_untraded"
        return "death_untraded"

    if focus == "player_kill_traded_by_enemy":
        if opening_role == "opening_kill":
            return "opening_kill_traded"
        return "kill_traded_by_enemy"

    if focus == "player_death_traded_by_team":
        return "death_traded_by_team"

    if focus == "player_kill_not_traded":
        return "kill_not_traded_by_enemy"

    return "other"


def build_evidence(trade_payload: dict[str, Any], round_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = round_map(round_payload)
    rows = []

    for event in trade_payload.get("rows", []):
        focus = safe_str(event.get("player_focus"))
        if focus == "none" or not focus:
            continue

        round_num = safe_int(event.get("round_num"))
        if round_num is None:
            continue

        rr = rounds.get(round_num, {})

        severity, score, reasons = severity_for_event(event, rr)
        category = category_for_event(event, rr)

        is_problem = focus in {"player_death_untraded", "player_kill_traded_by_enemy"}

        rows.append({
            "round_num": round_num,
            "kill_tick": safe_int(event.get("kill_tick")),
            "category": category,
            "player_focus": focus,
            "is_problem": is_problem,
            "severity": severity,
            "priority_score": score,
            "reasons": reasons,
            "round_result": safe_str(rr.get("player_round_result")),
            "player_side": safe_str(rr.get("player_side")),
            "death_phase": safe_str(rr.get("player_death_phase")),
            "opening_role": safe_str(rr.get("opening_role")),
            "has_plant": bool(rr.get("has_plant")),
            "bombsite": safe_str(rr.get("bombsite")),
            "player_kills": safe_int(rr.get("player_kills"), 0),
            "player_deaths": safe_int(rr.get("player_deaths"), 0),
            "player_damage": safe_float(rr.get("player_damage")),
            "low_impact_lost_round": bool(rr.get("player_low_impact_lost_round")),
            "attacker": safe_str(event.get("attacker")),
            "victim": safe_str(event.get("victim")),
            "weapon": safe_str(event.get("weapon")),
            "was_traded": bool(event.get("was_traded")),
            "trade_type": safe_str(event.get("trade_type")),
            "trade_tick": safe_int(event.get("trade_tick")),
            "trade_delay_ticks": safe_int(event.get("trade_delay_ticks")),
            "trade_attacker": safe_str(event.get("trade_attacker")),
            "trade_victim": safe_str(event.get("trade_victim")),
        })

    rows = sorted(rows, key=lambda r: (-safe_int(r.get("priority_score"), 0), safe_int(r.get("round_num"), 9999) or 9999, safe_int(r.get("kill_tick"), 999999999) or 999999999))
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    problem_rows = [r for r in rows if r.get("is_problem")]
    positive_rows = [r for r in rows if not r.get("is_problem")]

    category_counts = Counter(r.get("category") for r in rows)
    problem_category_counts = Counter(r.get("category") for r in problem_rows)
    severity_counts = Counter(r.get("severity") for r in rows)
    phase_counts = Counter(r.get("death_phase") for r in problem_rows)

    problem_rounds = defaultdict(list)
    for row in problem_rows:
        problem_rounds[row.get("round_num")].append(row.get("category"))

    repeated_problem_rounds = [
        {
            "round_num": rn,
            "problem_count": len(cats),
            "categories": list(cats),
        }
        for rn, cats in sorted(problem_rounds.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if len(cats) >= 2
    ]

    main_problem = ""
    if problem_category_counts:
        main_problem = problem_category_counts.most_common(1)[0][0]

    top_examples = []
    for row in problem_rows[:10]:
        top_examples.append({
            "round_num": row.get("round_num"),
            "priority_score": row.get("priority_score"),
            "category": row.get("category"),
            "severity": row.get("severity"),
            "round_result": row.get("round_result"),
            "death_phase": row.get("death_phase"),
            "player_kd_damage": f"{row.get('player_kills')}/{row.get('player_deaths')}/{row.get('player_damage')}",
            "reasons": row.get("reasons"),
        })

    verdict = "Недостаточно данных"
    if main_problem == "death_untraded":
        verdict = "Основной trade-spacing паттерн: смерти без быстрого размена."
    elif main_problem == "preplant_death_untraded":
        verdict = "Основной trade-spacing паттерн: смерти до plant без быстрого размена."
    elif main_problem == "postplant_death_untraded":
        verdict = "Основной trade-spacing паттерн: post-plant смерть без быстрого размена."
    elif main_problem == "kill_traded_by_enemy":
        verdict = "Основной trade-spacing паттерн: после kill тебя быстро разменивают."
    elif main_problem == "opening_death_untraded":
        verdict = "Основной trade-spacing паттерн: opening death без быстрого размена."

    return {
        "version": VERSION,
        "events_total": len(rows),
        "problem_events_total": len(problem_rows),
        "positive_or_neutral_events_total": len(positive_rows),
        "category_counts": dict(category_counts),
        "problem_category_counts": dict(problem_category_counts),
        "severity_counts": dict(severity_counts),
        "problem_death_phase_counts": dict(phase_counts),
        "main_problem": main_problem,
        "verdict": verdict,
        "repeated_problem_rounds": repeated_problem_rounds[:10],
        "top_examples": top_examples,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    layer_dir = data_root / "layers" / args.match_id
    round_json = layer_dir / f"canonical_round_timeline_{args.player}_v0_1.json"
    trade_json = layer_dir / f"canonical_trade_layer_{args.player}_v0_1.json"

    print("=== Trade Spacing Analyzer v0.1 ===")
    print(f"Round layer: {round_json} exists={round_json.exists()}")
    print(f"Trade layer: {trade_json} exists={trade_json.exists()}")

    round_payload = load_json(round_json)
    trade_payload = load_json(trade_json)

    evidence = build_evidence(trade_payload, round_payload)
    summary = summarize(evidence)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_layer": str(round_json),
            "trade_layer": str(trade_json),
        },
        "summary": summary,
        "rows": evidence,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"trade_spacing_{args.player}_v0_1.json"
    csv_path = out_dir / f"trade_spacing_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, evidence)

    print("")
    print("=== TRADE SPACING ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
