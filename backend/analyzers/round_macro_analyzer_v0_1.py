from __future__ import annotations

import argparse
import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


VERSION = "round_macro_analyzer_v0_1"
TRADE_WINDOW_TICKS = 320


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def norm_name(value: Any) -> str:
    return safe_str(value).strip().lower()


def find_parquet(data_root: Path, match_id: str, filename: str) -> Path | None:
    candidates = list(data_root.rglob(filename))
    if not candidates:
        return None

    match_candidates = [p for p in candidates if match_id.lower() in str(p).lower()]
    if match_candidates:
        candidates = match_candidates

    preferred_words = ["parsed", "parquet", "processed", "data"]
    def score(path: Path) -> tuple[int, int]:
        s = str(path).lower()
        preferred_score = 0 if any(w in s for w in preferred_words) else 1
        return (preferred_score, len(str(path)))

    return sorted(candidates, key=score)[0]


def read_parquet_optional(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"[WARN] Could not read {path}: {e}")
        return pd.DataFrame()


def first_existing_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    return None


def get_round_col(df: pd.DataFrame) -> str | None:
    return first_existing_col(df, ["round_num", "round", "roundNumber"])


def infer_player_side_for_round(round_num: int, player: str, kills: pd.DataFrame, damages: pd.DataFrame) -> str:
    player_l = norm_name(player)
    sides: list[str] = []

    if not kills.empty:
        rcol = get_round_col(kills)
        if rcol:
            k = kills[kills[rcol] == round_num]
        else:
            k = kills

        for _, row in k.iterrows():
            if norm_name(row.get("attacker_name")) == player_l:
                s = safe_str(row.get("attacker_side")).strip()
                if s:
                    sides.append(s)
            if norm_name(row.get("victim_name")) == player_l:
                s = safe_str(row.get("victim_side")).strip()
                if s:
                    sides.append(s)

    if not damages.empty:
        rcol = get_round_col(damages)
        if rcol:
            d = damages[damages[rcol] == round_num]
        else:
            d = damages

        for _, row in d.iterrows():
            if norm_name(row.get("attacker_name")) == player_l:
                s = safe_str(row.get("attacker_side")).strip()
                if s:
                    sides.append(s)
            if norm_name(row.get("victim_name")) == player_l:
                s = safe_str(row.get("victim_side")).strip()
                if s:
                    sides.append(s)

    if not sides:
        return ""

    return Counter(sides).most_common(1)[0][0]


def get_round_tick_bounds(round_row: pd.Series) -> tuple[int | None, int | None]:
    start = safe_int(round_row.get("start"))
    end = safe_int(round_row.get("official_end"), None)
    if end is None:
        end = safe_int(round_row.get("end"), None)
    return start, end


def get_plant_event(round_num: int, bomb: pd.DataFrame, round_row: pd.Series) -> dict[str, Any]:
    result = {
        "plant_tick": None,
        "plant_event": "",
        "bombsite": safe_str(round_row.get("bomb_site") or round_row.get("bombsite")),
        "has_plant": False,
    }

    if not bomb.empty:
        rcol = get_round_col(bomb)
        b = bomb[bomb[rcol] == round_num] if rcol else bomb
        if not b.empty:
            event_col = first_existing_col(b, ["event", "bomb_event", "type"])
            tick_col = first_existing_col(b, ["tick", "start_tick"])
            site_col = first_existing_col(b, ["bombsite", "bomb_site", "site"])

            if event_col and tick_col:
                planted = []
                fallback_plant = []
                for _, row in b.iterrows():
                    ev = safe_str(row.get(event_col)).lower()
                    if "plant" in ev:
                        fallback_plant.append(row)
                    if "planted" in ev or ev in {"bomb_planted", "plant"}:
                        planted.append(row)

                chosen = None
                if planted:
                    chosen = sorted(planted, key=lambda r: safe_int(r.get(tick_col), 10**18) or 10**18)[0]
                elif fallback_plant:
                    chosen = sorted(fallback_plant, key=lambda r: safe_int(r.get(tick_col), 10**18) or 10**18)[0]

                if chosen is not None:
                    result["plant_tick"] = safe_int(chosen.get(tick_col))
                    result["plant_event"] = safe_str(chosen.get(event_col))
                    result["bombsite"] = safe_str(chosen.get(site_col)) or result["bombsite"]
                    result["has_plant"] = True

    if not result["has_plant"]:
        bp = round_row.get("bomb_plant")
        bp_tick = safe_int(bp)
        if bp_tick is not None and bp_tick > 0:
            result["plant_tick"] = bp_tick
            result["plant_event"] = "rounds.bomb_plant"
            result["has_plant"] = True

    return result


