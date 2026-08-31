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


VERSION = "loss_pattern_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def dict_count_value(d: Any, keys: list[str]) -> int:
    if not isinstance(d, dict):
        return 0
    total = 0
    for k in keys:
        total += safe_int(d.get(k), 0) or 0
    return total


def case_tags(case: dict[str, Any]) -> tuple[list[str], dict[str, float], list[str]]:
    tags: list[str] = []
    weights: dict[str, float] = defaultdict(float)
    reasons: list[str] = []

    mechanics = case.get("mechanics") or {}
    trade = case.get("trade_spacing") or {}
    utility = case.get("utility") or {}
    impact = case.get("round_impact") or {}
    plant = case.get("plant_phase") or {}

    mechanics_roots = mechanics.get("actionable_root_cause_counts") or {}
    trade_problem_categories = trade.get("problem_category_counts") or {}
    impact_categories = impact.get("problem_categories") or []
    plant_categories = plant.get("categories") or []

    mechanics_first = dict_count_value(mechanics_roots, ["large_first_shot_error", "bad_pre_aim", "bad_counter_strafe"])
    if mechanics_first > 0:
        tags.append("mechanics_first_shot")
        weights["mechanics_first_shot"] += 12 * mechanics_first
        reasons.append("actionable mechanics issue in round")

    mechanics_other = safe_int(mechanics.get("actionable_count"), 0) or 0
    if mechanics_other > mechanics_first:
        tags.append("mechanics_other")
        weights["mechanics_other"] += 6 * (mechanics_other - mechanics_first)
        reasons.append("other actionable mechanics issue")

    trade_problems = safe_int(trade.get("problem_events_total"), 0) or 0
    if trade_problems > 0:
        tags.append("trade_spacing")
        weights["trade_spacing"] += 12 * trade_problems
        reasons.append("trade spacing problem")

    if dict_count_value(trade_problem_categories, ["death_untraded", "preplant_death_untraded", "postplant_death_untraded", "opening_death_untraded"]) > 0:
        tags.append("untraded_death")
        weights["untraded_death"] += 10
        reasons.append("death not traded")

    if dict_count_value(trade_problem_categories, ["kill_traded_by_enemy", "opening_kill_traded"]) > 0:
        tags.append("kill_then_traded")
        weights["kill_then_traded"] += 8
        reasons.append("player kill was quickly traded by enemy")

    if "low_impact_loss" in impact_categories or safe_str(case.get("case_label")) in {"low_signal_loss", "problem_loss", "major_problem_loss"}:
        if safe_float(case.get("player_damage")) < 40 and safe_int(case.get("player_kills"), 0) == 0:
            tags.append("low_impact")
            weights["low_impact"] += 14
            reasons.append("low kill/damage impact in lost round")

    if safe_str(case.get("opening_role")) == "opening_death":
        tags.append("opening_death")
        weights["opening_death"] += 16
        reasons.append("opening death")

    if safe_str(case.get("death_phase")) == "preplant" and safe_str(case.get("round_result")) == "loss":
        tags.append("preplant_death")
        weights["preplant_death"] += 8
        reasons.append("preplant death in lost round")

    plant_score = safe_float(plant.get("plant_phase_score"))
    if plant_score > 0:
        tags.append("plant_phase")
        weights["plant_phase"] += min(20, plant_score)
        reasons.append("plant phase problem")

    if "retake_no_impact" in plant_categories:
        tags.append("retake_no_impact")
        weights["retake_no_impact"] += 12
        reasons.append("retake no impact")

    if "postplant_no_impact" in plant_categories:
        tags.append("postplant_no_impact")
        weights["postplant_no_impact"] += 12
        reasons.append("postplant no impact")

    utility_events = safe_int(utility.get("events_total"), 0) or 0
    if utility_events == 0 and safe_float(case.get("player_damage")) < 40 and safe_str(case.get("round_result")) == "loss":
        tags.append("no_utility_low_impact")
        weights["no_utility_low_impact"] += 6
        reasons.append("low impact lost round with no utility event")

    if not tags:
        tags.append("unclassified_loss")
        weights["unclassified_loss"] += 1
        reasons.append("loss has no strong current tag")

    tags = list(dict.fromkeys(tags))
    reasons = list(dict.fromkeys(reasons))
    return tags, dict(weights), reasons


