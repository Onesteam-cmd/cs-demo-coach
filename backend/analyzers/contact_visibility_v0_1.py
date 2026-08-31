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

SAMPLE_STEP_TICKS = 8
MAX_CONTACT_FOV_DEG = 12.0
MAX_CONTACT_DISTANCE = 3500.0
CONTACT_MERGE_GAP_TICKS = 24
CONTACT_ACTION_WINDOW_TICKS = 96

MOVING_SHOT_SPEED = 40.0
SEVERE_MOVING_SHOT_SPEED = 90.0
DELAYED_SHOT_TICKS = 32
LARGE_FIRST_SHOT_ERROR_DEG = 4.0
VERY_LARGE_FIRST_SHOT_ERROR_DEG = 8.0
SNAPSHOT_TOLERANCE_TICKS = 4


def make_json_safe(value: Any) -> Any:
    try:
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(k): make_json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [make_json_safe(v) for v in value]
        if isinstance(value, np.ndarray):
            return [make_json_safe(v) for v in value.tolist()]
        if isinstance(value, pd.Series):
            return [make_json_safe(v) for v in value.tolist()]
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            value = float(value)
            return value if math.isfinite(value) else None
        if isinstance(value, np.bool_):
            return bool(value)
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        return value
    except Exception:
        return str(value)


def safe_value(value: Any) -> Any:
    return make_json_safe(value)


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)
    return make_json_safe(df.to_dict(orient="records"))


def read_table(parsed_dir: Path, name: str) -> pd.DataFrame:
    path = parsed_dir / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


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


def last_non_empty(series: pd.Series) -> Any:
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    if len(s) == 0:
        return None
    return s.iloc[-1]


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


def angle_error_to_target(viewer: dict[str, Any], target: dict[str, Any]) -> dict[str, float] | None:
    try:
        vx = float(viewer["X"])
        vy = float(viewer["Y"])
        vz = float(viewer["Z"]) + 64.0
        tx = float(target["X"])
        ty = float(target["Y"])

        target_head_z = float(target["Z"]) + 64.0
        target_body_z = float(target["Z"]) + 48.0

        target_yaw_head, target_pitch_head = angle_to_target(vx, vy, vz, tx, ty, target_head_z)
        target_yaw_body, target_pitch_body = angle_to_target(vx, vy, vz, tx, ty, target_body_z)

        view_yaw = float(viewer["yaw"])
        view_pitch = float(viewer["pitch"])

        yaw_err_head = angle_delta_deg(view_yaw, target_yaw_head)
        pitch_err_head = view_pitch - target_pitch_head
        total_head = math.sqrt(yaw_err_head ** 2 + pitch_err_head ** 2)

        yaw_err_body = angle_delta_deg(view_yaw, target_yaw_body)
        pitch_err_body = view_pitch - target_pitch_body
        total_body = math.sqrt(yaw_err_body ** 2 + pitch_err_body ** 2)

        dx = tx - vx
        dy = ty - vy
        dz = float(target["Z"]) - float(viewer["Z"])
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        return {
            "yaw_error_head": yaw_err_head,
            "pitch_error_head": pitch_err_head,
            "total_error_head": total_head,
            "yaw_error_body": yaw_err_body,
            "pitch_error_body": pitch_err_body,
            "total_error_body": total_body,
            "min_error": min(total_head, total_body),
            "distance": dist,
        }
    except Exception:
        return None


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


def prepare_view(view: pd.DataFrame, rounds: pd.DataFrame) -> pd.DataFrame:
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

    if "team_name" in view.columns:
        view["team_key"] = view["team_name"].map(normalize_name)
    else:
        view["team_key"] = ""

    if "health" in view.columns:
        view["alive_proxy"] = view["health"].fillna(0) > 0
    else:
        view["alive_proxy"] = True

    required = ["tick", "player_pid", "X", "Y", "Z", "yaw", "pitch", "team_key"]
    view = view.dropna(subset=[c for c in required if c in view.columns])
    view = view[view["player_pid"].astype(str) != ""]
    view = view[view["team_key"].astype(str) != ""]
    view = view[view["alive_proxy"] == True]
    view["tick"] = view["tick"].astype(int)

    view = add_round_num_by_ranges(view, rounds)
    view = view.dropna(subset=["round_num"])
    view["round_num"] = view["round_num"].astype(int)

    keep_cols = [
        "round_num",
        "tick",
        "player_pid",
        "player_name_resolved",
        "team_key",
        "team_name",
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
        "active_weapon_name",
        "steamid",
    ]
    keep_cols = [c for c in keep_cols if c in view.columns]

    view = view[keep_cols].sort_values(["round_num", "tick", "player_pid"]).reset_index(drop=True)
    return view