def filter_round(df: pd.DataFrame, round_num: int) -> pd.DataFrame:
    if df.empty:
        return df
    rcol = get_round_col(df)
    if rcol is None:
        return df.iloc[0:0]
    return df[df[rcol] == round_num].copy()


def player_damage(round_damages: pd.DataFrame, player: str, plant_tick: int | None = None, after: bool | None = None) -> float:
    if round_damages.empty:
        return 0.0

    d = round_damages
    if after is not None and plant_tick is not None and "tick" in d.columns:
        if after:
            d = d[d["tick"] >= plant_tick]
        else:
            d = d[d["tick"] < plant_tick]

    player_l = norm_name(player)
    dmg_col = first_existing_col(d, ["dmg_health_real", "dmg_health"])
    if dmg_col is None:
        return 0.0

    total = 0.0
    for _, row in d.iterrows():
        if norm_name(row.get("attacker_name")) == player_l:
            total += safe_float(row.get(dmg_col))
    return round(total, 1)


def player_received_damage(round_damages: pd.DataFrame, player: str) -> float:
    if round_damages.empty:
        return 0.0

    player_l = norm_name(player)
    dmg_col = first_existing_col(round_damages, ["dmg_health_real", "dmg_health"])
    if dmg_col is None:
        return 0.0

    total = 0.0
    for _, row in round_damages.iterrows():
        if norm_name(row.get("victim_name")) == player_l:
            total += safe_float(row.get(dmg_col))
    return round(total, 1)


