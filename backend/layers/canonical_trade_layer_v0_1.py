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
    find_parquet,
    first_col,
    norm,
    print_json,
    read_parquet_optional,
    round_col,
    safe_int,
    safe_str,
    write_csv,
    write_json,
)


VERSION = "canonical_trade_layer_v0_1"
TRADE_WINDOW_TICKS = 320


def compact_kill(row: pd.Series) -> dict[str, Any]:
    return {
        "round_num": safe_int(row.get("round_num")),
        "tick": safe_int(row.get("tick")),
        "attacker": safe_str(row.get("attacker_name")),
        "victim": safe_str(row.get("victim_name")),
        "weapon": safe_str(row.get("weapon")),
        "headshot": bool(row.get("headshot")) if "headshot" in row.index else False,
        "attacker_side": safe_str(row.get("attacker_side")),
        "victim_side": safe_str(row.get("victim_side")),
        "attacker_steamid": safe_str(row.get("attacker_steamid")),
        "victim_steamid": safe_str(row.get("victim_steamid")),
    }


def is_trade_candidate(original: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, str]:
    original_tick = original.get("tick")
    candidate_tick = candidate.get("tick")
    if original_tick is None or candidate_tick is None:
        return False, ""

    if not (original_tick < candidate_tick <= original_tick + TRADE_WINDOW_TICKS):
        return False, ""

    original_attacker_side = safe_str(original.get("attacker_side"))
    original_victim_side = safe_str(original.get("victim_side"))
    candidate_attacker_side = safe_str(candidate.get("attacker_side"))
    candidate_victim_side = safe_str(candidate.get("victim_side"))

    original_attacker = norm(original.get("attacker"))
    original_attacker_steamid = safe_str(original.get("attacker_steamid"))
    candidate_victim = norm(candidate.get("victim"))
    candidate_victim_steamid = safe_str(candidate.get("victim_steamid"))

    if original_victim_side and candidate_attacker_side == original_victim_side:
        if original_attacker_side and candidate_victim_side == original_attacker_side:
            if original_attacker_steamid and candidate_victim_steamid == original_attacker_steamid:
                return True, "direct_trade"
            if original_attacker and candidate_victim == original_attacker:
                return True, "direct_trade"
            return True, "team_trade"

    return False, ""


def analyze_kill_event(kill: dict[str, Any], all_kills_same_round: list[dict[str, Any]], player: str) -> dict[str, Any]:
    trade_event = None
    trade_type = ""

    for candidate in all_kills_same_round:
        ok, ttype = is_trade_candidate(kill, candidate)
        if ok:
            trade_event = candidate
            trade_type = ttype
            break

    player_l = norm(player)
    player_role = "none"
    if norm(kill.get("attacker")) == player_l:
        player_role = "attacker"
    elif norm(kill.get("victim")) == player_l:
        player_role = "victim"

    trade_delay = None
    if trade_event:
        trade_delay = (trade_event.get("tick") or 0) - (kill.get("tick") or 0)

    player_focus = "none"
    if player_role == "attacker" and trade_event:
        player_focus = "player_kill_traded_by_enemy"
    elif player_role == "attacker" and not trade_event:
        player_focus = "player_kill_not_traded"
    elif player_role == "victim" and trade_event:
        player_focus = "player_death_traded_by_team"
    elif player_role == "victim" and not trade_event:
        player_focus = "player_death_untraded"

    return {
        "round_num": kill.get("round_num"),
        "kill_tick": kill.get("tick"),
        "kill_id": f"R{kill.get('round_num')}_T{kill.get('tick')}_{kill.get('attacker')}->{kill.get('victim')}",
        "attacker": kill.get("attacker"),
        "victim": kill.get("victim"),
        "weapon": kill.get("weapon"),
        "headshot": kill.get("headshot"),
        "attacker_side": kill.get("attacker_side"),
        "victim_side": kill.get("victim_side"),
        "was_traded": bool(trade_event),
        "trade_type": trade_type,
        "trade_tick": trade_event.get("tick") if trade_event else None,
        "trade_delay_ticks": trade_delay,
        "trade_attacker": trade_event.get("attacker") if trade_event else "",
        "trade_victim": trade_event.get("victim") if trade_event else "",
        "player_role": player_role,
        "player_focus": player_focus,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    focus_counts = Counter(r.get("player_focus") for r in rows if r.get("player_focus") != "none")
    trade_types = Counter(r.get("trade_type") or "not_traded" for r in rows)
    player_events = [r for r in rows if r.get("player_role") != "none"]

    return {
        "version": VERSION,
        "kills_total": len(rows),
        "traded_kills_total": sum(1 for r in rows if r.get("was_traded")),
        "trade_type_counts": dict(trade_types),
        "player_events_total": len(player_events),
        "player_focus_counts": dict(focus_counts),
        "player_deaths_untraded": focus_counts.get("player_death_untraded", 0),
        "player_deaths_traded_by_team": focus_counts.get("player_death_traded_by_team", 0),
        "player_kills_traded_by_enemy": focus_counts.get("player_kill_traded_by_enemy", 0),
        "player_kills_not_traded": focus_counts.get("player_kill_not_traded", 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = (root / args.data_dir).resolve()

    kills_path = find_parquet(data_root, args.match_id, "kills.parquet")
    kills = read_parquet_optional(kills_path)

    print("=== Canonical Trade Layer v0.1 ===")
    print(f"kills: {kills_path if kills_path else 'MISSING'}")

    if kills.empty:
        raise SystemExit("kills.parquet missing or empty")

    if "round_num" not in kills.columns:
        rc = round_col(kills)
        if not rc:
            raise SystemExit("No round column in kills")
        kills = kills.rename(columns={rc: "round_num"})

    if "tick" in kills.columns:
        kills = kills.sort_values(["round_num", "tick"])

    rows = []
    for round_num, group in kills.groupby("round_num"):
        group_kills = [compact_kill(row) for _, row in group.iterrows()]
        for kill in group_kills:
            rows.append(analyze_kill_event(kill, group_kills, args.player))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "kills": str(kills_path) if kills_path else None,
        },
        "summary": summarize(rows),
        "rows": rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_trade_layer_{args.player}_v0_1.json"
    csv_path = out_dir / f"canonical_trade_layer_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== CANONICAL TRADE LAYER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
