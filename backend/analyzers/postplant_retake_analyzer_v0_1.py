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


VERSION = "postplant_retake_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def utility_rows_by_round(utility_payload: dict[str, Any], player: str) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    p = norm(player)

    for row in utility_payload.get("rows", []):
        if norm(row.get("player")) != p:
            continue
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn].append(row)

    return out


def trade_rows_by_round(trade_payload: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in trade_payload.get("rows", []):
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn].append(row)
    return out


def postplant_utility_count(utility_rows: list[dict[str, Any]], plant_tick: int | None) -> int:
    if plant_tick is None:
        return 0
    count = 0
    for row in utility_rows:
        tick = safe_int(row.get("tick"))
        if tick is not None and tick >= plant_tick:
            count += 1
    return count


def classify(row: dict[str, Any], utility_rows: list[dict[str, Any]], trade_rows: list[dict[str, Any]]) -> tuple[str, int, list[str], list[str]]:
    side = safe_str(row.get("player_side")).lower()
    result = safe_str(row.get("player_round_result"))
    alive_at_plant = bool(row.get("player_alive_at_plant"))
    deaths_after = safe_int(row.get("player_deaths_after_plant"), 0) or 0
    kills_after = safe_int(row.get("player_kills_after_plant"), 0) or 0
    damage_after = safe_float(row.get("player_damage_postplant"))
    plant_tick = safe_int(row.get("plant_tick"))
    post_util = postplant_utility_count(utility_rows, plant_tick)

    post_trade_problems = []
    for tr in trade_rows:
        if not bool(tr.get("is_problem")):
            continue
        if safe_str(tr.get("death_phase")) == "postplant" or safe_str(tr.get("category")) == "postplant_death_untraded":
            post_trade_problems.append(tr)

    score = 0
    categories: list[str] = []
    reasons: list[str] = []

    if result == "loss":
        score += 1

    if alive_at_plant and result == "loss" and kills_after == 0 and damage_after <= 0:
        score += 5
        if side == "ct":
            categories.append("retake_no_impact")
            reasons.append("alive at plant as CT but no retake impact")
        elif side == "t":
            categories.append("postplant_no_impact")
            reasons.append("alive at plant as T but no post-plant impact")
        else:
            categories.append("plant_phase_no_impact")
            reasons.append("alive at plant but no plant-phase impact")

    if deaths_after > 0 and result == "loss":
        score += 4
        categories.append("postplant_death_loss")
        reasons.append("died after plant in lost round")

    if post_trade_problems:
        score += 4 * len(post_trade_problems)
        categories.append("postplant_trade_problem")
        reasons.append("post-plant death/trade problem")

    if post_util == 0 and alive_at_plant and result == "loss":
        score += 2
        categories.append("no_postplant_utility")
        reasons.append("no post-plant utility event while alive at plant in lost round")

    if result == "win" and alive_at_plant and (kills_after > 0 or damage_after > 0):
        score -= 2
        categories.append("positive_plant_phase")
        reasons.append("positive plant-phase impact in won round")

    label = "neutral"
    if score >= 8:
        label = "major_plant_phase_problem"
    elif score >= 4:
        label = "plant_phase_problem"
    elif "positive_plant_phase" in categories:
        label = "positive_plant_phase"

    return label, score, list(dict.fromkeys(categories)), list(dict.fromkeys(reasons))


def build(round_payload: dict[str, Any], utility_payload: dict[str, Any], trade_payload: dict[str, Any], player: str) -> list[dict[str, Any]]:
    util_by_round = utility_rows_by_round(utility_payload, player)
    trade_by_round = trade_rows_by_round(trade_payload)

    rows = []

    for row in round_payload.get("rows", []):
        if not bool(row.get("has_plant")):
            continue

        rn = safe_int(row.get("round_num"))
        if rn is None:
            continue

        utility_rows = util_by_round.get(rn, [])
        trade_rows = trade_by_round.get(rn, [])

        label, score, categories, reasons = classify(row, utility_rows, trade_rows)

        plant_tick = safe_int(row.get("plant_tick"))
        rows.append({
            "round_num": rn,
            "plant_phase_label": label,
            "plant_phase_score": score,
            "categories": categories,
            "reasons": reasons,
            "round_result": safe_str(row.get("player_round_result")),
            "player_side": safe_str(row.get("player_side")),
            "bombsite": safe_str(row.get("bombsite")),
            "plant_tick": plant_tick,
            "alive_at_plant": bool(row.get("player_alive_at_plant")),
            "player_kills_after_plant": safe_int(row.get("player_kills_after_plant"), 0),
            "player_deaths_after_plant": safe_int(row.get("player_deaths_after_plant"), 0),
            "player_damage_postplant": safe_float(row.get("player_damage_postplant")),
            "postplant_utility_count": postplant_utility_count(utility_rows, plant_tick),
            "postplant_trade_problem_count": sum(
                1 for tr in trade_rows
                if bool(tr.get("is_problem")) and (
                    safe_str(tr.get("death_phase")) == "postplant"
                    or safe_str(tr.get("category")) == "postplant_death_untraded"
                )
            ),
        })

    return sorted(rows, key=lambda r: (-safe_int(r.get("plant_phase_score"), 0), safe_int(r.get("round_num"), 9999) or 9999))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(r.get("plant_phase_label") for r in rows)
    categories = Counter()
    for r in rows:
        for c in r.get("categories") or []:
            categories[c] += 1

    top = [
        {
            "round_num": r.get("round_num"),
            "plant_phase_label": r.get("plant_phase_label"),
            "plant_phase_score": r.get("plant_phase_score"),
            "categories": r.get("categories"),
            "round_result": r.get("round_result"),
            "side": r.get("player_side"),
            "postplant_kd_damage": f"{r.get('player_kills_after_plant')}/{r.get('player_deaths_after_plant')}/{r.get('player_damage_postplant')}",
            "reasons": r.get("reasons"),
        }
        for r in rows
        if safe_int(r.get("plant_phase_score"), 0) > 0
    ][:10]

    main_problem = ""
    problem_categories = {k: v for k, v in categories.items() if k != "positive_plant_phase"}
    if problem_categories:
        main_problem = Counter(problem_categories).most_common(1)[0][0]

    return {
        "version": VERSION,
        "plant_rounds_total": len(rows),
        "label_counts": dict(labels),
        "category_counts": dict(categories),
        "main_problem_category": main_problem,
        "top_problem_plant_rounds": top,
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
    utility_json = data_root / "layers" / args.match_id / "canonical_utility_timeline_v0_1.json"
    trade_json = data_root / "analysis" / args.match_id / f"trade_spacing_{args.player}_v0_1.json"

    print("=== Postplant Retake Analyzer v0.1 ===")
    print(f"Round layer: {round_json} exists={round_json.exists()}")
    print(f"Utility layer: {utility_json} exists={utility_json.exists()}")
    print(f"Trade spacing: {trade_json} exists={trade_json.exists()}")

    round_payload = load_json(round_json)
    utility_payload = load_json(utility_json)
    trade_payload = load_json(trade_json)

    rows = build(round_payload, utility_payload, trade_payload, args.player)
    summary = summarize(rows)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_layer": str(round_json),
            "utility_layer": str(utility_json),
            "trade_spacing": str(trade_json),
        },
        "summary": summary,
        "rows": rows,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"postplant_retake_{args.player}_v0_1.json"
    csv_path = out_dir / f"postplant_retake_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== POSTPLANT RETAKE ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