def analyze_round(
    round_row: pd.Series,
    player: str,
    kills: pd.DataFrame,
    damages: pd.DataFrame,
    bomb: pd.DataFrame,
) -> dict[str, Any]:
    round_num = safe_int(round_row.get("round_num"), -1)
    if round_num is None:
        round_num = -1

    rkills = filter_round(kills, round_num)
    rdamages = filter_round(damages, round_num)

    player_l = norm_name(player)
    start_tick, end_tick = get_round_tick_bounds(round_row)
    plant = get_plant_event(round_num, bomb, round_row)

    side = infer_player_side_for_round(round_num, player, kills, damages)
    winner = safe_str(round_row.get("winner"))
    reason = safe_str(round_row.get("reason"))

    player_kills_rows = []
    player_death_rows = []
    team_kills_after_player_death = []
    enemy_trade_after_player_kill = []

    if not rkills.empty:
        tick_col = first_existing_col(rkills, ["tick"])
        if tick_col:
            rkills = rkills.sort_values(tick_col)

        for _, row in rkills.iterrows():
            attacker = norm_name(row.get("attacker_name"))
            victim = norm_name(row.get("victim_name"))

            if attacker == player_l:
                player_kills_rows.append(row)
            if victim == player_l:
                player_death_rows.append(row)

    player_kills = len(player_kills_rows)
    player_deaths = len(player_death_rows)

    death_tick = None
    death_by = ""
    death_weapon = ""
    death_untraded = False
    died_after_plant = False
    died_before_plant = False

    if player_death_rows:
        death_row = player_death_rows[0]
        death_tick = safe_int(death_row.get("tick"))
        death_by = safe_str(death_row.get("attacker_name"))
        death_weapon = safe_str(death_row.get("weapon"))

        if plant["plant_tick"] is not None and death_tick is not None:
            died_after_plant = death_tick >= plant["plant_tick"]
            died_before_plant = death_tick < plant["plant_tick"]

        if death_tick is not None and not rkills.empty:
            killer_side = safe_str(death_row.get("attacker_side"))
            player_side = safe_str(death_row.get("victim_side")) or side
            killer_steamid = safe_str(death_row.get("attacker_steamid"))

            for _, krow in rkills.iterrows():
                ktick = safe_int(krow.get("tick"))
                if ktick is None:
                    continue
                if death_tick < ktick <= death_tick + TRADE_WINDOW_TICKS:
                    trade_by_side = safe_str(krow.get("attacker_side"))
                    victim_side = safe_str(krow.get("victim_side"))
                    victim_steamid = safe_str(krow.get("victim_steamid"))

                    if trade_by_side == player_side and victim_side == killer_side:
                        team_kills_after_player_death.append(krow)
                    elif killer_steamid and victim_steamid == killer_steamid:
                        team_kills_after_player_death.append(krow)

            death_untraded = len(team_kills_after_player_death) == 0

    for kill_row in player_kills_rows:
        kill_tick = safe_int(kill_row.get("tick"))
        if kill_tick is None:
            continue
        enemy_side = safe_str(kill_row.get("victim_side"))
        player_side = safe_str(kill_row.get("attacker_side")) or side

        for _, krow in rkills.iterrows():
            ktick = safe_int(krow.get("tick"))
            if ktick is None:
                continue
            if kill_tick < ktick <= kill_tick + TRADE_WINDOW_TICKS:
                if safe_str(krow.get("attacker_side")) == enemy_side and safe_str(krow.get("victim_side")) == player_side:
                    enemy_trade_after_player_kill.append(krow)
                    break

    damage_total = player_damage(rdamages, player)
    damage_postplant = player_damage(rdamages, player, plant["plant_tick"], after=True)
    damage_taken = player_received_damage(rdamages, player)

    kills_after_plant = 0
    kills_before_plant = player_kills
    if plant["plant_tick"] is not None and player_kills_rows:
        kills_after_plant = sum(
            1 for r in player_kills_rows
            if (safe_int(r.get("tick")) is not None and safe_int(r.get("tick")) >= plant["plant_tick"])
        )
        kills_before_plant = player_kills - kills_after_plant

    alive_at_plant = False
    if plant["has_plant"]:
        if death_tick is None:
            alive_at_plant = True
        elif plant["plant_tick"] is not None:
            alive_at_plant = death_tick > plant["plant_tick"]

    player_round_win = None
    if side and winner:
        player_round_win = side.lower() == winner.lower()

    flags: list[str] = []
    notes: list[str] = []

    if player_deaths and death_untraded:
        if plant["has_plant"] and died_after_plant:
            flags.append("postplant_death_untraded")
            notes.append("умер после plant без быстрого трейда")
        else:
            flags.append("death_untraded")
            notes.append("смерть без быстрого трейда")

    if enemy_trade_after_player_kill:
        flags.append("kill_traded_by_enemy")
        notes.append("после килла игрока быстро разменяли")

    if plant["has_plant"] and alive_at_plant and player_round_win is False and damage_postplant <= 0 and kills_after_plant <= 0:
        if side.lower() == "ct":
            flags.append("retake_no_impact")
            notes.append("был жив на plant, но в проигранном retake не дал post-plant impact")
        elif side.lower() == "t":
            flags.append("postplant_no_impact")
            notes.append("был жив на plant, но в проигранном post-plant не дал impact")
        else:
            flags.append("key_event_no_impact")
            notes.append("был жив на ключевом событии, но не дал impact после него")

    if player_round_win is False and player_kills == 0 and damage_total < 30:
        flags.append("low_impact_lost_round")
        notes.append("проигранный раунд с низким личным impact")

    if plant["has_plant"] and died_before_plant and player_round_win is False:
        flags.append("died_before_plant_lost_round")
        notes.append("умер до plant в проигранном раунде")

    if not flags and player_round_win is True and (player_kills > 0 or damage_total >= 50):
        flags.append("positive_impact_round")
        notes.append("выигранный раунд с заметным личным impact")

    priority_score = 0
    for f in flags:
        priority_score += {
            "postplant_death_untraded": 5,
            "retake_no_impact": 5,
            "postplant_no_impact": 5,
            "death_untraded": 4,
            "died_before_plant_lost_round": 4,
            "kill_traded_by_enemy": 3,
            "low_impact_lost_round": 3,
            "key_event_no_impact": 3,
            "positive_impact_round": 1,
        }.get(f, 1)

    return {
        "round_num": round_num,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "winner": winner,
        "reason": reason,
        "player_side": side,
        "player_round_win": player_round_win,
        "has_plant": plant["has_plant"],
        "plant_tick": plant["plant_tick"],
        "plant_event": plant["plant_event"],
        "bombsite": plant["bombsite"],
        "player_kills": player_kills,
        "player_deaths": player_deaths,
        "kills_before_plant": kills_before_plant,
        "kills_after_plant": kills_after_plant,
        "damage_total": damage_total,
        "damage_postplant": damage_postplant,
        "damage_taken": damage_taken,
        "death_tick": death_tick,
        "death_by": death_by,
        "death_weapon": death_weapon,
        "death_untraded": death_untraded,
        "alive_at_plant": alive_at_plant,
        "enemy_traded_player_kill_count": len(enemy_trade_after_player_kill),
        "team_trade_after_player_death_count": len(team_kills_after_player_death),
        "macro_flags": flags,
        "macro_notes": notes,
        "priority_score": priority_score,
    }


