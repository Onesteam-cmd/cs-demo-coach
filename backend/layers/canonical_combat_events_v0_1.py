from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import (
    find_parquet,
    first_col,
    norm,
    read_parquet_optional,
    round_col,
    safe_float,
    safe_int,
    safe_str,
    write_csv,
    write_json,
    print_json,
)


VERSION = "canonical_combat_events_v0_1"


def normalize_weapon(value: Any) -> str:
    w = safe_str(value).strip()
    low = w.lower()

    if not low:
        return ""

    replacements = {
        "weapon_ak47": "AK-47",
        "ak47": "AK-47",
        "weapon_m4a1": "M4A1",
        "weapon_m4a1_silencer": "M4A1-S",
        "weapon_awp": "AWP",
        "weapon_deagle": "Desert Eagle",
        "weapon_glock": "Glock",
        "weapon_usp_silencer": "USP-S",
        "weapon_hkp2000": "P2000",
        "weapon_galilar": "Galil AR",
        "weapon_famas": "FAMAS",
        "weapon_mp9": "MP9",
        "weapon_mac10": "MAC-10",
    }

    return replacements.get(low, w)


def weapon_class(weapon: str) -> str:
    low = safe_str(weapon).lower()

    if any(x in low for x in ["ak", "m4", "galil", "famas", "aug", "sg"]):
        return "rifle"
    if "awp" in low or "ssg" in low or "scar" in low or "g3sg1" in low:
        return "sniper"
    if any(x in low for x in ["glock", "usp", "p2000", "deagle", "elite", "p250", "tec", "five", "cz"]):
        return "pistol"
    if any(x in low for x in ["mp9", "mac", "mp7", "mp5", "ump", "p90", "bizon"]):
        return "smg"
    if any(x in low for x in ["nova", "xm", "mag", "sawed"]):
        return "shotgun"
    if any(x in low for x in ["hegrenade", "inferno", "molotov", "incendiary", "flash", "smoke"]):
        return "utility"
    if "knife" in low:
        return "knife"

    return "other"


def compact_kill(row: pd.Series, player: str) -> dict[str, Any]:
    p = norm(player)

    attacker = safe_str(row.get("attacker_name"))
    victim = safe_str(row.get("victim_name"))
    weapon = normalize_weapon(row.get("weapon"))

    if norm(attacker) == p:
        role = "kill"
    elif norm(victim) == p:
        role = "death"
    else:
        role = "other"

    return {
        "event_id": f"kill_R{safe_int(row.get('round_num'))}_T{safe_int(row.get('tick'))}_{attacker}->{victim}",
        "event_type": "kill",
        "round_num": safe_int(row.get("round_num")),
        "tick": safe_int(row.get("tick")),
        "player_role": role,
        "attacker": attacker,
        "victim": victim,
        "weapon": weapon,
        "weapon_class": weapon_class(weapon),
        "headshot": bool(row.get("headshot")) if "headshot" in row.index else False,
        "attacker_side": safe_str(row.get("attacker_side")),
        "victim_side": safe_str(row.get("victim_side")),
        "attacker_place": safe_str(row.get("attacker_place")),
        "victim_place": safe_str(row.get("victim_place")),
        "attacker_x": safe_float(row.get("attacker_X")),
        "attacker_y": safe_float(row.get("attacker_Y")),
        "attacker_z": safe_float(row.get("attacker_Z")),
        "victim_x": safe_float(row.get("victim_X")),
        "victim_y": safe_float(row.get("victim_Y")),
        "victim_z": safe_float(row.get("victim_Z")),
    }


def compact_damage(row: pd.Series, player: str) -> dict[str, Any]:
    p = norm(player)

    attacker = safe_str(row.get("attacker_name"))
    victim = safe_str(row.get("victim_name"))
    weapon = normalize_weapon(row.get("weapon"))

    if norm(attacker) == p:
        role = "damage_dealt"
    elif norm(victim) == p:
        role = "damage_taken"
    else:
        role = "other"

    dmg_col = "dmg_health_real" if "dmg_health_real" in row.index else "dmg_health"

    return {
        "event_id": f"damage_R{safe_int(row.get('round_num'))}_T{safe_int(row.get('tick'))}_{attacker}->{victim}",
        "event_type": "damage",
        "round_num": safe_int(row.get("round_num")),
        "tick": safe_int(row.get("tick")),
        "player_role": role,
        "attacker": attacker,
        "victim": victim,
        "weapon": weapon,
        "weapon_class": weapon_class(weapon),
        "hitgroup": safe_str(row.get("hitgroup")),
        "damage_health": safe_float(row.get(dmg_col)),
        "damage_armor": safe_float(row.get("dmg_armor")),
        "attacker_side": safe_str(row.get("attacker_side")),
        "victim_side": safe_str(row.get("victim_side")),
        "attacker_place": safe_str(row.get("attacker_place")),
        "victim_place": safe_str(row.get("victim_place")),
        "attacker_x": safe_float(row.get("attacker_X")),
        "attacker_y": safe_float(row.get("attacker_Y")),
        "attacker_z": safe_float(row.get("attacker_Z")),
        "victim_x": safe_float(row.get("victim_X")),
        "victim_y": safe_float(row.get("victim_Y")),
        "victim_z": safe_float(row.get("victim_Z")),
    }


