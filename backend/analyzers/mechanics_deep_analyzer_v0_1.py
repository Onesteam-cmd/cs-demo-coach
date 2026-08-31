import argparse
import csv
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pyarrow.parquet as pq


ANALYZER_VERSION = "mechanics_deep_analyzer_v0_1"
ASSUMED_TICK_RATE = 64.0


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def version_key(path: Path) -> Tuple[Tuple[int, ...], float, str]:
    name = path.name
    m = re.search(r"_v(\d+)(?:_(\d+))?", name)
    if m:
        version = tuple(int(x) for x in m.groups() if x is not None)
    else:
        version = (-1,)
    return version, path.stat().st_mtime, name


def latest_file(directory: Path, pattern: str) -> Optional[Path]:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    if not files:
        return None
    return max(files, key=version_key)


def parquet_columns(path: Path) -> List[str]:
    if not path.exists():
        return []
    return list(pq.ParquetFile(path).schema.names)


def read_parquet_selected(path: Path, desired: List[str]) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    available = parquet_columns(path)
    selected = [c for c in desired if c in available]
    if not selected:
        return pd.read_parquet(path)
    return pd.read_parquet(path, columns=selected)


def clean_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    s = str(value).strip()
    if s.lower() in ("nan", "none", "null", "<na>"):
        return ""
    return s


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return int(float(value))
    except Exception:
        return default


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def norm_name(value: Any) -> str:
    return clean_str(value).lower()


def find_col(columns: List[str], exact: List[str] = None, contains: List[str] = None) -> Optional[str]:
    exact = exact or []
    contains = contains or []
    lower_map = {str(c).lower(): str(c) for c in columns}

    for name in exact:
        key = name.lower()
        if key in lower_map:
            return lower_map[key]

    for needle in contains:
        n = needle.lower()
        for c in columns:
            if n in str(c).lower():
                return str(c)

    return None


def get(row: Dict[str, Any], col: Optional[str], default: Any = None) -> Any:
    if not col:
        return default
    return row.get(col, default)


def angle_wrap(deg: float) -> float:
    while deg > 180:
        deg -= 360
    while deg < -180:
        deg += 360
    return deg


def yaw_to_target(player_x: float, player_y: float, target_x: float, target_y: float) -> float:
    return math.degrees(math.atan2(target_y - player_y, target_x - player_x))


