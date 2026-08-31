from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, norm, write_csv, write_json, print_json


VERSION = "canonical_area_events_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_area(value: Any) -> str:
    area = safe_str(value).strip()
    if not area:
        return "unknown"

    low = area.lower()
    if low in {"nan", "none", "null"}:
        return "unknown"

    return area


def round_context(round_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for row in round_payload.get("rows", []):
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn] = {
                "round_result": safe_str(row.get("player_round_result")),
                "player_side": safe_str(row.get("player_side")),
                "has_plant": bool(row.get("has_plant")),
                "bombsite": safe_str(row.get("bombsite")),
                "opening_role": safe_str(row.get("opening_role")),
                "death_phase": safe_str(row.get("player_death_phase")),
            }
    return out


def phase_context(phase_payload: dict[str, Any]) -> dict[tuple[int, int, str], str]:
    out = {}

    for event in phase_payload.get("events", []):
        rn = safe_int(event.get("round_num"))
        tick = safe_int(event.get("tick"))
        source = safe_str(event.get("event_source"))
        etype = safe_str(event.get("event_type"))

        if rn is None or tick is None:
            continue

        out[(rn, tick, source + ":" + etype)] = safe_str(event.get("phase"))

    return out


def add_round_ctx(row: dict[str, Any], rounds: dict[int, dict[str, Any]]) -> dict[str, Any]:
    rn = safe_int(row.get("round_num"))
    ctx = rounds.get(rn, {})
    out = dict(row)
    out.update({
        "round_result": ctx.get("round_result", ""),
        "player_side": ctx.get("player_side", ""),
        "has_plant": ctx.get("has_plant", False),
        "bombsite": ctx.get("bombsite", ""),
        "opening_role": ctx.get("opening_role", ""),
        "death_phase": ctx.get("death_phase", ""),
    })
    return out


