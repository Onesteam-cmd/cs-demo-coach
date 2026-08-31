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
    for col in candidates:
        if col in df.columns:
            return col
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


def dist3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return float(math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def nearest_snapshot(ticks: pd.DataFrame, round_num: int, tick: int, lookback: int = 16) -> pd.DataFrame:
    if ticks.empty or "round_num" not in ticks.columns or "tick" not in ticks.columns:
        return pd.DataFrame()

    sub = ticks[
        (ticks["round_num"] == round_num)
        & (ticks["tick"] <= tick)
        & (ticks["tick"] >= tick - lookback)
    ]

    if sub.empty:
        sub = ticks[(ticks["round_num"] == round_num) & (ticks["tick"] <= tick)]
        if sub.empty:
            return pd.DataFrame()

    last_tick = sub["tick"].max()
    return sub[sub["tick"] == last_tick].copy()


def prepare_tables(
    ticks: pd.DataFrame,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    shots: pd.DataFrame,
    smokes: pd.DataFrame,
    infernos: pd.DataFrame,
    grenades: pd.DataFrame,
    bomb: pd.DataFrame,
) -> None:
    add_pid_from_name(ticks, "player", ["name", "player_name"])

    add_pid_from_name(kills, "attacker", ["attacker_name"])
    add_pid_from_name(kills, "victim", ["victim_name"])
    add_pid_from_name(kills, "assister", ["assister_name"])

    add_pid_from_name(damages, "attacker", ["attacker_name"])
    add_pid_from_name(damages, "victim", ["victim_name"])

    add_pid_from_name(shots, "player", ["player_name", "name"])

    add_pid_from_name(smokes, "thrower", ["thrower_name", "thrower"])
    add_pid_from_name(infernos, "thrower", ["thrower_name", "thrower"])
    add_pid_from_name(grenades, "thrower", ["thrower_name", "thrower"])

    add_pid_from_name(bomb, "player", ["name", "player_name"])


def collect_players(
    ticks: pd.DataFrame,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    shots: pd.DataFrame,
    smokes: pd.DataFrame,
    infernos: pd.DataFrame,
    grenades: pd.DataFrame,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    def add(df: pd.DataFrame, pid_col: str, name_col: str, side_col: str | None = None) -> None:
        if df.empty or pid_col not in df.columns or name_col not in df.columns:
            return

        cols = [pid_col, name_col]
        if side_col and side_col in df.columns:
            cols.append(side_col)

        part = df[cols].copy()
        part = part.rename(columns={pid_col: "pid", name_col: "name"})
        if side_col and side_col in part.columns:
            part = part.rename(columns={side_col: "side"})
        else:
            part["side"] = None

        part = part[part["pid"].astype(str) != ""]
        frames.append(part)

    add(ticks, "player_pid", "player_name_resolved", "side")

    add(kills, "attacker_pid", "attacker_name_resolved", "attacker_side")
    add(kills, "victim_pid", "victim_name_resolved", "victim_side")
    add(damages, "attacker_pid", "attacker_name_resolved", "attacker_side")
    add(damages, "victim_pid", "victim_name_resolved", "victim_side")
    add(shots, "player_pid", "player_name_resolved", "side")
    add(smokes, "thrower_pid", "thrower_name_resolved", "thrower_side")
    add(infernos, "thrower_pid", "thrower_name_resolved", "thrower_side")
    add(grenades, "thrower_pid", "thrower_name_resolved", "thrower_side")

    if not frames:
        return pd.DataFrame(columns=["pid", "name", "side"])

    players = pd.concat(frames, ignore_index=True)
    players = players[players["pid"].astype(str) != ""]

    players = (
        players.groupby("pid", dropna=False)
        .agg(
            name=("name", last_non_empty),
            side_samples=("side", lambda x: sorted(set(str(v) for v in x.dropna() if str(v).strip()))),
        )
        .reset_index()
    )

    return players


def build_player_stats(
    rounds: pd.DataFrame,
    ticks: pd.DataFrame,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    shots: pd.DataFrame,
    smokes: pd.DataFrame,
    infernos: pd.DataFrame,
    grenades: pd.DataFrame,
) -> pd.DataFrame:
    round_count = max(int(len(rounds)), 1)

    players = collect_players(ticks, kills, damages, shots, smokes, infernos, grenades)

    if players.empty:
        return pd.DataFrame()

    if not ticks.empty and "player_pid" in ticks.columns:
        rounds_seen = ticks.groupby("player_pid")["round_num"].nunique().rename("rounds_seen")
        players = players.merge(rounds_seen, left_on="pid", right_index=True, how="left")
    else:
        players["rounds_seen"] = 0

    if not kills.empty:
        kill_counts = kills.groupby("attacker_pid").size().rename("kills")
        death_counts = kills.groupby("victim_pid").size().rename("deaths")

        if "headshot" in kills.columns:
            hs_counts = kills[kills["headshot"] == True].groupby("attacker_pid").size().rename("headshot_kills")
        else:
            hs_counts = pd.Series(dtype="float64", name="headshot_kills")

        opener = kills.sort_values(["round_num", "tick"]).groupby("round_num").first().reset_index()
        opening_kills = opener.groupby("attacker_pid").size().rename("opening_kills")
        opening_deaths = opener.groupby("victim_pid").size().rename("opening_deaths")

        for s in [kill_counts, death_counts, hs_counts, opening_kills, opening_deaths]:
            players = players.merge(s, left_on="pid", right_index=True, how="left")
    else:
        for col in ["kills", "deaths", "headshot_kills", "opening_kills", "opening_deaths"]:
            players[col] = 0

    if not damages.empty:
        dmg_col = None
        for candidate in ["dmg_health_real", "dmg_health", "damage"]:
            if candidate in damages.columns:
                dmg_col = candidate
                break

        if dmg_col:
            dmg = damages.groupby("attacker_pid")[dmg_col].sum().rename("damage")
            damage_events = damages.groupby("attacker_pid").size().rename("damage_events")
            players = players.merge(dmg, left_on="pid", right_index=True, how="left")
            players = players.merge(damage_events, left_on="pid", right_index=True, how="left")
        else:
            players["damage"] = 0
            players["damage_events"] = 0
    else:
        players["damage"] = 0
        players["damage_events"] = 0

    if not shots.empty:
        shots = shots.copy()
        if "weapon" in shots.columns:
            shots["is_firearm"] = shots["weapon"].map(is_firearm_weapon)
        else:
            shots["is_firearm"] = True

        firearm_shots = shots[shots["is_firearm"]].groupby("player_pid").size().rename("firearm_shots")
        all_shots = shots.groupby("player_pid").size().rename("all_shots")

        players = players.merge(firearm_shots, left_on="pid", right_index=True, how="left")
        players = players.merge(all_shots, left_on="pid", right_index=True, how="left")
    else:
        players["firearm_shots"] = 0
        players["all_shots"] = 0

    if not smokes.empty and "thrower_pid" in smokes.columns:
        smoke_counts = smokes.groupby("thrower_pid").size().rename("smokes")
        players = players.merge(smoke_counts, left_on="pid", right_index=True, how="left")

    if not infernos.empty and "thrower_pid" in infernos.columns:
        inferno_counts = infernos.groupby("thrower_pid").size().rename("infernos")
        players = players.merge(inferno_counts, left_on="pid", right_index=True, how="left")

    if not grenades.empty and "thrower_pid" in grenades.columns:
        if "entity_id" in grenades.columns and "grenade_type" in grenades.columns:
            unique_grenades = grenades.drop_duplicates(["thrower_pid", "entity_id", "grenade_type"])
        elif "entity_id" in grenades.columns:
            unique_grenades = grenades.drop_duplicates(["thrower_pid", "entity_id"])
        else:
            unique_grenades = grenades.drop_duplicates(["thrower_pid", "tick"])

        grenade_counts = unique_grenades.groupby("thrower_pid").size().rename("grenades_tracked")
        players = players.merge(grenade_counts, left_on="pid", right_index=True, how="left")

    fill_cols = [
        "rounds_seen",
        "kills",
        "deaths",
        "headshot_kills",
        "opening_kills",
        "opening_deaths",
        "damage",
        "damage_events",
        "firearm_shots",
        "all_shots",
        "smokes",
        "infernos",
        "grenades_tracked",
    ]

    for col in fill_cols:
        if col not in players.columns:
            players[col] = 0
        players[col] = players[col].fillna(0)

    players["kd"] = players.apply(lambda r: round(float(r["kills"]) / max(float(r["deaths"]), 1.0), 2), axis=1)
    players["adr"] = players["damage"].map(lambda x: round(float(x) / round_count, 1))
    players["hs_percent"] = players.apply(
        lambda r: round(100.0 * float(r["headshot_kills"]) / max(float(r["kills"]), 1.0), 1),
        axis=1,
    )
    players["damage_events_per_100_firearm_shots"] = players.apply(
        lambda r: round(100.0 * float(r["damage_events"]) / max(float(r["firearm_shots"]), 1.0), 1),
        axis=1,
    )

    players["opening_kd"] = players.apply(
        lambda r: f"{int(r['opening_kills'])}/{int(r['opening_deaths'])}",
        axis=1,
    )

    players = players.sort_values(["kills", "damage", "kd"], ascending=[False, False, False]).reset_index(drop=True)
    return players


def build_death_review(kills: pd.DataFrame, ticks: pd.DataFrame, trade_window_ticks: int) -> pd.DataFrame:
    if kills.empty:
        return pd.DataFrame()

    deaths: list[dict[str, Any]] = []
    kills_sorted = kills.sort_values(["round_num", "tick"]).reset_index(drop=True)

    for _, row in kills_sorted.iterrows():
        round_num = int(row.get("round_num", 0))
        tick = int(row.get("tick", 0))

        attacker_pid = str(row.get("attacker_pid", ""))
        victim_pid = str(row.get("victim_pid", ""))

        attacker_side = row.get("attacker_side")
        victim_side = row.get("victim_side")

        later = kills_sorted[
            (kills_sorted["round_num"] == round_num)
            & (kills_sorted["tick"] > tick)
            & (kills_sorted["tick"] <= tick + trade_window_ticks)
            & (kills_sorted["victim_pid"] == attacker_pid)
        ]

        if "attacker_side" in later.columns:
            later = later[later["attacker_side"] == victim_side]

        traded = not later.empty
        trade_delay_ticks = int(later.iloc[0]["tick"] - tick) if traded else None

        teammates_near_600 = 0
        teammates_near_1000 = 0
        nearest_teammate_distance = None

        try:
            victim_pos = (
                float(row.get("victim_X", 0.0)),
                float(row.get("victim_Y", 0.0)),
                float(row.get("victim_Z", 0.0)),
            )
        except Exception:
            victim_pos = (0.0, 0.0, 0.0)

        snap = nearest_snapshot(ticks, round_num, tick)

        if not snap.empty and "side" in snap.columns and "player_pid" in snap.columns:
            teammates = snap[
                (snap["side"] == victim_side)
                & (snap["player_pid"] != victim_pid)
            ].copy()

            if "health" in teammates.columns:
                teammates = teammates[teammates["health"] > 0]

            if not teammates.empty and all(c in teammates.columns for c in ["X", "Y", "Z"]):
                teammates["distance_to_victim"] = teammates.apply(
                    lambda t: dist3(
                        (float(t.get("X", 0.0)), float(t.get("Y", 0.0)), float(t.get("Z", 0.0))),
                        victim_pos,
                    ),
                    axis=1,
                )
                nearest_teammate_distance = float(teammates["distance_to_victim"].min())
                teammates_near_600 = int((teammates["distance_to_victim"] <= 600).sum())
                teammates_near_1000 = int((teammates["distance_to_victim"] <= 1000).sum())

        tags = []

        if traded:
            tags.append("traded")
        else:
            tags.append("not_traded")

        if not traded and teammates_near_600 > 0:
            tags.append("possible_missed_trade")
        if not traded and teammates_near_1000 == 0:
            tags.append("isolated_death")
        if bool(row.get("headshot", False)):
            tags.append("died_to_headshot")
        if bool(row.get("thrusmoke", False)):
            tags.append("killed_through_smoke")
        if bool(row.get("attackerblind", False)):
            tags.append("enemy_killed_while_blind")
        if bool(row.get("attackerinair", False)):
            tags.append("enemy_in_air")

        deaths.append(
            {
                "round_num": round_num,
                "tick": tick,
                "victim_name": row.get("victim_name"),
                "victim_pid": victim_pid,
                "victim_side": victim_side,
                "victim_place": row.get("victim_place"),
                "attacker_name": row.get("attacker_name"),
                "attacker_pid": attacker_pid,
                "attacker_side": attacker_side,
                "attacker_place": row.get("attacker_place"),
                "weapon": row.get("weapon"),
                "headshot": bool(row.get("headshot", False)),
                "hitgroup": row.get("hitgroup"),
                "distance": safe_value(row.get("distance")),
                "traded": traded,
                "trade_delay_ticks": trade_delay_ticks,
                "nearest_teammate_distance": nearest_teammate_distance,
                "teammates_near_600": teammates_near_600,
                "teammates_near_1000": teammates_near_1000,
                "tags": tags,
            }
        )

    return pd.DataFrame(deaths)


def build_round_summaries(rounds: pd.DataFrame, kills: pd.DataFrame, bomb: pd.DataFrame) -> pd.DataFrame:
    if rounds.empty:
        return pd.DataFrame()

    rows = []
    kills_sorted = kills.sort_values(["round_num", "tick"]) if not kills.empty else pd.DataFrame()

    for _, r in rounds.iterrows():
        rn = int(r.get("round_num", 0))
        rk = kills_sorted[kills_sorted["round_num"] == rn] if not kills_sorted.empty else pd.DataFrame()
        opener = rk.iloc[0] if not rk.empty else None

        bomb_events = bomb[bomb["round_num"] == rn] if not bomb.empty and "round_num" in bomb.columns else pd.DataFrame()
        plant_tick = None
        plant_site = None

        if not bomb_events.empty and "event" in bomb_events.columns:
            plants = bomb_events[bomb_events["event"].astype(str).str.lower().str.contains("plant", na=False)]
            if not plants.empty:
                plant_tick = safe_value(plants.iloc[0].get("tick"))
                plant_site = safe_value(plants.iloc[0].get("bombsite"))

        rows.append(
            {
                "round_num": rn,
                "start": safe_value(r.get("start")),
                "freeze_end": safe_value(r.get("freeze_end")),
                "end": safe_value(r.get("end")),
                "winner": r.get("winner"),
                "reason": r.get("reason"),
                "bomb_plant_tick": safe_value(r.get("bomb_plant", plant_tick)),
                "bomb_site": safe_value(r.get("bomb_site", plant_site)),
                "kill_count": int(len(rk)),
                "opening_killer": None if opener is None else opener.get("attacker_name"),
                "opening_victim": None if opener is None else opener.get("victim_name"),
                "opening_tick": None if opener is None else int(opener.get("tick")),
                "ct_kills": int((rk["attacker_side"] == "ct").sum()) if not rk.empty and "attacker_side" in rk.columns else 0,
                "t_kills": int((rk["attacker_side"] == "t").sum()) if not rk.empty and "attacker_side" in rk.columns else 0,
            }
        )

    return pd.DataFrame(rows)


def build_patterns(player_stats: pd.DataFrame, death_review: pd.DataFrame) -> list[dict[str, Any]]:
    patterns = []

    if not death_review.empty:
        missed = death_review[death_review["tags"].map(lambda tags: "possible_missed_trade" in tags)]
        isolated = death_review[death_review["tags"].map(lambda tags: "isolated_death" in tags)]
        smoke = death_review[death_review["tags"].map(lambda tags: "killed_through_smoke" in tags)]

        if len(missed) > 0:
            patterns.append(
                {
                    "type": "teamplay_or_spacing",
                    "title": "Возможные непройденные трейды",
                    "count": int(len(missed)),
                    "practical_meaning": "Игроки умирали рядом с тиммейтами, но убийца не был быстро разменян. Нужно проверить spacing, готовность к трейду и синхронность пиков.",
                }
            )

        if len(isolated) > 0:
            patterns.append(
                {
                    "type": "positioning",
                    "title": "Изолированные смерти",
                    "count": int(len(isolated)),
                    "practical_meaning": "Смерти без близкого тиммейта рядом. Это может быть нормой для lurk/anchor, но часто указывает на плохую позицию или несвоевременное смещение.",
                }
            )

        if len(smoke) > 0:
            patterns.append(
                {
                    "type": "risk",
                    "title": "Смерти через дым",
                    "count": int(len(smoke)),
                    "practical_meaning": "Нужно проверить, были ли это читаемые позиции, шум, спам через стандартный дым или плохое перемещение за smoke.",
                }
            )

    if not player_stats.empty:
        low_hit = player_stats[
            (player_stats["firearm_shots"] >= 40)
            & (player_stats["damage_events_per_100_firearm_shots"] < 20)
        ]

        if len(low_hit) > 0:
            patterns.append(
                {
                    "type": "mechanics_proxy",
                    "title": "Низкое число damage-событий на 100 firearm-выстрелов",
                    "count": int(len(low_hit)),
                    "practical_meaning": "Это не точная accuracy, но ранний индикатор: много стрельбы с малым количеством результативных попаданий.",
                }
            )

    return patterns


def make_html_report(report: dict[str, Any], out_path: Path) -> None:
    def esc(v: Any) -> str:
        return html.escape("" if v is None else str(v))

    stats = report.get("player_stats", [])
    deaths = report.get("death_review", [])
    rounds = report.get("round_summaries", [])
    patterns = report.get("patterns", [])
    summary = report.get("summary", {})

    stats_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(p.get('name'))}</td>
            <td>{esc(p.get('kills'))}</td>
            <td>{esc(p.get('deaths'))}</td>
            <td>{esc(p.get('kd'))}</td>
            <td>{esc(p.get('adr'))}</td>
            <td>{esc(p.get('headshot_kills'))}</td>
            <td>{esc(p.get('hs_percent'))}%</td>
            <td>{esc(p.get('firearm_shots'))}</td>
            <td>{esc(p.get('damage_events_per_100_firearm_shots'))}</td>
            <td>{esc(p.get('opening_kd'))}</td>
        </tr>
        """
        for p in stats
    )

    pattern_cards = "\n".join(
        f"""
        <div class="card">
            <div class="tag">{esc(p.get('type'))}</div>
            <h3>{esc(p.get('title'))}: {esc(p.get('count'))}</h3>
            <p>{esc(p.get('practical_meaning'))}</p>
        </div>
        """
        for p in patterns
    )

    death_rows = "\n".join(
        f"""
        <tr>
            <td>R{esc(d.get('round_num'))}</td>
            <td>{esc(d.get('tick'))}</td>
            <td>{esc(d.get('victim_name'))}</td>
            <td>{esc(d.get('attacker_name'))}</td>
            <td>{esc(d.get('weapon'))}</td>
            <td>{'yes' if d.get('headshot') else 'no'}</td>
            <td>{'yes' if d.get('traded') else 'no'}</td>
            <td>{esc(d.get('teammates_near_600'))}/{esc(d.get('teammates_near_1000'))}</td>
            <td>{esc(', '.join(d.get('tags', [])))}</td>
        </tr>
        """
        for d in deaths[:120]
    )

    round_rows = "\n".join(
        f"""
        <tr>
            <td>R{esc(r.get('round_num'))}</td>
            <td>{esc(r.get('winner'))}</td>
            <td>{esc(r.get('reason'))}</td>
            <td>{esc(r.get('kill_count'))}</td>
            <td>{esc(r.get('opening_killer'))} → {esc(r.get('opening_victim'))}</td>
            <td>{esc(r.get('bomb_site'))}</td>
        </tr>
        """
        for r in rounds
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Report v1.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #080d13;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1280px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
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
    .tag {{
        display: inline-block;
        color: #9fc3ff;
        background: #16243a;
        border: 1px solid #28466f;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 12px;
        margin-bottom: 10px;
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
    }}
    th {{
        background: #172232;
        color: #bfd0e4;
    }}
    tr:hover td {{ background: #142033; }}
    .section {{ margin-top: 34px; }}
    .two {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
    }}
    .notice {{
        border: 1px solid #36557e;
        background: #101b2a;
        color: #c7d9f0;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 20px 0;
    }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Report v1.1</h1>
    <p class="muted">Исправлена идентификация игроков: статистика объединяется по имени, чтобы обойти погрешности SteamID в таблицах.</p>

    <div class="notice">
        Точный aim-анализ ещё не включён. Сначала стабилизируем модель матча, затем подключим view angles/yaw/pitch и начнём считать прицел, флики, counter-strafe и timing первого выстрела.
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Раундов</div><div class="metric">{esc(summary.get('rounds'))}</div></div>
        <div class="card"><div class="muted">Киллов</div><div class="metric">{esc(summary.get('kills'))}</div></div>
        <div class="card"><div class="muted">Игроков</div><div class="metric">{esc(summary.get('players'))}</div></div>
    </div>

    <div class="section">
        <h2>Главные ранние паттерны</h2>
        <div class="two">
            {pattern_cards or '<div class="card"><p>Паттерны не найдены или данных пока недостаточно.</p></div>'}
        </div>
    </div>

    <div class="section">
        <h2>Игроки</h2>
        <table>
            <thead>
                <tr>
                    <th>Игрок</th><th>K</th><th>D</th><th>K/D</th><th>ADR</th><th>HS Kills</th><th>HS%</th><th>Firearm shots</th><th>Damage events / 100 shots</th><th>Open K/D</th>
                </tr>
            </thead>
            <tbody>{stats_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Раунды</h2>
        <table>
            <thead>
                <tr><th>Раунд</th><th>Победитель</th><th>Причина</th><th>Киллы</th><th>Opening duel</th><th>Bomb site</th></tr>
            </thead>
            <tbody>{round_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Смерти для разбора</h2>
        <p class="muted">Это список моментов-кандидатов. Особенно важны not_traded, possible_missed_trade и isolated_death.</p>
        <table>
            <thead>
                <tr><th>Раунд</th><th>Tick</th><th>Умер</th><th>Убил</th><th>Оружие</th><th>HS</th><th>Trade</th><th>Тиммейты рядом 600/1000</th><th>Теги</th></tr>
            </thead>
            <tbody>{death_rows}</tbody>
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
    parser.add_argument("--trade-window-ticks", type=int, default=320)
    args = parser.parse_args()

    parsed_dir: Path = args.parsed_dir
    if not parsed_dir.exists():
        raise SystemExit(f"Parsed dir not found: {parsed_dir}")

    out_dir = Path("data/reports") / parsed_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    rounds = read_table(parsed_dir, "rounds")
    kills = read_table(parsed_dir, "kills")
    damages = read_table(parsed_dir, "damages")
    grenades = read_table(parsed_dir, "grenades")
    smokes = read_table(parsed_dir, "smokes")
    infernos = read_table(parsed_dir, "infernos")
    bomb = read_table(parsed_dir, "bomb")
    shots = read_table(parsed_dir, "shots")
    ticks = read_table(parsed_dir, "ticks")

    prepare_tables(ticks, kills, damages, shots, smokes, infernos, grenades, bomb)

    player_stats = build_player_stats(rounds, ticks, kills, damages, shots, smokes, infernos, grenades)
    death_review = build_death_review(kills, ticks, args.trade_window_ticks)
    round_summaries = build_round_summaries(rounds, kills, bomb)
    patterns = build_patterns(player_stats, death_review)

    report = {
        "summary": {
            "demo_name": parsed_dir.name,
            "rounds": int(len(rounds)),
            "kills": int(len(kills)),
            "damages": int(len(damages)),
            "shots": int(len(shots)),
            "ticks": int(len(ticks)),
            "players": int(len(player_stats)),
            "trade_window_ticks": int(args.trade_window_ticks),
            "identity_mode": "name_based_v1_1",
            "notes": [
                "v1.1 merges player records by normalized player name because some Awpy tables can contain SteamID precision mismatches.",
                "Exact aim analysis is still disabled until yaw/pitch view angles are added.",
            ],
        },
        "player_stats": records(player_stats),
        "round_summaries": records(round_summaries),
        "death_review": records(death_review),
        "patterns": patterns,
    }

    json_path = out_dir / "report_v1_1.json"
    html_path = out_dir / "report_v1_1.html"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html_report(report, html_path)

    print("=== CS Demo Coach report v1.1 ===")
    print(f"Parsed dir: {parsed_dir}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")
    print("")
    print("Top players:")

    if player_stats.empty:
        print("  No players found.")
    else:
        cols = [
            "name",
            "kills",
            "deaths",
            "kd",
            "adr",
            "opening_kills",
            "opening_deaths",
            "firearm_shots",
            "damage_events_per_100_firearm_shots",
        ]
        print(player_stats[cols].head(12).to_string(index=False))

    print("")
    print("Patterns:")
    if not patterns:
        print("  No early patterns found.")
    else:
        for p in patterns:
            print(f"  - {p['title']}: {p['count']}")

    print("")
    print("Next: open report_v1_1.html in browser.")


if __name__ == "__main__":
    main()
