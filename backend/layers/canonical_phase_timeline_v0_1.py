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


VERSION = "canonical_phase_timeline_v0_1"


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


def active_start(round_row: dict[str, Any]) -> int | None:
    freeze_end = safe_int(round_row.get("freeze_end_tick"))
    start = safe_int(round_row.get("start_tick"))
    return freeze_end if freeze_end is not None else start


def active_end(round_row: dict[str, Any]) -> int | None:
    return safe_int(round_row.get("end_tick"))


def phase_for_tick(round_row: dict[str, Any], tick: int | None) -> str:
    if tick is None:
        return "unknown"

    start = active_start(round_row)
    end = active_end(round_row)
    plant = safe_int(round_row.get("plant_tick"))

    if start is None:
        return "unknown"

    if tick < start:
        return "freeze_or_preround"

    if plant is not None and tick >= plant:
        return "postplant"

    phase_end = plant if plant is not None else end
    if phase_end is None or phase_end <= start:
        return "active_unknown"

    progress = (tick - start) / max(1, phase_end - start)

    if progress < 0.33:
        return "early"
    if progress < 0.66:
        return "mid"
    return "late"


def phase_progress(round_row: dict[str, Any], tick: int | None) -> float | None:
    if tick is None:
        return None

    start = active_start(round_row)
    end = active_end(round_row)
    plant = safe_int(round_row.get("plant_tick"))

    if start is None:
        return None

    phase_end = plant if plant is not None and tick < plant else end
    if phase_end is None or phase_end <= start:
        return None

    return round(max(0.0, min(1.0, (tick - start) / max(1, phase_end - start))), 3)


def add_event(events: list[dict[str, Any]], round_row: dict[str, Any], event: dict[str, Any]) -> None:
    tick = safe_int(event.get("tick"))
    rn = safe_int(event.get("round_num"))

    event["phase"] = phase_for_tick(round_row, tick)
    event["phase_progress"] = phase_progress(round_row, tick)
    event["round_result"] = safe_str(round_row.get("player_round_result"))
    event["player_side"] = safe_str(round_row.get("player_side"))
    event["has_plant"] = bool(round_row.get("has_plant"))
    event["plant_tick"] = safe_int(round_row.get("plant_tick"))

    if rn is not None:
        events.append(event)