def summarize(rounds_out: list[dict[str, Any]]) -> dict[str, Any]:
    flag_counter = Counter()
    side_counter = Counter()
    win_loss = Counter()
    plant_rounds = 0

    for r in rounds_out:
        side = r.get("player_side") or "unknown"
        side_counter[side] += 1

        if r.get("player_round_win") is True:
            win_loss["wins"] += 1
        elif r.get("player_round_win") is False:
            win_loss["losses"] += 1
        else:
            win_loss["unknown"] += 1

        if r.get("has_plant"):
            plant_rounds += 1

        for f in r.get("macro_flags", []):
            flag_counter[f] += 1

    priority_rounds = sorted(
        [r for r in rounds_out if r.get("priority_score", 0) > 0],
        key=lambda x: (-x.get("priority_score", 0), x.get("round_num", 9999)),
    )

    negative_priority = [
        r for r in priority_rounds
        if not (r.get("macro_flags") == ["positive_impact_round"])
    ]

    main_problem = ""
    if flag_counter:
        problem_flags = {k: v for k, v in flag_counter.items() if k != "positive_impact_round"}
        if problem_flags:
            main_problem = Counter(problem_flags).most_common(1)[0][0]

    return {
        "version": VERSION,
        "rounds_total": len(rounds_out),
        "plant_rounds": plant_rounds,
        "player_side_counts": dict(side_counter),
        "win_loss": dict(win_loss),
        "macro_flag_counts": dict(flag_counter),
        "main_macro_problem": main_problem,
        "top_priority_rounds": [
            {
                "round_num": r["round_num"],
                "priority_score": r["priority_score"],
                "flags": r["macro_flags"],
                "notes": r["macro_notes"],
            }
            for r in negative_priority[:10]
        ],
    }


