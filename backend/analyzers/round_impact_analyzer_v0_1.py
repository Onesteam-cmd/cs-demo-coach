from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_int, safe_float, safe_str, norm, write_csv, write_json, print_json


VERSION = "round_impact_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def rows_by_round(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn].append(row)
    return out


def utility_count_from_round(row: dict[str, Any]) -> int:
    util = row.get("player_utility") or {}
    if not isinstance(util, dict):
        return 0

    total = safe_int(util.get("grenade_throws_total"), 0) or 0
    active_smokes = safe_int(util.get("smokes_active_count"), 0) or 0
    active_infernos = safe_int(util.get("infernos_active_count"), 0) or 0

    return total + active_smokes + active_infernos


def impact_score(row: dict[str, Any], trade_rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    result = safe_str(row.get("player_round_result"))
    kills = safe_int(row.get("player_kills"), 0) or 0
    deaths = safe_int(row.get("player_deaths"), 0) or 0
    damage = safe_float(row.get("player_damage"))
    utility_count = utility_count_from_round(row)
    opening = safe_str(row.get("opening_role"))
    alive_at_plant = bool(row.get("player_alive_at_plant"))
    postplant_damage = safe_float(row.get("player_damage_postplant"))

    score = 0
    reasons: list[str] = []

    if kills > 0:
        score += kills * 3
        reasons.append(f"kills={kills}")

    if damage >= 100:
        score += 4
        reasons.append("100+ damage")
    elif damage >= 60:
        score += 2
        reasons.append("60+ damage")
    elif damage >= 30:
        score += 1
        reasons.append("30+ damage")

    if opening == "opening_kill":
        score += 4
        reasons.append("opening kill")

    if utility_count >= 3:
        score += 2
        reasons.append("used multiple utility events")
    elif utility_count > 0:
        score += 1
        reasons.append("used utility")

    if alive_at_plant and postplant_damage > 0:
        score += 2
        reasons.append("post-plant damage")

    for tr in trade_rows:
        cat = safe_str(tr.get("category"))
        if cat in {"death_traded_by_team", "kill_not_traded_by_enemy"}:
            score += 1
            reasons.append(cat)

    if deaths:
        score -= 2
        reasons.append("death")

    for tr in trade_rows:
        if bool(tr.get("is_problem")):
            score -= 3
            reasons.append(safe_str(tr.get("category")))

    if result == "win" and score > 0:
        score += 1

    return score, list(dict.fromkeys(reasons))


def problem_score(row: dict[str, Any], trade_rows: list[dict[str, Any]]) -> tuple[int, list[str], list[str]]:
    result = safe_str(row.get("player_round_result"))
    kills = safe_int(row.get("player_kills"), 0) or 0
    deaths = safe_int(row.get("player_deaths"), 0) or 0
    damage = safe_float(row.get("player_damage"))
    death_phase = safe_str(row.get("player_death_phase"))
    opening = safe_str(row.get("opening_role"))
    low_impact = bool(row.get("player_low_impact_lost_round"))
    utility_count = utility_count_from_round(row)
    has_plant = bool(row.get("has_plant"))
    alive_at_plant = bool(row.get("player_alive_at_plant"))
    postplant_damage = safe_float(row.get("player_damage_postplant"))
    kills_after_plant = safe_int(row.get("player_kills_after_plant"), 0) or 0

    score = 0
    categories: list[str] = []
    reasons: list[str] = []

    if result == "loss":
        score += 1

    if low_impact:
        score += 4
        categories.append("low_impact_loss")
        reasons.append("lost round with low personal impact")

    if deaths and death_phase == "preplant" and result == "loss":
        score += 3
        categories.append("preplant_death_loss")
        reasons.append("died before plant in lost round")

    if deaths and death_phase == "postplant" and result == "loss":
        score += 4
        categories.append("postplant_death_loss")
        reasons.append("died after plant in lost round")

    if opening == "opening_death":
        score += 5
        categories.append("opening_death")
        reasons.append("opening death")

    if has_plant and alive_at_plant and result == "loss" and kills_after_plant == 0 and postplant_damage <= 0:
        score += 4
        categories.append("plant_phase_no_impact")
        reasons.append("alive at plant but no post-plant impact in lost round")

    if utility_count == 0 and result == "loss" and damage < 40:
        score += 2
        categories.append("no_utility_low_impact_loss")
        reasons.append("low impact lost round without utility event")

    for tr in trade_rows:
        if bool(tr.get("is_problem")):
            cat = safe_str(tr.get("category"))
            score += safe_int(tr.get("priority_score"), 0) or 0
            categories.append(cat)
            reasons.append(cat)

    return score, list(dict.fromkeys(categories)), list(dict.fromkeys(reasons))


def classify_round(row: dict[str, Any], impact: int, problem: int, categories: list[str]) -> str:
    result = safe_str(row.get("player_round_result"))

    if result == "win" and impact >= 6:
        return "positive_impact_win"

    if result == "win" and problem >= 6:
        return "won_but_risky"

    if result == "loss" and problem >= 10:
        return "major_problem_loss"

    if result == "loss" and problem >= 5:
        return "problem_loss"

    if result == "loss" and impact >= 6:
        return "good_impact_loss"

    if result == "loss":
        return "low_signal_loss"

    return "neutral"


def build(round_payload: dict[str, Any], trade_spacing_payload: dict[str, Any]) -> list[dict[str, Any]]:
    trade_by_round = rows_by_round(trade_spacing_payload.get("rows", []))
    out = []

    for row in round_payload.get("rows", []):
        rn = safe_int(row.get("round_num"))
        if rn is None:
            continue

        trs = trade_by_round.get(rn, [])

        impact, impact_reasons = impact_score(row, trs)
        problem, problem_categories, problem_reasons = problem_score(row, trs)
        label = classify_round(row, impact, problem, problem_categories)

        out.append({
            "round_num": rn,
            "round_label": label,
            "impact_score": impact,
            "problem_score": problem,
            "problem_categories": problem_categories,
            "impact_reasons": impact_reasons,
            "problem_reasons": problem_reasons,
            "round_result": safe_str(row.get("player_round_result")),
            "player_side": safe_str(row.get("player_side")),
            "has_plant": bool(row.get("has_plant")),
            "bombsite": safe_str(row.get("bombsite")),
            "opening_role": safe_str(row.get("opening_role")),
            "death_phase": safe_str(row.get("player_death_phase")),
            "player_kills": safe_int(row.get("player_kills"), 0),
            "player_deaths": safe_int(row.get("player_deaths"), 0),
            "player_damage": safe_float(row.get("player_damage")),
            "player_damage_taken": safe_float(row.get("player_damage_taken")),
            "player_damage_postplant": safe_float(row.get("player_damage_postplant")),
            "player_alive_at_plant": bool(row.get("player_alive_at_plant")),
            "player_utility_event_count": utility_count_from_round(row),
            "trade_problem_count": sum(1 for tr in trs if bool(tr.get("is_problem"))),
            "trade_problem_categories": list(dict.fromkeys([safe_str(tr.get("category")) for tr in trs if bool(tr.get("is_problem"))])),
        })

    return sorted(out, key=lambda r: (-safe_int(r.get("problem_score"), 0), safe_int(r.get("round_num"), 9999) or 9999))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(r.get("round_label") for r in rows)
    categories = Counter()
    for r in rows:
        for c in r.get("problem_categories") or []:
            categories[c] += 1

    top_problem_rounds = [
        {
            "round_num": r.get("round_num"),
            "round_label": r.get("round_label"),
            "problem_score": r.get("problem_score"),
            "impact_score": r.get("impact_score"),
            "problem_categories": r.get("problem_categories"),
            "kd_damage": f"{r.get('player_kills')}/{r.get('player_deaths')}/{r.get('player_damage')}",
            "reasons": r.get("problem_reasons"),
        }
        for r in rows
        if safe_int(r.get("problem_score"), 0) > 0
    ][:12]

    top_impact_rounds = [
        {
            "round_num": r.get("round_num"),
            "round_label": r.get("round_label"),
            "impact_score": r.get("impact_score"),
            "problem_score": r.get("problem_score"),
            "kd_damage": f"{r.get('player_kills')}/{r.get('player_deaths')}/{r.get('player_damage')}",
            "reasons": r.get("impact_reasons"),
        }
        for r in sorted(rows, key=lambda x: (-safe_int(x.get("impact_score"), 0), safe_int(x.get("round_num"), 9999) or 9999))
        if safe_int(r.get("impact_score"), 0) > 0
    ][:8]

    main_problem = categories.most_common(1)[0][0] if categories else ""

    return {
        "version": VERSION,
        "rounds_total": len(rows),
        "round_label_counts": dict(labels),
        "problem_category_counts": dict(categories),
        "main_problem_category": main_problem,
        "top_problem_rounds": top_problem_rounds,
        "top_impact_rounds": top_impact_rounds,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    round_json = data_root / "layers" / args.match_id / f"canonical_round_timeline_{args.player}_v0_1.json"
    trade_spacing_json = data_root / "analysis" / args.match_id / f"trade_spacing_{args.player}_v0_1.json"

    print("=== Round Impact Analyzer v0.1 ===")
    print(f"Round layer: {round_json} exists={round_json.exists()}")
    print(f"Trade spacing: {trade_spacing_json} exists={trade_spacing_json.exists()}")

    round_payload = load_json(round_json)
    trade_spacing_payload = load_json(trade_spacing_json)

    rows = build(round_payload, trade_spacing_payload)
    summary = summarize(rows)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_layer": str(round_json),
            "trade_spacing": str(trade_spacing_json),
        },
        "summary": summary,
        "rows": rows,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"round_impact_{args.player}_v0_1.json"
    csv_path = out_dir / f"round_impact_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== ROUND IMPACT ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
