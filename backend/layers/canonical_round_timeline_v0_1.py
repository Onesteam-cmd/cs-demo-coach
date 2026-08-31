from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import (
    filter_round,
    find_parquet,
    first_col,
    norm,
    normalize_grenade_type,
    print_json,
    read_parquet_optional,
    round_col,
    safe_float,
    safe_int,
    safe_str,
    write_csv,
    write_json,
)


VERSION = "canonical_round_timeline_v0_1"


def infer_player_side(player: str, rkills: pd.DataFrame, rdamages: pd.DataFrame) -> str:
    p = norm(player)
    sides: list[str] = []

    for _, row in rkills.iterrows():
        if norm(row.get("attacker_name")) == p:
            s = safe_str(row.get("attacker_side"))
            if s:
                sides.append(s)
        if norm(row.get("victim_name")) == p:
            s = safe_str(row.get("victim_side"))
            if s:
                sides.append(s)

    for _, row in rdamages.iterrows():
        if norm(row.get("attacker_name")) == p:
            s = safe_str(row.get("attacker_side"))
            if s:
                sides.append(s)
        if norm(row.get("victim_name")) == p:
            s = safe_str(row.get("victim_side"))
            if s:
                sides.append(s)

    if not sides:
        return ""

    return Counter(sides).most_common(1)[0][0]


def detect_plant(round_row: pd.Series, rbomb: pd.DataFrame) -> dict[str, Any]:
    result = {
        "has_plant": False,
        "plant_tick": None,
        "plant_event": "",
        "bombsite": safe_str(round_row.get("bomb_site") or round_row.get("bombsite")),
    }

    if not rbomb.empty:
        event_col = first_col(rbomb, ["event", "bomb_event", "type"])
        tick_col = first_col(rbomb, ["tick", "start_tick"])
        site_col = first_col(rbomb, ["bombsite", "bomb_site", "site"])

        if event_col and tick_col:
            plant_rows = []
            for _, row in rbomb.iterrows():
                ev = safe_str(row.get(event_col)).lower()
                if "plant" in ev:
                    plant_rows.append(row)

            if plant_rows:
                chosen = sorted(plant_rows, key=lambda r: safe_int(r.get(tick_col), 10**18) or 10**18)[0]
                result["has_plant"] = True
                result["plant_tick"] = safe_int(chosen.get(tick_col))
                result["plant_event"] = safe_str(chosen.get(event_col))
                if site_col:
                    result["bombsite"] = safe_str(chosen.get(site_col)) or result["bombsite"]

    if not result["has_plant"]:
        bp = safe_int(round_row.get("bomb_plant"))
        if bp is not None and bp > 0:
            result["has_plant"] = True
            result["plant_tick"] = bp
            result["plant_event"] = "rounds.bomb_plant"

    return result


def compact_kill(row: pd.Series) -> dict[str, Any]:
    return {
        "tick": safe_int(row.get("tick")),
        "attacker": safe_str(row.get("attacker_name")),
        "victim": safe_str(row.get("victim_name")),
        "weapon": safe_str(row.get("weapon")),
        "headshot": bool(row.get("headshot")) if "headshot" in row.index else False,
        "attacker_side": safe_str(row.get("attacker_side")),
        "victim_side": safe_str(row.get("victim_side")),
    }


def damage_by_player(rdamages: pd.DataFrame, player: str, as_attacker: bool, tick_from: int | None = None, tick_to: int | None = None) -> float:
    if rdamages.empty:
        return 0.0

    dmg_col = first_col(rdamages, ["dmg_health_real", "dmg_health"])
    if not dmg_col:
        return 0.0

    d = rdamages
    if "tick" in d.columns:
        if tick_from is not None:
            d = d[d["tick"] >= tick_from]
        if tick_to is not None:
            d = d[d["tick"] <= tick_to]

    p = norm(player)
    name_col = "attacker_name" if as_attacker else "victim_name"

    total = 0.0
    for _, row in d.iterrows():
        if norm(row.get(name_col)) == p:
            total += safe_float(row.get(dmg_col))

    return round(total, 1)


def first_player_damage_tick(rdamages: pd.DataFrame, player: str, as_attacker: bool) -> int | None:
    if rdamages.empty or "tick" not in rdamages.columns:
        return None

    p = norm(player)
    name_col = "attacker_name" if as_attacker else "victim_name"
    ticks = []

    for _, row in rdamages.iterrows():
        if norm(row.get(name_col)) == p:
            t = safe_int(row.get("tick"))
            if t is not None:
                ticks.append(t)

    return min(ticks) if ticks else None