def render_html(payload: dict[str, Any], html_path: Path) -> None:
    summary = payload["summary"]
    rounds = payload["rounds"]

    flag_rows = ""
    for k, v in sorted(summary.get("macro_flag_counts", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        flag_rows += f"<tr><td><code>{html.escape(k)}</code></td><td>{v}</td></tr>\n"

    top_rows = ""
    for r in sorted(rounds, key=lambda x: (-x.get("priority_score", 0), x.get("round_num", 9999))):
        if r.get("priority_score", 0) <= 0:
            continue
        if r.get("macro_flags") == ["positive_impact_round"]:
            continue

        flags = ", ".join(r.get("macro_flags", []))
        notes = "; ".join(r.get("macro_notes", []))
        top_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(safe_str(r.get('player_side')))}</td>"
            f"<td>{html.escape(safe_str(r.get('winner')))}</td>"
            f"<td>{'yes' if r.get('has_plant') else 'no'}</td>"
            f"<td>{html.escape(flags)}</td>"
            f"<td>{html.escape(notes)}</td>"
            f"<td>{r.get('player_kills')} / {r.get('player_deaths')} / {r.get('damage_total')}</td>"
            "</tr>\n"
        )

    all_rows = ""
    for r in sorted(rounds, key=lambda x: x.get("round_num", 9999)):
        flags = ", ".join(r.get("macro_flags", []))
        notes = "; ".join(r.get("macro_notes", []))
        win = r.get("player_round_win")
        if win is True:
            win_text = "win"
        elif win is False:
            win_text = "loss"
        else:
            win_text = "unknown"

        all_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{html.escape(win_text)}</td>"
            f"<td>{html.escape(safe_str(r.get('player_side')))}</td>"
            f"<td>{html.escape(safe_str(r.get('winner')))}</td>"
            f"<td>{html.escape(safe_str(r.get('reason')))}</td>"
            f"<td>{html.escape(safe_str(r.get('bombsite')))}</td>"
            f"<td>{r.get('player_kills')}</td>"
            f"<td>{r.get('player_deaths')}</td>"
            f"<td>{r.get('damage_total')}</td>"
            f"<td>{r.get('damage_postplant')}</td>"
            f"<td>{html.escape(flags)}</td>"
            f"<td>{html.escape(notes)}</td>"
            "</tr>\n"
        )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Round Macro Analyzer v0.1</title>
<style>
    body {{
        font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif;
        background: #101114;
        color: #e9edf1;
        margin: 24px;
    }}
    h1, h2 {{ margin-bottom: 10px; }}
    .muted {{ color: #9aa3ad; }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin: 18px 0;
    }}
    .card {{
        background: #181b20;
        border: 1px solid #2b3139;
        border-radius: 12px;
        padding: 14px;
    }}
    .value {{
        font-size: 28px;
        font-weight: 700;
        margin-top: 4px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 12px;
        font-size: 14px;
    }}
    th, td {{
        border-bottom: 1px solid #2b3139;
        padding: 8px;
        text-align: left;
        vertical-align: top;
    }}
    th {{
        color: #c6d2df;
        background: #181b20;
        position: sticky;
        top: 0;
    }}
    code {{
        color: #d7e7ff;
    }}
    a {{
        color: #8ab4ff;
    }}
</style>
</head>
<body>
<h1>Round Macro Analyzer v0.1</h1>
<div class="muted">
    Match: <code>{html.escape(payload["match_id"])}</code> · Player: <code>{html.escape(payload["player"])}</code> ·
    Generated by <code>{VERSION}</code>
</div>

<div class="grid">
    <div class="card"><div class="muted">Rounds analyzed</div><div class="value">{summary.get("rounds_total", 0)}</div></div>
    <div class="card"><div class="muted">Plant rounds</div><div class="value">{summary.get("plant_rounds", 0)}</div></div>
    <div class="card"><div class="muted">Win / loss</div><div class="value">{summary.get("win_loss", {}).get("wins", 0)} / {summary.get("win_loss", {}).get("losses", 0)}</div></div>
    <div class="card"><div class="muted">Main macro problem</div><div class="value" style="font-size:18px">{html.escape(summary.get("main_macro_problem") or "not enough signal")}</div></div>
</div>

<h2>Flag counts</h2>
<table>
<thead><tr><th>Flag</th><th>Count</th></tr></thead>
<tbody>
{flag_rows}
</tbody>
</table>

<h2>Top priority macro rounds</h2>
<p class="muted">Это не финальный тренерский диагноз, а первый автоматический macro-layer. Его задача — подсветить раунды для проверки: plant/retake/post-plant, deaths without trade, low impact lost rounds.</p>
<table>
<thead>
<tr>
<th>Round</th><th>Priority</th><th>Player side</th><th>Winner</th><th>Plant</th><th>Flags</th><th>Notes</th><th>K/D/Dmg</th>
</tr>
</thead>
<tbody>
{top_rows}
</tbody>
</table>

