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


MOVING_SHOT_SPEED = 40.0
SEVERE_MOVING_SHOT_SPEED = 90.0
PREV_SAMPLE_TICKS = 8
BURST_GAP_TICKS = 64
VIEW_MATCH_TOLERANCE_TICKS = 2


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

    ticks = df["tick"].to_numpy()
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
    if view.empty:
        return view

    view = view.copy()

    add_pid_from_name(view, "player", ["player_name", "name"])

    for col in ["X", "Y", "Z", "yaw", "pitch", "velocity_X", "velocity_Y", "velocity_Z", "tick"]:
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
    shots: pd.DataFrame,
    damages: pd.DataFrame,
    kills: pd.DataFrame,
    rounds: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    shots = shots.copy()
    damages = damages.copy()
    kills = kills.copy()

    add_pid_from_name(shots, "player", ["player_name", "name"])

    add_pid_from_name(damages, "attacker", ["attacker_name"])
    add_pid_from_name(damages, "victim", ["victim_name"])

    add_pid_from_name(kills, "attacker", ["attacker_name"])
    add_pid_from_name(kills, "victim", ["victim_name"])

    shots = add_round_num_by_ranges(shots, rounds)
    damages = add_round_num_by_ranges(damages, rounds)
    kills = add_round_num_by_ranges(kills, rounds)

    if "weapon" in shots.columns:
        shots["is_firearm"] = shots["weapon"].map(is_firearm_weapon)
    else:
        shots["is_firearm"] = True

    shots = shots[shots["is_firearm"]].copy()
    shots = shots[shots["player_pid"].astype(str) != ""]
    shots["tick"] = pd.to_numeric(shots["tick"], errors="coerce")
    shots = shots.dropna(subset=["tick"])
    shots["tick"] = shots["tick"].astype(int)

    for df in [damages, kills]:
        if "tick" in df.columns:
            df["tick"] = pd.to_numeric(df["tick"], errors="coerce")
            df.dropna(subset=["tick"], inplace=True)
            df["tick"] = df["tick"].astype(int)

    return shots, damages, kills


def attach_view_snapshot(
    events: pd.DataFrame,
    event_pid_col: str,
    event_tick_col: str,
    view: pd.DataFrame,
    prefix: str,
    tolerance: int = VIEW_MATCH_TOLERANCE_TICKS,
) -> pd.DataFrame:
    if events.empty:
        return events.copy()

    out_frames = []

    view_cols = [
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
    ]
    view_cols = [c for c in view_cols if c in view.columns]

    renamed = {
        c: f"{prefix}_{c}"
        for c in view_cols
        if c != "tick"
    }

    for pid, ev in events.groupby(event_pid_col, dropna=False):
        ev = ev.copy().sort_values(event_tick_col)

        vv = view[view["player_pid"] == pid].copy()
        if vv.empty:
            for new_col in renamed.values():
                ev[new_col] = np.nan
            ev[f"{prefix}_matched"] = False
            out_frames.append(ev)
            continue

        vv = vv[view_cols].copy().sort_values("tick")
        vv = vv.rename(columns=renamed)

        merged = pd.merge_asof(
            ev,
            vv,
            left_on=event_tick_col,
            right_on="tick",
            direction="nearest",
            tolerance=tolerance,
            suffixes=("", f"_{prefix}_right"),
        )

        right_tick_col = f"tick_{prefix}_right"
        if right_tick_col in merged.columns:
            merged.drop(columns=[right_tick_col], inplace=True)

        sample_col = f"{prefix}_yaw"
        merged[f"{prefix}_matched"] = merged[sample_col].notna() if sample_col in merged.columns else False

        out_frames.append(merged)

    if not out_frames:
        return events.copy()

    return pd.concat(out_frames, ignore_index=True)


def add_burst_features(shots: pd.DataFrame) -> pd.DataFrame:
    if shots.empty:
        return shots

    shots = shots.sort_values(["player_pid", "tick"]).copy()
    shots["prev_shot_tick"] = shots.groupby("player_pid")["tick"].shift(1)
    shots["gap_from_prev_shot"] = shots["tick"] - shots["prev_shot_tick"]
    shots["is_burst_first"] = shots["gap_from_prev_shot"].isna() | (shots["gap_from_prev_shot"] > BURST_GAP_TICKS)

    burst_ids = []
    for _, group in shots.groupby("player_pid", sort=False):
        burst_ids.extend(group["is_burst_first"].astype(int).cumsum().tolist())
    shots["burst_id"] = burst_ids

    return shots


