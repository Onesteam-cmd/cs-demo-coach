from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, norm, write_csv, write_json, print_json


VERSION = "utility_value_analyzer_v0_1"


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


def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        try:
            return pd.read_csv(path, encoding="utf-8")
        except Exception:
            return pd.DataFrame()


def norm_col(value: Any) -> str:
    return safe_str(value).strip().lower().replace(" ", "_").replace("-", "_")


def get_col(row: pd.Series, aliases: list[str], default: Any = None) -> Any:
    cols = {norm_col(c): c for c in row.index}
    for alias in aliases:
        key = norm_col(alias)
        if key in cols:
            value = row.get(cols[key])
            try:
                if pd.isna(value):
                    return default
            except Exception:
                pass
            return value
    return default


def rows_by_round(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn].append(row)
    return out


def single_case_by_round(casebook: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for case in casebook.get("cases", []):
        rn = safe_int(case.get("round_num"))
        if rn is not None:
            out[rn] = case
    return out


def parse_manual_utility_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []

    if df.empty:
        return rows

    for idx, r in df.iterrows():
        round_num = safe_int(get_col(r, ["round_num", "round", "r"]))
        tick = safe_int(get_col(r, ["tick", "start_tick", "event_tick"]))

        if round_num is None:
            text = " ".join(safe_str(x) for x in r.values)
            import re
            m = re.search(r"\bR(\d+)\b", text, flags=re.IGNORECASE)
            if m:
                round_num = safe_int(m.group(1))

        utility_type = safe_str(get_col(r, ["utility_type", "type", "kind", "event_type"]))
        quality = safe_str(get_col(r, ["quality"]))
        problem = safe_str(get_col(r, ["problem"]))
        purpose = safe_str(get_col(r, ["intended_purpose", "purpose"]))
        keep = safe_str(get_col(r, ["keep_for_training"]))
        known_lineup = safe_str(get_col(r, ["known_lineup"]))

        if round_num is None and not quality and not problem:
            continue

        rows.append({
            "manual_event_id": f"manual_utility_{idx + 1}",
            "round_num": round_num,
            "tick": tick,
            "utility_type": utility_type,
            "quality": quality,
            "problem": problem,
            "purpose": purpose,
            "known_lineup": known_lineup,
            "keep_for_training": keep,
        })

    return rows


def utility_round_summary(utility_rows: list[dict[str, Any]], player: str) -> dict[str, Any]:
    p = norm(player)
    focus = [r for r in utility_rows if norm(r.get("player")) == p]

    kind_counts = Counter(safe_str(r.get("event_kind")) for r in focus)
    type_counts = Counter(safe_str(r.get("utility_type")) for r in focus if safe_str(r.get("event_kind")) == "grenade_throw")
    role_counts = Counter(safe_str(r.get("role")) for r in focus if safe_str(r.get("event_kind")) == "grenade_throw")

    throw_ticks = [safe_int(r.get("tick")) for r in focus if safe_str(r.get("event_kind")) == "grenade_throw" and safe_int(r.get("tick")) is not None]

    return {
        "events_total": len(focus),
        "grenade_throws": sum(type_counts.values()),
        "kind_counts": dict(kind_counts),
        "type_counts": dict(type_counts),
        "role_counts": dict(role_counts),
        "first_throw_tick": min(throw_ticks) if throw_ticks else None,
        "last_throw_tick": max(throw_ticks) if throw_ticks else None,
    }


def manual_round_summary(manual_rows: list[dict[str, Any]]) -> dict[str, Any]:
    quality = Counter(safe_str(r.get("quality")) or "unknown" for r in manual_rows)
    problem = Counter(safe_str(r.get("problem")) or "unknown" for r in manual_rows)
    purpose = Counter(safe_str(r.get("purpose")) or "unknown" for r in manual_rows)

    badish = [
        r for r in manual_rows
        if safe_str(r.get("quality")).lower() in {"partial", "bad"}
        or safe_str(r.get("problem")).lower() not in {"", "none", "unknown"}
    ]

    return {
        "manual_events_total": len(manual_rows),
        "quality_counts": dict(quality),
        "problem_counts": dict(problem),
        "purpose_counts": dict(purpose),
        "problem_events_total": len(badish),
        "problem_events": badish[:6],
    }


def postplant_utility_count(utility_rows: list[dict[str, Any]], plant_tick: int | None, player: str) -> int:
    if plant_tick is None:
        return 0

    p = norm(player)
    count = 0
    for row in utility_rows:
        if norm(row.get("player")) != p:
            continue
        tick = safe_int(row.get("tick"))
        if tick is not None and tick >= plant_tick:
            count += 1
    return count


def classify_round(case: dict[str, Any], utility_sum: dict[str, Any], manual_sum: dict[str, Any], player: str) -> tuple[list[str], int, list[str]]:
    tags: list[str] = []
    reasons: list[str] = []
    score = 0

    result = safe_str(case.get("round_result"))
    damage = safe_float(case.get("player_damage"))
    kills = safe_int(case.get("player_kills"), 0) or 0
    has_plant = bool(case.get("has_plant"))
    plant_score = safe_float(case.get("plant_phase", {}).get("plant_phase_score"))
    low_impact = result == "loss" and kills == 0 and damage < 40

    events_total = safe_int(utility_sum.get("events_total"), 0) or 0
    throws = safe_int(utility_sum.get("grenade_throws"), 0) or 0
    manual_problem_events = safe_int(manual_sum.get("problem_events_total"), 0) or 0

    if low_impact and events_total == 0:
        tags.append("no_utility_low_impact_loss")
        score += 18
        reasons.append("lost round with low impact and no utility event")

    if low_impact and events_total > 0:
        tags.append("utility_used_but_low_impact_loss")
        score += 10
        reasons.append("utility existed but round still had low personal impact")

    if manual_problem_events > 0:
        tags.append("manual_utility_problem")
        score += min(24, manual_problem_events * 8)
        reasons.append("manual utility review found partial/bad/problem events")

    problem_counts = manual_sum.get("problem_counts") or {}
    for problem_name in ["too_late", "gap", "no_value", "wrong_place"]:
        count = safe_int(problem_counts.get(problem_name), 0) or 0
        if count > 0:
            tags.append(f"utility_{problem_name}")
            score += min(15, count * 6)
            reasons.append(f"manual problem: {problem_name}")

    if has_plant and plant_score > 0:
        # This is deliberately simple in v0.1. We only flag possible plant-phase utility issue,
        # not a final diagnosis.
        tags.append("plant_phase_utility_context")
        score += 5
        reasons.append("plant phase problem exists; utility context should be reviewed")

    if result == "loss" and throws == 0 and damage < 60:
        tags.append("no_throw_low_value_loss")
        score += 6
        reasons.append("lost round without grenade throw and low/moderate damage")

    if not tags and events_total > 0:
        tags.append("utility_present_no_current_problem")
        reasons.append("utility was present; no current utility problem tag")

    if not tags:
        tags.append("no_utility_signal")
        reasons.append("no current utility signal")

    return list(dict.fromkeys(tags)), score, list(dict.fromkeys(reasons))


def build_rows(casebook: dict[str, Any], utility: dict[str, Any], manual_rows: list[dict[str, Any]], player: str) -> list[dict[str, Any]]:
    cases = single_case_by_round(casebook)
    utility_by_round = rows_by_round(utility.get("rows", []))

    manual_by_round: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in manual_rows:
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            manual_by_round[rn].append(row)

    all_rounds = sorted(set(cases.keys()) | set(utility_by_round.keys()) | set(manual_by_round.keys()))

    rows = []
    for rn in all_rounds:
        case = cases.get(rn, {})
        util_rows = utility_by_round.get(rn, [])
        man_rows = manual_by_round.get(rn, [])

        us = utility_round_summary(util_rows, player)
        ms = manual_round_summary(man_rows)
        tags, score, reasons = classify_round(case, us, ms, player)

        rows.append({
            "round_num": rn,
            "utility_value_tags": tags,
            "utility_value_score": score,
            "utility_value_reasons": reasons,
            "round_result": safe_str(case.get("round_result")),
            "case_label": safe_str(case.get("case_label")),
            "case_priority_score": safe_float(case.get("case_priority_score")),
            "player_kills": safe_int(case.get("player_kills"), 0),
            "player_deaths": safe_int(case.get("player_deaths"), 0),
            "player_damage": safe_float(case.get("player_damage")),
            "has_plant": bool(case.get("has_plant")),
            "plant_phase_score": safe_float(case.get("plant_phase", {}).get("plant_phase_score")),
            "utility_events_total": us.get("events_total"),
            "grenade_throws": us.get("grenade_throws"),
            "utility_type_counts": us.get("type_counts"),
            "utility_role_counts": us.get("role_counts"),
            "manual_utility_events": ms.get("manual_events_total"),
            "manual_quality_counts": ms.get("quality_counts"),
            "manual_problem_counts": ms.get("problem_counts"),
            "manual_problem_events_total": ms.get("problem_events_total"),
            "manual_problem_events": ms.get("problem_events"),
        })

    return sorted(rows, key=lambda r: (-safe_int(r.get("utility_value_score"), 0), safe_int(r.get("round_num"), 9999) or 9999))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tag_counts = Counter()
    quality_counts = Counter()
    problem_counts = Counter()

    for row in rows:
        for tag in row.get("utility_value_tags") or []:
            tag_counts[tag] += 1

        for k, v in (row.get("manual_quality_counts") or {}).items():
            quality_counts[k] += safe_int(v, 0) or 0

        for k, v in (row.get("manual_problem_counts") or {}).items():
            problem_counts[k] += safe_int(v, 0) or 0

    problem_rows = [
        r for r in rows
        if safe_int(r.get("utility_value_score"), 0) > 0
        and "utility_present_no_current_problem" not in (r.get("utility_value_tags") or [])
    ]

    return {
        "version": VERSION,
        "rounds_total": len(rows),
        "tag_counts": dict(tag_counts),
        "manual_quality_counts": dict(quality_counts),
        "manual_problem_counts": dict(problem_counts),
        "problem_rounds_total": len(problem_rows),
        "top_utility_problem_rounds": [
            {
                "round_num": r.get("round_num"),
                "score": r.get("utility_value_score"),
                "tags": r.get("utility_value_tags"),
                "round_result": r.get("round_result"),
                "kd_damage": f"{r.get('player_kills')}/{r.get('player_deaths')}/{r.get('player_damage')}",
                "reasons": r.get("utility_value_reasons"),
            }
            for r in problem_rows[:10]
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
    utility_json = data_root / "layers" / args.match_id / "canonical_utility_timeline_v0_1.json"
    manual_csv = data_root / "reviews" / args.match_id / f"utility_map_review_{args.player}_v0_1.csv"

    print("=== Utility Value Analyzer v0.1 ===")
    print(f"Round casebook: {casebook_json} exists={casebook_json.exists()}")
    print(f"Utility layer:  {utility_json} exists={utility_json.exists()}")
    print(f"Manual utility: {manual_csv} exists={manual_csv.exists()}")

    casebook = load_json(casebook_json)
    utility = load_json(utility_json)
    manual_df = read_csv_optional(manual_csv)
    manual_rows = parse_manual_utility_rows(manual_df)

    rows = build_rows(casebook, utility, manual_rows, args.player)
    summary = summarize(rows)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_casebook": str(casebook_json),
            "utility_layer": str(utility_json),
            "manual_utility_csv": str(manual_csv),
        },
        "summary": summary,
        "rows": rows,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"utility_value_{args.player}_v0_1.json"
    csv_path = out_dir / f"utility_value_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== UTILITY VALUE ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