<h2>All rounds</h2>
<table>
<thead>
<tr>
<th>Round</th><th>Result</th><th>Side</th><th>Winner</th><th>Reason</th><th>Site</th><th>K</th><th>D</th><th>Dmg</th><th>Post-plant dmg</th><th>Flags</th><th>Notes</th>
</tr>
</thead>
<tbody>
{all_rows}
</tbody>
</table>
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")


def write_manual_queue(payload: dict[str, Any], csv_path: Path) -> None:
    if csv_path.exists():
        print(f"[OK] Manual queue already exists, not overwriting: {csv_path}")
        return

    rows = []
    for r in sorted(payload["rounds"], key=lambda x: (-x.get("priority_score", 0), x.get("round_num", 9999))):
        if r.get("priority_score", 0) <= 0:
            continue
        if r.get("macro_flags") == ["positive_impact_round"]:
            continue

        rows.append({
            "round_num": r.get("round_num"),
            "priority_score": r.get("priority_score"),
            "auto_flags": ",".join(r.get("macro_flags", [])),
            "auto_notes": "; ".join(r.get("macro_notes", [])),
            "player_side": r.get("player_side"),
            "winner": r.get("winner"),
            "has_plant": r.get("has_plant"),
            "player_kills": r.get("player_kills"),
            "player_deaths": r.get("player_deaths"),
            "damage_total": r.get("damage_total"),
            "review_status": "todo",
            "real_macro_issue": "",
            "root_cause": "",
            "keep_for_training": "",
            "manual_note": "",
        })

    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Manual macro queue written: {csv_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = (root / args.data_dir).resolve()

    paths = {
        "rounds": find_parquet(data_root, args.match_id, "rounds.parquet"),
        "bomb": find_parquet(data_root, args.match_id, "bomb.parquet"),
        "kills": find_parquet(data_root, args.match_id, "kills.parquet"),
        "damages": find_parquet(data_root, args.match_id, "damages.parquet"),
    }

    print("=== Round Macro Analyzer v0.1 ===")
    print(f"Project root: {root}")
    print(f"Data root: {data_root}")
    print(f"Match ID: {args.match_id}")
    print(f"Player: {args.player}")
    print("")
    print("Detected parquet files:")
    for k, v in paths.items():
        print(f"  {k}: {v if v else 'MISSING'}")

    rounds = read_parquet_optional(paths["rounds"])
    bomb = read_parquet_optional(paths["bomb"])
    kills = read_parquet_optional(paths["kills"])
    damages = read_parquet_optional(paths["damages"])

    if rounds.empty:
        raise SystemExit("rounds.parquet not found or empty. Cannot build macro analyzer.")

    if "round_num" not in rounds.columns:
        rcol = get_round_col(rounds)
        if rcol:
            rounds = rounds.rename(columns={rcol: "round_num"})
        else:
            raise SystemExit("rounds table has no round number column.")

    out_rounds = []
    for _, rr in rounds.sort_values("round_num").iterrows():
        out_rounds.append(analyze_round(rr, args.player, kills, damages, bomb))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) if v else None for k, v in paths.items()},
        "source_shapes": {
            "rounds": list(rounds.shape),
            "bomb": list(bomb.shape),
            "kills": list(kills.shape),
            "damages": list(damages.shape),
        },
        "summary": summarize(out_rounds),
        "rounds": out_rounds,
    }

    reports_dir = data_root / "reports" / args.match_id
    reviews_dir = data_root / "reviews" / args.match_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / f"round_macro_{args.player}_v0_1.json"
    html_path = reports_dir / f"round_macro_{args.player}_v0_1.html"
    csv_path = reviews_dir / f"macro_review_{args.player}_v0_1.csv"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(payload, html_path)
    write_manual_queue(payload, csv_path)

    print("")
    print("=== ROUND MACRO v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"Manual queue: {csv_path}")
    print("")
    print("Summary:")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