def build_shot_mechanics(shots: pd.DataFrame, view: pd.DataFrame) -> pd.DataFrame:
    if shots.empty:
        return pd.DataFrame()

    shots = add_burst_features(shots)

    current = attach_view_snapshot(
        events=shots,
        event_pid_col="player_pid",
        event_tick_col="tick",
        view=view,
        prefix="view",
    )

    current["sample_tick_prev8"] = current["tick"] - PREV_SAMPLE_TICKS

    with_prev = attach_view_snapshot(
        events=current,
        event_pid_col="player_pid",
        event_tick_col="sample_tick_prev8",
        view=view,
        prefix="prev8",
    )

    with_prev["shot_speed"] = pd.to_numeric(with_prev.get("view_velocity_speed"), errors="coerce")
    with_prev["speed_prev8"] = pd.to_numeric(with_prev.get("prev8_velocity_speed"), errors="coerce")
    with_prev["speed_drop_prev8_to_shot"] = with_prev["speed_prev8"] - with_prev["shot_speed"]

    with_prev["moving_shot"] = with_prev["shot_speed"] > MOVING_SHOT_SPEED
    with_prev["severe_moving_shot"] = with_prev["shot_speed"] > SEVERE_MOVING_SHOT_SPEED

    with_prev["bad_counter_strafe_candidate"] = (
        (with_prev["is_burst_first"] == True)
        & (with_prev["speed_prev8"] > 120)
        & (with_prev["shot_speed"] > MOVING_SHOT_SPEED)
    )

    with_prev["first_bullet_moving_candidate"] = (
        (with_prev["is_burst_first"] == True)
        & (with_prev["shot_speed"] > MOVING_SHOT_SPEED)
    )

    return with_prev


def compute_damage_angles(damages: pd.DataFrame, view: pd.DataFrame) -> pd.DataFrame:
    if damages.empty:
        return pd.DataFrame()

    damages = damages.copy()
    damages = damages[damages["attacker_pid"].astype(str) != ""].copy()

    if damages.empty:
        return damages

    dmg_view = attach_view_snapshot(
        events=damages,
        event_pid_col="attacker_pid",
        event_tick_col="tick",
        view=view,
        prefix="attacker_view",
    )

    required = [
        "attacker_view_X",
        "attacker_view_Y",
        "attacker_view_Z",
        "attacker_view_yaw",
        "attacker_view_pitch",
        "victim_X",
        "victim_Y",
        "victim_Z",
    ]

    if not all(c in dmg_view.columns for c in required):
        dmg_view["rough_aim_error_deg"] = np.nan
        return dmg_view

    errors = []
    yaw_errors = []
    pitch_errors = []

    for _, r in dmg_view.iterrows():
        try:
            attacker_eye_z = float(r["attacker_view_Z"]) + 64.0

            hitgroup = str(r.get("hitgroup", "")).lower()
            if "head" in hitgroup or hitgroup == "1":
                target_z = float(r["victim_Z"]) + 64.0
            else:
                target_z = float(r["victim_Z"]) + 48.0

            target_yaw, target_pitch = angle_to_target(
                float(r["attacker_view_X"]),
                float(r["attacker_view_Y"]),
                attacker_eye_z,
                float(r["victim_X"]),
                float(r["victim_Y"]),
                target_z,
            )

            yaw_err = angle_delta_deg(float(r["attacker_view_yaw"]), target_yaw)
            pitch_err = float(r["attacker_view_pitch"]) - target_pitch
            total_err = math.sqrt(yaw_err * yaw_err + pitch_err * pitch_err)

            errors.append(total_err)
            yaw_errors.append(yaw_err)
            pitch_errors.append(pitch_err)
        except Exception:
            errors.append(np.nan)
            yaw_errors.append(np.nan)
            pitch_errors.append(np.nan)

    dmg_view["rough_aim_error_deg"] = errors
    dmg_view["rough_yaw_error_deg"] = yaw_errors
    dmg_view["rough_pitch_error_deg"] = pitch_errors

    return dmg_view