def count_player_utility(rgrenades: pd.DataFrame, rsmokes: pd.DataFrame, rinfernos: pd.DataFrame, player: str) -> dict[str, Any]:
    p = norm(player)
    type_counts = Counter()

    if not rgrenades.empty:
        thrower_col = first_col(rgrenades, ["thrower", "thrower_name"])
        type_col = first_col(rgrenades, ["grenade_type", "type"])
        entity_col = first_col(rgrenades, ["entity_id"])

        if thrower_col and type_col:
            g = rgrenades[rgrenades[thrower_col].map(norm) == p].copy()
            if not g.empty and entity_col:
                if "tick" in g.columns:
                    g = g.sort_values("tick").groupby(entity_col, as_index=False).first()
                else:
                    g = g.groupby(entity_col, as_index=False).first()

            for _, row in g.iterrows():
                type_counts[normalize_grenade_type(row.get(type_col))] += 1

    smoke_count = 0
    if not rsmokes.empty:
        thrower_col = first_col(rsmokes, ["thrower_name", "thrower"])
        if thrower_col:
            smoke_count = int((rsmokes[thrower_col].map(norm) == p).sum())

    inferno_count = 0
    if not rinfernos.empty:
        thrower_col = first_col(rinfernos, ["thrower_name", "thrower"])
        if thrower_col:
            inferno_count = int((rinfernos[thrower_col].map(norm) == p).sum())

    return {
        "grenade_throw_counts": dict(type_counts),
        "grenade_throws_total": int(sum(type_counts.values())),
        "smokes_active_count": smoke_count,
        "infernos_active_count": inferno_count,
    }


def phase_from_tick(tick: int | None, plant_tick: int | None) -> str:
    if tick is None:
        return "none"
    if plant_tick is None:
        return "nonplant"
    if tick < plant_tick:
        return "preplant"
    return "postplant"