def combat_area_events(combat: dict[str, Any], rounds: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for k in combat.get("kills", []):
        role = safe_str(k.get("player_role"))
        if role not in {"kill", "death"}:
            continue

        if role == "kill":
            player_area = normalize_area(k.get("attacker_place"))
            enemy_area = normalize_area(k.get("victim_place"))
            value_type = "positive"
        else:
            player_area = normalize_area(k.get("victim_place"))
            enemy_area = normalize_area(k.get("attacker_place"))
            value_type = "negative"

        row = {
            "event_id": safe_str(k.get("event_id")),
            "event_source": "combat",
            "event_type": role,
            "value_type": value_type,
            "round_num": safe_int(k.get("round_num")),
            "tick": safe_int(k.get("tick")),
            "player_area": player_area,
            "enemy_area": enemy_area,
            "area": player_area,
            "weapon": safe_str(k.get("weapon")),
            "weapon_class": safe_str(k.get("weapon_class")),
            "headshot": bool(k.get("headshot")),
            "details": {
                "attacker": k.get("attacker"),
                "victim": k.get("victim"),
                "attacker_side": k.get("attacker_side"),
                "victim_side": k.get("victim_side"),
                "is_opening_kill_event": k.get("is_opening_kill_event"),
            },
        }
        rows.append(add_round_ctx(row, rounds))

    for d in combat.get("damages", []):
        role = safe_str(d.get("player_role"))
        if role not in {"damage_dealt", "damage_taken"}:
            continue

        if role == "damage_dealt":
            player_area = normalize_area(d.get("attacker_place"))
            enemy_area = normalize_area(d.get("victim_place"))
            value_type = "positive"
        else:
            player_area = normalize_area(d.get("victim_place"))
            enemy_area = normalize_area(d.get("attacker_place"))
            value_type = "negative"

        row = {
            "event_id": safe_str(d.get("event_id")),
            "event_source": "combat",
            "event_type": role,
            "value_type": value_type,
            "round_num": safe_int(d.get("round_num")),
            "tick": safe_int(d.get("tick")),
            "player_area": player_area,
            "enemy_area": enemy_area,
            "area": player_area,
            "weapon": safe_str(d.get("weapon")),
            "weapon_class": safe_str(d.get("weapon_class")),
            "damage_health": safe_float(d.get("damage_health")),
            "details": {
                "attacker": d.get("attacker"),
                "victim": d.get("victim"),
                "hitgroup": d.get("hitgroup"),
            },
        }
        rows.append(add_round_ctx(row, rounds))

    return rows


def utility_area_events(utility: dict[str, Any], rounds: dict[int, dict[str, Any]], player: str) -> list[dict[str, Any]]:
    rows = []
    p = norm(player)

    for u in utility.get("rows", []):
        if norm(u.get("player")) != p:
            continue

        area = normalize_area(u.get("place"))

        row = {
            "event_id": f"utility_R{safe_int(u.get('round_num'))}_T{safe_int(u.get('tick'))}_{safe_str(u.get('event_kind'))}_{safe_str(u.get('entity_id'))}",
            "event_source": "utility",
            "event_type": safe_str(u.get("event_kind")),
            "value_type": "context",
            "round_num": safe_int(u.get("round_num")),
            "tick": safe_int(u.get("tick")),
            "player_area": area,
            "enemy_area": "",
            "area": area,
            "utility_type": safe_str(u.get("utility_type")),
            "utility_role": safe_str(u.get("role")),
            "details": {
                "end_tick": u.get("end_tick"),
                "x": u.get("x"),
                "y": u.get("y"),
                "z": u.get("z"),
            },
        }
        rows.append(add_round_ctx(row, rounds))

    return rows


def mechanics_area_events(mechanics: dict[str, Any], rounds: dict[int, dict[str, Any]], combat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    combat_by_round_tick: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for c in combat_rows:
        rn = safe_int(c.get("round_num"))
        tick = safe_int(c.get("tick"))
        if rn is None or tick is None:
            continue
        combat_by_round_tick.setdefault((rn, tick), []).append(c)

    for m in mechanics.get("rows", []):
        rn = safe_int(m.get("round_num"))
        tick = safe_int(m.get("tick"))

        inferred_area = "unknown"
        if rn is not None and tick is not None:
            nearest = []
            for c in combat_rows:
                crn = safe_int(c.get("round_num"))
                ctick = safe_int(c.get("tick"))
                if crn != rn or ctick is None:
                    continue
                delta = abs(ctick - tick)
                if delta <= 256:
                    nearest.append((delta, c))
            if nearest:
                inferred_area = normalize_area(sorted(nearest, key=lambda x: x[0])[0][1].get("area"))

        row = {
            "event_id": safe_str(m.get("event_id")),
            "event_source": "mechanics",
            "event_type": "mechanics_actionable" if bool(m.get("is_actionable")) else "mechanics_event",
            "value_type": "negative" if bool(m.get("is_actionable")) else "context",
            "round_num": rn,
            "tick": tick,
            "player_area": inferred_area,
            "enemy_area": "",
            "area": inferred_area,
            "root_cause": safe_str(m.get("root_cause")),
            "priority_score": safe_float(m.get("priority_score")),
            "details": {
                "real_issue": m.get("real_issue"),
                "keep_for_training": m.get("keep_for_training"),
                "aim_error_deg": m.get("aim_error_deg"),
                "speed": m.get("speed"),
            },
        }
        rows.append(add_round_ctx(row, rounds))

    return rows


def trade_area_events(trade: dict[str, Any], rounds: dict[int, dict[str, Any]], combat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for t in trade.get("rows", []):
        if safe_str(t.get("player_focus")) == "none":
            continue

        rn = safe_int(t.get("round_num"))
        tick = safe_int(t.get("kill_tick"))

        inferred_area = "unknown"
        if rn is not None and tick is not None:
            nearest = []
            for c in combat_rows:
                crn = safe_int(c.get("round_num"))
                ctick = safe_int(c.get("tick"))
                if crn != rn or ctick is None:
                    continue
                delta = abs(ctick - tick)
                if delta <= 64:
                    nearest.append((delta, c))
            if nearest:
                inferred_area = normalize_area(sorted(nearest, key=lambda x: x[0])[0][1].get("area"))

        row = {
            "event_id": f"trade_R{rn}_T{tick}_{safe_str(t.get('category'))}",
            "event_source": "trade_spacing",
            "event_type": safe_str(t.get("category")),
            "value_type": "negative" if bool(t.get("is_problem")) else "positive",
            "round_num": rn,
            "tick": tick,
            "player_area": inferred_area,
            "enemy_area": "",
            "area": inferred_area,
            "priority_score": safe_float(t.get("priority_score")),
            "details": {
                "severity": t.get("severity"),
                "reasons": t.get("reasons"),
                "trade_delay_ticks": t.get("trade_delay_ticks"),
            },
        }
        rows.append(add_round_ctx(row, rounds))

    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    area_counts = Counter(safe_str(r.get("area")) for r in rows)
    negative_area_counts = Counter(safe_str(r.get("area")) for r in rows if r.get("value_type") == "negative")
    positive_area_counts = Counter(safe_str(r.get("area")) for r in rows if r.get("value_type") == "positive")
    utility_area_counts = Counter(safe_str(r.get("area")) for r in rows if r.get("event_source") == "utility")

    problem_rows = [
        r for r in rows
        if r.get("value_type") == "negative"
        and safe_str(r.get("area")) not in {"", "unknown"}
    ]

    top_problem_areas = []
    for area, count in negative_area_counts.most_common(10):
        if area in {"", "unknown"}:
            continue
        area_rows = [r for r in problem_rows if safe_str(r.get("area")) == area]
        top_problem_areas.append({
            "area": area,
            "negative_events": count,
            "positive_events": positive_area_counts.get(area, 0),
            "utility_events": utility_area_counts.get(area, 0),
            "source_counts": dict(Counter(r.get("event_source") for r in area_rows)),
            "event_type_counts": dict(Counter(r.get("event_type") for r in area_rows)),
            "rounds": sorted(set(safe_int(r.get("round_num")) for r in area_rows if safe_int(r.get("round_num")) is not None))[:10],
        })

    return {
        "version": VERSION,
        "area_events_total": len(rows),
        "area_counts": dict(area_counts),
        "negative_area_counts": dict(negative_area_counts),
        "positive_area_counts": dict(positive_area_counts),
        "utility_area_counts": dict(utility_area_counts),
        "top_problem_areas": top_problem_areas,
    }


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
        "combat": data_root / "layers" / args.match_id / f"canonical_combat_events_{args.player}_v0_1.json",
        "utility": data_root / "layers" / args.match_id / "canonical_utility_timeline_v0_1.json",
        "mechanics": data_root / "layers" / args.match_id / f"canonical_mechanics_events_{args.player}_v0_1.json",
        "trade": data_root / "analysis" / args.match_id / f"trade_spacing_{args.player}_v0_1.json",
    }

    print("=== Canonical Area Events v0.1 ===")
    for name, path in paths.items():
        print(f"{name}: {path} exists={path.exists()}")

    round_payload = load_json(paths["round"])
    combat_payload = load_json(paths["combat"])
    utility_payload = load_json(paths["utility"])
    mechanics_payload = load_json(paths["mechanics"])
    trade_payload = load_json(paths["trade"])

    rounds = round_context(round_payload)

    combat_rows = combat_area_events(combat_payload, rounds)

    rows = []
    rows.extend(combat_rows)
    rows.extend(utility_area_events(utility_payload, rounds, args.player))
    rows.extend(mechanics_area_events(mechanics_payload, rounds, combat_rows))
    rows.extend(trade_area_events(trade_payload, rounds, combat_rows))

    rows = sorted(rows, key=lambda r: (
        safe_int(r.get("round_num"), 9999) or 9999,
        safe_int(r.get("tick"), 999999999) or 999999999,
        safe_str(r.get("event_source")),
    ))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) for k, v in paths.items()},
        "summary": summarize(rows),
        "rows": rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_area_events_{args.player}_v0_1.json"
    csv_path = out_dir / f"canonical_area_events_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== CANONICAL AREA EVENTS v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()

