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


VERSION = "canonical_utility_timeline_v0_1"


def reduce_grenade_trajectory(grenades: pd.DataFrame) -> pd.DataFrame:
    if grenades.empty:
        return grenades

    entity_col = first_col(grenades, ["entity_id"])
    if not entity_col:
        keys = [c for c in ["round_num", "thrower", "thrower_name", "grenade_type", "tick"] if c in grenades.columns]
        if keys:
            return grenades.drop_duplicates(keys).copy()
        return grenades.copy()

    g = grenades.copy()
    if "tick" in g.columns:
        g = g.sort_values("tick")

    return g.groupby(entity_col, as_index=False).first()


def utility_damage_by_round_and_player(damages: pd.DataFrame) -> dict[tuple[int, str], float]:
    result: dict[tuple[int, str], float] = defaultdict(float)

    if damages.empty:
        return result

    rc = round_col(damages)
    dmg_col = first_col(damages, ["dmg_health_real", "dmg_health"])
    weapon_col = first_col(damages, ["weapon"])

    if not rc or not dmg_col or not weapon_col:
        return result

    utility_words = ["grenade", "hegrenade", "inferno", "molotov", "incendiary", "flashbang", "smoke"]
    for _, row in damages.iterrows():
        weapon = safe_str(row.get(weapon_col)).lower()
        if not any(w in weapon for w in utility_words):
            continue

        round_num = safe_int(row.get(rc))
        attacker = safe_str(row.get("attacker_name"))
        if round_num is None or not attacker:
            continue

        result[(round_num, attacker)] += safe_float(row.get(dmg_col))

    return {k: round(v, 1) for k, v in result.items()}


def build_grenade_events(grenades: pd.DataFrame, utility_damage: dict[tuple[int, str], float]) -> list[dict[str, Any]]:
    rows = []
    if grenades.empty:
        return rows

    g = reduce_grenade_trajectory(grenades)

    rc = round_col(g)
    thrower_col = first_col(g, ["thrower", "thrower_name"])
    type_col = first_col(g, ["grenade_type", "type"])
    entity_col = first_col(g, ["entity_id"])

    if not rc or not thrower_col or not type_col:
        return rows

    for _, row in g.iterrows():
        round_num = safe_int(row.get(rc))
        thrower = safe_str(row.get(thrower_col))
        utility_type = normalize_grenade_type(row.get(type_col))

        rows.append({
            "event_kind": "grenade_throw",
            "round_num": round_num,
            "tick": safe_int(row.get("tick")),
            "end_tick": None,
            "entity_id": safe_str(row.get(entity_col)) if entity_col else "",
            "player": thrower,
            "side": safe_str(row.get("thrower_side")),
            "utility_type": utility_type,
            "role": "fire" if utility_type in {"molotov", "incendiary"} else utility_type,
            "place": safe_str(row.get("thrower_place")),
            "x": safe_float(row.get("X")),
            "y": safe_float(row.get("Y")),
            "z": safe_float(row.get("Z")),
            "round_player_utility_damage": utility_damage.get((round_num, thrower), 0.0),
        })

    return rows


def build_area_events(df: pd.DataFrame, kind: str, utility_type: str, role: str, utility_damage: dict[tuple[int, str], float]) -> list[dict[str, Any]]:
    rows = []
    if df.empty:
        return rows

    rc = round_col(df)
    thrower_col = first_col(df, ["thrower_name", "thrower"])
    entity_col = first_col(df, ["entity_id"])

    if not rc or not thrower_col:
        return rows

    for _, row in df.iterrows():
        round_num = safe_int(row.get(rc))
        thrower = safe_str(row.get(thrower_col))

        rows.append({
            "event_kind": kind,
            "round_num": round_num,
            "tick": safe_int(row.get("start_tick")),
            "end_tick": safe_int(row.get("end_tick")),
            "entity_id": safe_str(row.get(entity_col)) if entity_col else "",
            "player": thrower,
            "side": safe_str(row.get("thrower_side")),
            "utility_type": utility_type,
            "role": role,
            "place": safe_str(row.get("thrower_place")),
            "x": safe_float(row.get("X")),
            "y": safe_float(row.get("Y")),
            "z": safe_float(row.get("Z")),
            "round_player_utility_damage": utility_damage.get((round_num, thrower), 0.0),
        })

    return rows


def summarize(rows: list[dict[str, Any]], focus_player: str) -> dict[str, Any]:
    type_counts = Counter(r.get("utility_type") for r in rows if r.get("event_kind") == "grenade_throw")
    role_counts = Counter(r.get("role") for r in rows if r.get("event_kind") == "grenade_throw")
    kind_counts = Counter(r.get("event_kind") for r in rows)

    player_rows = [r for r in rows if norm(r.get("player")) == norm(focus_player)]
    player_type_counts = Counter(r.get("utility_type") for r in player_rows if r.get("event_kind") == "grenade_throw")
    player_kind_counts = Counter(r.get("event_kind") for r in player_rows)

    player_rounds_with_utility = sorted(set(r.get("round_num") for r in player_rows if r.get("round_num") is not None))

    return {
        "version": VERSION,
        "events_total": len(rows),
        "event_kind_counts": dict(kind_counts),
        "grenade_throw_type_counts_all": dict(type_counts),
        "grenade_throw_role_counts_all": dict(role_counts),
        "focus_player": focus_player,
        "focus_player_events_total": len(player_rows),
        "focus_player_event_kind_counts": dict(player_kind_counts),
        "focus_player_grenade_type_counts": dict(player_type_counts),
        "focus_player_rounds_with_utility": player_rounds_with_utility,
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
        "grenades": find_parquet(data_root, args.match_id, "grenades.parquet"),
        "smokes": find_parquet(data_root, args.match_id, "smokes.parquet"),
        "infernos": find_parquet(data_root, args.match_id, "infernos.parquet"),
        "damages": find_parquet(data_root, args.match_id, "damages.parquet"),
    }

    print("=== Canonical Utility Timeline v0.1 ===")
    for k, v in paths.items():
        print(f"{k}: {v if v else 'MISSING'}")

    grenades = read_parquet_optional(paths["grenades"])
    smokes = read_parquet_optional(paths["smokes"])
    infernos = read_parquet_optional(paths["infernos"])
    damages = read_parquet_optional(paths["damages"])

    utility_damage = utility_damage_by_round_and_player(damages)

    rows = []
    rows.extend(build_grenade_events(grenades, utility_damage))
    rows.extend(build_area_events(smokes, "smoke_active", "smoke", "smoke", utility_damage))
    rows.extend(build_area_events(infernos, "inferno_active", "fire", "fire", utility_damage))

    rows = sorted(rows, key=lambda r: (
        r.get("round_num") if r.get("round_num") is not None else 9999,
        r.get("tick") if r.get("tick") is not None else 999999999,
        r.get("event_kind") or "",
    ))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) if v else None for k, v in paths.items()},
        "summary": summarize(rows, args.player),
        "rows": rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_utility_timeline_v0_1.json"
    csv_path = out_dir / f"canonical_utility_timeline_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== CANONICAL UTILITY TIMELINE v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