def add_opening_and_multikill_flags(kill_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_round: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for row in kill_rows:
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            by_round[rn].append(row)

    out = []

    for rn, rows in by_round.items():
        ordered = sorted(rows, key=lambda r: safe_int(r.get("tick"), 999999999) or 999999999)
        player_kills = 0
        player_deaths = 0

        for idx, row in enumerate(ordered):
            row = dict(row)
            row["is_opening_kill_event"] = idx == 0

            if row.get("player_role") == "kill":
                player_kills += 1
                row["player_kill_number_in_round"] = player_kills
            else:
                row["player_kill_number_in_round"] = None

            if row.get("player_role") == "death":
                player_deaths += 1
                row["player_death_number_in_round"] = player_deaths
            else:
                row["player_death_number_in_round"] = None

            out.append(row)

    return sorted(out, key=lambda r: (safe_int(r.get("round_num"), 9999) or 9999, safe_int(r.get("tick"), 999999999) or 999999999))


def summarize(kills: list[dict[str, Any]], damages: list[dict[str, Any]]) -> dict[str, Any]:
    player_kills = [r for r in kills if r.get("player_role") == "kill"]
    player_deaths = [r for r in kills if r.get("player_role") == "death"]
    damage_dealt = [r for r in damages if r.get("player_role") == "damage_dealt"]
    damage_taken = [r for r in damages if r.get("player_role") == "damage_taken"]

    weapon_kills = Counter(r.get("weapon") for r in player_kills)
    weapon_deaths = Counter(r.get("weapon") for r in player_deaths)
    class_kills = Counter(r.get("weapon_class") for r in player_kills)
    class_deaths = Counter(r.get("weapon_class") for r in player_deaths)

    hs_kills = sum(1 for r in player_kills if bool(r.get("headshot")))
    opening_kills = sum(1 for r in player_kills if bool(r.get("is_opening_kill_event")))
    opening_deaths = sum(1 for r in player_deaths if bool(r.get("is_opening_kill_event")))

    multi_kill_rounds = Counter()
    kills_by_round = Counter(safe_int(r.get("round_num")) for r in player_kills)
    for rn, count in kills_by_round.items():
        if count >= 2:
            multi_kill_rounds[str(rn)] = count

    total_damage_dealt = round(sum(safe_float(r.get("damage_health")) for r in damage_dealt), 1)
    total_damage_taken = round(sum(safe_float(r.get("damage_health")) for r in damage_taken), 1)

    return {
        "version": VERSION,
        "kill_events_total": len(kills),
        "damage_events_total": len(damages),
        "player_kills": len(player_kills),
        "player_deaths": len(player_deaths),
        "player_kd": f"{len(player_kills)}/{len(player_deaths)}",
        "player_damage_dealt": total_damage_dealt,
        "player_damage_taken": total_damage_taken,
        "player_headshot_kills": hs_kills,
        "player_headshot_kill_rate": round(hs_kills / max(1, len(player_kills)), 3),
        "player_opening_kills": opening_kills,
        "player_opening_deaths": opening_deaths,
        "player_weapon_kill_counts": dict(weapon_kills),
        "player_weapon_death_counts": dict(weapon_deaths),
        "player_weapon_class_kill_counts": dict(class_kills),
        "player_weapon_class_death_counts": dict(class_deaths),
        "player_multikill_rounds": dict(multi_kill_rounds),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    kills_path = find_parquet(data_root, args.match_id, "kills.parquet")
    damages_path = find_parquet(data_root, args.match_id, "damages.parquet")

    print("=== Canonical Combat Events v0.1 ===")
    print(f"Kills:   {kills_path if kills_path else 'MISSING'}")
    print(f"Damages: {damages_path if damages_path else 'MISSING'}")

    kills_df = read_parquet_optional(kills_path)
    damages_df = read_parquet_optional(damages_path)

    if kills_df.empty:
        raise SystemExit("kills.parquet missing or empty")
    if damages_df.empty:
        raise SystemExit("damages.parquet missing or empty")

    if "round_num" not in kills_df.columns:
        rc = round_col(kills_df)
        if not rc:
            raise SystemExit("No round column in kills")
        kills_df = kills_df.rename(columns={rc: "round_num"})

    if "round_num" not in damages_df.columns:
        rc = round_col(damages_df)
        if not rc:
            raise SystemExit("No round column in damages")
        damages_df = damages_df.rename(columns={rc: "round_num"})

    kill_rows = [compact_kill(row, args.player) for _, row in kills_df.iterrows()]
    kill_rows = add_opening_and_multikill_flags(kill_rows)

    damage_rows = [compact_damage(row, args.player) for _, row in damages_df.iterrows()]
    damage_rows = sorted(damage_rows, key=lambda r: (safe_int(r.get("round_num"), 9999) or 9999, safe_int(r.get("tick"), 999999999) or 999999999))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "kills": str(kills_path),
            "damages": str(damages_path),
        },
        "summary": summarize(kill_rows, damage_rows),
        "kills": kill_rows,
        "damages": damage_rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_combat_events_{args.player}_v0_1.json"
    kill_csv = out_dir / f"canonical_combat_kills_{args.player}_v0_1.csv"
    damage_csv = out_dir / f"canonical_combat_damages_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(kill_csv, kill_rows)
    write_csv(damage_csv, damage_rows)

    print("")
    print("=== CANONICAL COMBAT EVENTS v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"Kills CSV:   {kill_csv}")
    print(f"Damages CSV: {damage_csv}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