def distance_3d(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[float]:
    ax, ay, az = safe_float(a.get("x")), safe_float(a.get("y")), safe_float(a.get("z"))
    bx, by, bz = safe_float(b.get("x")), safe_float(b.get("y")), safe_float(b.get("z"))
    if None in (ax, ay, az, bx, by, bz):
        return None
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def horizontal_distance(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[float]:
    ax, ay = safe_float(a.get("x")), safe_float(a.get("y"))
    bx, by = safe_float(b.get("x")), safe_float(b.get("y"))
    if None in (ax, ay, bx, by):
        return None
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def calc_speed(row: Dict[str, Any]) -> Optional[float]:
    vx = safe_float(row.get("velocity_X"))
    vy = safe_float(row.get("velocity_Y"))
    vz = safe_float(row.get("velocity_Z"))
    if vx is None and vy is None and vz is None:
        return None
    vx = vx or 0.0
    vy = vy or 0.0
    vz = vz or 0.0
    return math.sqrt(vx * vx + vy * vy + vz * vz)


def speed_band(speed: Optional[float]) -> str:
    if speed is None:
        return "unknown"
    if speed < 20:
        return "stopped"
    if speed < 90:
        return "slow_moving"
    if speed < 170:
        return "moving"
    return "fast_moving"


def aim_error_band(error: Optional[float]) -> str:
    if error is None:
        return "unknown"
    ae = abs(error)
    if ae <= 3:
        return "good"
    if ae <= 8:
        return "acceptable"
    if ae <= 15:
        return "off"
    return "large_error"


def confidence_from_context(has_view: bool, has_combat: bool, has_shot: bool) -> str:
    score = 0
    if has_view:
        score += 2
    if has_combat:
        score += 2
    if has_shot:
        score += 1
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def nearest_row(df: Optional[pd.DataFrame], tick: int, tick_col: str = "tick", max_delta: int = 32) -> Optional[Dict[str, Any]]:
    if df is None or df.empty or tick_col not in df.columns:
        return None

    window = df[(df[tick_col] >= tick - max_delta) & (df[tick_col] <= tick + max_delta)]
    if window.empty:
        return None

    idx = (window[tick_col] - tick).abs().idxmin()
    return window.loc[idx].to_dict()


def rows_in_window(df: Optional[pd.DataFrame], tick: int, before: int, after: int, tick_col: str = "tick") -> pd.DataFrame:
    if df is None or df.empty or tick_col not in df.columns:
        return pd.DataFrame()
    return df[(df[tick_col] >= tick - before) & (df[tick_col] <= tick + after)].copy()


def detect_combat_cols(df: Optional[pd.DataFrame]) -> Dict[str, Optional[str]]:
    c = [str(x) for x in df.columns] if df is not None else []
    return {
        "round": find_col(c, ["round_num", "round"], ["round"]),
        "tick": find_col(c, ["tick"], ["tick"]),
        "attacker": find_col(c, ["attacker_name", "attackerName", "attacker"], ["attacker"]),
        "victim": find_col(c, ["victim_name", "victimName", "victim"], ["victim"]),
        "attacker_side": find_col(c, ["attacker_side", "attackerSide"], ["attacker_side", "attackerside"]),
        "victim_side": find_col(c, ["victim_side", "victimSide"], ["victim_side", "victimside"]),
        "weapon": find_col(c, ["weapon", "weapon_name"], ["weapon"]),
        "damage": find_col(c, ["damage", "dmg_health", "health_damage", "hp_damage"], ["damage", "dmg"]),
        "attacker_x": find_col(c, ["attacker_x", "attackerX"], ["attacker_x", "attackerx"]),
        "attacker_y": find_col(c, ["attacker_y", "attackerY"], ["attacker_y", "attackery"]),
        "attacker_z": find_col(c, ["attacker_z", "attackerZ"], ["attacker_z", "attackerz"]),
        "victim_x": find_col(c, ["victim_x", "victimX"], ["victim_x", "victimx"]),
        "victim_y": find_col(c, ["victim_y", "victimY"], ["victim_y", "victimy"]),
        "victim_z": find_col(c, ["victim_z", "victimZ"], ["victim_z", "victimz"]),
        "place": find_col(c, ["place", "area", "site"], ["place", "area", "site"]),
        "flash": find_col(c, ["flash", "blind"], ["flash", "blind"]),
    }


def extract_pos(row: Dict[str, Any], prefix: str, cols: Dict[str, Optional[str]]) -> Dict[str, Any]:
    return {
        "x": safe_float(get(row, cols.get(f"{prefix}_x"))),
        "y": safe_float(get(row, cols.get(f"{prefix}_y"))),
        "z": safe_float(get(row, cols.get(f"{prefix}_z"))),
    }


def build_player_combat_events(kills: Optional[pd.DataFrame], damages: Optional[pd.DataFrame], player: str) -> List[Dict[str, Any]]:
    out = []
    player_norm = norm_name(player)

    for source, df in [("kills", kills), ("damages", damages)]:
        if df is None or df.empty:
            continue

        c = detect_combat_cols(df)

        for i, row in df.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None:
                continue

            attacker = clean_str(get(d, c.get("attacker")))
            victim = clean_str(get(d, c.get("victim")))

            attacker_is_player = norm_name(attacker) == player_norm
            victim_is_player = norm_name(victim) == player_norm

            if not attacker_is_player and not victim_is_player:
                continue

            if attacker_is_player:
                role = "player_attacker"
                opponent = victim
                player_pos = extract_pos(d, "attacker", c)
                opponent_pos = extract_pos(d, "victim", c)
                opponent_side = clean_str(get(d, c.get("victim_side")))
            else:
                role = "player_victim"
                opponent = attacker
                player_pos = extract_pos(d, "victim", c)
                opponent_pos = extract_pos(d, "attacker", c)
                opponent_side = clean_str(get(d, c.get("attacker_side")))

            damage = safe_float(get(d, c.get("damage")))
            weapon = clean_str(get(d, c.get("weapon")))
            place = clean_str(get(d, c.get("place")))
            flash_value = clean_str(get(d, c.get("flash")))

            out.append({
                "source": source,
                "source_index": int(i),
                "round_num": rn,
                "tick": tick,
                "role": role,
                "opponent": opponent,
                "opponent_side": opponent_side,
                "weapon": weapon,
                "damage": damage,
                "place": place,
                "player_pos": player_pos,
                "opponent_pos": opponent_pos,
                "flash_raw": flash_value,
            })

    out.sort(key=lambda x: (x["round_num"], x["tick"], x["source"]))
    return out


def nearest_combat_event(events: List[Dict[str, Any]], round_num: int, tick: int, max_delta: int = 160) -> Optional[Dict[str, Any]]:
    candidates = [
        e for e in events
        if e["round_num"] == round_num and abs(e["tick"] - tick) <= max_delta
    ]
    if not candidates:
        return None

    return sorted(candidates, key=lambda e: (abs(e["tick"] - tick), 0 if e["source"] == "kills" else 1))[0]


def classify_deep_flags(root_cause: str, speed: Optional[float], yaw_error_abs: Optional[float], shots_after_count: int, combat_role: str, confidence: str) -> List[str]:
    flags = []
    root = root_cause.lower()

    if speed is not None and speed >= 90:
        flags.append("movement_risk_at_contact")

    if yaw_error_abs is not None:
        if yaw_error_abs > 20:
            flags.append("large_crosshair_offset")
        elif yaw_error_abs > 10:
            flags.append("moderate_crosshair_offset")
        elif yaw_error_abs <= 5:
            flags.append("crosshair_near_target")

    if shots_after_count == 0 and combat_role == "player_victim":
        flags.append("no_shot_response_near_event")

    if "counter" in root or "moving" in root:
        flags.append("manual_movement_issue")

    if "pre_aim" in root or "first_shot" in root or "large_first_shot" in root:
        flags.append("manual_aim_issue")

    if "enemy_timing" in root:
        flags.append("manual_timing_context")

    if confidence == "low":
        flags.append("low_confidence_deep_context")

    flags.append("visibility_flash_context_missing_or_limited")

    return list(dict.fromkeys(flags))


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player
    player_norm = norm_name(player)

    parsed_dir = root / "data" / "parsed" / match_id
    layers_dir = root / "data" / "layers" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    warnings: List[str] = []

    mechanics_csv = latest_file(layers_dir, f"canonical_mechanics_events_{player}_v*.csv")
    if mechanics_csv is None:
        raise FileNotFoundError(f"MISSING canonical mechanics events CSV for {player}")

    mechanics = pd.read_csv(mechanics_csv)

    view_path = parsed_dir / "view_ticks_demoparser2.parquet"
    shots_path = parsed_dir / "shots.parquet"
    kills_path = parsed_dir / "kills.parquet"
    damages_path = parsed_dir / "damages.parquet"

    view_cols = parquet_columns(view_path)
    shot_cols = parquet_columns(shots_path)
    kill_cols = parquet_columns(kills_path)
    damage_cols = parquet_columns(damages_path)

    view_needed = [c for c in [
        "tick", "player_name", "name", "steamid", "team_name",
        "X", "Y", "Z", "yaw", "pitch",
        "velocity_X", "velocity_Y", "velocity_Z",
        "health", "armor_value", "active_weapon_name"
    ] if c in view_cols]

    shots_needed = [c for c in [
        "tick", "round_num", "player_name", "player_steamid", "player_side",
        "player_X", "player_Y", "player_Z", "player_place", "weapon"
    ] if c in shot_cols]

    kills_needed = [c for c in kill_cols if any(x in c.lower() for x in [
        "round", "tick", "attacker", "victim", "weapon", "damage", "place", "flash", "_x", "_y", "_z"
    ])]

    damages_needed = [c for c in damage_cols if any(x in c.lower() for x in [
        "round", "tick", "attacker", "victim", "weapon", "damage", "dmg", "place", "_x", "_y", "_z"
    ])]

    view = read_parquet_selected(view_path, view_needed)
    shots = read_parquet_selected(shots_path, shots_needed)
    kills = read_parquet_selected(kills_path, kills_needed)
    damages = read_parquet_selected(damages_path, damages_needed)

    if view is None or view.empty:
        raise FileNotFoundError("MISSING or empty view_ticks_demoparser2.parquet")

    if shots is None or shots.empty:
        warnings.append("shots.parquet missing or empty; shot timing will be limited")

    view_name_col = "player_name" if "player_name" in view.columns else ("name" if "name" in view.columns else None)
    if not view_name_col:
        raise ValueError("MISSING player name column in view_ticks_demoparser2")

    view_player = view[view[view_name_col].astype(str).str.lower() == player_norm].copy()
    if view_player.empty:
        raise ValueError(f"No view rows for player {player}")

    view_player["tick"] = pd.to_numeric(view_player["tick"], errors="coerce")
    view_player = view_player.dropna(subset=["tick"]).copy()
    view_player["tick"] = view_player["tick"].astype(int)
    view_player = view_player.sort_values("tick")

    shots_player = pd.DataFrame()
    if shots is not None and not shots.empty:
        shot_name_col = "player_name" if "player_name" in shots.columns else None
        if shot_name_col:
            shots_player = shots[shots[shot_name_col].astype(str).str.lower() == player_norm].copy()
            shots_player["tick"] = pd.to_numeric(shots_player["tick"], errors="coerce")
            shots_player = shots_player.dropna(subset=["tick"]).copy()
            shots_player["tick"] = shots_player["tick"].astype(int)
            shots_player = shots_player.sort_values("tick")

    combat_events = build_player_combat_events(kills, damages, player)

    mcols = [str(c) for c in mechanics.columns]
    event_id_col = find_col(mcols, ["event_id"], ["event_id"])
    round_col = find_col(mcols, ["round_num", "round"], ["round"])
    tick_col = find_col(mcols, ["tick"], ["tick"])
    root_col = find_col(mcols, ["root_cause"], ["root"])
    real_issue_col = find_col(mcols, ["real_issue"], ["real_issue"])
    actionable_col = find_col(mcols, ["is_actionable", "actionable"], ["actionable"])
    clean_col = find_col(mcols, ["is_clean_training_example", "keep_for_training"], ["clean", "training"])
    review_col = find_col(mcols, ["review_status"], ["review"])
    priority_col = find_col(mcols, ["priority_score"], ["priority"])

    deep_events: List[Dict[str, Any]] = []

    for idx, row in mechanics.iterrows():
        d = row.to_dict()

        rn = safe_int(get(d, round_col))
        tick = safe_int(get(d, tick_col))
        if rn is None or tick is None:
            continue

        event_id = clean_str(get(d, event_id_col)) or f"mechanics_{idx}"
        root_cause = clean_str(get(d, root_col)) or "unknown"
        real_issue = clean_str(get(d, real_issue_col))
        actionable = clean_str(get(d, actionable_col))
        clean_training = clean_str(get(d, clean_col))
        review_status = clean_str(get(d, review_col))
        priority_score = safe_float(get(d, priority_col), 0.0)

        view_row = nearest_row(view_player, tick, max_delta=32)
        shots_window = rows_in_window(shots_player, tick, before=96, after=160)

        combat = nearest_combat_event(combat_events, rn, tick, max_delta=192)

        has_view = view_row is not None
        has_shot = not shots_window.empty
        has_combat = combat is not None

        player_snapshot = None
        if view_row:
            speed = calc_speed(view_row)
            player_snapshot = {
                "nearest_tick": safe_int(view_row.get("tick")),
                "tick_delta": abs((safe_int(view_row.get("tick")) or tick) - tick),
                "x": safe_float(view_row.get("X")),
                "y": safe_float(view_row.get("Y")),
                "z": safe_float(view_row.get("Z")),
                "yaw": safe_float(view_row.get("yaw")),
                "pitch": safe_float(view_row.get("pitch")),
                "speed": speed,
                "speed_band": speed_band(speed),
                "health": safe_float(view_row.get("health")),
                "armor": safe_float(view_row.get("armor_value")),
                "active_weapon": clean_str(view_row.get("active_weapon_name")),
            }
        else:
            speed = None

        shot_items = []
        first_shot_tick = None
        for _, srow in shots_window.iterrows():
            sd = srow.to_dict()
            st = safe_int(sd.get("tick"))
            if st is None:
                continue
            if first_shot_tick is None or st < first_shot_tick:
                first_shot_tick = st
            shot_items.append({
                "tick": st,
                "delta_from_event": st - tick,
                "weapon": clean_str(sd.get("weapon")),
                "place": clean_str(sd.get("player_place")),
                "x": safe_float(sd.get("player_X")),
                "y": safe_float(sd.get("player_Y")),
                "z": safe_float(sd.get("player_Z")),
            })

        first_shot_delay_ticks = None
        if first_shot_tick is not None:
            first_shot_delay_ticks = first_shot_tick - tick

        yaw_error = None
        target_yaw = None
        distance = None
        horizontal_dist = None

        combat_context = None
        if combat:
            player_pos = combat.get("player_pos") or {}
            opponent_pos = combat.get("opponent_pos") or {}

            # Prefer view position for player if available; combat position can be parser event position.
            if player_snapshot and player_snapshot.get("x") is not None and player_snapshot.get("y") is not None:
                player_pos_for_angle = {
                    "x": player_snapshot.get("x"),
                    "y": player_snapshot.get("y"),
                    "z": player_snapshot.get("z"),
                }
            else:
                player_pos_for_angle = player_pos

            if player_pos_for_angle.get("x") is not None and opponent_pos.get("x") is not None:
                distance = distance_3d(player_pos_for_angle, opponent_pos)
                horizontal_dist = horizontal_distance(player_pos_for_angle, opponent_pos)

                if player_snapshot and player_snapshot.get("yaw") is not None:
                    target_yaw = yaw_to_target(
                        float(player_pos_for_angle["x"]),
                        float(player_pos_for_angle["y"]),
                        float(opponent_pos["x"]),
                        float(opponent_pos["y"]),
                    )
                    yaw_error = angle_wrap(float(player_snapshot["yaw"]) - target_yaw)

            combat_context = {
                "source": combat.get("source"),
                "source_index": combat.get("source_index"),
                "tick": combat.get("tick"),
                "delta_from_event": combat.get("tick") - tick,
                "role": combat.get("role"),
                "opponent": combat.get("opponent"),
                "opponent_side": combat.get("opponent_side"),
                "weapon": combat.get("weapon"),
                "damage": combat.get("damage"),
                "place": combat.get("place"),
                "player_pos": combat.get("player_pos"),
                "opponent_pos": combat.get("opponent_pos"),
                "flash_raw": combat.get("flash_raw"),
            }

        yaw_error_abs = abs(yaw_error) if yaw_error is not None else None
        deep_confidence = confidence_from_context(has_view, has_combat, has_shot)

        shots_after_count = len([x for x in shot_items if x["delta_from_event"] >= 0])
        combat_role = combat_context.get("role") if combat_context else ""

        flags = classify_deep_flags(root_cause, speed, yaw_error_abs, shots_after_count, combat_role, deep_confidence)

        deep_label = "context_only"
        if "large_crosshair_offset" in flags:
            deep_label = "aim_crosshair_offset"
        elif "movement_risk_at_contact" in flags and ("manual_movement_issue" in flags or shots_after_count > 0):
            deep_label = "movement_shooting_context"
        elif "no_shot_response_near_event" in flags:
            deep_label = "reaction_or_timing_no_response"
        elif "manual_timing_context" in flags:
            deep_label = "timing_context"
        elif "manual_aim_issue" in flags:
            deep_label = "manual_aim_issue_with_partial_context"

        deep_events.append({
            "event_id": event_id,
            "round_num": rn,
            "tick": tick,
            "root_cause": root_cause,
            "real_issue": real_issue,
            "is_actionable": actionable,
            "is_clean_training_example": clean_training,
            "review_status": review_status,
            "source_priority_score": priority_score,
            "deep_label": deep_label,
            "deep_confidence": deep_confidence,
            "deep_flags": flags,
            "player_snapshot": player_snapshot,
            "shot_context": {
                "shots_in_window": len(shot_items),
                "shots_after_event": shots_after_count,
                "first_shot_tick": first_shot_tick,
                "first_shot_delay_ticks": first_shot_delay_ticks,
                "first_shot_delay_ms_assumed": round((first_shot_delay_ticks / ASSUMED_TICK_RATE) * 1000, 1) if first_shot_delay_ticks is not None else None,
                "shots_sample": shot_items[:12],
            },
            "combat_context": combat_context,
            "aim_context": {
                "target_yaw_approx": target_yaw,
                "player_yaw": player_snapshot.get("yaw") if player_snapshot else None,
                "yaw_error_deg_approx": yaw_error,
                "yaw_error_abs_deg_approx": yaw_error_abs,
                "yaw_error_band": aim_error_band(yaw_error_abs),
                "distance_3d": distance,
                "horizontal_distance": horizontal_dist,
                "calculation_note": "approximate yaw-to-target from parsed positions; not a full visibility/raycast check",
            },
            "limitations": [
                "visibility/raycast is not available in v0.1",
                "flash/blind context is missing or partial",
                "manual event tick may not equal exact first-visible tick",
                "yaw error is approximate and depends on parsed positions",
            ],
        })

    label_counts = Counter(x["deep_label"] for x in deep_events)
    confidence_counts = Counter(x["deep_confidence"] for x in deep_events)
    flag_counts = Counter(flag for x in deep_events for flag in x["deep_flags"])
    speed_band_counts = Counter((x.get("player_snapshot") or {}).get("speed_band", "unknown") for x in deep_events)
    aim_band_counts = Counter(x.get("aim_context", {}).get("yaw_error_band", "unknown") for x in deep_events)

    actionable_deep = [
        x for x in deep_events
        if x["deep_confidence"] in ("medium", "high") and x["deep_label"] != "context_only"
    ]

    top_examples = sorted(
        actionable_deep,
        key=lambda x: (
            2 if x["deep_confidence"] == "high" else 1,
            1 if x["real_issue"] == "yes" else 0,
            x.get("aim_context", {}).get("yaw_error_abs_deg_approx") or 0,
        ),
        reverse=True
    )[:15]

    summary = {
        "version": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "events_total": len(deep_events),
        "deep_actionable_events_total": len(actionable_deep),
        "deep_label_counts": dict(label_counts),
        "deep_confidence_counts": dict(confidence_counts),
        "deep_flag_counts": dict(flag_counts),
        "speed_band_counts": dict(speed_band_counts),
        "yaw_error_band_counts": dict(aim_band_counts),
        "top_examples": [
            {
                "event_id": x["event_id"],
                "round_num": x["round_num"],
                "tick": x["tick"],
                "root_cause": x["root_cause"],
                "deep_label": x["deep_label"],
                "deep_confidence": x["deep_confidence"],
                "deep_flags": x["deep_flags"],
                "speed_band": (x.get("player_snapshot") or {}).get("speed_band"),
                "yaw_error_abs_deg_approx": x.get("aim_context", {}).get("yaw_error_abs_deg_approx"),
                "shots_after_event": x.get("shot_context", {}).get("shots_after_event"),
                "opponent": (x.get("combat_context") or {}).get("opponent"),
            }
            for x in top_examples
        ],
        "source_files": {
            "canonical_mechanics_events": rel(mechanics_csv, root),
            "view_ticks_demoparser2": rel(view_path, root),
            "shots": rel(shots_path, root),
            "kills": rel(kills_path, root),
            "damages": rel(damages_path, root),
        },
        "warnings": warnings,
        "known_limitations_v0_1": [
            "No full raycast/visibility check yet.",
            "Flash/blind context is unavailable or partial.",
            "Yaw error is approximate and should be used as evidence, not absolute truth.",
            "Manual mechanics event ticks may be offset from actual first-visible timing.",
        ],
    }

    package = {
        "meta": {
            "version": ANALYZER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "purpose": "deep mechanics context layer for aim/reaction/movement review",
        },
        "summary": summary,
        "deep_events": deep_events,
    }

    out_json = analysis_dir / f"mechanics_deep_{player}_v0_1.json"
    out_current = analysis_dir / "mechanics_deep_current.json"
    out_csv = analysis_dir / f"mechanics_deep_{player}_v0_1.csv"

    write_json(out_json, package)
    write_json(out_current, package)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "event_id",
            "round_num",
            "tick",
            "root_cause",
            "real_issue",
            "is_actionable",
            "is_clean_training_example",
            "deep_label",
            "deep_confidence",
            "deep_flags",
            "speed",
            "speed_band",
            "player_yaw",
            "target_yaw_approx",
            "yaw_error_deg_approx",
            "yaw_error_abs_deg_approx",
            "yaw_error_band",
            "distance_3d",
            "horizontal_distance",
            "shots_in_window",
            "shots_after_event",
            "first_shot_delay_ms_assumed",
            "combat_source",
            "combat_role",
            "opponent",
            "combat_place",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for x in deep_events:
            ps = x.get("player_snapshot") or {}
            ac = x.get("aim_context") or {}
            sc = x.get("shot_context") or {}
            cc = x.get("combat_context") or {}

            writer.writerow({
                "event_id": x.get("event_id"),
                "round_num": x.get("round_num"),
                "tick": x.get("tick"),
                "root_cause": x.get("root_cause"),
                "real_issue": x.get("real_issue"),
                "is_actionable": x.get("is_actionable"),
                "is_clean_training_example": x.get("is_clean_training_example"),
                "deep_label": x.get("deep_label"),
                "deep_confidence": x.get("deep_confidence"),
                "deep_flags": " | ".join(x.get("deep_flags", [])),
                "speed": ps.get("speed"),
                "speed_band": ps.get("speed_band"),
                "player_yaw": ps.get("yaw"),
                "target_yaw_approx": ac.get("target_yaw_approx"),
                "yaw_error_deg_approx": ac.get("yaw_error_deg_approx"),
                "yaw_error_abs_deg_approx": ac.get("yaw_error_abs_deg_approx"),
                "yaw_error_band": ac.get("yaw_error_band"),
                "distance_3d": ac.get("distance_3d"),
                "horizontal_distance": ac.get("horizontal_distance"),
                "shots_in_window": sc.get("shots_in_window"),
                "shots_after_event": sc.get("shots_after_event"),
                "first_shot_delay_ms_assumed": sc.get("first_shot_delay_ms_assumed"),
                "combat_source": cc.get("source"),
                "combat_role": cc.get("role"),
                "opponent": cc.get("opponent"),
                "combat_place": cc.get("place"),
            })

    return {
        "status": "ok",
        "analyzer": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "summary": summary,
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "csv": rel(out_csv, root),
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