def build_player_mechanics(shot_mech: pd.DataFrame, damage_angles: pd.DataFrame) -> pd.DataFrame:
    if shot_mech.empty:
        return pd.DataFrame()

    rows = []

    for pid, g in shot_mech.groupby("player_pid"):
        name = last_non_empty(g["player_name_resolved"]) if "player_name_resolved" in g.columns else pid

        total_shots = int(len(g))
        moving_shots = int(g["moving_shot"].fillna(False).sum())
        severe_moving_shots = int(g["severe_moving_shot"].fillna(False).sum())

        firsts = g[g["is_burst_first"] == True].copy()
        first_bullets = int(len(firsts))
        first_bullet_moving = int(firsts["first_bullet_moving_candidate"].fillna(False).sum()) if not firsts.empty else 0
        bad_cs = int(g["bad_counter_strafe_candidate"].fillna(False).sum())

        avg_speed = float(g["shot_speed"].dropna().mean()) if g["shot_speed"].notna().any() else None
        p90_speed = float(g["shot_speed"].dropna().quantile(0.9)) if g["shot_speed"].notna().any() else None

        dmg = damage_angles[damage_angles["attacker_pid"] == pid] if not damage_angles.empty and "attacker_pid" in damage_angles.columns else pd.DataFrame()

        damage_events = int(len(dmg))
        avg_rough_aim_error = None
        median_rough_aim_error = None

        if not dmg.empty and "rough_aim_error_deg" in dmg.columns:
            clean = dmg["rough_aim_error_deg"].dropna()
            if len(clean) > 0:
                avg_rough_aim_error = float(clean.mean())
                median_rough_aim_error = float(clean.median())

        moving_pct = round(100.0 * moving_shots / max(total_shots, 1), 1)
        first_moving_pct = round(100.0 * first_bullet_moving / max(first_bullets, 1), 1)

        discipline_score = max(0.0, 100.0 - first_moving_pct * 1.4 - bad_cs * 2.0)
        discipline_score = round(min(100.0, discipline_score), 1)

        red_flags = []

        if first_bullet_moving >= 5:
            red_flags.append("часто первый выстрел в движении")
        if bad_cs >= 3:
            red_flags.append("кандидаты на плохой counter-strafe")
        if moving_pct >= 25:
            red_flags.append("высокая доля выстрелов в движении")
        if severe_moving_shots >= 5:
            red_flags.append("много грубых выстрелов на скорости")

        rows.append(
            {
                "player_pid": pid,
                "name": name,
                "firearm_shots": total_shots,
                "moving_shots": moving_shots,
                "moving_shot_percent": moving_pct,
                "severe_moving_shots": severe_moving_shots,
                "first_bullets": first_bullets,
                "first_bullet_moving": first_bullet_moving,
                "first_bullet_moving_percent": first_moving_pct,
                "bad_counter_strafe_candidates": bad_cs,
                "avg_shot_speed": None if avg_speed is None else round(avg_speed, 1),
                "p90_shot_speed": None if p90_speed is None else round(p90_speed, 1),
                "damage_events": damage_events,
                "avg_rough_aim_error_deg_on_damage": None if avg_rough_aim_error is None else round(avg_rough_aim_error, 2),
                "median_rough_aim_error_deg_on_damage": None if median_rough_aim_error is None else round(median_rough_aim_error, 2),
                "first_bullet_discipline_score": discipline_score,
                "red_flags": red_flags,
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(
        ["bad_counter_strafe_candidates", "first_bullet_moving", "moving_shot_percent"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    return df


def build_moment_candidates(shot_mech: pd.DataFrame, limit: int = 80) -> pd.DataFrame:
    if shot_mech.empty:
        return pd.DataFrame()

    candidates = shot_mech[
        (shot_mech["first_bullet_moving_candidate"] == True)
        | (shot_mech["bad_counter_strafe_candidate"] == True)
        | (shot_mech["severe_moving_shot"] == True)
    ].copy()

    if candidates.empty:
        return pd.DataFrame()

    def tag_row(r: pd.Series) -> str:
        tags = []
        if bool(r.get("bad_counter_strafe_candidate", False)):
            tags.append("bad_counter_strafe_candidate")
        if bool(r.get("first_bullet_moving_candidate", False)):
            tags.append("first_bullet_moving")
        if bool(r.get("severe_moving_shot", False)):
            tags.append("severe_moving_shot")
        return ", ".join(tags)

    candidates["tags"] = candidates.apply(tag_row, axis=1)

    cols = [
        "round_num",
        "tick",
        "player_name_resolved",
        "weapon",
        "shot_speed",
        "speed_prev8",
        "speed_drop_prev8_to_shot",
        "is_burst_first",
        "moving_shot",
        "severe_moving_shot",
        "bad_counter_strafe_candidate",
        "tags",
    ]

    cols = [c for c in cols if c in candidates.columns]

    candidates = candidates.sort_values(
        ["bad_counter_strafe_candidate", "shot_speed", "speed_prev8"],
        ascending=[False, False, False],
    )

    return candidates[cols].head(limit).reset_index(drop=True)


def make_html_report(report: dict[str, Any], out_path: Path) -> None:
    def esc(v: Any) -> str:
        return html.escape("" if v is None else str(v))

    summary = report.get("summary", {})
    players = report.get("player_mechanics", [])
    moments = report.get("moment_candidates", [])

    player_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(p.get('name'))}</td>
            <td>{esc(p.get('firearm_shots'))}</td>
            <td>{esc(p.get('moving_shots'))}</td>
            <td>{esc(p.get('moving_shot_percent'))}%</td>
            <td>{esc(p.get('first_bullets'))}</td>
            <td>{esc(p.get('first_bullet_moving'))}</td>
            <td>{esc(p.get('first_bullet_moving_percent'))}%</td>
            <td>{esc(p.get('bad_counter_strafe_candidates'))}</td>
            <td>{esc(p.get('avg_shot_speed'))}</td>
            <td>{esc(p.get('p90_shot_speed'))}</td>
            <td>{esc(p.get('first_bullet_discipline_score'))}</td>
            <td>{esc(', '.join(p.get('red_flags', [])))}</td>
        </tr>
        """
        for p in players
    )

    moment_rows = "\n".join(
        f"""
        <tr>
            <td>R{esc(m.get('round_num'))}</td>
            <td>{esc(m.get('tick'))}</td>
            <td>{esc(m.get('player_name_resolved'))}</td>
            <td>{esc(m.get('weapon'))}</td>
            <td>{esc(round(m.get('shot_speed'), 1) if isinstance(m.get('shot_speed'), (int, float)) else m.get('shot_speed'))}</td>
            <td>{esc(round(m.get('speed_prev8'), 1) if isinstance(m.get('speed_prev8'), (int, float)) else m.get('speed_prev8'))}</td>
            <td>{esc(round(m.get('speed_drop_prev8_to_shot'), 1) if isinstance(m.get('speed_drop_prev8_to_shot'), (int, float)) else m.get('speed_drop_prev8_to_shot'))}</td>
            <td>{esc(m.get('is_burst_first'))}</td>
            <td>{esc(m.get('tags'))}</td>
        </tr>
        """
        for m in moments
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Mechanics v0.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1380px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{
        margin: 0 0 12px;
    }}
    .muted {{
        color: #93a4b7;
    }}
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
        font-size: 14px;
        vertical-align: top;
    }}
    th {{
        background: #172232;
        color: #bfd0e4;
    }}
    tr:hover td {{
        background: #142033;
    }}
    .section {{
        margin-top: 34px;
    }}
    .small {{
        font-size: 13px;
    }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Mechanics Analyzer v0.1</h1>
    <p class="muted">Первый механический слой: view angles + velocity + shots. Пока без полноценной видимости и без финальной классификации underflick/overflick.</p>

    <div class="notice">
        Порог moving shot сейчас предварительный: скорость &gt; {MOVING_SHOT_SPEED}. Грубый moving shot: скорость &gt; {SEVERE_MOVING_SHOT_SPEED}. После нескольких демок пороги откалибруем под реальные FACEIT/Valve данные.
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Игроков</div><div class="metric">{esc(summary.get('players'))}</div></div>
        <div class="card"><div class="muted">Firearm shots</div><div class="metric">{esc(summary.get('firearm_shots'))}</div></div>
        <div class="card"><div class="muted">Moving shots</div><div class="metric">{esc(summary.get('moving_shots'))}</div></div>
        <div class="card"><div class="muted">Bad CS candidates</div><div class="metric">{esc(summary.get('bad_counter_strafe_candidates'))}</div></div>
    </div>

    <div class="section">
        <h2>Механика игроков</h2>
        <table>
            <thead>
                <tr>
                    <th>Игрок</th>
                    <th>Shots</th>
                    <th>Moving</th>
                    <th>Moving %</th>
                    <th>First bullets</th>
                    <th>First moving</th>
                    <th>First moving %</th>
                    <th>Bad CS</th>
                    <th>Avg speed</th>
                    <th>P90 speed</th>
                    <th>Discipline</th>
                    <th>Red flags</th>
                </tr>
            </thead>
            <tbody>{player_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Моменты-кандидаты для разбора</h2>
        <p class="muted small">Это не финальный обвинительный вывод, а список моментов, которые стоит открыть в demo/replay: первый выстрел в движении, плохая остановка, высокая скорость в момент выстрела.</p>
        <table>
            <thead>
                <tr>
                    <th>Раунд</th>
                    <th>Tick</th>
                    <th>Игрок</th>
                    <th>Оружие</th>
                    <th>Speed at shot</th>
                    <th>Speed -8 ticks</th>
                    <th>Speed drop</th>
                    <th>First bullet</th>
                    <th>Tags</th>
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
    shots = read_table(parsed_dir, "shots")
    damages = read_table(parsed_dir, "damages")
    kills = read_table(parsed_dir, "kills")
    view = pd.read_parquet(view_path)

    view = prepare_view(view)
    shots, damages, kills = prepare_events(shots, damages, kills, rounds)

    shot_mech = build_shot_mechanics(shots, view)
    damage_angles = compute_damage_angles(damages, view)

    player_mechanics = build_player_mechanics(shot_mech, damage_angles)
    moment_candidates = build_moment_candidates(shot_mech, limit=120)

    summary = {
        "demo_name": parsed_dir.name,
        "view_rows": int(len(view)),
        "firearm_shots": int(len(shot_mech)),
        "damage_events": int(len(damage_angles)),
        "players": int(len(player_mechanics)),
        "moving_shots": int(shot_mech["moving_shot"].fillna(False).sum()) if not shot_mech.empty else 0,
        "severe_moving_shots": int(shot_mech["severe_moving_shot"].fillna(False).sum()) if not shot_mech.empty else 0,
        "first_bullet_moving_candidates": int(shot_mech["first_bullet_moving_candidate"].fillna(False).sum()) if not shot_mech.empty else 0,
        "bad_counter_strafe_candidates": int(shot_mech["bad_counter_strafe_candidate"].fillna(False).sum()) if not shot_mech.empty else 0,
        "moving_shot_speed_threshold": MOVING_SHOT_SPEED,
        "severe_moving_shot_speed_threshold": SEVERE_MOVING_SHOT_SPEED,
        "prev_sample_ticks": PREV_SAMPLE_TICKS,
        "burst_gap_ticks": BURST_GAP_TICKS,
        "notes": [
            "Mechanics v0.1 uses velocity and view angle data from demoparser2.",
            "Underflick/overflick is not final here because visibility/contact modeling is not implemented yet.",
            "Rough aim error on damage events is approximate and should not be used as final verdict.",
        ],
    }

    report = {
        "summary": summary,
        "player_mechanics": records(player_mechanics),
        "moment_candidates": records(moment_candidates),
    }

    json_path = out_dir / "mechanics_v0_1.json"
    html_path = out_dir / "mechanics_v0_1.html"
    shot_path = out_dir / "shot_mechanics_v0_1.parquet"
    damage_path = out_dir / "damage_angles_v0_1.parquet"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html_report(report, html_path)

    if not shot_mech.empty:
        shot_mech.to_parquet(shot_path, index=False)

    if not damage_angles.empty:
        damage_angles.to_parquet(damage_path, index=False)

    print("=== CS Demo Coach Mechanics v0.1 ===")
    print(f"Parsed dir: {parsed_dir}")
    print(f"View rows: {summary['view_rows']}")
    print(f"Firearm shots: {summary['firearm_shots']}")
    print(f"Moving shots: {summary['moving_shots']}")
    print(f"Severe moving shots: {summary['severe_moving_shots']}")
    print(f"First bullet moving candidates: {summary['first_bullet_moving_candidates']}")
    print(f"Bad counter-strafe candidates: {summary['bad_counter_strafe_candidates']}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")

    print("")
    print("Player mechanics:")
    if player_mechanics.empty:
        print("  No player mechanics found.")
    else:
        cols = [
            "name",
            "firearm_shots",
            "moving_shots",
            "moving_shot_percent",
            "first_bullets",
            "first_bullet_moving",
            "first_bullet_moving_percent",
            "bad_counter_strafe_candidates",
            "avg_shot_speed",
            "p90_shot_speed",
            "first_bullet_discipline_score",
        ]
        print(player_mechanics[cols].to_string(index=False))

    print("")
    print("Next: open mechanics_v0_1.html in browser.")


if __name__ == "__main__":
    main()