def primary_pattern(weights: dict[str, float]) -> str:
    if not weights:
        return "unclassified_loss"
    return sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def title_for_pattern(pattern: str) -> str:
    return {
        "mechanics_first_shot": "Проигранные раунды через качество первого выстрела",
        "trade_spacing": "Проигранные раунды через плохой trade spacing",
        "untraded_death": "Проигранные раунды через смерть без размена",
        "kill_then_traded": "Проигранные раунды, где kill не сохраняет advantage",
        "low_impact": "Проигранные раунды с низким личным impact",
        "opening_death": "Проигранные раунды из-за opening death",
        "preplant_death": "Проигранные раунды со смертью до plant",
        "plant_phase": "Проигранные plant-phase раунды",
        "retake_no_impact": "Retake без impact",
        "postplant_no_impact": "Post-plant без impact",
        "no_utility_low_impact": "Низкий impact без utility-value",
        "mechanics_other": "Другие mechanics-проблемы",
        "unclassified_loss": "Не классифицированный проигранный раунд",
    }.get(pattern, pattern)


def build_rows(casebook: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    for case in casebook.get("cases", []):
        if safe_str(case.get("round_result")) != "loss":
            continue

        tags, weights, reasons = case_tags(case)
        primary = primary_pattern(weights)

        rows.append({
            "round_num": safe_int(case.get("round_num")),
            "primary_loss_pattern": primary,
            "primary_loss_title": title_for_pattern(primary),
            "loss_tags": tags,
            "loss_tag_weights": weights,
            "loss_reasons": reasons,
            "case_label": safe_str(case.get("case_label")),
            "case_priority_score": safe_float(case.get("case_priority_score")),
            "player_side": safe_str(case.get("player_side")),
            "has_plant": bool(case.get("has_plant")),
            "bombsite": safe_str(case.get("bombsite")),
            "opening_role": safe_str(case.get("opening_role")),
            "death_phase": safe_str(case.get("death_phase")),
            "player_kills": safe_int(case.get("player_kills"), 0),
            "player_deaths": safe_int(case.get("player_deaths"), 0),
            "player_damage": safe_float(case.get("player_damage")),
            "mechanics_actionable": safe_int(case.get("mechanics", {}).get("actionable_count"), 0),
            "trade_problem_events": safe_int(case.get("trade_spacing", {}).get("problem_events_total"), 0),
            "utility_events": safe_int(case.get("utility", {}).get("events_total"), 0),
            "impact_problem_score": safe_float(case.get("round_impact", {}).get("problem_score")),
            "plant_phase_score": safe_float(case.get("plant_phase", {}).get("plant_phase_score")),
        })

    return sorted(rows, key=lambda r: (-safe_float(r.get("case_priority_score")), safe_int(r.get("round_num"), 9999) or 9999))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    primary_counts = Counter(r.get("primary_loss_pattern") for r in rows)
    tag_counts = Counter()

    for r in rows:
        for tag in r.get("loss_tags") or []:
            tag_counts[tag] += 1

    pattern_blocks = []
    by_pattern: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for r in rows:
        by_pattern[safe_str(r.get("primary_loss_pattern"))].append(r)

    for pattern, items in sorted(by_pattern.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        pattern_blocks.append({
            "pattern": pattern,
            "title": title_for_pattern(pattern),
            "rounds_count": len(items),
            "rounds": [safe_int(x.get("round_num")) for x in items[:10]],
            "avg_case_priority": round(sum(safe_float(x.get("case_priority_score")) for x in items) / max(1, len(items)), 1),
            "avg_damage": round(sum(safe_float(x.get("player_damage")) for x in items) / max(1, len(items)), 1),
        })

    return {
        "version": VERSION,
        "loss_rounds_total": len(rows),
        "primary_pattern_counts": dict(primary_counts),
        "loss_tag_counts": dict(tag_counts),
        "top_loss_patterns": pattern_blocks[:8],
        "top_loss_rounds": [
            {
                "round_num": r.get("round_num"),
                "primary_loss_pattern": r.get("primary_loss_pattern"),
                "case_priority_score": r.get("case_priority_score"),
                "kd_damage": f"{r.get('player_kills')}/{r.get('player_deaths')}/{r.get('player_damage')}",
                "reasons": r.get("loss_reasons"),
            }
            for r in rows[:10]
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

    casebook_json = data_root / "cases" / args.match_id / f"round_cases_{args.player}_v0_1.json"

    print("=== Loss Pattern Analyzer v0.1 ===")
    print(f"Round casebook: {casebook_json} exists={casebook_json.exists()}")

    casebook = load_json(casebook_json)
    rows = build_rows(casebook)
    summary = summarize(rows)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_casebook": str(casebook_json),
        },
        "summary": summary,
        "rows": rows,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"loss_patterns_{args.player}_v0_1.json"
    csv_path = out_dir / f"loss_patterns_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== LOSS PATTERN ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