def prepare_events(rounds: pd.DataFrame, shots: pd.DataFrame, kills: pd.DataFrame, damages: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    shots = shots.copy()
    kills = kills.copy()
    damages = damages.copy()

    add_pid_from_name(shots, "player", ["player_name", "name"])
    add_pid_from_name(kills, "attacker", ["attacker_name"])
    add_pid_from_name(kills, "victim", ["victim_name"])
    add_pid_from_name(damages, "attacker", ["attacker_name"])
    add_pid_from_name(damages, "victim", ["victim_name"])

    shots = add_round_num_by_ranges(shots, rounds)
    kills = add_round_num_by_ranges(kills, rounds)
    damages = add_round_num_by_ranges(damages, rounds)

    for df in [shots, kills, damages]:
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

    shots = shots[shots["is_firearm"] == True].copy()
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

    return shots, kills, damages


def build_view_index(view: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        str(pid): group.sort_values("tick").reset_index(drop=True)
        for pid, group in view.groupby("player_pid")
    }


def get_snapshot(view_index: dict[str, pd.DataFrame], pid: str, tick: int, tolerance: int = SNAPSHOT_TOLERANCE_TICKS) -> dict[str, Any] | None:
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


def shot_metrics(
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

    err = angle_error_to_target(shooter, target)
    if err is None:
        return None

    return {
        "tick": tick,
        "weapon": shot_row.get("weapon", shooter.get("active_weapon_name")),
        "speed": safe_value(shooter.get("velocity_speed")),
        "error_head": safe_value(err.get("total_error_head")),
        "error_body": safe_value(err.get("total_error_body")),
        "min_error": safe_value(err.get("min_error")),
        "distance": safe_value(err.get("distance")),
    }


def first_row(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None
    return df.sort_values("tick").iloc[0]


def detect_contact_observations(
    view: pd.DataFrame,
    sample_step: int,
    max_fov: float,
    max_distance: float,
) -> pd.DataFrame:
    if view.empty:
        return pd.DataFrame()

    sampled = view[view["tick"] % sample_step == 0].copy()

    if sampled.empty:
        unique_ticks = sorted(view["tick"].unique().tolist())
        keep_ticks = set(unique_ticks[::sample_step])
        sampled = view[view["tick"].isin(keep_ticks)].copy()

    observations: list[dict[str, Any]] = []

    grouped = sampled.groupby(["round_num", "tick"], sort=True)
    total_groups = grouped.ngroups
    processed = 0

    for (round_num, tick), group in grouped:
        processed += 1

        if processed % 2000 == 0:
            print(f"  processed sampled ticks: {processed}/{total_groups}")

        rows = group.to_dict(orient="records")
        if len(rows) < 2:
            continue

        for viewer in rows:
            viewer_pid = str(viewer.get("player_pid", ""))
            viewer_team = str(viewer.get("team_key", ""))

            if not viewer_pid or not viewer_team:
                continue

            for target in rows:
                target_pid = str(target.get("player_pid", ""))
                target_team = str(target.get("team_key", ""))

                if not target_pid or not target_team:
                    continue

                if target_pid == viewer_pid:
                    continue

                if target_team == viewer_team:
                    continue

                err = angle_error_to_target(viewer, target)
                if err is None:
                    continue

                if err["distance"] > max_distance:
                    continue

                if err["min_error"] > max_fov:
                    continue

                observations.append({
                    "round_num": int(round_num),
                    "tick": int(tick),
                    "viewer_pid": viewer_pid,
                    "viewer_name": viewer.get("player_name_resolved"),
                    "viewer_team": viewer.get("team_name", viewer_team),
                    "target_pid": target_pid,
                    "target_name": target.get("player_name_resolved"),
                    "target_team": target.get("team_name", target_team),
                    "viewer_x": safe_value(viewer.get("X")),
                    "viewer_y": safe_value(viewer.get("Y")),
                    "viewer_z": safe_value(viewer.get("Z")),
                    "target_x": safe_value(target.get("X")),
                    "target_y": safe_value(target.get("Y")),
                    "target_z": safe_value(target.get("Z")),
                    "viewer_speed": safe_value(viewer.get("velocity_speed")),
                    "viewer_weapon": viewer.get("active_weapon_name"),
                    "distance": safe_value(err["distance"]),
                    "error_head": safe_value(err["total_error_head"]),
                    "error_body": safe_value(err["total_error_body"]),
                    "min_error": safe_value(err["min_error"]),
                })

    return pd.DataFrame(observations)


def build_contact_segments(observations: pd.DataFrame, merge_gap_ticks: int) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame()

    observations = observations.sort_values(["round_num", "viewer_pid", "target_pid", "tick"]).reset_index(drop=True)

    segments: list[dict[str, Any]] = []

    for (round_num, viewer_pid, target_pid), g in observations.groupby(["round_num", "viewer_pid", "target_pid"], sort=False):
        g = g.sort_values("tick").reset_index(drop=True)

        current_rows: list[dict[str, Any]] = []
        prev_tick: int | None = None

        def flush(rows: list[dict[str, Any]]) -> None:
            if not rows:
                return

            start = rows[0]
            end = rows[-1]
            df = pd.DataFrame(rows)

            min_idx = df["min_error"].astype(float).idxmin()
            best = df.loc[min_idx]

            segments.append({
                "round_num": int(round_num),
                "viewer_pid": str(viewer_pid),
                "viewer_name": start.get("viewer_name"),
                "viewer_team": start.get("viewer_team"),
                "target_pid": str(target_pid),
                "target_name": start.get("target_name"),
                "target_team": start.get("target_team"),
                "contact_start_tick": int(start["tick"]),
                "contact_end_tick": int(end["tick"]),
                "duration_ticks": int(end["tick"] - start["tick"]),
                "samples": int(len(rows)),
                "start_distance": safe_value(start.get("distance")),
                "min_distance": safe_value(df["distance"].astype(float).min()),
                "start_error": safe_value(start.get("min_error")),
                "min_error": safe_value(best.get("min_error")),
                "min_error_tick": int(best.get("tick")),
                "viewer_speed_start": safe_value(start.get("viewer_speed")),
                "viewer_speed_avg": safe_value(df["viewer_speed"].astype(float).mean()),
                "viewer_weapon_start": start.get("viewer_weapon"),
                "visibility_model": "angle_fov_proxy_no_walls_no_smokes",
            })

        for _, row in g.iterrows():
            r = row.to_dict()
            tick = int(r["tick"])

            if prev_tick is None or tick - prev_tick <= merge_gap_ticks:
                current_rows.append(r)
            else:
                flush(current_rows)
                current_rows = [r]

            prev_tick = tick

        flush(current_rows)

    return pd.DataFrame(segments)


def annotate_contacts(
    contacts: pd.DataFrame,
    shots: pd.DataFrame,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    view_index: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if contacts.empty:
        return contacts

    rows: list[dict[str, Any]] = []

    for _, c in contacts.iterrows():
        round_num = int(c["round_num"])
        start = int(c["contact_start_tick"])
        end = int(c["contact_end_tick"])
        action_end = end + CONTACT_ACTION_WINDOW_TICKS

        viewer_pid = str(c["viewer_pid"])
        target_pid = str(c["target_pid"])

        viewer_shots = shots[
            (shots["round_num"] == round_num)
            & (shots["player_pid"] == viewer_pid)
            & (shots["tick"] >= start)
            & (shots["tick"] <= action_end)
        ].copy()

        target_shots = shots[
            (shots["round_num"] == round_num)
            & (shots["player_pid"] == target_pid)
            & (shots["tick"] >= start)
            & (shots["tick"] <= action_end)
        ].copy()

        viewer_first_shot = first_row(viewer_shots)
        target_first_shot = first_row(target_shots)

        viewer_metrics = shot_metrics(viewer_first_shot, target_pid, view_index)
        target_metrics = shot_metrics(target_first_shot, viewer_pid, view_index)

        viewer_first_tick = None if viewer_first_shot is None else int(viewer_first_shot["tick"])
        target_first_tick = None if target_first_shot is None else int(target_first_shot["tick"])

        viewer_kills_target = kills[
            (kills["round_num"] == round_num)
            & (kills["attacker_pid"] == viewer_pid)
            & (kills["victim_pid"] == target_pid)
            & (kills["tick"] >= start)
            & (kills["tick"] <= action_end)
        ].copy()

        target_kills_viewer = kills[
            (kills["round_num"] == round_num)
            & (kills["attacker_pid"] == target_pid)
            & (kills["victim_pid"] == viewer_pid)
            & (kills["tick"] >= start)
            & (kills["tick"] <= action_end)
        ].copy()

        viewer_damage_target = damages[
            (damages["round_num"] == round_num)
            & (damages["attacker_pid"] == viewer_pid)
            & (damages["victim_pid"] == target_pid)
            & (damages["tick"] >= start)
            & (damages["tick"] <= action_end)
        ].copy()

        target_damage_viewer = damages[
            (damages["round_num"] == round_num)
            & (damages["attacker_pid"] == target_pid)
            & (damages["victim_pid"] == viewer_pid)
            & (damages["tick"] >= start)
            & (damages["tick"] <= action_end)
        ].copy()

        viewer_kill_tick = None
        target_kill_tick = None

        if not viewer_kills_target.empty:
            viewer_kill_tick = int(viewer_kills_target["tick"].min())

        if not target_kills_viewer.empty:
            target_kill_tick = int(target_kills_viewer["tick"].min())

        if viewer_kill_tick is not None and target_kill_tick is not None:
            if viewer_kill_tick <= target_kill_tick:
                outcome = "viewer_killed_target"
            else:
                outcome = "target_killed_viewer"
        elif viewer_kill_tick is not None:
            outcome = "viewer_killed_target"
        elif target_kill_tick is not None:
            outcome = "target_killed_viewer"
        elif not viewer_damage_target.empty:
            outcome = "viewer_damaged_target"
        elif not target_damage_viewer.empty:
            outcome = "target_damaged_viewer"
        else:
            outcome = "no_confirmed_damage"

        if viewer_first_tick is not None and target_first_tick is not None:
            if viewer_first_tick < target_first_tick:
                first_shooter = "viewer"
            elif target_first_tick < viewer_first_tick:
                first_shooter = "target"
            else:
                first_shooter = "simultaneous"
        elif viewer_first_tick is not None:
            first_shooter = "viewer"
        elif target_first_tick is not None:
            first_shooter = "target"
        else:
            first_shooter = "none"

        viewer_shot_delay = None if viewer_first_tick is None else int(viewer_first_tick - start)

        tags: list[str] = []
        note: list[str] = []

        if viewer_first_tick is None:
            tags.append("viewer_no_shot_after_contact")
            note.append("враг был в зоне взгляда по angle-proxy, но выстрела от игрока не найдено")

        if viewer_shot_delay is not None and viewer_shot_delay > DELAYED_SHOT_TICKS:
            tags.append("delayed_first_shot_after_contact")
            note.append("между первым контактом и первым выстрелом большая задержка")

        if outcome == "target_killed_viewer":
            tags.append("contact_lost")
            note.append("контакт закончился смертью игрока")

        if outcome == "viewer_killed_target":
            tags.append("contact_won")
            note.append("контакт закончился убийством цели")

        if outcome == "target_damaged_viewer":
            tags.append("target_damaged_viewer")

        if outcome == "viewer_damaged_target":
            tags.append("viewer_damaged_target")

        if first_shooter == "target" and outcome == "target_killed_viewer":
            tags.append("target_shot_first_and_won")
            note.append("цель начала стрелять первой и выиграла контакт")

        if first_shooter == "viewer" and outcome == "target_killed_viewer":
            tags.append("viewer_shot_first_but_lost")
            note.append("игрок выстрелил первым, но проиграл контакт")

        if viewer_metrics is not None:
            speed = viewer_metrics.get("speed")
            min_error = viewer_metrics.get("min_error")

            if speed is not None and speed > MOVING_SHOT_SPEED:
                tags.append("viewer_first_shot_moving")
                note.append("первый выстрел игрока был на скорости")

            if speed is not None and speed > SEVERE_MOVING_SHOT_SPEED:
                tags.append("viewer_first_shot_severe_moving")

            if min_error is not None and min_error > LARGE_FIRST_SHOT_ERROR_DEG:
                tags.append("viewer_large_first_shot_error")
                note.append("первый выстрел игрока был далеко от головы/тела цели по rough angle")

            if min_error is not None and min_error > VERY_LARGE_FIRST_SHOT_ERROR_DEG:
                tags.append("viewer_very_large_first_shot_error")

        if c.get("start_error") is not None and float(c.get("start_error")) <= 2.0:
            tags.append("good_initial_crosshair_alignment")

        if not note:
            note.append("контакт найден angle-proxy моделью; открыть момент для ручной проверки")

        row = c.to_dict()
        row.update({
            "action_window_end_tick": int(action_end),
            "viewer_first_shot_tick": viewer_first_tick,
            "target_first_shot_tick": target_first_tick,
            "viewer_shot_delay_ticks": viewer_shot_delay,
            "first_shooter": first_shooter,
            "viewer_shots_after_contact": int(len(viewer_shots)),
            "target_shots_after_contact": int(len(target_shots)),
            "viewer_damage_events_to_target": int(len(viewer_damage_target)),
            "target_damage_events_to_viewer": int(len(target_damage_viewer)),
            "viewer_kill_tick": viewer_kill_tick,
            "target_kill_tick": target_kill_tick,
            "outcome": outcome,
            "viewer_first_shot_speed": None if viewer_metrics is None else safe_value(viewer_metrics.get("speed")),
            "viewer_first_shot_error_min_deg": None if viewer_metrics is None else safe_value(viewer_metrics.get("min_error")),
            "viewer_first_shot_error_head_deg": None if viewer_metrics is None else safe_value(viewer_metrics.get("error_head")),
            "viewer_first_shot_error_body_deg": None if viewer_metrics is None else safe_value(viewer_metrics.get("error_body")),
            "target_first_shot_speed": None if target_metrics is None else safe_value(target_metrics.get("speed")),
            "target_first_shot_error_min_deg": None if target_metrics is None else safe_value(target_metrics.get("min_error")),
            "tags": tags,
            "practical_note": "; ".join(note),
        })

        rows.append(row)

    return pd.DataFrame(rows)


def priority_score(row: pd.Series) -> int:
    tags = row.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    score = 0

    if "contact_lost" in tags:
        score += 35
    if "viewer_no_shot_after_contact" in tags:
        score += 30
    if "viewer_shot_first_but_lost" in tags:
        score += 30
    if "delayed_first_shot_after_contact" in tags:
        score += 25
    if "viewer_first_shot_moving" in tags:
        score += 20
    if "viewer_large_first_shot_error" in tags:
        score += 20
    if "viewer_very_large_first_shot_error" in tags:
        score += 10
    if "target_shot_first_and_won" in tags:
        score += 15
    if "contact_won" in tags:
        score += 5
    if "good_initial_crosshair_alignment" in tags and "viewer_shot_first_but_lost" in tags:
        score += 12

    duration = row.get("duration_ticks")
    try:
        if duration is not None and float(duration) >= 32:
            score += 8
    except Exception:
        pass

    return int(score)


def build_player_summary(contacts: pd.DataFrame) -> pd.DataFrame:
    if contacts.empty:
        return pd.DataFrame()

    rows = []

    for pid, g in contacts.groupby("viewer_pid"):
        name = last_non_empty(g["viewer_name"])

        total = int(len(g))
        won = int((g["outcome"] == "viewer_killed_target").sum())
        lost = int((g["outcome"] == "target_killed_viewer").sum())
        no_shot = int(g["tags"].map(lambda x: "viewer_no_shot_after_contact" in x).sum())
        delayed = int(g["tags"].map(lambda x: "delayed_first_shot_after_contact" in x).sum())
        moving = int(g["tags"].map(lambda x: "viewer_first_shot_moving" in x).sum())
        large_err = int(g["tags"].map(lambda x: "viewer_large_first_shot_error" in x).sum())
        shot_first_lost = int(g["tags"].map(lambda x: "viewer_shot_first_but_lost" in x).sum())
        target_first_won = int(g["tags"].map(lambda x: "target_shot_first_and_won" in x).sum())
        good_align = int(g["tags"].map(lambda x: "good_initial_crosshair_alignment" in x).sum())

        delays = pd.to_numeric(g["viewer_shot_delay_ticks"], errors="coerce").dropna()
        avg_delay = float(delays.mean()) if len(delays) > 0 else None
        p75_delay = float(delays.quantile(0.75)) if len(delays) > 0 else None

        flags = []

        if no_shot >= 4:
            flags.append("часто видит контакт, но не стреляет")
        if delayed >= 4:
            flags.append("часто поздний первый выстрел")
        if moving >= 4:
            flags.append("часто первый выстрел на скорости")
        if large_err >= 4:
            flags.append("часто первый выстрел далеко от цели")
        if shot_first_lost >= 3:
            flags.append("стреляет первым, но проигрывает часть контактов")

        reaction_score = 100.0
        reaction_score -= no_shot * 5.5
        reaction_score -= delayed * 4.5
        reaction_score -= shot_first_lost * 5.0
        reaction_score -= moving * 2.5
        reaction_score -= large_err * 2.5
        reaction_score = round(max(0.0, min(100.0, reaction_score)), 1)

        rows.append({
            "player_pid": pid,
            "name": name,
            "contacts_as_viewer": total,
            "contacts_won": won,
            "contacts_lost": lost,
            "no_shot_after_contact": no_shot,
            "delayed_first_shot": delayed,
            "viewer_first_shot_moving": moving,
            "viewer_large_first_shot_error": large_err,
            "viewer_shot_first_but_lost": shot_first_lost,
            "target_shot_first_and_won": target_first_won,
            "good_initial_alignment": good_align,
            "avg_shot_delay_ticks": None if avg_delay is None else round(avg_delay, 1),
            "p75_shot_delay_ticks": None if p75_delay is None else round(p75_delay, 1),
            "reaction_contact_score": reaction_score,
            "flags": flags,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(
        ["contacts_lost", "no_shot_after_contact", "delayed_first_shot", "viewer_shot_first_but_lost"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    return df


def make_html(report: dict[str, Any], out_path: Path) -> None:
    def e(v: Any) -> str:
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        return html.escape("" if v is None else str(v))

    def f(v: Any, ndigits: int = 1) -> str:
        if v is None:
            return "—"
        try:
            if pd.isna(v):
                return "—"
        except Exception:
            pass
        if isinstance(v, (int, float, np.integer, np.floating)):
            v = float(v)
            if not math.isfinite(v):
                return "—"
            if abs(v - int(v)) < 0.0001:
                return str(int(v))
            return str(round(v, ndigits))
        return str(v)

    summary = report["summary"]
    players = report["player_contact_summary"]
    moments = report["priority_contacts"]

    player_rows = "\n".join(
        f"""
        <tr>
            <td>{e(p.get('name'))}</td>
            <td>{e(p.get('contacts_as_viewer'))}</td>
            <td>{e(p.get('contacts_won'))}</td>
            <td>{e(p.get('contacts_lost'))}</td>
            <td>{e(p.get('no_shot_after_contact'))}</td>
            <td>{e(p.get('delayed_first_shot'))}</td>
            <td>{e(p.get('viewer_first_shot_moving'))}</td>
            <td>{e(p.get('viewer_large_first_shot_error'))}</td>
            <td>{e(p.get('viewer_shot_first_but_lost'))}</td>
            <td>{e(p.get('avg_shot_delay_ticks'))}</td>
            <td>{e(p.get('p75_shot_delay_ticks'))}</td>
            <td>{e(p.get('reaction_contact_score'))}</td>
            <td>{e(p.get('flags'))}</td>
        </tr>
        """
        for p in players
    )

    moment_rows = "\n".join(
        f"""
        <tr>
            <td>{e(m.get('priority_score'))}</td>
            <td>R{e(m.get('round_num'))}</td>
            <td>{e(m.get('contact_start_tick'))}</td>
            <td>{e(m.get('contact_end_tick'))}</td>
            <td>{e(m.get('viewer_name'))}</td>
            <td>{e(m.get('target_name'))}</td>
            <td>{e(f(m.get('duration_ticks')))}</td>
            <td>{e(f(m.get('start_error'), 2))}</td>
            <td>{e(f(m.get('min_error'), 2))}</td>
            <td>{e(f(m.get('start_distance')))}</td>
            <td>{e(m.get('first_shooter'))}</td>
            <td>{e(m.get('outcome'))}</td>
            <td>{e(f(m.get('viewer_shot_delay_ticks')))}</td>
            <td>{e(f(m.get('viewer_first_shot_speed')))}</td>
            <td>{e(f(m.get('viewer_first_shot_error_min_deg'), 2))}</td>
            <td>{e(m.get('tags'))}</td>
            <td>{e(m.get('practical_note'))}</td>
        </tr>
        """
        for m in moments
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Contact Visibility v0.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1580px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .notice {{
        border: 1px solid #36557e;
        background: #101b2a;
        color: #c7d9f0;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 20px 0;
    }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 14px;
        margin: 20px 0 30px;
    }}
    .card {{
        background: linear-gradient(180deg, #121c29, #0f1722);
        border: 1px solid #223043;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,.22);
    }}
    .metric {{
        font-size: 28px;
        font-weight: 800;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0 34px;
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
    tr:hover td {{
        background: #142033;
    }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Contact Visibility v0.1</h1>
    <p class="muted">Первый слой контактов до kill-событий: кто видел врага в зоне взгляда, когда был первый выстрел и чем закончился контакт.</p>

    <div class="notice">
        Ограничение: это angle/FOV proxy без raycast по стенам, дымам и реальной геометрии карты. Поэтому это не финальный verdict, а слой кандидатов для профессионального разбора.
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{e(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Observations</div><div class="metric">{e(summary.get('observations'))}</div></div>
        <div class="card"><div class="muted">Contacts</div><div class="metric">{e(summary.get('contacts'))}</div></div>
        <div class="card"><div class="muted">Priority</div><div class="metric">{e(summary.get('priority_contacts'))}</div></div>
        <div class="card"><div class="muted">Sample step</div><div class="metric">{e(summary.get('sample_step_ticks'))}</div></div>
    </div>

    <h2>Сводка игроков по contact visibility</h2>
    <table>
        <thead>
            <tr>
                <th>Игрок</th>
                <th>Contacts</th>
                <th>Won</th>
                <th>Lost</th>
                <th>No shot</th>
                <th>Delayed shot</th>
                <th>Moving first</th>
                <th>Large aim err</th>
                <th>Shot first lost</th>
                <th>Avg delay</th>
                <th>P75 delay</th>
                <th>Score</th>
                <th>Flags</th>
            </tr>
        </thead>
        <tbody>{player_rows}</tbody>
    </table>

    <h2>Приоритетные contact-моменты</h2>
    <table>
        <thead>
            <tr>
                <th>Priority</th>
                <th>Round</th>
                <th>Start</th>
                <th>End</th>
                <th>Viewer</th>
                <th>Target</th>
                <th>Duration</th>
                <th>Start err</th>
                <th>Min err</th>
                <th>Distance</th>
                <th>First shooter</th>
                <th>Outcome</th>
                <th>Shot delay</th>
                <th>Shot speed</th>
                <th>Shot err</th>
                <th>Tags</th>
                <th>Практический смысл</th>
            </tr>
        </thead>
        <tbody>{moment_rows}</tbody>
    </table>
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parsed_dir", type=Path, help="Path to data/parsed/<demo_name>")
    parser.add_argument("--sample-step", type=int, default=SAMPLE_STEP_TICKS)
    parser.add_argument("--max-fov", type=float, default=MAX_CONTACT_FOV_DEG)
    parser.add_argument("--max-distance", type=float, default=MAX_CONTACT_DISTANCE)
    args = parser.parse_args()

    parsed_dir = args.parsed_dir
    if not parsed_dir.exists():
        raise SystemExit(f"Parsed dir not found: {parsed_dir}")

    view_path = parsed_dir / "view_ticks_demoparser2.parquet"
    if not view_path.exists():
        raise SystemExit(f"View layer not found: {view_path}")

    out_dir = Path("data/reports") / parsed_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== Load data ===")
    rounds = read_table(parsed_dir, "rounds")
    shots = read_table(parsed_dir, "shots")
    kills = read_table(parsed_dir, "kills")
    damages = read_table(parsed_dir, "damages")
    view = pd.read_parquet(view_path)

    print("=== Prepare view/events ===")
    view = prepare_view(view, rounds)
    shots, kills, damages = prepare_events(rounds, shots, kills, damages)

    print(f"Prepared view rows: {len(view)}")
    print(f"Prepared shots: {len(shots)}")
    print(f"Prepared kills: {len(kills)}")
    print(f"Prepared damages: {len(damages)}")

    print("=== Detect contact observations ===")
    observations = detect_contact_observations(
        view=view,
        sample_step=args.sample_step,
        max_fov=args.max_fov,
        max_distance=args.max_distance,
    )

    print(f"Contact observations: {len(observations)}")

    print("=== Build contact segments ===")
    contacts = build_contact_segments(observations, merge_gap_ticks=CONTACT_MERGE_GAP_TICKS)
    print(f"Raw contact segments: {len(contacts)}")

    view_index = build_view_index(view)

    print("=== Annotate contacts ===")
    contacts = annotate_contacts(contacts, shots, kills, damages, view_index)

    if not contacts.empty:
        contacts["priority_score"] = contacts.apply(priority_score, axis=1)
        contacts = contacts.sort_values(["priority_score", "round_num", "contact_start_tick"], ascending=[False, True, True]).reset_index(drop=True)

    player_summary = build_player_summary(contacts)

    priority_contacts = contacts[contacts["priority_score"] > 0].head(180).copy() if not contacts.empty else pd.DataFrame()

    summary = {
        "demo_name": parsed_dir.name,
        "view_rows": int(len(view)),
        "observations": int(len(observations)),
        "contacts": int(len(contacts)),
        "priority_contacts": int(len(priority_contacts)),
        "players": int(len(player_summary)),
        "sample_step_ticks": int(args.sample_step),
        "max_contact_fov_deg": float(args.max_fov),
        "max_contact_distance": float(args.max_distance),
        "contact_merge_gap_ticks": CONTACT_MERGE_GAP_TICKS,
        "action_window_ticks": CONTACT_ACTION_WINDOW_TICKS,
        "visibility_model": "angle_fov_proxy_no_walls_no_smokes",
        "notes": [
            "This is not true wall/smoke visibility. It only detects enemy inside the player's view-angle cone.",
            "Use priority contacts as candidates for manual demo review.",
            "Next versions should add map geometry, smoke blocking and contact-to-duel grouping.",
        ],
    }

    report = make_json_safe({
        "summary": summary,
        "player_contact_summary": records(player_summary),
        "priority_contacts": records(priority_contacts),
    })

    json_path = out_dir / "contact_visibility_v0_1.json"
    html_path = out_dir / "contact_visibility_v0_1.html"
    contacts_path = out_dir / "contacts_v0_1.parquet"
    priority_path = out_dir / "priority_contacts_v0_1.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html(report, html_path)

    if not contacts.empty:
        contacts.to_parquet(contacts_path, index=False)
    if not priority_contacts.empty:
        priority_contacts.to_csv(priority_path, index=False, encoding="utf-8-sig")

    print("")
    print("=== CS Demo Coach Contact Visibility v0.1 ===")
    print(f"Parsed dir: {parsed_dir}")
    print(f"Observations: {summary['observations']}")
    print(f"Contacts: {summary['contacts']}")
    print(f"Priority contacts: {summary['priority_contacts']}")
    print(f"Players: {summary['players']}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")
    print(f"Contacts parquet: {contacts_path}")
    print(f"Priority CSV: {priority_path}")

    print("")
    print("Player contact summary:")
    if player_summary.empty:
        print("  No player contact summary.")
    else:
        cols = [
            "name",
            "contacts_as_viewer",
            "contacts_won",
            "contacts_lost",
            "no_shot_after_contact",
            "delayed_first_shot",
            "viewer_first_shot_moving",
            "viewer_large_first_shot_error",
            "viewer_shot_first_but_lost",
            "avg_shot_delay_ticks",
            "reaction_contact_score",
        ]
        print(player_summary[cols].to_string(index=False))

    print("")
    print("Next: open contact_visibility_v0_1.html in browser.")


if __name__ == "__main__":
    main()
