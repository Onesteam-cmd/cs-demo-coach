from __future__ import annotations

import argparse
import html
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


NON_FIREARM_PATTERNS = (
    "knife",
    "flashbang",
    "smokegrenade",
    "hegrenade",
    "molotov",
    "incgrenade",
    "decoy",
    "c4",
    "taser",
)

DUEL_LOOKBACK_TICKS = 256
DUEL_LOOKAHEAD_TICKS = 16
MOVING_SHOT_SPEED = 40.0
SEVERE_MOVING_SHOT_SPEED = 90.0
LARGE_FIRST_SHOT_ERROR_DEG = 4.0
VERY_LARGE_FIRST_SHOT_ERROR_DEG = 8.0
VIEW_SNAPSHOT_TOLERANCE_TICKS = 4


def read_table(parsed_dir: Path, name: str) -> pd.DataFrame:
    path = parsed_dir / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def safe_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
        if math.isfinite(value):
            return value
        return None
    if isinstance(value, np.bool_):
        return bool(value)

    return value


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)
    return [{str(k): safe_value(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def normalize_name(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""

    text = re.sub(r"\s+", " ", text)
    return text.lower()


def last_non_empty(series: pd.Series) -> Any:
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    if len(s) == 0:
        return None
    return s.iloc[-1]


def first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def add_pid_from_name(df: pd.DataFrame, prefix: str, candidates: list[str]) -> None:
    if df.empty:
        return

    name_col = first_existing(df, candidates)

    if name_col is None:
        df[f"{prefix}_name_resolved"] = ""
        df[f"{prefix}_pid"] = ""
        return

    df[f"{prefix}_name_resolved"] = df[name_col].fillna("").astype(str).str.strip()
    df[f"{prefix}_pid"] = df[f"{prefix}_name_resolved"].map(normalize_name)


def is_firearm_weapon(weapon: Any) -> bool:
    if weapon is None:
        return False
    text = str(weapon).lower()
    return not any(p in text for p in NON_FIREARM_PATTERNS)


def angle_delta_deg(a: float, b: float) -> float:
    return float((a - b + 180.0) % 360.0 - 180.0)


def angle_to_target(
    src_x: float,
    src_y: float,
    src_z: float,
    dst_x: float,
    dst_y: float,
    dst_z: float,
) -> tuple[float, float]:
    dx = dst_x - src_x
    dy = dst_y - src_y
    dz = dst_z - src_z

    yaw = math.degrees(math.atan2(dy, dx))
    horizontal = math.sqrt(dx * dx + dy * dy)
    pitch = -math.degrees(math.atan2(dz, max(horizontal, 1e-6)))

    return yaw, pitch


def dist3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return float(math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def add_round_num_by_ranges(df: pd.DataFrame, rounds: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "tick" not in df.columns:
        return df

    if "round_num" in df.columns:
        return df

    if rounds.empty or not all(c in rounds.columns for c in ["round_num", "start", "end"]):
        df["round_num"] = None
        return df

    r = rounds[["round_num", "start", "end"]].dropna().sort_values("start").copy()
    if r.empty:
        df["round_num"] = None
        return df

    starts = r["start"].to_numpy()
    ends = r["end"].to_numpy()
    nums = r["round_num"].to_numpy()

    ticks = pd.to_numeric(df["tick"], errors="coerce").to_numpy()
    idx = np.searchsorted(starts, ticks, side="right") - 1

    out = np.full(len(df), None, dtype=object)
    valid = (idx >= 0) & (idx < len(r))

    for i in np.where(valid)[0]:
        ri = idx[i]
        if ticks[i] <= ends[ri]:
            out[i] = int(nums[ri])

    df["round_num"] = out
    return df


def prepare_view(view: pd.DataFrame) -> pd.DataFrame:
    view = view.copy()
    add_pid_from_name(view, "player", ["player_name", "name"])

    for col in ["X", "Y", "Z", "yaw", "pitch", "velocity_X", "velocity_Y", "velocity_Z", "tick", "health", "armor_value"]:
        if col in view.columns:
            view[col] = pd.to_numeric(view[col], errors="coerce")

    for col in ["velocity_X", "velocity_Y", "velocity_Z"]:
        if col not in view.columns:
            view[col] = 0.0

    view["velocity_speed"] = np.sqrt(
        view["velocity_X"].fillna(0) ** 2
        + view["velocity_Y"].fillna(0) ** 2
        + view["velocity_Z"].fillna(0) ** 2
    )

    keep_cols = [
        "player_pid",
        "player_name_resolved",
        "tick",
        "X",
        "Y",
        "Z",
        "yaw",
        "pitch",
        "velocity_X",
        "velocity_Y",
        "velocity_Z",
        "velocity_speed",
        "health",
        "armor_value",
        "is_alive",
        "active_weapon_name",
        "team_name",
        "steamid",
    ]
    keep_cols = [c for c in keep_cols if c in view.columns]

    view = view[keep_cols].dropna(subset=["tick", "player_pid"])
    view = view[view["player_pid"].astype(str) != ""]
    view["tick"] = view["tick"].astype(int)
    view = view.sort_values(["player_pid", "tick"]).reset_index(drop=True)

    return view


def prepare_events(
    rounds: pd.DataFrame,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    shots: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    kills = kills.copy()
    damages = damages.copy()
    shots = shots.copy()

    add_pid_from_name(kills, "attacker", ["attacker_name"])
    add_pid_from_name(kills, "victim", ["victim_name"])

    add_pid_from_name(damages, "attacker", ["attacker_name"])
    add_pid_from_name(damages, "victim", ["victim_name"])

    add_pid_from_name(shots, "player", ["player_name", "name"])

    kills = add_round_num_by_ranges(kills, rounds)
    damages = add_round_num_by_ranges(damages, rounds)
    shots = add_round_num_by_ranges(shots, rounds)

    for df in [kills, damages, shots]:
        if "tick" in df.columns:
            df["tick"] = pd.to_numeric(df["tick"], errors="coerce")
            df.dropna(subset=["tick"], inplace=True)
            df["tick"] = df["tick"].astype(int)

        if "round_num" in df.columns:
            df["round_num"] = pd.to_numeric(df["round_num"], errors="coerce")
            df.dropna(subset=["round_num"], inplace=True)
            df["round_num"] = df["round_num"].astype(int)

    if "weapon" in shots.columns:
        shots["is_firearm"] = shots["weapon"].map(is_firearm_weapon)
    else:
        shots["is_firearm"] = True

    shots = shots[shots["is_firearm"]].copy()
    shots = shots[shots["player_pid"].astype(str) != ""].copy()

    kills = kills[
        (kills["attacker_pid"].astype(str) != "")
        & (kills["victim_pid"].astype(str) != "")
        & (kills["attacker_pid"] != kills["victim_pid"])
    ].copy()

    damages = damages[
        (damages["attacker_pid"].astype(str) != "")
        & (damages["victim_pid"].astype(str) != "")
        & (damages["attacker_pid"] != damages["victim_pid"])
    ].copy()

    return kills, damages, shots


def build_view_index(view: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        str(pid): group.sort_values("tick").reset_index(drop=True)
        for pid, group in view.groupby("player_pid")
    }


def get_snapshot(
    view_index: dict[str, pd.DataFrame],
    pid: str,
    tick: int,
    tolerance: int = VIEW_SNAPSHOT_TOLERANCE_TICKS,
) -> dict[str, Any] | None:
    pid = str(pid)
    if pid not in view_index:
        return None

    df = view_index[pid]
    if df.empty:
        return None

    ticks = df["tick"].to_numpy()
    idx = int(np.searchsorted(ticks, tick, side="left"))

    candidates = []

    if idx < len(df):
        candidates.append(idx)
    if idx - 1 >= 0:
        candidates.append(idx - 1)

    if not candidates:
        return None

    best_idx = min(candidates, key=lambda i: abs(int(ticks[i]) - tick))
    best_tick = int(ticks[best_idx])

    if abs(best_tick - tick) > tolerance:
        return None

    return df.iloc[best_idx].to_dict()


def shot_snapshot(
    shot_row: pd.Series | None,
    target_pid: str,
    view_index: dict[str, pd.DataFrame],
) -> dict[str, Any] | None:
    if shot_row is None:
        return None

    shooter_pid = str(shot_row.get("player_pid", ""))
    tick = int(shot_row.get("tick"))

    shooter = get_snapshot(view_index, shooter_pid, tick)
    target = get_snapshot(view_index, target_pid, tick)

    if shooter is None or target is None:
        return None

    try:
        shooter_eye = (
            float(shooter["X"]),
            float(shooter["Y"]),
            float(shooter["Z"]) + 64.0,
        )

        target_head = (
            float(target["X"]),
            float(target["Y"]),
            float(target["Z"]) + 64.0,
        )

        target_body = (
            float(target["X"]),
            float(target["Y"]),
            float(target["Z"]) + 48.0,
        )

        target_yaw_head, target_pitch_head = angle_to_target(*shooter_eye, *target_head)
        target_yaw_body, target_pitch_body = angle_to_target(*shooter_eye, *target_body)

        view_yaw = float(shooter["yaw"])
        view_pitch = float(shooter["pitch"])

        yaw_error_head = angle_delta_deg(view_yaw, target_yaw_head)
        pitch_error_head = view_pitch - target_pitch_head
        total_error_head = math.sqrt(yaw_error_head ** 2 + pitch_error_head ** 2)

        yaw_error_body = angle_delta_deg(view_yaw, target_yaw_body)
        pitch_error_body = view_pitch - target_pitch_body
        total_error_body = math.sqrt(yaw_error_body ** 2 + pitch_error_body ** 2)

        distance = dist3(
            (float(shooter["X"]), float(shooter["Y"]), float(shooter["Z"])),
            (float(target["X"]), float(target["Y"]), float(target["Z"])),
        )

        return {
            "tick": tick,
            "weapon": shot_row.get("weapon", shooter.get("active_weapon_name")),
            "speed": float(shooter.get("velocity_speed", np.nan)),
            "yaw": view_yaw,
            "pitch": view_pitch,
            "target_yaw_head": target_yaw_head,
            "target_pitch_head": target_pitch_head,
            "yaw_error_head": yaw_error_head,
            "pitch_error_head": pitch_error_head,
            "total_error_head": total_error_head,
            "yaw_error_body": yaw_error_body,
            "pitch_error_body": pitch_error_body,
            "total_error_body": total_error_body,
            "distance": distance,
            "shooter_x": safe_value(shooter.get("X")),
            "shooter_y": safe_value(shooter.get("Y")),
            "shooter_z": safe_value(shooter.get("Z")),
            "target_x": safe_value(target.get("X")),
            "target_y": safe_value(target.get("Y")),
            "target_z": safe_value(target.get("Z")),
        }
    except Exception:
        return None


def first_row(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None
    return df.sort_values("tick").iloc[0]


def count_rows(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    return int(len(df))


def build_kill_duels(
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    shots: pd.DataFrame,
    view_index: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if kills.empty:
        return pd.DataFrame()

    duel_rows: list[dict[str, Any]] = []

    for _, k in kills.sort_values(["round_num", "tick"]).iterrows():
        round_num = int(k["round_num"])
        kill_tick = int(k["tick"])

        attacker_pid = str(k["attacker_pid"])
        victim_pid = str(k["victim_pid"])

        window_start = kill_tick - DUEL_LOOKBACK_TICKS
        window_end = kill_tick + DUEL_LOOKAHEAD_TICKS

        attacker_shots = shots[
            (shots["round_num"] == round_num)
            & (shots["player_pid"] == attacker_pid)
            & (shots["tick"] >= window_start)
            & (shots["tick"] <= window_end)
        ].copy()

        victim_shots = shots[
            (shots["round_num"] == round_num)
            & (shots["player_pid"] == victim_pid)
            & (shots["tick"] >= window_start)
            & (shots["tick"] <= window_end)
        ].copy()

        attacker_first = first_row(attacker_shots)
        victim_first = first_row(victim_shots)

        attacker_first_snap = shot_snapshot(attacker_first, victim_pid, view_index)
        victim_first_snap = shot_snapshot(victim_first, attacker_pid, view_index)

        attacker_first_tick = None if attacker_first is None else int(attacker_first["tick"])
        victim_first_tick = None if victim_first is None else int(victim_first["tick"])

        if attacker_first_tick is not None and victim_first_tick is not None:
            if attacker_first_tick < victim_first_tick:
                first_shooter = "attacker"
                first_shot_tick_diff = int(victim_first_tick - attacker_first_tick)
            elif victim_first_tick < attacker_first_tick:
                first_shooter = "victim"
                first_shot_tick_diff = int(attacker_first_tick - victim_first_tick)
            else:
                first_shooter = "simultaneous"
                first_shot_tick_diff = 0
        elif attacker_first_tick is not None:
            first_shooter = "attacker"
            first_shot_tick_diff = None
        elif victim_first_tick is not None:
            first_shooter = "victim"
            first_shot_tick_diff = None
        else:
            first_shooter = "none"
            first_shot_tick_diff = None

        attacker_to_victim_damage = damages[
            (damages["round_num"] == round_num)
            & (damages["attacker_pid"] == attacker_pid)
            & (damages["victim_pid"] == victim_pid)
            & (damages["tick"] >= window_start)
            & (damages["tick"] <= window_end)
        ].copy()

        victim_to_attacker_damage = damages[
            (damages["round_num"] == round_num)
            & (damages["attacker_pid"] == victim_pid)
            & (damages["victim_pid"] == attacker_pid)
            & (damages["tick"] >= window_start)
            & (damages["tick"] <= window_end)
        ].copy()

        first_attacker_damage_tick = None
        first_victim_damage_tick = None

        if not attacker_to_victim_damage.empty:
            first_attacker_damage_tick = int(attacker_to_victim_damage["tick"].min())

        if not victim_to_attacker_damage.empty:
            first_victim_damage_tick = int(victim_to_attacker_damage["tick"].min())

        tags = []
        practical_note = []

        victim_fired = victim_first_tick is not None
        attacker_fired = attacker_first_tick is not None

        if not victim_fired:
            tags.append("victim_died_without_firing")
            practical_note.append("умерший не сделал выстрел в окне дуэли: проверить готовность к контакту, угол, тайминг, ослепление или смерть в спину")

        if first_shooter == "victim":
            tags.append("victim_shot_first_but_lost")
            practical_note.append("умерший выстрелил первым, но проиграл: проверить качество первого выстрела, остановку, спрей или цель наведения")

        if first_shooter == "attacker":
            tags.append("attacker_shot_first_and_won")

        if attacker_first_snap is not None:
            attacker_speed = attacker_first_snap.get("speed")
            attacker_err = attacker_first_snap.get("total_error_head")

            if attacker_speed is not None and attacker_speed > MOVING_SHOT_SPEED:
                tags.append("attacker_first_shot_moving")
            if attacker_speed is not None and attacker_speed > SEVERE_MOVING_SHOT_SPEED:
                tags.append("attacker_first_shot_severe_moving")
            if attacker_err is not None and attacker_err > LARGE_FIRST_SHOT_ERROR_DEG:
                tags.append("attacker_large_first_shot_error")
            if attacker_err is not None and attacker_err > VERY_LARGE_FIRST_SHOT_ERROR_DEG:
                tags.append("attacker_very_large_first_shot_error")

        if victim_first_snap is not None:
            victim_speed = victim_first_snap.get("speed")
            victim_err = victim_first_snap.get("total_error_head")

            if victim_speed is not None and victim_speed > MOVING_SHOT_SPEED:
                tags.append("victim_first_shot_moving")
                practical_note.append("умерший сделал первый выстрел на скорости: возможная проблема counter-strafe")
            if victim_speed is not None and victim_speed > SEVERE_MOVING_SHOT_SPEED:
                tags.append("victim_first_shot_severe_moving")
            if victim_err is not None and victim_err > LARGE_FIRST_SHOT_ERROR_DEG:
                tags.append("victim_large_first_shot_error")
                practical_note.append("первый выстрел умершего был далеко от головы/тела цели: возможный промах из-за aim placement или резкого перевода")
            if victim_err is not None and victim_err > VERY_LARGE_FIRST_SHOT_ERROR_DEG:
                tags.append("victim_very_large_first_shot_error")

        if bool(k.get("headshot", False)):
            tags.append("kill_headshot")

        if bool(k.get("thrusmoke", False)):
            tags.append("kill_through_smoke")
            practical_note.append("килл через дым: проверить шум, спам, стандартную позицию или плохое движение за smoke")

        if bool(k.get("attackerblind", False)):
            tags.append("attacker_blind_kill")

        if bool(k.get("victimblind", False)):
            tags.append("victim_blind_death")

        if not practical_note:
            practical_note.append("момент требует просмотра: базовые признаки грубой ошибки не сработали, но дуэль можно открыть по tick")

        duel_rows.append(
            {
                "round_num": round_num,
                "kill_tick": kill_tick,
                "attacker_name": k.get("attacker_name"),
                "attacker_pid": attacker_pid,
                "victim_name": k.get("victim_name"),
                "victim_pid": victim_pid,
                "attacker_side": k.get("attacker_side"),
                "victim_side": k.get("victim_side"),
                "attacker_place": k.get("attacker_place"),
                "victim_place": k.get("victim_place"),
                "weapon": k.get("weapon"),
                "headshot": bool(k.get("headshot", False)),
                "distance_awpy": safe_value(k.get("distance")),
                "first_shooter": first_shooter,
                "first_shot_tick_diff": first_shot_tick_diff,
                "attacker_first_shot_tick": attacker_first_tick,
                "victim_first_shot_tick": victim_first_tick,
                "attacker_shots_in_window": count_rows(attacker_shots),
                "victim_shots_in_window": count_rows(victim_shots),
                "attacker_damage_events_to_victim": count_rows(attacker_to_victim_damage),
                "victim_damage_events_to_attacker": count_rows(victim_to_attacker_damage),
                "first_attacker_damage_tick": first_attacker_damage_tick,
                "first_victim_damage_tick": first_victim_damage_tick,
                "attacker_first_shot_speed": None if attacker_first_snap is None else safe_value(attacker_first_snap.get("speed")),
                "victim_first_shot_speed": None if victim_first_snap is None else safe_value(victim_first_snap.get("speed")),
                "attacker_first_shot_error_head_deg": None if attacker_first_snap is None else safe_value(attacker_first_snap.get("total_error_head")),
                "victim_first_shot_error_head_deg": None if victim_first_snap is None else safe_value(victim_first_snap.get("total_error_head")),
                "attacker_first_shot_error_body_deg": None if attacker_first_snap is None else safe_value(attacker_first_snap.get("total_error_body")),
                "victim_first_shot_error_body_deg": None if victim_first_snap is None else safe_value(victim_first_snap.get("total_error_body")),
                "estimated_distance": None if attacker_first_snap is None else safe_value(attacker_first_snap.get("distance")),
                "tags": tags,
                "practical_note": "; ".join(practical_note),
            }
        )

    return pd.DataFrame(duel_rows)


def build_player_duel_summary(duels: pd.DataFrame) -> pd.DataFrame:
    if duels.empty:
        return pd.DataFrame()

    players = sorted(
        set(duels["attacker_pid"].dropna().astype(str).tolist())
        | set(duels["victim_pid"].dropna().astype(str).tolist())
    )

    rows = []

    for pid in players:
        kills = duels[duels["attacker_pid"] == pid].copy()
        deaths = duels[duels["victim_pid"] == pid].copy()

        name = None
        if not kills.empty:
            name = last_non_empty(kills["attacker_name"])
        if name is None and not deaths.empty:
            name = last_non_empty(deaths["victim_name"])

        died_without_firing = int(deaths["tags"].map(lambda x: "victim_died_without_firing" in x).sum()) if not deaths.empty else 0
        lost_after_shooting_first = int((deaths["first_shooter"] == "victim").sum()) if not deaths.empty else 0
        death_first_shot_moving = int(deaths["tags"].map(lambda x: "victim_first_shot_moving" in x).sum()) if not deaths.empty else 0
        death_large_first_error = int(deaths["tags"].map(lambda x: "victim_large_first_shot_error" in x).sum()) if not deaths.empty else 0

        kills_after_shooting_first = int((kills["first_shooter"] == "attacker").sum()) if not kills.empty else 0
        kills_without_victim_firing = int(kills["tags"].map(lambda x: "victim_died_without_firing" in x).sum()) if not kills.empty else 0
        attacker_first_moving_on_kill = int(kills["tags"].map(lambda x: "attacker_first_shot_moving" in x).sum()) if not kills.empty else 0
        attacker_large_error_on_kill = int(kills["tags"].map(lambda x: "attacker_large_first_shot_error" in x).sum()) if not kills.empty else 0

        victim_error_avg = None
        victim_speed_avg = None

        if not deaths.empty:
            err = pd.to_numeric(deaths["victim_first_shot_error_head_deg"], errors="coerce").dropna()
            spd = pd.to_numeric(deaths["victim_first_shot_speed"], errors="coerce").dropna()
            if len(err) > 0:
                victim_error_avg = float(err.mean())
            if len(spd) > 0:
                victim_speed_avg = float(spd.mean())

        flags = []

        if died_without_firing >= 3:
            flags.append("часто умирает без выстрела")
        if lost_after_shooting_first >= 3:
            flags.append("часто стреляет первым, но проигрывает")
        if death_first_shot_moving >= 3:
            flags.append("первый выстрел в проигранных дуэлях часто на скорости")
        if death_large_first_error >= 3:
            flags.append("первый выстрел в проигранных дуэлях часто далеко от цели")
        if attacker_first_moving_on_kill >= 4:
            flags.append("выигрывает часть дуэлей рискованными первыми выстрелами в движении")

        defensive_score = 100.0
        defensive_score -= died_without_firing * 7.0
        defensive_score -= lost_after_shooting_first * 5.0
        defensive_score -= death_first_shot_moving * 4.0
        defensive_score -= death_large_first_error * 4.0
        defensive_score = round(max(0.0, min(100.0, defensive_score)), 1)

        rows.append(
            {
                "player_pid": pid,
                "name": name or pid,
                "duel_kills": int(len(kills)),
                "duel_deaths": int(len(deaths)),
                "kills_after_shooting_first": kills_after_shooting_first,
                "kills_without_victim_firing": kills_without_victim_firing,
                "attacker_first_moving_on_kill": attacker_first_moving_on_kill,
                "attacker_large_error_on_kill": attacker_large_error_on_kill,
                "died_without_firing": died_without_firing,
                "lost_after_shooting_first": lost_after_shooting_first,
                "death_first_shot_moving": death_first_shot_moving,
                "death_large_first_error": death_large_first_error,
                "avg_victim_first_shot_speed": None if victim_speed_avg is None else round(victim_speed_avg, 1),
                "avg_victim_first_shot_error_head_deg": None if victim_error_avg is None else round(victim_error_avg, 2),
                "defensive_duel_score": defensive_score,
                "flags": flags,
            }
        )

    df = pd.DataFrame(rows)

    df = df.sort_values(
        ["died_without_firing", "lost_after_shooting_first", "death_first_shot_moving", "duel_deaths"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    return df


def build_priority_moments(duels: pd.DataFrame, limit: int = 120) -> pd.DataFrame:
    if duels.empty:
        return pd.DataFrame()

    def priority(row: pd.Series) -> int:
        tags = row.get("tags", [])
        score = 0

        if "victim_died_without_firing" in tags:
            score += 40
        if "victim_shot_first_but_lost" in tags:
            score += 35
        if "victim_first_shot_moving" in tags:
            score += 25
        if "victim_large_first_shot_error" in tags:
            score += 25
        if "kill_through_smoke" in tags:
            score += 20
        if "victim_blind_death" in tags:
            score += 15
        if row.get("headshot") is True:
            score += 5

        return score

    moments = duels.copy()
    moments["priority_score"] = moments.apply(priority, axis=1)

    moments = moments[moments["priority_score"] > 0].copy()

    if moments.empty:
        return pd.DataFrame()

    cols = [
        "priority_score",
        "round_num",
        "kill_tick",
        "victim_name",
        "attacker_name",
        "weapon",
        "first_shooter",
        "victim_shots_in_window",
        "attacker_shots_in_window",
        "victim_first_shot_speed",
        "victim_first_shot_error_head_deg",
        "attacker_first_shot_speed",
        "attacker_first_shot_error_head_deg",
        "tags",
        "practical_note",
    ]

    cols = [c for c in cols if c in moments.columns]

    moments = moments.sort_values(["priority_score", "round_num", "kill_tick"], ascending=[False, True, True])
    return moments[cols].head(limit).reset_index(drop=True)


def make_html_report(report: dict[str, Any], out_path: Path) -> None:
    def esc(v: Any) -> str:
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        return html.escape("" if v is None else str(v))

    def fmt(v: Any, ndigits: int = 1) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float)) and math.isfinite(float(v)):
            return str(round(float(v), ndigits))
        return str(v)

    summary = report.get("summary", {})
    players = report.get("player_duel_summary", [])
    moments = report.get("priority_moments", [])

    player_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(p.get('name'))}</td>
            <td>{esc(p.get('duel_kills'))}</td>
            <td>{esc(p.get('duel_deaths'))}</td>
            <td>{esc(p.get('died_without_firing'))}</td>
            <td>{esc(p.get('lost_after_shooting_first'))}</td>
            <td>{esc(p.get('death_first_shot_moving'))}</td>
            <td>{esc(p.get('death_large_first_error'))}</td>
            <td>{esc(p.get('kills_after_shooting_first'))}</td>
            <td>{esc(p.get('kills_without_victim_firing'))}</td>
            <td>{esc(p.get('avg_victim_first_shot_speed'))}</td>
            <td>{esc(p.get('avg_victim_first_shot_error_head_deg'))}</td>
            <td>{esc(p.get('defensive_duel_score'))}</td>
            <td>{esc(p.get('flags'))}</td>
        </tr>
        """
        for p in players
    )

    moment_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(m.get('priority_score'))}</td>
            <td>R{esc(m.get('round_num'))}</td>
            <td>{esc(m.get('kill_tick'))}</td>
            <td>{esc(m.get('victim_name'))}</td>
            <td>{esc(m.get('attacker_name'))}</td>
            <td>{esc(m.get('weapon'))}</td>
            <td>{esc(m.get('first_shooter'))}</td>
            <td>{esc(m.get('victim_shots_in_window'))}</td>
            <td>{esc(m.get('attacker_shots_in_window'))}</td>
            <td>{esc(fmt(m.get('victim_first_shot_speed')))}</td>
            <td>{esc(fmt(m.get('victim_first_shot_error_head_deg'), 2))}</td>
            <td>{esc(m.get('tags'))}</td>
            <td>{esc(m.get('practical_note'))}</td>
        </tr>
        """
        for m in moments
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Duel Model v0.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1480px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 16px;
        margin: 20px 0;
    }}
    .card {{
        background: linear-gradient(180deg, #121c29, #0f1722);
        border: 1px solid #223043;
        border-radius: 16px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.25);
    }}
    .metric {{
        font-size: 30px;
        font-weight: 800;
    }}
    .notice {{
        border: 1px solid #36557e;
        background: #101b2a;
        color: #c7d9f0;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 20px 0;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0 32px;
        background: #101721;
        border-radius: 14px;
        overflow: hidden;
    }}
    th, td {{
        padding: 10px 12px;
        border-bottom: 1px solid #223043;
        text-align: left;
        font-size: 13px;
        vertical-align: top;
    }}
    th {{
        background: #172232;
        color: #bfd0e4;
    }}
    tr:hover td {{ background: #142033; }}
    .section {{ margin-top: 34px; }}
    .small {{ font-size: 13px; }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Duel/Contact Model v0.1</h1>
    <p class="muted">Первый слой дуэлей: kill-based contacts. Модель смотрит не все выстрелы подряд, а конкретные контакты, закончившиеся убийством.</p>

    <div class="notice">
        Ограничение v0.1: это ещё не полноценная wall/smoke visibility-модель. Дуэли строятся от kill-событий и ближайших выстрелов вокруг них. Поэтому выводы уже практические, но спорные моменты нужно открывать в демке.
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Kill duels</div><div class="metric">{esc(summary.get('kill_duels'))}</div></div>
        <div class="card"><div class="muted">Died no shot</div><div class="metric">{esc(summary.get('victim_died_without_firing'))}</div></div>
        <div class="card"><div class="muted">Shot first lost</div><div class="metric">{esc(summary.get('victim_shot_first_but_lost'))}</div></div>
        <div class="card"><div class="muted">Priority moments</div><div class="metric">{esc(summary.get('priority_moments'))}</div></div>
    </div>

    <div class="section">
        <h2>Дуэльная сводка игроков</h2>
        <table>
            <thead>
                <tr>
                    <th>Игрок</th>
                    <th>Duel K</th>
                    <th>Duel D</th>
                    <th>Died no shot</th>
                    <th>Shot first lost</th>
                    <th>Death first moving</th>
                    <th>Death large aim err</th>
                    <th>Kills shot first</th>
                    <th>Kills no victim shot</th>
                    <th>Avg death shot speed</th>
                    <th>Avg death aim err</th>
                    <th>Def score</th>
                    <th>Flags</th>
                </tr>
            </thead>
            <tbody>{player_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Приоритетные моменты для просмотра</h2>
        <p class="muted small">Это моменты, которые уже можно открывать в demo/replay: смерть без выстрела, проигрыш после первого выстрела, первый выстрел на скорости, большая ошибка наведения.</p>
        <table>
            <thead>
                <tr>
                    <th>Priority</th>
                    <th>Round</th>
                    <th>Tick</th>
                    <th>Умер</th>
                    <th>Убил</th>
                    <th>Оружие</th>
                    <th>First shooter</th>
                    <th>Victim shots</th>
                    <th>Attacker shots</th>
                    <th>Victim speed</th>
                    <th>Victim aim err</th>
                    <th>Tags</th>
                    <th>Практический смысл</th>
                </tr>
            </thead>
            <tbody>{moment_rows}</tbody>
        </table>
    </div>
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parsed_dir", type=Path, help="Path to data/parsed/<demo_name>")
    args = parser.parse_args()

    parsed_dir: Path = args.parsed_dir
    if not parsed_dir.exists():
        raise SystemExit(f"Parsed dir not found: {parsed_dir}")

    view_path = parsed_dir / "view_ticks_demoparser2.parquet"
    if not view_path.exists():
        raise SystemExit(f"View layer not found: {view_path}")

    out_dir = Path("data/reports") / parsed_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    rounds = read_table(parsed_dir, "rounds")
    kills = read_table(parsed_dir, "kills")
    damages = read_table(parsed_dir, "damages")
    shots = read_table(parsed_dir, "shots")
    view = pd.read_parquet(view_path)

    view = prepare_view(view)
    kills, damages, shots = prepare_events(rounds, kills, damages, shots)

    view_index = build_view_index(view)

    kill_duels = build_kill_duels(kills, damages, shots, view_index)
    player_duel_summary = build_player_duel_summary(kill_duels)
    priority_moments = build_priority_moments(kill_duels, limit=160)

    if kill_duels.empty:
        victim_died_without_firing = 0
        victim_shot_first_but_lost = 0
        victim_first_shot_moving = 0
    else:
        victim_died_without_firing = int(kill_duels["tags"].map(lambda x: "victim_died_without_firing" in x).sum())
        victim_shot_first_but_lost = int((kill_duels["first_shooter"] == "victim").sum())
        victim_first_shot_moving = int(kill_duels["tags"].map(lambda x: "victim_first_shot_moving" in x).sum())

    summary = {
        "demo_name": parsed_dir.name,
        "kill_duels": int(len(kill_duels)),
        "players": int(len(player_duel_summary)),
        "priority_moments": int(len(priority_moments)),
        "victim_died_without_firing": victim_died_without_firing,
        "victim_shot_first_but_lost": victim_shot_first_but_lost,
        "victim_first_shot_moving": victim_first_shot_moving,
        "duel_lookback_ticks": DUEL_LOOKBACK_TICKS,
        "duel_lookahead_ticks": DUEL_LOOKAHEAD_TICKS,
        "moving_shot_speed": MOVING_SHOT_SPEED,
        "large_first_shot_error_deg": LARGE_FIRST_SHOT_ERROR_DEG,
        "notes": [
            "Duel model v0.1 is kill-based, not full visibility-based.",
            "It uses nearest view snapshots to estimate first shot movement and rough aim error.",
            "The next step should add visibility/contact discovery, not only kill-seeded duels.",
        ],
    }

    report = {
        "summary": summary,
        "player_duel_summary": records(player_duel_summary),
        "priority_moments": records(priority_moments),
    }

    json_path = out_dir / "duel_model_v0_1.json"
    html_path = out_dir / "duel_model_v0_1.html"
    duels_path = out_dir / "kill_duels_v0_1.parquet"
    priority_path = out_dir / "priority_moments_v0_1.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html_report(report, html_path)

    if not kill_duels.empty:
        kill_duels.to_parquet(duels_path, index=False)

    if not priority_moments.empty:
        priority_moments.to_csv(priority_path, index=False, encoding="utf-8-sig")

    print("=== CS Demo Coach Duel/Contact Model v0.1 ===")
    print(f"Parsed dir: {parsed_dir}")
    print(f"Kill duels: {summary['kill_duels']}")
    print(f"Players: {summary['players']}")
    print(f"Victim died without firing: {summary['victim_died_without_firing']}")
    print(f"Victim shot first but lost: {summary['victim_shot_first_but_lost']}")
    print(f"Victim first shot moving: {summary['victim_first_shot_moving']}")
    print(f"Priority moments: {summary['priority_moments']}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")
    print(f"Duels parquet: {duels_path}")
    print(f"Priority CSV: {priority_path}")

    print("")
    print("Player duel summary:")
    if player_duel_summary.empty:
        print("  No duel summary found.")
    else:
        cols = [
            "name",
            "duel_kills",
            "duel_deaths",
            "died_without_firing",
            "lost_after_shooting_first",
            "death_first_shot_moving",
            "death_large_first_error",
            "defensive_duel_score",
        ]
        print(player_duel_summary[cols].to_string(index=False))

    print("")
    print("Next: open duel_model_v0_1.html in browser.")


if __name__ == "__main__":
    main()
