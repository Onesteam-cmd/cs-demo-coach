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


VERSION = "combat_profile_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def round_result_map(round_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for row in round_payload.get("rows", []):
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn] = row
    return out


def by_round(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn].append(row)
    return out


def build_round_rows(combat: dict[str, Any], round_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = round_result_map(round_payload)

    kill_by_round = by_round(combat.get("kills", []))
    damage_by_round = by_round(combat.get("damages", []))

    all_rounds = sorted(set(rounds.keys()) | set(kill_by_round.keys()) | set(damage_by_round.keys()))
    rows = []

    for rn in all_rounds:
        rr = rounds.get(rn, {})
        kills = kill_by_round.get(rn, [])
        damages = damage_by_round.get(rn, [])

        player_kills = [k for k in kills if k.get("player_role") == "kill"]
        player_deaths = [k for k in kills if k.get("player_role") == "death"]
        damage_dealt = [d for d in damages if d.get("player_role") == "damage_dealt"]
        damage_taken = [d for d in damages if d.get("player_role") == "damage_taken"]

        damage_total = round(sum(safe_float(d.get("damage_health")) for d in damage_dealt), 1)
        taken_total = round(sum(safe_float(d.get("damage_health")) for d in damage_taken), 1)

        hs_kills = sum(1 for k in player_kills if bool(k.get("headshot")))
        opening_kill = any(k.get("player_role") == "kill" and bool(k.get("is_opening_kill_event")) for k in kills)
        opening_death = any(k.get("player_role") == "death" and bool(k.get("is_opening_kill_event")) for k in kills)

        weapon_kills = Counter(k.get("weapon") for k in player_kills)
        weapon_deaths = Counter(k.get("weapon") for k in player_deaths)
        class_kills = Counter(k.get("weapon_class") for k in player_kills)
        class_deaths = Counter(k.get("weapon_class") for k in player_deaths)

        combat_label = "neutral"
        if len(player_kills) >= 2:
            combat_label = "multi_kill_round"
        elif opening_kill:
            combat_label = "opening_kill_round"
        elif opening_death:
            combat_label = "opening_death_round"
        elif len(player_kills) == 0 and damage_total < 40 and safe_str(rr.get("player_round_result")) == "loss":
            combat_label = "low_combat_impact_loss"
        elif len(player_deaths) > 0 and len(player_kills) == 0:
            combat_label = "death_no_kill"
        elif len(player_kills) > 0 and len(player_deaths) > 0:
            combat_label = "kill_and_death"
        elif len(player_kills) > 0:
            combat_label = "positive_combat"

        rows.append({
            "round_num": rn,
            "combat_label": combat_label,
            "round_result": safe_str(rr.get("player_round_result")),
            "player_side": safe_str(rr.get("player_side")),
            "has_plant": bool(rr.get("has_plant")),
            "opening_role": safe_str(rr.get("opening_role")),
            "death_phase": safe_str(rr.get("player_death_phase")),
            "kills": len(player_kills),
            "deaths": len(player_deaths),
            "damage_dealt": damage_total,
            "damage_taken": taken_total,
            "headshot_kills": hs_kills,
            "opening_kill": opening_kill,
            "opening_death": opening_death,
            "weapon_kill_counts": dict(weapon_kills),
            "weapon_death_counts": dict(weapon_deaths),
            "weapon_class_kill_counts": dict(class_kills),
            "weapon_class_death_counts": dict(class_deaths),
        })

    return sorted(rows, key=lambda r: (safe_int(r.get("round_num"), 9999) or 9999))


def weapon_rows(combat: dict[str, Any]) -> list[dict[str, Any]]:
    kills = combat.get("kills", [])
    damages = combat.get("damages", [])

    player_kills = [k for k in kills if k.get("player_role") == "kill"]
    player_deaths = [k for k in kills if k.get("player_role") == "death"]
    damage_dealt = [d for d in damages if d.get("player_role") == "damage_dealt"]
    damage_taken = [d for d in damages if d.get("player_role") == "damage_taken"]

    weapons = sorted(set(
        [safe_str(k.get("weapon")) for k in player_kills + player_deaths]
        + [safe_str(d.get("weapon")) for d in damage_dealt + damage_taken]
    ))

    rows = []
    for weapon in weapons:
        if not weapon:
            continue

        wk = [k for k in player_kills if safe_str(k.get("weapon")) == weapon]
        wd = [k for k in player_deaths if safe_str(k.get("weapon")) == weapon]
        dd = [d for d in damage_dealt if safe_str(d.get("weapon")) == weapon]
        dt = [d for d in damage_taken if safe_str(d.get("weapon")) == weapon]

        rows.append({
            "weapon": weapon,
            "weapon_class": safe_str((wk or wd or dd or dt)[0].get("weapon_class")),
            "kills": len(wk),
            "deaths": len(wd),
            "damage_dealt": round(sum(safe_float(d.get("damage_health")) for d in dd), 1),
            "damage_taken": round(sum(safe_float(d.get("damage_health")) for d in dt), 1),
            "headshot_kills": sum(1 for k in wk if bool(k.get("headshot"))),
        })

    return sorted(rows, key=lambda r: (-safe_int(r.get("kills"), 0), -safe_float(r.get("damage_dealt")), safe_str(r.get("weapon"))))


def summarize(round_rows: list[dict[str, Any]], weapon_rows_data: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(r.get("combat_label") for r in round_rows)
    results = Counter(r.get("round_result") for r in round_rows)

    total_kills = sum(safe_int(r.get("kills"), 0) or 0 for r in round_rows)
    total_deaths = sum(safe_int(r.get("deaths"), 0) or 0 for r in round_rows)
    total_damage = round(sum(safe_float(r.get("damage_dealt")) for r in round_rows), 1)
    total_taken = round(sum(safe_float(r.get("damage_taken")) for r in round_rows), 1)

    top_weapons = [
        {
            "weapon": w.get("weapon"),
            "kills": w.get("kills"),
            "deaths": w.get("deaths"),
            "damage_dealt": w.get("damage_dealt"),
        }
        for w in weapon_rows_data[:8]
    ]

    top_rounds = [
        {
            "round_num": r.get("round_num"),
            "combat_label": r.get("combat_label"),
            "round_result": r.get("round_result"),
            "kd_damage": f"{r.get('kills')}/{r.get('deaths')}/{r.get('damage_dealt')}",
            "opening_role": r.get("opening_role"),
        }
        for r in sorted(round_rows, key=lambda x: (-(safe_int(x.get("kills"), 0) or 0), -safe_float(x.get("damage_dealt")), safe_int(x.get("round_num"), 9999) or 9999))[:10]
    ]

    return {
        "version": VERSION,
        "rounds_total": len(round_rows),
        "combat_label_counts": dict(labels),
        "round_result_counts": dict(results),
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "total_damage_dealt": total_damage,
        "total_damage_taken": total_taken,
        "average_damage_per_round": round(total_damage / max(1, len(round_rows)), 1),
        "top_weapons": top_weapons,
        "top_combat_rounds": top_rounds,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    combat_json = data_root / "layers" / args.match_id / f"canonical_combat_events_{args.player}_v0_1.json"
    round_json = data_root / "layers" / args.match_id / f"canonical_round_timeline_{args.player}_v0_1.json"

    print("=== Combat Profile Analyzer v0.1 ===")
    print(f"Combat layer: {combat_json} exists={combat_json.exists()}")
    print(f"Round layer:  {round_json} exists={round_json.exists()}")

    combat = load_json(combat_json)
    round_payload = load_json(round_json)

    rounds = build_round_rows(combat, round_payload)
    weapons = weapon_rows(combat)
    summary = summarize(rounds, weapons)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "combat_layer": str(combat_json),
            "round_layer": str(round_json),
        },
        "summary": summary,
        "rounds": rounds,
        "weapons": weapons,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"combat_profile_{args.player}_v0_1.json"
    rounds_csv = out_dir / f"combat_profile_rounds_{args.player}_v0_1.csv"
    weapons_csv = out_dir / f"combat_profile_weapons_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(rounds_csv, rounds)
    write_csv(weapons_csv, weapons)

    print("")
    print("=== COMBAT PROFILE ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"Rounds CSV:  {rounds_csv}")
    print(f"Weapons CSV: {weapons_csv}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
