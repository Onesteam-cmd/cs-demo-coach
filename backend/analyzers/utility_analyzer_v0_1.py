from __future__ import annotations

import argparse
import html
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


UTILITY_WEAPON_HINTS = [
    "hegrenade",
    "inferno",
    "molotov",
    "incgrenade",
    "decoy",
    "flashbang",
    "smokegrenade",
]


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


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(make_json_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def lower(value: Any) -> str:
    return norm(value).lower()


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = lower(value)
    return text in {"true", "1", "yes", "y", "да"}


def agg_grenade_throws(grenades: pd.DataFrame) -> pd.DataFrame:
    if grenades.empty:
        return pd.DataFrame()

    needed = ["entity_id", "thrower", "thrower_steamid", "grenade_type", "round_num", "tick", "X", "Y", "Z"]
    for col in needed:
        if col not in grenades.columns:
            grenades[col] = None

    group_cols = ["entity_id", "thrower", "thrower_steamid", "grenade_type", "round_num"]

    throws = (
        grenades
        .sort_values(["round_num", "entity_id", "tick"])
        .groupby(group_cols, dropna=False)
        .agg(
            start_tick=("tick", "min"),
            end_tick=("tick", "max"),
            samples=("tick", "count"),
            start_X=("X", "first"),
            start_Y=("Y", "first"),
            start_Z=("Z", "first"),
            end_X=("X", "last"),
            end_Y=("Y", "last"),
            end_Z=("Z", "last"),
        )
        .reset_index()
    )

    throws["duration_ticks"] = throws["end_tick"] - throws["start_tick"]
    return throws


def summarize_counts_by_player(throws: pd.DataFrame, smokes: pd.DataFrame, infernos: pd.DataFrame) -> dict[str, dict[str, Any]]:
    players: dict[str, dict[str, Any]] = {}

    def ensure(player: str) -> dict[str, Any]:
        player = player or "unknown"
        if player not in players:
            players[player] = {
                "player": player,
                "grenade_throws_total": 0,
                "grenade_types": {},
                "smokes": 0,
                "infernos": 0,
                "avg_smoke_duration_ticks": None,
                "avg_inferno_duration_ticks": None,
                "utility_damage_dealt": 0,
                "utility_damage_taken": 0,
                "he_damage_dealt": 0,
                "fire_damage_dealt": 0,
                "team_utility_damage": 0,
                "flash_assists": 0,
                "blind_kills_by_player": 0,
                "score": 0.0,
                "flags": [],
            }
        return players[player]

    if not throws.empty:
        counts = throws.groupby(["thrower", "grenade_type"], dropna=False).size().reset_index(name="count")
        for _, row in counts.iterrows():
            player = norm(row["thrower"]) or "unknown"
            grenade_type = norm(row["grenade_type"]) or "unknown"
            count = int(row["count"])
            p = ensure(player)
            p["grenade_throws_total"] += count
            p["grenade_types"][grenade_type] = p["grenade_types"].get(grenade_type, 0) + count

    if not smokes.empty and "thrower_name" in smokes.columns:
        tmp = smokes.copy()
        tmp["duration_ticks"] = tmp["end_tick"] - tmp["start_tick"]
        for player, g in tmp.groupby("thrower_name", dropna=False):
            p = ensure(norm(player) or "unknown")
            p["smokes"] = int(len(g))
            p["avg_smoke_duration_ticks"] = round(float(g["duration_ticks"].mean()), 1) if len(g) else None

    if not infernos.empty and "thrower_name" in infernos.columns:
        tmp = infernos.copy()
        tmp["duration_ticks"] = tmp["end_tick"] - tmp["start_tick"]
        for player, g in tmp.groupby("thrower_name", dropna=False):
            p = ensure(norm(player) or "unknown")
            p["infernos"] = int(len(g))
            p["avg_inferno_duration_ticks"] = round(float(g["duration_ticks"].mean()), 1) if len(g) else None

    return players


def add_damage_summary(players: dict[str, dict[str, Any]], damages: pd.DataFrame) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if damages.empty or "weapon" not in damages.columns:
        return events

    df = damages.copy()
    df["weapon_l"] = df["weapon"].astype(str).str.lower()
    utility_mask = df["weapon_l"].apply(lambda w: any(h in w for h in UTILITY_WEAPON_HINTS))
    util = df[utility_mask].copy()

    if util.empty:
        return events

    for _, row in util.iterrows():
        attacker = norm(row.get("attacker_name")) or "unknown"
        victim = norm(row.get("victim_name")) or "unknown"
        weapon = norm(row.get("weapon")) or "unknown"
        dmg = n(row.get("dmg_health_real"), n(row.get("dmg_health"), 0.0))

        if attacker not in players:
            players[attacker] = {
                "player": attacker,
                "grenade_throws_total": 0,
                "grenade_types": {},
                "smokes": 0,
                "infernos": 0,
                "avg_smoke_duration_ticks": None,
                "avg_inferno_duration_ticks": None,
                "utility_damage_dealt": 0,
                "utility_damage_taken": 0,
                "he_damage_dealt": 0,
                "fire_damage_dealt": 0,
                "team_utility_damage": 0,
                "flash_assists": 0,
                "blind_kills_by_player": 0,
                "score": 0.0,
                "flags": [],
            }

        if victim not in players:
            players[victim] = {
                "player": victim,
                "grenade_throws_total": 0,
                "grenade_types": {},
                "smokes": 0,
                "infernos": 0,
                "avg_smoke_duration_ticks": None,
                "avg_inferno_duration_ticks": None,
                "utility_damage_dealt": 0,
                "utility_damage_taken": 0,
                "he_damage_dealt": 0,
                "fire_damage_dealt": 0,
                "team_utility_damage": 0,
                "flash_assists": 0,
                "blind_kills_by_player": 0,
                "score": 0.0,
                "flags": [],
            }

        players[attacker]["utility_damage_dealt"] += dmg
        players[victim]["utility_damage_taken"] += dmg

        weapon_l = lower(weapon)
        if "hegrenade" in weapon_l:
            players[attacker]["he_damage_dealt"] += dmg
        if "inferno" in weapon_l or "molotov" in weapon_l or "incgrenade" in weapon_l:
            players[attacker]["fire_damage_dealt"] += dmg

        same_side = (
            norm(row.get("attacker_side"))
            and norm(row.get("victim_side"))
            and norm(row.get("attacker_side")) == norm(row.get("victim_side"))
        )
        if same_side:
            players[attacker]["team_utility_damage"] += dmg

        events.append({
            "round": int(n(row.get("round_num"), 0)),
            "tick": int(n(row.get("tick"), 0)),
            "attacker": attacker,
            "victim": victim,
            "weapon": weapon,
            "damage": round(float(dmg), 1),
            "same_side": bool(same_side),
            "attacker_place": norm(row.get("attacker_place")),
            "victim_place": norm(row.get("victim_place")),
        })

    events.sort(key=lambda x: x["damage"], reverse=True)
    return events


def add_kill_flash_summary(players: dict[str, dict[str, Any]], kills: pd.DataFrame) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    if kills.empty:
        return events

    for _, row in kills.iterrows():
        attacker = norm(row.get("attacker_name")) or "unknown"
        assister = norm(row.get("assister_name")) or ""
        victim = norm(row.get("victim_name")) or "unknown"

        if assister and boolish(row.get("assistedflash")):
            if assister not in players:
                players[assister] = {
                    "player": assister,
                    "grenade_throws_total": 0,
                    "grenade_types": {},
                    "smokes": 0,
                    "infernos": 0,
                    "avg_smoke_duration_ticks": None,
                    "avg_inferno_duration_ticks": None,
                    "utility_damage_dealt": 0,
                    "utility_damage_taken": 0,
                    "he_damage_dealt": 0,
                    "fire_damage_dealt": 0,
                    "team_utility_damage": 0,
                    "flash_assists": 0,
                    "blind_kills_by_player": 0,
                    "score": 0.0,
                    "flags": [],
                }

            players[assister]["flash_assists"] += 1
            events.append({
                "type": "flash_assist",
                "round": int(n(row.get("round_num"), 0)),
                "tick": int(n(row.get("tick"), 0)),
                "assister": assister,
                "attacker": attacker,
                "victim": victim,
            })

        if boolish(row.get("attackerblind")):
            if attacker not in players:
                players[attacker] = {
                    "player": attacker,
                    "grenade_throws_total": 0,
                    "grenade_types": {},
                    "smokes": 0,
                    "infernos": 0,
                    "avg_smoke_duration_ticks": None,
                    "avg_inferno_duration_ticks": None,
                    "team_utility_damage": 0,
                    "utility_damage_dealt": 0,
                    "utility_damage_taken": 0,
                    "he_damage_dealt": 0,
                    "fire_damage_dealt": 0,
                    "flash_assists": 0,
                    "blind_kills_by_player": 0,
                    "score": 0.0,
                    "flags": [],
                }
            players[attacker]["blind_kills_by_player"] += 1

    return events


def finalize_player_scores(players: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for p in players.values():
        throws = p["grenade_throws_total"]
        damage = p["utility_damage_dealt"]
        team_damage = p["team_utility_damage"]
        flash_assists = p["flash_assists"]

        score = 0.0
        score += min(damage * 0.8, 80)
        score += flash_assists * 20
        score += p["smokes"] * 2
        score += p["infernos"] * 3
        score += max(throws - p["smokes"] - p["infernos"], 0) * 0.5
        score -= team_damage * 0.7

        flags = []

        if throws == 0:
            flags.append("нет найденных бросков utility")
        if p["smokes"] == 0:
            flags.append("нет смоков")
        if p["infernos"] == 0:
            flags.append("нет молотовов/инферно")
        if damage == 0:
            flags.append("нет utility damage")
        if team_damage > 0:
            flags.append("team utility damage")
        if flash_assists == 0:
            flags.append("нет flash assists")

        p["utility_damage_dealt"] = round(float(p["utility_damage_dealt"]), 1)
        p["utility_damage_taken"] = round(float(p["utility_damage_taken"]), 1)
        p["he_damage_dealt"] = round(float(p["he_damage_dealt"]), 1)
        p["fire_damage_dealt"] = round(float(p["fire_damage_dealt"]), 1)
        p["team_utility_damage"] = round(float(p["team_utility_damage"]), 1)
        p["score"] = round(float(score), 1)
        p["flags"] = flags

        rows.append(p)

    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows


def build_smoke_events(smokes: pd.DataFrame) -> list[dict[str, Any]]:
    if smokes.empty:
        return []

    events = []
    for _, row in smokes.iterrows():
        start = n(row.get("start_tick"), 0)
        end = n(row.get("end_tick"), 0)
        events.append({
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": int(start),
            "end_tick": int(end),
            "duration_ticks": int(end - start),
            "thrower": norm(row.get("thrower_name")) or "unknown",
            "side": norm(row.get("thrower_side")),
            "place": norm(row.get("thrower_place")),
            "x": round(n(row.get("X")), 1),
            "y": round(n(row.get("Y")), 1),
            "z": round(n(row.get("Z")), 1),
        })
    events.sort(key=lambda x: (x["round"], x["start_tick"]))
    return events


def build_inferno_events(infernos: pd.DataFrame) -> list[dict[str, Any]]:
    if infernos.empty:
        return []

    events = []
    for _, row in infernos.iterrows():
        start = n(row.get("start_tick"), 0)
        end = n(row.get("end_tick"), 0)
        events.append({
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": int(start),
            "end_tick": int(end),
            "duration_ticks": int(end - start),
            "thrower": norm(row.get("thrower_name")) or "unknown",
            "side": norm(row.get("thrower_side")),
            "place": norm(row.get("thrower_place")),
            "x": round(n(row.get("X")), 1),
            "y": round(n(row.get("Y")), 1),
            "z": round(n(row.get("Z")), 1),
        })
    events.sort(key=lambda x: (x["round"], x["start_tick"]))
    return events


def build_grenade_throw_events(throws: pd.DataFrame) -> list[dict[str, Any]]:
    if throws.empty:
        return []

    events = []
    for _, row in throws.iterrows():
        events.append({
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": int(n(row.get("start_tick"), 0)),
            "end_tick": int(n(row.get("end_tick"), 0)),
            "thrower": norm(row.get("thrower")) or "unknown",
            "grenade_type": norm(row.get("grenade_type")) or "unknown",
            "duration_ticks": int(n(row.get("duration_ticks"), 0)),
            "samples": int(n(row.get("samples"), 0)),
            "start": [round(n(row.get("start_X")), 1), round(n(row.get("start_Y")), 1), round(n(row.get("start_Z")), 1)],
            "end": [round(n(row.get("end_X")), 1), round(n(row.get("end_Y")), 1), round(n(row.get("end_Z")), 1)],
        })
    events.sort(key=lambda x: (x["round"], x["start_tick"]))
    return events


def render_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]], empty: str = "Нет данных.") -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'

    head = "".join(f"<th>{esc(label)}</th>" for _, label in cols)

    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{esc(row.get(key))}</td>" for key, _ in cols)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"""
    <table>
        <thead><tr>{head}</tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
    </table>
    """


def render_html(data: dict[str, Any]) -> str:
    primary = data.get("primary_player_summary") or {}

    player_rows = data.get("players", [])
    player_table = render_table(
        player_rows,
        [
            ("player", "Player"),
            ("score", "Utility score"),
            ("grenade_throws_total", "Throws"),
            ("smokes", "Smokes"),
            ("infernos", "Infernos"),
            ("utility_damage_dealt", "Util dmg"),
            ("he_damage_dealt", "HE dmg"),
            ("fire_damage_dealt", "Fire dmg"),
            ("team_utility_damage", "Team util dmg"),
            ("flash_assists", "Flash assists"),
            ("flags", "Flags"),
        ],
    )

    smoke_table = render_table(
        data.get("smoke_events", [])[:80],
        [
            ("round", "R"),
            ("start_tick", "Start"),
            ("end_tick", "End"),
            ("duration_ticks", "Duration"),
            ("thrower", "Thrower"),
            ("side", "Side"),
            ("place", "Thrower place"),
            ("x", "X"),
            ("y", "Y"),
            ("z", "Z"),
        ],
    )

    inferno_table = render_table(
        data.get("inferno_events", [])[:80],
        [
            ("round", "R"),
            ("start_tick", "Start"),
            ("end_tick", "End"),
            ("duration_ticks", "Duration"),
            ("thrower", "Thrower"),
            ("side", "Side"),
            ("place", "Thrower place"),
            ("x", "X"),
            ("y", "Y"),
            ("z", "Z"),
        ],
    )

    damage_table = render_table(
        data.get("utility_damage_events", [])[:80],
        [
            ("round", "R"),
            ("tick", "Tick"),
            ("attacker", "Attacker"),
            ("victim", "Victim"),
            ("weapon", "Weapon"),
            ("damage", "Damage"),
            ("same_side", "Team dmg"),
            ("attacker_place", "Attacker place"),
            ("victim_place", "Victim place"),
        ],
    )

    throw_table = render_table(
        data.get("grenade_throw_events", [])[:120],
        [
            ("round", "R"),
            ("start_tick", "Start"),
            ("end_tick", "End"),
            ("thrower", "Thrower"),
            ("grenade_type", "Type"),
            ("duration_ticks", "Duration"),
            ("samples", "Samples"),
            ("start", "Start XYZ"),
            ("end", "End XYZ"),
        ],
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Utility Analyzer v0.1 — {esc(data["match_id"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 1100px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
    </style>
</head>
<body>
    <h1>Utility Analyzer v0.1</h1>
    <p class="muted">
        Match: <code>{esc(data["match_id"])}</code> ·
        Player: <code>{esc(data["player"])}</code><br>
        Это базовый слой utility. Он считает броски, смоки, молотовы/инферно, utility damage и flash assists. Он пока не знает, закрыл ли конкретный smoke проход идеально.
    </p>

    <div class="grid">
        <div class="card"><div class="card-title">Primary utility score</div><div class="card-value">{esc(primary.get("score"))}</div></div>
        <div class="card"><div class="card-title">Throws</div><div class="card-value">{esc(primary.get("grenade_throws_total"))}</div></div>
        <div class="card"><div class="card-title">Smokes</div><div class="card-value">{esc(primary.get("smokes"))}</div></div>
        <div class="card"><div class="card-title">Infernos</div><div class="card-value">{esc(primary.get("infernos"))}</div></div>
        <div class="card"><div class="card-title">Utility damage</div><div class="card-value">{esc(primary.get("utility_damage_dealt"))}</div></div>
        <div class="card"><div class="card-title">Flash assists</div><div class="card-value">{esc(primary.get("flash_assists"))}</div></div>
    </div>

    <section>
        <h2>Player utility summary</h2>
        {player_table}
    </section>

    <section>
        <h2>Utility damage events</h2>
        {damage_table}
    </section>

    <section>
        <h2>Smoke events</h2>
        {smoke_table}
    </section>

    <section>
        <h2>Inferno / molotov events</h2>
        {inferno_table}
    </section>

    <section>
        <h2>Grenade throw events from trajectory table</h2>
        {throw_table}
    </section>
</body>
</html>
"""