def build_events(
    round_payload: dict[str, Any],
    combat_payload: dict[str, Any],
    utility_payload: dict[str, Any],
    mechanics_payload: dict[str, Any],
    trade_payload: dict[str, Any],
    player: str,
) -> list[dict[str, Any]]:
    rounds = round_map(round_payload)
    events: list[dict[str, Any]] = []
    p = norm(player)

    for k in combat_payload.get("kills", []):
        rn = safe_int(k.get("round_num"))
        rr = rounds.get(rn)
        if not rr:
            continue

        if safe_str(k.get("player_role")) not in {"kill", "death"}:
            continue

        add_event(events, rr, {
            "event_id": safe_str(k.get("event_id")),
            "event_source": "combat",
            "event_type": safe_str(k.get("player_role")),
            "round_num": rn,
            "tick": safe_int(k.get("tick")),
            "value_type": "positive" if safe_str(k.get("player_role")) == "kill" else "negative",
            "weapon": safe_str(k.get("weapon")),
            "weapon_class": safe_str(k.get("weapon_class")),
            "headshot": bool(k.get("headshot")),
            "details": {
                "attacker": k.get("attacker"),
                "victim": k.get("victim"),
                "is_opening_kill_event": k.get("is_opening_kill_event"),
            },
        })

    for d in combat_payload.get("damages", []):
        rn = safe_int(d.get("round_num"))
        rr = rounds.get(rn)
        if not rr:
            continue

        role = safe_str(d.get("player_role"))
        if role not in {"damage_dealt", "damage_taken"}:
            continue

        add_event(events, rr, {
            "event_id": safe_str(d.get("event_id")),
            "event_source": "combat",
            "event_type": role,
            "round_num": rn,
            "tick": safe_int(d.get("tick")),
            "value_type": "positive" if role == "damage_dealt" else "negative",
            "weapon": safe_str(d.get("weapon")),
            "weapon_class": safe_str(d.get("weapon_class")),
            "damage_health": safe_float(d.get("damage_health")),
            "details": {
                "attacker": d.get("attacker"),
                "victim": d.get("victim"),
                "hitgroup": d.get("hitgroup"),
            },
        })

    for u in utility_payload.get("rows", []):
        if norm(u.get("player")) != p:
            continue

        rn = safe_int(u.get("round_num"))
        rr = rounds.get(rn)
        if not rr:
            continue

        add_event(events, rr, {
            "event_id": f"utility_R{rn}_T{safe_int(u.get('tick'))}_{safe_str(u.get('event_kind'))}_{safe_str(u.get('entity_id'))}",
            "event_source": "utility",
            "event_type": safe_str(u.get("event_kind")),
            "round_num": rn,
            "tick": safe_int(u.get("tick")),
            "value_type": "context",
            "utility_type": safe_str(u.get("utility_type")),
            "utility_role": safe_str(u.get("role")),
            "details": {
                "place": u.get("place"),
                "end_tick": u.get("end_tick"),
            },
        })

    for m in mechanics_payload.get("rows", []):
        rn = safe_int(m.get("round_num"))
        rr = rounds.get(rn)
        if not rr:
            continue

        add_event(events, rr, {
            "event_id": safe_str(m.get("event_id")),
            "event_source": "mechanics",
            "event_type": "mechanics_actionable" if bool(m.get("is_actionable")) else "mechanics_event",
            "round_num": rn,
            "tick": safe_int(m.get("tick")),
            "value_type": "negative" if bool(m.get("is_actionable")) else "context",
            "root_cause": safe_str(m.get("root_cause")),
            "priority_score": safe_float(m.get("priority_score")),
            "details": {
                "real_issue": m.get("real_issue"),
                "keep_for_training": m.get("keep_for_training"),
                "aim_error_deg": m.get("aim_error_deg"),
                "speed": m.get("speed"),
            },
        })

    for t in trade_payload.get("rows", []):
        rn = safe_int(t.get("round_num"))
        rr = rounds.get(rn)
        if not rr:
            continue

        if safe_str(t.get("player_focus")) == "none":
            continue

        add_event(events, rr, {
            "event_id": f"trade_R{rn}_T{safe_int(t.get('kill_tick'))}_{safe_str(t.get('category'))}",
            "event_source": "trade_spacing",
            "event_type": safe_str(t.get("category")),
            "round_num": rn,
            "tick": safe_int(t.get("kill_tick")),
            "value_type": "negative" if bool(t.get("is_problem")) else "positive",
            "priority_score": safe_float(t.get("priority_score")),
            "details": {
                "severity": t.get("severity"),
                "reasons": t.get("reasons"),
                "trade_delay_ticks": t.get("trade_delay_ticks"),
            },
        })

    return sorted(events, key=lambda e: (
        safe_int(e.get("round_num"), 9999) or 9999,
        safe_int(e.get("tick"), 999999999) or 999999999,
        safe_str(e.get("event_source")),
    ))


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    phase_counts = Counter(e.get("phase") for e in events)
    source_counts = Counter(e.get("event_source") for e in events)
    type_counts = Counter(e.get("event_type") for e in events)
    negative_phase_counts = Counter(e.get("phase") for e in events if e.get("value_type") == "negative")
    positive_phase_counts = Counter(e.get("phase") for e in events if e.get("value_type") == "positive")

    return {
        "version": VERSION,
        "events_total": len(events),
        "phase_counts": dict(phase_counts),
        "event_source_counts": dict(source_counts),
        "event_type_counts": dict(type_counts),
        "negative_phase_counts": dict(negative_phase_counts),
        "positive_phase_counts": dict(positive_phase_counts),
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

    print("=== Canonical Phase Timeline v0.1 ===")
    for name, path in paths.items():
        print(f"{name}: {path} exists={path.exists()}")

    round_payload = load_json(paths["round"])
    combat_payload = load_json(paths["combat"])
    utility_payload = load_json(paths["utility"])
    mechanics_payload = load_json(paths["mechanics"])
    trade_payload = load_json(paths["trade"])

    events = build_events(round_payload, combat_payload, utility_payload, mechanics_payload, trade_payload, args.player)
    summary = summarize(events)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) for k, v in paths.items()},
        "summary": summary,
        "events": events,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_phase_timeline_{args.player}_v0_1.json"
    csv_path = out_dir / f"canonical_phase_timeline_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, events)

    print("")
    print("=== CANONICAL PHASE TIMELINE v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