def analyze_round(
    round_row: pd.Series,
    player: str,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    bomb: pd.DataFrame,
    grenades: pd.DataFrame,
    smokes: pd.DataFrame,
    infernos: pd.DataFrame,
) -> dict[str, Any]:
    round_num = safe_int(round_row.get("round_num"), -1) or -1

    rkills = filter_round(kills, round_num)
    rdamages = filter_round(damages, round_num)
    rbomb = filter_round(bomb, round_num)
    rgrenades = filter_round(grenades, round_num)
    rsmokes = filter_round(smokes, round_num)
    rinfernos = filter_round(infernos, round_num)

    if not rkills.empty and "tick" in rkills.columns:
        rkills = rkills.sort_values("tick")

    plant = detect_plant(round_row, rbomb)
    plant_tick = plant.get("plant_tick")

    player_side = infer_player_side(player, rkills, rdamages)
    winner = safe_str(round_row.get("winner"))
    player_round_result = "unknown"
    if player_side and winner:
        player_round_result = "win" if player_side.lower() == winner.lower() else "loss"

    p = norm(player)
    kill_events = [compact_kill(row) for _, row in rkills.iterrows()]
    player_kills = [k for k in kill_events if norm(k.get("attacker")) == p]
    player_deaths = [k for k in kill_events if norm(k.get("victim")) == p]

    player_death_tick = player_deaths[0].get("tick") if player_deaths else None
    player_first_kill_tick = player_kills[0].get("tick") if player_kills else None

    alive_at_plant = False
    if plant.get("has_plant"):
        if player_death_tick is None:
            alive_at_plant = True
        elif plant_tick is not None:
            alive_at_plant = player_death_tick > plant_tick

    kills_before_plant = len(player_kills)
    kills_after_plant = 0
    deaths_before_plant = 0
    deaths_after_plant = 0

    if plant_tick is not None:
        kills_after_plant = sum(1 for k in player_kills if k.get("tick") is not None and k.get("tick") >= plant_tick)
        kills_before_plant = len(player_kills) - kills_after_plant
        deaths_after_plant = sum(1 for k in player_deaths if k.get("tick") is not None and k.get("tick") >= plant_tick)
        deaths_before_plant = len(player_deaths) - deaths_after_plant

    first_round_kill = kill_events[0] if kill_events else None
    opening_role = "none"
    if first_round_kill:
        if norm(first_round_kill.get("attacker")) == p:
            opening_role = "opening_kill"
        elif norm(first_round_kill.get("victim")) == p:
            opening_role = "opening_death"

    dmg_total = damage_by_player(rdamages, player, True)
    dmg_taken = damage_by_player(rdamages, player, False)
    dmg_postplant = damage_by_player(rdamages, player, True, tick_from=plant_tick if plant_tick is not None else None)
    first_damage_dealt_tick = first_player_damage_tick(rdamages, player, True)
    first_damage_taken_tick = first_player_damage_tick(rdamages, player, False)

    utility = count_player_utility(rgrenades, rsmokes, rinfernos, player)

    low_impact = (
        player_round_result == "loss"
        and len(player_kills) == 0
        and dmg_total < 30
    )

    return {
        "match_round_key": f"R{round_num}",
        "round_num": round_num,
        "start_tick": safe_int(round_row.get("start")),
        "freeze_end_tick": safe_int(round_row.get("freeze_end")),
        "end_tick": safe_int(round_row.get("official_end")) or safe_int(round_row.get("end")),
        "winner": winner,
        "reason": safe_str(round_row.get("reason")),
        "bombsite": plant.get("bombsite"),
        "has_plant": plant.get("has_plant"),
        "plant_tick": plant_tick,
        "plant_event": plant.get("plant_event"),
        "player": player,
        "player_side": player_side,
        "player_round_result": player_round_result,
        "player_alive_at_plant": alive_at_plant,
        "player_death_tick": player_death_tick,
        "player_death_phase": phase_from_tick(player_death_tick, plant_tick),
        "player_first_kill_tick": player_first_kill_tick,
        "player_first_damage_dealt_tick": first_damage_dealt_tick,
        "player_first_damage_taken_tick": first_damage_taken_tick,
        "opening_role": opening_role,
        "player_kills": len(player_kills),
        "player_deaths": len(player_deaths),
        "player_damage": dmg_total,
        "player_damage_taken": dmg_taken,
        "player_damage_postplant": dmg_postplant,
        "player_kills_before_plant": kills_before_plant,
        "player_kills_after_plant": kills_after_plant,
        "player_deaths_before_plant": deaths_before_plant,
        "player_deaths_after_plant": deaths_after_plant,
        "player_low_impact_lost_round": low_impact,
        "player_utility": utility,
        "round_kill_events": kill_events,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    side_counts = Counter(r.get("player_side") or "unknown" for r in rows)
    results = Counter(r.get("player_round_result") or "unknown" for r in rows)
    death_phases = Counter(r.get("player_death_phase") or "unknown" for r in rows)
    opening = Counter(r.get("opening_role") or "none" for r in rows)

    return {
        "version": VERSION,
        "rounds_total": len(rows),
        "plant_rounds": sum(1 for r in rows if r.get("has_plant")),
        "player_side_counts": dict(side_counts),
        "player_result_counts": dict(results),
        "player_death_phase_counts": dict(death_phases),
        "opening_role_counts": dict(opening),
        "player_total_kills": sum(int(r.get("player_kills") or 0) for r in rows),
        "player_total_deaths": sum(int(r.get("player_deaths") or 0) for r in rows),
        "player_total_damage": round(sum(float(r.get("player_damage") or 0) for r in rows), 1),
        "low_impact_lost_rounds": sum(1 for r in rows if r.get("player_low_impact_lost_round")),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = (root / args.data_dir).resolve()

    paths = {
        "rounds": find_parquet(data_root, args.match_id, "rounds.parquet"),
        "bomb": find_parquet(data_root, args.match_id, "bomb.parquet"),
        "kills": find_parquet(data_root, args.match_id, "kills.parquet"),
        "damages": find_parquet(data_root, args.match_id, "damages.parquet"),
        "grenades": find_parquet(data_root, args.match_id, "grenades.parquet"),
        "smokes": find_parquet(data_root, args.match_id, "smokes.parquet"),
        "infernos": find_parquet(data_root, args.match_id, "infernos.parquet"),
    }

    print("=== Canonical Round Timeline v0.1 ===")
    for k, v in paths.items():
        print(f"{k}: {v if v else 'MISSING'}")

    rounds = read_parquet_optional(paths["rounds"])
    if rounds.empty:
        raise SystemExit("rounds.parquet missing or empty")

    if "round_num" not in rounds.columns:
        rc = round_col(rounds)
        if not rc:
            raise SystemExit("No round column in rounds")
        rounds = rounds.rename(columns={rc: "round_num"})

    bomb = read_parquet_optional(paths["bomb"])
    kills = read_parquet_optional(paths["kills"])
    damages = read_parquet_optional(paths["damages"])
    grenades = read_parquet_optional(paths["grenades"])
    smokes = read_parquet_optional(paths["smokes"])
    infernos = read_parquet_optional(paths["infernos"])

    rows = []
    for _, row in rounds.sort_values("round_num").iterrows():
        rows.append(analyze_round(row, args.player, kills, damages, bomb, grenades, smokes, infernos))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) if v else None for k, v in paths.items()},
        "summary": summarize(rows),
        "rows": rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_round_timeline_{args.player}_v0_1.json"
    csv_path = out_dir / f"canonical_round_timeline_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== CANONICAL ROUND TIMELINE v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
