from __future__ import annotations

import argparse
import html
import json
import math
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


def clean_steamid(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    if isinstance(value, (int, np.integer)):
        return str(int(value))

    if isinstance(value, (float, np.floating)):
        if math.isfinite(float(value)):
            return str(int(value))
        return ""

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return ""

    try:
        if "e+" in text.lower() or "." in text:
            return str(int(float(text)))
    except Exception:
        return text

    return text


def add_clean_id(df: pd.DataFrame, src: str, dst: str) -> None:
    if df.empty or src not in df.columns:
        return

    series = df[src]
    try:
        if pd.api.types.is_numeric_dtype(series):
            df[dst] = series.astype("Int64").astype(str).replace("<NA>", "")
            return
    except Exception:
        pass

    df[dst] = series.map(clean_steamid)


def safe_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)

    return value


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is not None:
        df = df.head(limit)
    return [{str(k): safe_value(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def is_firearm_weapon(weapon: Any) -> bool:
    if weapon is None:
        return False
    text = str(weapon).lower()
    return not any(p in text for p in NON_FIREARM_PATTERNS)


def dist3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return float(math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def last_non_empty(series: pd.Series) -> Any:
    s = series.dropna()
    if len(s) == 0:
        return None
    return s.iloc[-1]


def nearest_snapshot(ticks: pd.DataFrame, round_num: int, tick: int, lookback: int = 16) -> pd.DataFrame:
    if ticks.empty:
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

    last_tick = sub["tick"].max()
    return sub[sub["tick"] == last_tick].copy()


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

    player_rows: list[dict[str, Any]] = []

    if not ticks.empty:
        base = (
            ticks.dropna(subset=["steamid"])
            .groupby("steamid_clean", dropna=False)
            .agg(
                name=("name", last_non_empty),
                rounds_seen=("round_num", "nunique"),
                tick_rows=("tick", "count"),
            )
            .reset_index()
            .rename(columns={"steamid_clean": "steamid"})
        )
        player_rows.extend(records(base))

    event_sources = []
    for df, sid_col, name_col in [
        (kills, "attacker_steamid_clean", "attacker_name"),
        (kills, "victim_steamid_clean", "victim_name"),
        (damages, "attacker_steamid_clean", "attacker_name"),
        (damages, "victim_steamid_clean", "victim_name"),
        (shots, "player_steamid_clean", "player_name"),
    ]:
        if not df.empty and sid_col in df.columns and name_col in df.columns:
            event_sources.append(df[[sid_col, name_col]].rename(columns={sid_col: "steamid", name_col: "name"}))

    if event_sources:
        event_players = pd.concat(event_sources, ignore_index=True)
        event_players = event_players[event_players["steamid"].astype(str) != ""]
        event_players = event_players.groupby("steamid").agg(name=("name", last_non_empty)).reset_index()
        player_rows.extend(records(event_players))

    players = pd.DataFrame(player_rows)
    if players.empty:
        return pd.DataFrame()

    players = players[players["steamid"].astype(str) != ""]
    players = players.groupby("steamid").agg(name=("name", last_non_empty)).reset_index()

    if not kills.empty:
        kill_counts = kills.groupby("attacker_steamid_clean").size().rename("kills")
        death_counts = kills.groupby("victim_steamid_clean").size().rename("deaths")
        hs_counts = kills[kills.get("headshot", False) == True].groupby("attacker_steamid_clean").size().rename("headshot_kills")

        opener = kills.sort_values(["round_num", "tick"]).groupby("round_num").first().reset_index()
        opening_kills = opener.groupby("attacker_steamid_clean").size().rename("opening_kills")
        opening_deaths = opener.groupby("victim_steamid_clean").size().rename("opening_deaths")

        for s in [kill_counts, death_counts, hs_counts, opening_kills, opening_deaths]:
            players = players.merge(s, left_on="steamid", right_index=True, how="left")
    else:
        for col in ["kills", "deaths", "headshot_kills", "opening_kills", "opening_deaths"]:
            players[col] = 0

    if not damages.empty:
        dmg_col = "dmg_health_real" if "dmg_health_real" in damages.columns else "dmg_health"
        dmg = damages.groupby("attacker_steamid_clean")[dmg_col].sum().rename("damage")
        damage_events = damages.groupby("attacker_steamid_clean").size().rename("damage_events")
        players = players.merge(dmg, left_on="steamid", right_index=True, how="left")
        players = players.merge(damage_events, left_on="steamid", right_index=True, how="left")
    else:
        players["damage"] = 0
        players["damage_events"] = 0

    if not shots.empty:
        shots = shots.copy()
        shots["is_firearm"] = shots["weapon"].map(is_firearm_weapon) if "weapon" in shots.columns else False
        firearm_shots = shots[shots["is_firearm"]].groupby("player_steamid_clean").size().rename("firearm_shots")
        all_shots = shots.groupby("player_steamid_clean").size().rename("all_shots")
        players = players.merge(firearm_shots, left_on="steamid", right_index=True, how="left")
        players = players.merge(all_shots, left_on="steamid", right_index=True, how="left")
    else:
        players["firearm_shots"] = 0
        players["all_shots"] = 0

    util_frames = []

    if not smokes.empty and "thrower_steamid_clean" in smokes.columns:
        util_frames.append(
            smokes.groupby("thrower_steamid_clean")
            .size()
            .rename("smokes")
            .reset_index()
            .rename(columns={"thrower_steamid_clean": "steamid"})
        )

    if not infernos.empty and "thrower_steamid_clean" in infernos.columns:
        util_frames.append(
            infernos.groupby("thrower_steamid_clean")
            .size()
            .rename("infernos")
            .reset_index()
            .rename(columns={"thrower_steamid_clean": "steamid"})
        )

    if not grenades.empty and "entity_id" in grenades.columns and "thrower_steamid_clean" in grenades.columns:
        unique_grenades = grenades.drop_duplicates(["entity_id", "grenade_type"])
        g = (
            unique_grenades.groupby("thrower_steamid_clean")
            .size()
            .rename("grenades_tracked")
            .reset_index()
            .rename(columns={"thrower_steamid_clean": "steamid"})
        )
        util_frames.append(g)

    for util in util_frames:
        players = players.merge(util, on="steamid", how="left")

    fill_cols = [
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
    players["estimated_hit_events_per_100_shots"] = players.apply(
        lambda r: round(100.0 * float(r["damage_events"]) / max(float(r["firearm_shots"]), 1.0), 1),
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
        attacker_id = str(row.get("attacker_steamid_clean", ""))
        victim_id = str(row.get("victim_steamid_clean", ""))
        attacker_side = row.get("attacker_side")
        victim_side = row.get("victim_side")

        later = kills_sorted[
            (kills_sorted["round_num"] == round_num)
            & (kills_sorted["tick"] > tick)
            & (kills_sorted["tick"] <= tick + trade_window_ticks)
            & (kills_sorted["victim_steamid_clean"] == attacker_id)
        ]

        if "attacker_side" in later.columns:
            later = later[later["attacker_side"] == victim_side]

        traded = not later.empty
        trade_delay_ticks = int(later.iloc[0]["tick"] - tick) if traded else None

        teammates_near_600 = 0
        teammates_near_1000 = 0
        nearest_teammate_distance = None

        victim_pos = (
            float(row.get("victim_X", 0.0)),
            float(row.get("victim_Y", 0.0)),
            float(row.get("victim_Z", 0.0)),
        )

        snap = nearest_snapshot(ticks, round_num, tick)

        if not snap.empty and "side" in snap.columns:
            teammates = snap[
                (snap["side"] == victim_side)
                & (snap["steamid_clean"] != victim_id)
                & (snap.get("health", 0) > 0)
            ].copy()

            if not teammates.empty:
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
        if bool(row.get("attackerblind", False)):
            tags.append("enemy_killed_while_blind")
        if bool(row.get("thrusmoke", False)):
            tags.append("killed_through_smoke")
        if bool(row.get("attackerinair", False)):
            tags.append("enemy_in_air")

        deaths.append(
            {
                "round_num": round_num,
                "tick": tick,
                "victim_name": row.get("victim_name"),
                "victim_steamid": victim_id,
                "victim_side": victim_side,
                "victim_place": row.get("victim_place"),
                "attacker_name": row.get("attacker_name"),
                "attacker_steamid": attacker_id,
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

        if not bomb_events.empty:
            plants = bomb_events[bomb_events.get("event", "") == "plant"]
            if not plants.empty:
                plant_tick = int(plants.iloc[0].get("tick"))
                plant_site = plants.iloc[0].get("bombsite")

        rows.append(
            {
                "round_num": rn,
                "start": safe_value(r.get("start")),
                "freeze_end": safe_value(r.get("freeze_end")),
                "end": safe_value(r.get("end")),
                "winner": r.get("winner"),
                "reason": r.get("reason"),
                "bomb_plant_tick": safe_value(r.get("bomb_plant", plant_tick)),
                "bomb_site": r.get("bomb_site", plant_site),
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
            & (player_stats["estimated_hit_events_per_100_shots"] < 20)
        ]

        if len(low_hit) > 0:
            patterns.append(
                {
                    "type": "mechanics_proxy",
                    "title": "Низкое число damage-событий на 100 выстрелов",
                    "count": int(len(low_hit)),
                    "practical_meaning": "Это не точная accuracy, но полезный ранний индикатор: много стрельбы с малым количеством результативных попаданий.",
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
            <td>{esc(p.get('estimated_hit_events_per_100_shots'))}</td>
            <td>{esc(p.get('opening_kills'))}/{esc(p.get('opening_deaths'))}</td>
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
        for d in deaths[:80]
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

    summary = report.get("summary", {})

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Report v1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #0b0f14;
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
        background: #111923;
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
        position: sticky;
        top: 0;
    }}
    tr:hover td {{ background: #142033; }}
    .section {{ margin-top: 34px; }}
    .two {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
    }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Report v1</h1>
    <p class="muted">Первичный отчёт: статистика матча, opening duels, трейды, изолированные смерти, utility proxy. Точный aim-анализ будет добавлен после подключения view angles.</p>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Раундов</div><div class="metric">{esc(summary.get('rounds'))}</div></div>
        <div class="card"><div class="muted">Киллов</div><div class="metric">{esc(summary.get('kills'))}</div></div>
        <div class="card"><div class="muted">Damage-событий</div><div class="metric">{esc(summary.get('damages'))}</div></div>
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
                    <th>Игрок</th><th>K</th><th>D</th><th>K/D</th><th>ADR</th><th>HS Kills</th><th>HS%</th><th>Firearm shots</th><th>Hit events / 100 shots</th><th>Open K/D</th>
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
        <h2>Смерти для ручного просмотра</h2>
        <p class="muted">Это не финальный тренерский вывод, а список моментов-кандидатов. Особенно важны not_traded, possible_missed_trade и isolated_death.</p>
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

    for df, pairs in [
        (ticks, [("steamid", "steamid_clean")]),
        (kills, [
            ("attacker_steamid", "attacker_steamid_clean"),
            ("victim_steamid", "victim_steamid_clean"),
            ("assister_steamid", "assister_steamid_clean"),
        ]),
        (damages, [
            ("attacker_steamid", "attacker_steamid_clean"),
            ("victim_steamid", "victim_steamid_clean"),
        ]),
        (shots, [("player_steamid", "player_steamid_clean")]),
        (smokes, [("thrower_steamid", "thrower_steamid_clean")]),
        (infernos, [("thrower_steamid", "thrower_steamid_clean")]),
        (grenades, [("thrower_steamid", "thrower_steamid_clean")]),
        (bomb, [("steamid", "steamid_clean")]),
    ]:
        for src, dst in pairs:
            add_clean_id(df, src, dst)

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
            "trade_window_ticks": int(args.trade_window_ticks),
            "notes": [
                "Report v1 works without yaw/pitch, so exact aim analysis is not enabled yet.",
                "Grenades table from Awpy is trajectory-like data; utility counts are estimated through unique entity_id values and specialized smoke/inferno tables.",
            ],
        },
        "player_stats": records(player_stats),
        "round_summaries": records(round_summaries),
        "death_review": records(death_review),
        "patterns": patterns,
    }

    json_path = out_dir / "report_v1.json"
    html_path = out_dir / "report_v1.html"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html_report(report, html_path)

    print("=== CS Demo Coach report v1 ===")
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
            "estimated_hit_events_per_100_shots",
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
    print("Next: open report_v1.html in browser.")


if __name__ == "__main__":
    main()
