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


VERSION = "canonical_round_state_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def round_map(round_payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for row in round_payload.get("rows", []):
        rn = safe_int(row.get("round_num"))
        if rn is not None:
            out[rn] = row
    return out


def kills_by_round(combat_payload: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for k in combat_payload.get("kills", []):
        rn = safe_int(k.get("round_num"))
        if rn is None:
            continue
        out[rn].append(k)

    for rn in out:
        out[rn] = sorted(out[rn], key=lambda x: safe_int(x.get("tick"), 999999999) or 999999999)

    return out


def side_key(side: str) -> str:
    s = safe_str(side).strip().lower()
    if s == "ct":
        return "ct"
    if s == "t":
        return "t"
    return "unknown"


def advantage_label(ct_alive: int, t_alive: int, player_side: str) -> str:
    ps = side_key(player_side)

    if ps == "ct":
        diff = ct_alive - t_alive
    elif ps == "t":
        diff = t_alive - ct_alive
    else:
        diff = 0

    if diff >= 2:
        return "player_team_big_advantage"
    if diff == 1:
        return "player_team_advantage"
    if diff == 0:
        return "even"
    if diff == -1:
        return "player_team_disadvantage"
    return "player_team_big_disadvantage"


def diff_value(ct_alive: int, t_alive: int, player_side: str) -> int:
    ps = side_key(player_side)
    if ps == "ct":
        return ct_alive - t_alive
    if ps == "t":
        return t_alive - ct_alive
    return 0


def build_round_states(round_row: dict[str, Any], kills: list[dict[str, Any]], player: str) -> list[dict[str, Any]]:
    rn = safe_int(round_row.get("round_num"))
    player_side = safe_str(round_row.get("player_side"))
    result = safe_str(round_row.get("player_round_result"))
    winner = safe_str(round_row.get("winner"))

    ct_alive = 5
    t_alive = 5

    states = []
    p = norm(player)

    for idx, k in enumerate(kills, start=1):
        before_ct = ct_alive
        before_t = t_alive
        before_diff = diff_value(before_ct, before_t, player_side)
        before_label = advantage_label(before_ct, before_t, player_side)

        victim_side = side_key(k.get("victim_side"))
        if victim_side == "ct":
            ct_alive = max(0, ct_alive - 1)
        elif victim_side == "t":
            t_alive = max(0, t_alive - 1)

        after_diff = diff_value(ct_alive, t_alive, player_side)
        after_label = advantage_label(ct_alive, t_alive, player_side)

        player_role = safe_str(k.get("player_role"))
        attacker = safe_str(k.get("attacker"))
        victim = safe_str(k.get("victim"))

        swing = after_diff - before_diff

        player_event = player_role in {"kill", "death"}
        if player_role == "kill":
            player_swing_type = "positive_kill_swing"
        elif player_role == "death":
            player_swing_type = "negative_death_swing"
        else:
            player_swing_type = "none"

        states.append({
            "round_num": rn,
            "kill_index": idx,
            "tick": safe_int(k.get("tick")),
            "player": player,
            "player_side": player_side,
            "round_result": result,
            "winner": winner,
            "has_plant": bool(round_row.get("has_plant")),
            "plant_tick": safe_int(round_row.get("plant_tick")),
            "event_phase": "postplant" if safe_int(round_row.get("plant_tick")) is not None and safe_int(k.get("tick")) is not None and safe_int(k.get("tick")) >= safe_int(round_row.get("plant_tick")) else "preplant_or_nonplant",
            "attacker": attacker,
            "victim": victim,
            "weapon": safe_str(k.get("weapon")),
            "headshot": bool(k.get("headshot")),
            "attacker_side": safe_str(k.get("attacker_side")),
            "victim_side": safe_str(k.get("victim_side")),
            "player_event": player_event,
            "player_role": player_role,
            "player_swing_type": player_swing_type,
            "ct_alive_before": before_ct,
            "t_alive_before": before_t,
            "ct_alive_after": ct_alive,
            "t_alive_after": t_alive,
            "player_team_diff_before": before_diff,
            "player_team_diff_after": after_diff,
            "player_team_state_before": before_label,
            "player_team_state_after": after_label,
            "swing_delta": swing,
            "is_opening_kill_event": bool(k.get("is_opening_kill_event")),
        })

    return states


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    player_events = [r for r in rows if bool(r.get("player_event"))]
    player_kills = [r for r in player_events if safe_str(r.get("player_role")) == "kill"]
    player_deaths = [r for r in player_events if safe_str(r.get("player_role")) == "death"]

    state_before_counts = Counter(r.get("player_team_state_before") for r in player_events)
    swing_counts = Counter(r.get("player_swing_type") for r in player_events)
    result_counts = Counter(r.get("round_result") for r in player_events)

    negative_deaths_even_or_adv = [
        r for r in player_deaths
        if safe_str(r.get("player_team_state_before")) in {"even", "player_team_advantage", "player_team_big_advantage"}
    ]

    positive_kills_disadv = [
        r for r in player_kills
        if safe_str(r.get("player_team_state_before")) in {"player_team_disadvantage", "player_team_big_disadvantage"}
    ]

    return {
        "version": VERSION,
        "state_events_total": len(rows),
        "player_state_events_total": len(player_events),
        "player_kill_swing_events": len(player_kills),
        "player_death_swing_events": len(player_deaths),
        "player_event_state_before_counts": dict(state_before_counts),
        "player_swing_type_counts": dict(swing_counts),
        "player_event_result_counts": dict(result_counts),
        "negative_deaths_even_or_advantage": len(negative_deaths_even_or_adv),
        "positive_kills_from_disadvantage": len(positive_kills_disadv),
        "top_negative_swing_rounds": [
            {
                "round_num": r.get("round_num"),
                "tick": r.get("tick"),
                "state_before": r.get("player_team_state_before"),
                "state_after": r.get("player_team_state_after"),
                "round_result": r.get("round_result"),
                "weapon": r.get("weapon"),
            }
            for r in negative_deaths_even_or_adv[:10]
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

    round_json = data_root / "layers" / args.match_id / f"canonical_round_timeline_{args.player}_v0_1.json"
    combat_json = data_root / "layers" / args.match_id / f"canonical_combat_events_{args.player}_v0_1.json"

    print("=== Canonical Round State v0.1 ===")
    print(f"Round layer:  {round_json} exists={round_json.exists()}")
    print(f"Combat layer: {combat_json} exists={combat_json.exists()}")

    round_payload = load_json(round_json)
    combat_payload = load_json(combat_json)

    rounds = round_map(round_payload)
    kills = kills_by_round(combat_payload)

    rows = []
    for rn, rr in sorted(rounds.items()):
        rows.extend(build_round_states(rr, kills.get(rn, []), args.player))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "round_layer": str(round_json),
            "combat_layer": str(combat_json),
        },
        "summary": summarize(rows),
        "rows": rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_round_state_{args.player}_v0_1.json"
    csv_path = out_dir / f"canonical_round_state_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== CANONICAL ROUND STATE v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