def build(parsed_dir: Path, match_id: str, player: str) -> dict[str, Any]:
    grenades = read_parquet(parsed_dir / "grenades.parquet")
    smokes = read_parquet(parsed_dir / "smokes.parquet")
    infernos = read_parquet(parsed_dir / "infernos.parquet")
    damages = read_parquet(parsed_dir / "damages.parquet")
    kills = read_parquet(parsed_dir / "kills.parquet")

    throws = agg_grenade_throws(grenades)

    players = summarize_counts_by_player(throws, smokes, infernos)
    damage_events = add_damage_summary(players, damages)
    flash_events = add_kill_flash_summary(players, kills)
    player_rows = finalize_player_scores(players)

    primary = None
    for row in player_rows:
        if lower(row.get("player")) == lower(player):
            primary = row
            break

    data = {
        "version": "utility_analyzer_v0_1",
        "match_id": match_id,
        "player": player,
        "source_parsed_dir": str(parsed_dir),
        "summary": {
            "grenade_trajectory_rows": int(len(grenades)),
            "deduped_grenade_throws": int(len(throws)),
            "smokes": int(len(smokes)),
            "infernos": int(len(infernos)),
            "utility_damage_events": int(len(damage_events)),
            "flash_events": int(len(flash_events)),
            "players": int(len(player_rows)),
        },
        "primary_player_summary": primary,
        "players": player_rows,
        "utility_damage_events": damage_events,
        "flash_events": flash_events,
        "smoke_events": build_smoke_events(smokes),
        "inferno_events": build_inferno_events(infernos),
        "grenade_throw_events": build_grenade_throw_events(throws),
    }

    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Build basic utility analyzer v0.1.")
    parser.add_argument("parsed_dir", type=Path)
    parser.add_argument("--match-id", default=None)
    parser.add_argument("--player", default="Player")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    parsed_dir = args.parsed_dir
    if not parsed_dir.exists():
        raise FileNotFoundError(f"Parsed dir not found: {parsed_dir}")

    match_id = args.match_id or parsed_dir.name
    report_dir = Path("data/reports") / match_id
    report_dir.mkdir(parents=True, exist_ok=True)

    data = build(parsed_dir, match_id, args.player)

    json_path = report_dir / "utility_analyzer_v0_1.json"
    html_path = report_dir / "utility_analyzer_v0_1.html"

    write_json(json_path, data)
    html_path.write_text(render_html(data), encoding="utf-8")

    print("OK: Utility Analyzer v0.1 created")
    print(f"  Match: {match_id}")
    print(f"  Player: {args.player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Summary:")
    for k, v in data["summary"].items():
        print(f"  {k}: {v}")

    primary = data.get("primary_player_summary") or {}
    print("")
    print("Primary player utility:")
    for key in [
        "grenade_throws_total",
        "grenade_types",
        "smokes",
        "infernos",
        "utility_damage_dealt",
        "he_damage_dealt",
        "fire_damage_dealt",
        "team_utility_damage",
        "flash_assists",
        "blind_kills_by_player",
        "score",
        "flags",
    ]:
        print(f"  {key}: {primary.get(key)}")

    print("")
    print("Top utility players:")
    for row in data["players"][:5]:
        print(
            f"  {row['player']}: score={row['score']} throws={row['grenade_throws_total']} "
            f"smokes={row['smokes']} infernos={row['infernos']} dmg={row['utility_damage_dealt']} flash_assists={row['flash_assists']}"
        )

    if args.open:
        os.startfile(str(html_path))


if __name__ == "__main__":
    main()
