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


UTILITY_WEAPON_HINTS = ["hegrenade", "inferno", "molotov", "incgrenade"]


def safe(value: Any) -> Any:
    try:
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(k): safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [safe(v) for v in value]
        if isinstance(value, np.ndarray):
            return [safe(v) for v in value.tolist()]
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            v = float(value)
            return v if math.isfinite(v) else None
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
    path.write_text(json.dumps(safe(data), ensure_ascii=False, indent=2), encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def s(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def low(value: Any) -> str:
    return s(value).lower()


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return low(value) in {"true", "1", "yes", "y", "да"}


def normalize_grenade_type(value: Any) -> str:
    t = low(value)

    if "flash" in t:
        return "flashbang"
    if "smoke" in t:
        return "smoke"
    if "hegrenade" in t or "he_grenade" in t:
        return "he"
    if "molotov" in t:
        return "molotov"
    if "incendiary" in t or "incgrenade" in t:
        return "incendiary"
    if "decoy" in t:
        return "decoy"

    return t or "unknown"


def utility_role(grenade_type: str) -> str:
    if grenade_type in {"molotov", "incendiary"}:
        return "fire"
    return grenade_type


def empty_player(name: str) -> dict[str, Any]:
    return {
        "player": name or "unknown",
        "grenade_throws_total": 0,
        "grenade_types": {},
        "roles": {},
        "smokes": 0,
        "infernos": 0,
        "utility_damage_dealt": 0.0,
        "utility_damage_taken": 0.0,
        "he_damage_dealt": 0.0,
        "fire_damage_dealt": 0.0,
        "team_utility_damage": 0.0,
        "flash_assists": 0,
        "blind_kills_by_player": 0,
        "score": 0.0,
        "flags": [],
    }


def ensure(players: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    name = name or "unknown"
    if name not in players:
        players[name] = empty_player(name)
    return players[name]


def aggregate_throws(grenades: pd.DataFrame) -> pd.DataFrame:
    if grenades.empty:
        return pd.DataFrame()

    df = grenades.copy()

    for col in ["entity_id", "thrower", "thrower_steamid", "grenade_type", "round_num", "tick", "X", "Y", "Z"]:
        if col not in df.columns:
            df[col] = None

    df["grenade_type_raw"] = df["grenade_type"].astype(str)
    df["grenade_type_norm"] = df["grenade_type"].apply(normalize_grenade_type)
    df["utility_role"] = df["grenade_type_norm"].apply(utility_role)

    group_cols = ["entity_id", "thrower", "thrower_steamid", "grenade_type_norm", "utility_role", "round_num"]

    out = (
        df.sort_values(["round_num", "entity_id", "tick"])
        .groupby(group_cols, dropna=False)
        .agg(
            start_tick=("tick", "min"),
            end_tick=("tick", "max"),
            samples=("tick", "count"),
            raw_types=("grenade_type_raw", lambda x: ", ".join(sorted(set(str(v) for v in x.dropna())))),
            start_X=("X", "first"),
            start_Y=("Y", "first"),
            start_Z=("Z", "first"),
            end_X=("X", "last"),
            end_Y=("Y", "last"),
            end_Z=("Z", "last"),
        )
        .reset_index()
    )

    out["duration_ticks"] = out["end_tick"] - out["start_tick"]
    return out


def add_throw_summary(players: dict[str, dict[str, Any]], throws: pd.DataFrame) -> None:
    if throws.empty:
        return

    counts = throws.groupby(["thrower", "grenade_type_norm", "utility_role"], dropna=False).size().reset_index(name="count")

    for _, row in counts.iterrows():
        player = s(row.get("thrower")) or "unknown"
        gtype = s(row.get("grenade_type_norm")) or "unknown"
        role = s(row.get("utility_role")) or "unknown"
        count = int(n(row.get("count"), 0))

        p = ensure(players, player)
        p["grenade_throws_total"] += count
        p["grenade_types"][gtype] = p["grenade_types"].get(gtype, 0) + count
        p["roles"][role] = p["roles"].get(role, 0) + count


def add_smoke_summary(players: dict[str, dict[str, Any]], smokes: pd.DataFrame) -> None:
    if smokes.empty or "thrower_name" not in smokes.columns:
        return

    for player, g in smokes.groupby("thrower_name", dropna=False):
        p = ensure(players, s(player) or "unknown")
        p["smokes"] = int(len(g))


def add_inferno_summary(players: dict[str, dict[str, Any]], infernos: pd.DataFrame) -> None:
    if infernos.empty or "thrower_name" not in infernos.columns:
        return

    for player, g in infernos.groupby("thrower_name", dropna=False):
        p = ensure(players, s(player) or "unknown")
        p["infernos"] = int(len(g))


def add_damage_summary(players: dict[str, dict[str, Any]], damages: pd.DataFrame) -> list[dict[str, Any]]:
    if damages.empty or "weapon" not in damages.columns:
        return []

    df = damages.copy()
    df["weapon_l"] = df["weapon"].astype(str).str.lower()
    util = df[df["weapon_l"].apply(lambda w: any(h in w for h in UTILITY_WEAPON_HINTS))].copy()

    events = []

    for _, row in util.iterrows():
        attacker = s(row.get("attacker_name")) or "unknown"
        victim = s(row.get("victim_name")) or "unknown"
        weapon = s(row.get("weapon")) or "unknown"
        dmg = n(row.get("dmg_health_real"), n(row.get("dmg_health"), 0.0))

        a = ensure(players, attacker)
        v = ensure(players, victim)

        a["utility_damage_dealt"] += dmg
        v["utility_damage_taken"] += dmg

        weapon_l = low(weapon)
        if "hegrenade" in weapon_l:
            a["he_damage_dealt"] += dmg
        if "inferno" in weapon_l or "molotov" in weapon_l or "incgrenade" in weapon_l:
            a["fire_damage_dealt"] += dmg

        same_side = bool(s(row.get("attacker_side")) and s(row.get("victim_side")) and s(row.get("attacker_side")) == s(row.get("victim_side")))
        if same_side:
            a["team_utility_damage"] += dmg

        events.append({
            "round": int(n(row.get("round_num"), 0)),
            "tick": int(n(row.get("tick"), 0)),
            "attacker": attacker,
            "victim": victim,
            "weapon": weapon,
            "damage": round(float(dmg), 1),
            "same_side": same_side,
            "attacker_place": s(row.get("attacker_place")),
            "victim_place": s(row.get("victim_place")),
        })

    events.sort(key=lambda x: x["damage"], reverse=True)
    return events


def add_flash_summary(players: dict[str, dict[str, Any]], kills: pd.DataFrame) -> list[dict[str, Any]]:
    if kills.empty:
        return []

    events = []

    for _, row in kills.iterrows():
        attacker = s(row.get("attacker_name")) or "unknown"
        assister = s(row.get("assister_name"))
        victim = s(row.get("victim_name")) or "unknown"

        if assister and truthy(row.get("assistedflash")):
            ensure(players, assister)["flash_assists"] += 1
            events.append({
                "type": "flash_assist",
                "round": int(n(row.get("round_num"), 0)),
                "tick": int(n(row.get("tick"), 0)),
                "assister": assister,
                "attacker": attacker,
                "victim": victim,
            })

        if truthy(row.get("attackerblind")):
            ensure(players, attacker)["blind_kills_by_player"] += 1

    return events


def finalize_players(players: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for p in players.values():
        throws = int(p["grenade_throws_total"])
        smokes = int(p["smokes"])
        infernos = int(p["infernos"])
        damage = float(p["utility_damage_dealt"])
        team_damage = float(p["team_utility_damage"])
        flash_assists = int(p["flash_assists"])

        score = 0.0
        score += min(damage * 0.8, 80)
        score += flash_assists * 20
        score += smokes * 2
        score += infernos * 3
        score += max(throws - smokes - infernos, 0) * 0.5
        score -= team_damage * 0.7

        flags = []
        if smokes == 0:
            flags.append("нет смоков")
        if infernos == 0:
            flags.append("нет молотовов/инферно")
        if damage == 0:
            flags.append("нет utility damage")
        if flash_assists == 0:
            flags.append("нет flash assists")
        if team_damage > 0:
            flags.append("team utility damage")

        for key in ["utility_damage_dealt", "utility_damage_taken", "he_damage_dealt", "fire_damage_dealt", "team_utility_damage"]:
            p[key] = round(float(p[key]), 1)

        p["score"] = round(float(score), 1)
        p["flags"] = flags
        rows.append(p)

    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows


def build_throw_events(throws: pd.DataFrame) -> list[dict[str, Any]]:
    if throws.empty:
        return []

    events = []
    for _, row in throws.iterrows():
        events.append({
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": int(n(row.get("start_tick"), 0)),
            "end_tick": int(n(row.get("end_tick"), 0)),
            "thrower": s(row.get("thrower")) or "unknown",
            "grenade_type": s(row.get("grenade_type_norm")) or "unknown",
            "utility_role": s(row.get("utility_role")) or "unknown",
            "raw_types": s(row.get("raw_types")),
            "duration_ticks": int(n(row.get("duration_ticks"), 0)),
            "samples": int(n(row.get("samples"), 0)),
            "start": [round(n(row.get("start_X")), 1), round(n(row.get("start_Y")), 1), round(n(row.get("start_Z")), 1)],
            "end": [round(n(row.get("end_X")), 1), round(n(row.get("end_Y")), 1), round(n(row.get("end_Z")), 1)],
        })

    events.sort(key=lambda x: (x["round"], x["start_tick"]))
    return events


def build_smoke_events(smokes: pd.DataFrame) -> list[dict[str, Any]]:
    if smokes.empty:
        return []

    out = []
    for _, row in smokes.iterrows():
        start = n(row.get("start_tick"), 0)
        end = n(row.get("end_tick"), 0)
        out.append({
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": int(start),
            "end_tick": int(end),
            "duration_ticks": int(end - start),
            "thrower": s(row.get("thrower_name")) or "unknown",
            "side": s(row.get("thrower_side")),
            "place": s(row.get("thrower_place")),
            "x": round(n(row.get("X")), 1),
            "y": round(n(row.get("Y")), 1),
            "z": round(n(row.get("Z")), 1),
        })

    out.sort(key=lambda x: (x["round"], x["start_tick"]))
    return out


def build_inferno_events(infernos: pd.DataFrame) -> list[dict[str, Any]]:
    if infernos.empty:
        return []

    out = []
    for _, row in infernos.iterrows():
        start = n(row.get("start_tick"), 0)
        end = n(row.get("end_tick"), 0)
        out.append({
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": int(start),
            "end_tick": int(end),
            "duration_ticks": int(end - start),
            "thrower": s(row.get("thrower_name")) or "unknown",
            "side": s(row.get("thrower_side")),
            "place": s(row.get("thrower_place")),
            "x": round(n(row.get("X")), 1),
            "y": round(n(row.get("Y")), 1),
            "z": round(n(row.get("Z")), 1),
        })

    out.sort(key=lambda x: (x["round"], x["start_tick"]))
    return out


def utility_verdict(primary: dict[str, Any] | None, rank: int | None, players_total: int) -> list[str]:
    if not primary:
        return ["Нет utility summary для основного игрока."]

    notes = []
    throws = int(n(primary.get("grenade_throws_total"), 0))
    smokes = int(n(primary.get("smokes"), 0))
    infernos = int(n(primary.get("infernos"), 0))
    damage = n(primary.get("utility_damage_dealt"), 0)
    flash_assists = int(n(primary.get("flash_assists"), 0))
    team_damage = n(primary.get("team_utility_damage"), 0)

    notes.append(f"Utility rank: {rank}/{players_total}. Это грубый рейтинг по броскам, урону, смокам, молотовам и flash assists.")

    if throws < 50:
        notes.append("Бросков utility немного относительно части игроков матча. Возможная зона роста — активнее использовать гранаты по плану раунда.")
    else:
        notes.append("По количеству бросков utility используется регулярно.")

    if smokes <= 4:
        notes.append("Смоков мало или умеренно. Следующий слой должен проверить не только количество, но и качество smoke.")
    if infernos <= 5:
        notes.append("Молотовов/инферно умеренно или мало. Нужно проверить, были ли они под stop-push/clear/retake.")
    if damage < 30:
        notes.append("Utility damage низкий. В этой демке гранаты почти не создавали прямого урона.")
    if flash_assists == 0:
        notes.append("Flash assists нет. Это не доказывает плохие флешки, но показывает, что парсер не нашёл убийств с flash assist.")
    if team_damage > 0:
        notes.append("Есть team utility damage — это нужно проверить вручную.")

    notes.append("v0.2 пока не оценивает, закрыл ли smoke конкретный проход. Для этого нужен отдельный lineups/area layer.")
    return notes


def render_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="muted">Нет данных.</p>'

    head = "".join(f"<th>{esc(label)}</th>" for _, label in cols)
    body = []

    for row in rows:
        cells = "".join(f"<td>{esc(row.get(key))}</td>" for key, _ in cols)
        body.append(f"<tr>{cells}</tr>")

    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(data: dict[str, Any]) -> str:
    primary = data.get("primary_player_summary") or {}
    players = data.get("players", [])

    rank = None
    for i, row in enumerate(players, 1):
        if low(row.get("player")) == low(data.get("player")):
            rank = i
            break

    verdict_items = "".join(f"<li>{esc(x)}</li>" for x in utility_verdict(primary, rank, len(players)))

    player_table = render_table(players, [
        ("player", "Player"),
        ("score", "Utility score"),
        ("grenade_throws_total", "Throws"),
        ("grenade_types", "Types"),
        ("roles", "Roles"),
        ("smokes", "Smokes"),
        ("infernos", "Infernos"),
        ("utility_damage_dealt", "Util dmg"),
        ("he_damage_dealt", "HE dmg"),
        ("fire_damage_dealt", "Fire dmg"),
        ("team_utility_damage", "Team util dmg"),
        ("flash_assists", "Flash assists"),
        ("flags", "Flags"),
    ])

    damage_table = render_table(data.get("utility_damage_events", [])[:80], [
        ("round", "R"),
        ("tick", "Tick"),
        ("attacker", "Attacker"),
        ("victim", "Victim"),
        ("weapon", "Weapon"),
        ("damage", "Damage"),
        ("same_side", "Team dmg"),
        ("attacker_place", "Attacker place"),
        ("victim_place", "Victim place"),
    ])

    smoke_table = render_table(data.get("smoke_events", [])[:80], [
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
    ])

    inferno_table = render_table(data.get("inferno_events", [])[:80], [
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
    ])

    throw_table = render_table(data.get("grenade_throw_events", [])[:120], [
        ("round", "R"),
        ("start_tick", "Start"),
        ("end_tick", "End"),
        ("thrower", "Thrower"),
        ("grenade_type", "Type"),
        ("utility_role", "Role"),
        ("raw_types", "Raw types"),
        ("duration_ticks", "Duration"),
        ("samples", "Samples"),
        ("start", "Start XYZ"),
        ("end", "End XYZ"),
    ])

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Utility Analyzer v0.2 — {esc(data.get("match_id"))}</title>
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
        li {{ margin-bottom: 7px; }}
    </style>
</head>
<body>
    <h1>Utility Analyzer v0.2</h1>
    <p class="muted">
        Match: <code>{esc(data.get("match_id"))}</code> · Player: <code>{esc(data.get("player"))}</code><br>
        v0.2 нормализует типы гранат: CFlashbang/CFlashbangProjectile → flashbang, CSmokeGrenade/CSmokeGrenadeProjectile → smoke.
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
        <h2>Utility verdict v0.2</h2>
        <ul>{verdict_items}</ul>
    </section>

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
        <h2>Grenade throw events</h2>
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

    throws = aggregate_throws(grenades)

    players: dict[str, dict[str, Any]] = {}
    add_throw_summary(players, throws)
    add_smoke_summary(players, smokes)
    add_inferno_summary(players, infernos)
    damage_events = add_damage_summary(players, damages)
    flash_events = add_flash_summary(players, kills)

    player_rows = finalize_players(players)

    primary = None
    for row in player_rows:
        if low(row.get("player")) == low(player):
            primary = row
            break

    data = {
        "version": "utility_analyzer_v0_2",
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
            "normalized_grenade_types": sorted([str(x) for x in throws["grenade_type_norm"].dropna().unique()]) if not throws.empty else [],
        },
        "primary_player_summary": primary,
        "players": player_rows,
        "utility_damage_events": damage_events,
        "flash_events": flash_events,
        "smoke_events": build_smoke_events(smokes),
        "inferno_events": build_inferno_events(infernos),
        "grenade_throw_events": build_throw_events(throws),
    }

    return data


def main() -> None:
    parser = argparse.ArgumentParser()
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

    json_path = report_dir / "utility_analyzer_v0_2.json"
    html_path = report_dir / "utility_analyzer_v0_2.html"

    write_json(json_path, data)
    html_path.write_text(render_html(data), encoding="utf-8")

    print("OK: Utility Analyzer v0.2 created")
    print(f"  Match: {match_id}")
    print(f"  Player: {args.player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")

    print("")
    print("Summary:")
    for k, v in data["summary"].items():
        print(f"  {k}: {v}")

    print("")
    print("Primary player utility:")
    primary = data.get("primary_player_summary") or {}
    for key in [
        "grenade_throws_total",
        "grenade_types",
        "roles",
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
            f"types={row['grenade_types']} smokes={row['smokes']} infernos={row['infernos']} "
            f"dmg={row['utility_damage_dealt']} flash_assists={row['flash_assists']}"
        )

    if args.open:
        os.startfile(str(html_path))


if __name__ == "__main__":
    main()
