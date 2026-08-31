from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


VERSION = "round_macro_analyzer_v0_2"
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


def norm(value: Any) -> str:
    return safe_str(value).strip().lower()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def round_col(df: pd.DataFrame) -> str | None:
    return first_col(df, ["round_num", "round", "roundNumber"])


def find_parquet(data_root: Path, match_id: str, filename: str) -> Path | None:
    candidates = list(data_root.rglob(filename))
    if not candidates:
        return None

    matched = [p for p in candidates if match_id.lower() in str(p).lower()]
    if matched:
        candidates = matched

    return sorted(candidates, key=lambda p: (0 if "parsed" in str(p).lower() else 1, len(str(p))))[0]


def read_parquet(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"[WARN] Could not read {path}: {e}")
        return pd.DataFrame()


def filter_round(df: pd.DataFrame, round_num: int) -> pd.DataFrame:
    if df.empty:
        return df
    rc = round_col(df)
    if rc is None:
        return df.iloc[0:0].copy()
    return df[df[rc] == round_num].copy()


def infer_player_side(player: str, rkills: pd.DataFrame, rdamages: pd.DataFrame) -> str:
    p = norm(player)
    sides: list[str] = []

    for _, row in rkills.iterrows():
        if norm(row.get("attacker_name")) == p:
            s = safe_str(row.get("attacker_side"))
            if s:
                sides.append(s)
        if norm(row.get("victim_name")) == p:
            s = safe_str(row.get("victim_side"))
            if s:
                sides.append(s)

    for _, row in rdamages.iterrows():
        if norm(row.get("attacker_name")) == p:
            s = safe_str(row.get("attacker_side"))
            if s:
                sides.append(s)
        if norm(row.get("victim_name")) == p:
            s = safe_str(row.get("victim_side"))
            if s:
                sides.append(s)

    if not sides:
        return ""
    return Counter(sides).most_common(1)[0][0]


def plant_info(round_row: pd.Series, rbomb: pd.DataFrame) -> dict[str, Any]:
    result = {
        "has_plant": False,
        "plant_tick": None,
        "plant_event": "",
        "bombsite": safe_str(round_row.get("bomb_site") or round_row.get("bombsite")),
    }

    if not rbomb.empty:
        event_col = first_col(rbomb, ["event", "bomb_event", "type"])
        tick_col = first_col(rbomb, ["tick", "start_tick"])
        site_col = first_col(rbomb, ["bombsite", "bomb_site", "site"])

        if event_col and tick_col:
            plant_rows = []
            for _, row in rbomb.iterrows():
                ev = safe_str(row.get(event_col)).lower()
                if "plant" in ev:
                    plant_rows.append(row)

            if plant_rows:
                chosen = sorted(plant_rows, key=lambda r: safe_int(r.get(tick_col), 10**18) or 10**18)[0]
                result["has_plant"] = True
                result["plant_tick"] = safe_int(chosen.get(tick_col))
                result["plant_event"] = safe_str(chosen.get(event_col))
                if site_col:
                    result["bombsite"] = safe_str(chosen.get(site_col)) or result["bombsite"]

    if not result["has_plant"]:
        bp = safe_int(round_row.get("bomb_plant"))
        if bp is not None and bp > 0:
            result["has_plant"] = True
            result["plant_tick"] = bp
            result["plant_event"] = "rounds.bomb_plant"

    return result


def damage_by_player(rdamages: pd.DataFrame, player: str, tick_from: int | None = None) -> float:
    if rdamages.empty:
        return 0.0

    dmg_col = first_col(rdamages, ["dmg_health_real", "dmg_health"])
    if not dmg_col:
        return 0.0

    d = rdamages
    if tick_from is not None and "tick" in d.columns:
        d = d[d["tick"] >= tick_from]

    total = 0.0
    p = norm(player)
    for _, row in d.iterrows():
        if norm(row.get("attacker_name")) == p:
            total += safe_float(row.get(dmg_col))
    return round(total, 1)


def damage_taken_by_player(rdamages: pd.DataFrame, player: str) -> float:
    if rdamages.empty:
        return 0.0

    dmg_col = first_col(rdamages, ["dmg_health_real", "dmg_health"])
    if not dmg_col:
        return 0.0

    total = 0.0
    p = norm(player)
    for _, row in rdamages.iterrows():
        if norm(row.get("victim_name")) == p:
            total += safe_float(row.get(dmg_col))
    return round(total, 1)


def kill_summary(row: pd.Series) -> dict[str, Any]:
    return {
        "tick": safe_int(row.get("tick")),
        "attacker": safe_str(row.get("attacker_name")),
        "victim": safe_str(row.get("victim_name")),
        "weapon": safe_str(row.get("weapon")),
        "headshot": bool(row.get("headshot")) if "headshot" in row.index else False,
        "attacker_side": safe_str(row.get("attacker_side")),
        "victim_side": safe_str(row.get("victim_side")),
        "attacker_steamid": safe_str(row.get("attacker_steamid")),
        "victim_steamid": safe_str(row.get("victim_steamid")),
    }


def find_trade_after_player_death(death: dict[str, Any], rkills: pd.DataFrame, player_side: str) -> dict[str, Any] | None:
    death_tick = death.get("tick")
    killer_name = norm(death.get("attacker"))
    killer_steamid = safe_str(death.get("attacker_steamid"))
    killer_side = safe_str(death.get("attacker_side"))

    if death_tick is None:
        return None

    for _, row in rkills.iterrows():
        k = kill_summary(row)
        ktick = k.get("tick")
        if ktick is None:
            continue
        if not (death_tick < ktick <= death_tick + TRADE_WINDOW_TICKS):
            continue

        attacker_side = safe_str(k.get("attacker_side"))
        victim_side = safe_str(k.get("victim_side"))
        victim_name = norm(k.get("victim"))
        victim_steamid = safe_str(k.get("victim_steamid"))

        same_team_trade = player_side and attacker_side == player_side and victim_side == killer_side
        exact_killer_trade = (killer_steamid and victim_steamid == killer_steamid) or (killer_name and victim_name == killer_name)

        if same_team_trade or exact_killer_trade:
            return {
                "trade_tick": ktick,
                "trade_by": k.get("attacker"),
                "traded_player": k.get("victim"),
                "delay_ticks": ktick - death_tick,
            }

    return None


def find_enemy_trade_after_player_kill(player_kill: dict[str, Any], player_death: dict[str, Any] | None) -> dict[str, Any] | None:
    if not player_death:
        return None

    kill_tick = player_kill.get("tick")
    death_tick = player_death.get("tick")

    if kill_tick is None or death_tick is None:
        return None

    if kill_tick < death_tick <= kill_tick + TRADE_WINDOW_TICKS:
        return {
            "death_tick": death_tick,
            "death_by": player_death.get("attacker"),
            "delay_ticks": death_tick - kill_tick,
        }

    return None


def phase_for_tick(tick: int | None, plant_tick: int | None) -> str:
    if tick is None:
        return "unknown"
    if plant_tick is None:
        return "nonplant"
    if tick < plant_tick:
        return "preplant"
    return "postplant"


def analyze_round(round_row: pd.Series, player: str, kills: pd.DataFrame, damages: pd.DataFrame, bomb: pd.DataFrame) -> dict[str, Any]:
    round_num = safe_int(round_row.get("round_num"), -1) or -1

    rkills = filter_round(kills, round_num)
    rdamages = filter_round(damages, round_num)
    rbomb = filter_round(bomb, round_num)

    if not rkills.empty and "tick" in rkills.columns:
        rkills = rkills.sort_values("tick")

    p = norm(player)
    pi = plant_info(round_row, rbomb)
    plant_tick = pi.get("plant_tick")

    side = infer_player_side(player, rkills, rdamages)
    winner = safe_str(round_row.get("winner"))
    reason = safe_str(round_row.get("reason"))

    player_round_win = None
    if side and winner:
        player_round_win = side.lower() == winner.lower()

    kill_events = [kill_summary(r) for _, r in rkills.iterrows()]

    player_kills = [k for k in kill_events if norm(k.get("attacker")) == p]
    player_deaths = [k for k in kill_events if norm(k.get("victim")) == p]
    player_death = player_deaths[0] if player_deaths else None

    first_kill = kill_events[0] if kill_events else None
    opening_action = "none"
    if first_kill:
        if norm(first_kill.get("attacker")) == p:
            opening_action = "opening_kill"
        elif norm(first_kill.get("victim")) == p:
            opening_action = "opening_death"

    death_phase = phase_for_tick(player_death.get("tick") if player_death else None, plant_tick)

    death_trade = find_trade_after_player_death(player_death, rkills, side) if player_death else None
    death_untraded = bool(player_death and not death_trade)

    enemy_trade_after_player_kill = []
    for pk in player_kills:
        trade = find_enemy_trade_after_player_kill(pk, player_death)
        if trade:
            enemy_trade_after_player_kill.append({
                "player_kill_tick": pk.get("tick"),
                "killed_enemy": pk.get("victim"),
                **trade,
            })

    kills_after_plant = 0
    kills_before_plant = len(player_kills)
    if plant_tick is not None:
        kills_after_plant = sum(1 for k in player_kills if (k.get("tick") is not None and k.get("tick") >= plant_tick))
        kills_before_plant = len(player_kills) - kills_after_plant

    alive_at_plant = False
    if pi.get("has_plant"):
        if not player_death:
            alive_at_plant = True
        elif player_death.get("tick") is not None and plant_tick is not None:
            alive_at_plant = player_death.get("tick") > plant_tick

    dmg_total = damage_by_player(rdamages, player)
    dmg_postplant = damage_by_player(rdamages, player, plant_tick if plant_tick is not None else None)
    dmg_taken = damage_taken_by_player(rdamages, player)

    flags: list[str] = []
    categories: list[str] = []
    notes: list[str] = []

    if opening_action == "opening_death" and death_untraded:
        flags.append("opening_death_untraded")
        categories.append("entry_timing")
        notes.append("отдал первый death раунда без быстрого размена")

    if death_untraded and "opening_death_untraded" not in flags:
        flags.append("death_untraded")
        categories.append("trade_spacing")
        notes.append("смерть без быстрого размена")

    if enemy_trade_after_player_kill:
        flags.append("entry_kill_then_traded")
        categories.append("trade_spacing")
        notes.append("после своего kill был быстро разменян соперником")

    if player_death and death_phase == "postplant" and death_untraded:
        flags.append("postplant_death_untraded")
        categories.append("postplant_retake")
        notes.append("умер после plant без быстрого размена")

    if pi.get("has_plant") and alive_at_plant and player_round_win is False and kills_after_plant == 0 and dmg_postplant <= 0:
        if side.lower() == "ct":
            flags.append("retake_no_impact")
            categories.append("postplant_retake")
            notes.append("был жив на plant, но в проигранном retake не дал post-plant impact")
        elif side.lower() == "t":
            flags.append("postplant_no_impact")
            categories.append("postplant_retake")
            notes.append("был жив на plant, но в проигранном post-plant не дал impact")
        else:
            flags.append("key_event_no_impact")
            categories.append("postplant_retake")
            notes.append("был жив на ключевом событии, но после него не дал impact")

    if player_round_win is False and len(player_kills) == 0 and dmg_total < 30:
        flags.append("low_impact_lost_round")
        categories.append("low_impact")
        notes.append("проигранный раунд с низким личным impact")

    if player_death and death_phase == "preplant" and player_round_win is False:
        flags.append("died_before_plant_lost_round")
        categories.append("entry_timing")
        notes.append("умер до plant в проигранном раунде")

    if not flags and player_round_win is True and (len(player_kills) > 0 or dmg_total >= 50):
        flags.append("positive_impact_round")
        categories.append("positive")
        notes.append("выигранный раунд с заметным личным impact")

    categories = list(dict.fromkeys(categories))

    score_table = {
        "opening_death_untraded": 7,
        "postplant_death_untraded": 6,
        "retake_no_impact": 5,
        "postplant_no_impact": 5,
        "death_untraded": 4,
        "entry_kill_then_traded": 4,
        "died_before_plant_lost_round": 3,
        "low_impact_lost_round": 3,
        "key_event_no_impact": 3,
        "positive_impact_round": 1,
    }
    priority_score = sum(score_table.get(f, 1) for f in flags)

    if flags == ["positive_impact_round"]:
        priority_score = 1

    return {
        "round_num": round_num,
        "start_tick": safe_int(round_row.get("start")),
        "freeze_end_tick": safe_int(round_row.get("freeze_end")),
        "end_tick": safe_int(round_row.get("official_end")) or safe_int(round_row.get("end")),
        "winner": winner,
        "reason": reason,
        "player_side": side,
        "player_round_win": player_round_win,
        "has_plant": pi.get("has_plant"),
        "plant_tick": plant_tick,
        "plant_event": pi.get("plant_event"),
        "bombsite": pi.get("bombsite"),
        "opening_action": opening_action,
        "death_phase": death_phase,
        "player_kills": len(player_kills),
        "player_deaths": len(player_deaths),
        "kills_before_plant": kills_before_plant,
        "kills_after_plant": kills_after_plant,
        "damage_total": dmg_total,
        "damage_postplant": dmg_postplant,
        "damage_taken": dmg_taken,
        "alive_at_plant": alive_at_plant,
        "player_death": player_death,
        "death_trade": death_trade,
        "death_untraded": death_untraded,
        "enemy_trade_after_player_kill": enemy_trade_after_player_kill,
        "player_kill_events": player_kills,
        "round_first_kill": first_kill,
        "macro_flags": list(dict.fromkeys(flags)),
        "macro_categories": categories,
        "macro_notes": list(dict.fromkeys(notes)),
        "priority_score": priority_score,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    flags = Counter()
    categories = Counter()
    phases = Counter()
    opening = Counter()
    side_counts = Counter()
    win_loss = Counter()

    for r in rows:
        side_counts[r.get("player_side") or "unknown"] += 1
        phases[r.get("death_phase") or "unknown"] += 1
        opening[r.get("opening_action") or "none"] += 1

        if r.get("player_round_win") is True:
            win_loss["wins"] += 1
        elif r.get("player_round_win") is False:
            win_loss["losses"] += 1
        else:
            win_loss["unknown"] += 1

        for f in r.get("macro_flags", []):
            flags[f] += 1
        for c in r.get("macro_categories", []):
            categories[c] += 1

    problem_flags = {k: v for k, v in flags.items() if k != "positive_impact_round"}
    main_flag = Counter(problem_flags).most_common(1)[0][0] if problem_flags else ""

    problem_categories = {k: v for k, v in categories.items() if k != "positive"}
    main_category = Counter(problem_categories).most_common(1)[0][0] if problem_categories else ""

    top = [
        r for r in sorted(rows, key=lambda x: (-x.get("priority_score", 0), x.get("round_num", 999)))
        if r.get("priority_score", 0) > 0 and r.get("macro_flags") != ["positive_impact_round"]
    ]

    return {
        "version": VERSION,
        "rounds_total": len(rows),
        "plant_rounds": sum(1 for r in rows if r.get("has_plant")),
        "player_side_counts": dict(side_counts),
        "win_loss": dict(win_loss),
        "death_phase_counts": dict(phases),
        "opening_action_counts": dict(opening),
        "macro_flag_counts": dict(flags),
        "macro_category_counts": dict(categories),
        "main_macro_flag": main_flag,
        "main_macro_category": main_category,
        "top_priority_rounds": [
            {
                "round_num": r.get("round_num"),
                "priority_score": r.get("priority_score"),
                "flags": r.get("macro_flags"),
                "categories": r.get("macro_categories"),
                "notes": r.get("macro_notes"),
                "opening_action": r.get("opening_action"),
                "death_phase": r.get("death_phase"),
                "kd_damage": f"{r.get('player_kills')}/{r.get('player_deaths')}/{r.get('damage_total')}",
            }
            for r in top[:12]
        ],
    }


def render_html(payload: dict[str, Any], out_path: Path) -> None:
    s = payload["summary"]
    rows = payload["rounds"]

    def table_counts(d: dict[str, Any]) -> str:
        out = ""
        for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])):
            out += f"<tr><td><code>{html.escape(str(k))}</code></td><td>{v}</td></tr>\n"
        return out

    top_rows = ""
    for r in s.get("top_priority_rounds", []):
        top_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(str(r.get('opening_action')))}</td>"
            f"<td>{html.escape(str(r.get('death_phase')))}</td>"
            f"<td>{html.escape(', '.join(r.get('categories') or []))}</td>"
            f"<td>{html.escape(', '.join(r.get('flags') or []))}</td>"
            f"<td>{html.escape('; '.join(r.get('notes') or []))}</td>"
            f"<td>{html.escape(str(r.get('kd_damage')))}</td>"
            "</tr>\n"
        )

    all_rows = ""
    for r in sorted(rows, key=lambda x: x.get("round_num", 999)):
        win = "win" if r.get("player_round_win") is True else "loss" if r.get("player_round_win") is False else "unknown"
        all_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{html.escape(win)}</td>"
            f"<td>{html.escape(str(r.get('player_side') or ''))}</td>"
            f"<td>{html.escape(str(r.get('winner') or ''))}</td>"
            f"<td>{html.escape(str(r.get('opening_action') or ''))}</td>"
            f"<td>{html.escape(str(r.get('death_phase') or ''))}</td>"
            f"<td>{'yes' if r.get('has_plant') else 'no'}</td>"
            f"<td>{html.escape(str(r.get('bombsite') or ''))}</td>"
            f"<td>{r.get('player_kills')}/{r.get('player_deaths')}/{r.get('damage_total')}</td>"
            f"<td>{r.get('damage_postplant')}</td>"
            f"<td>{html.escape(', '.join(r.get('macro_categories') or []))}</td>"
            f"<td>{html.escape(', '.join(r.get('macro_flags') or []))}</td>"
            f"<td>{html.escape('; '.join(r.get('macro_notes') or []))}</td>"
            "</tr>\n"
        )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Round Macro Analyzer v0.2</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif;
    background: #101114;
    color: #e9edf1;
    margin: 24px;
}}
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
    font-size: 26px;
    font-weight: 700;
    margin-top: 5px;
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
code {{ color: #d7e7ff; }}
</style>
</head>
<body>
<h1>Round Macro Analyzer v0.2</h1>
<div class="muted">Match: <code>{html.escape(payload["match_id"])}</code> · Player: <code>{html.escape(payload["player"])}</code></div>

<div class="grid">
    <div class="card"><div class="muted">Rounds</div><div class="value">{s.get("rounds_total")}</div></div>
    <div class="card"><div class="muted">Plant rounds</div><div class="value">{s.get("plant_rounds")}</div></div>
    <div class="card"><div class="muted">Win / loss</div><div class="value">{s.get("win_loss", {}).get("wins", 0)} / {s.get("win_loss", {}).get("losses", 0)}</div></div>
    <div class="card"><div class="muted">Main macro category</div><div class="value" style="font-size:18px">{html.escape(str(s.get("main_macro_category") or "not enough signal"))}</div></div>
    <div class="card"><div class="muted">Main macro flag</div><div class="value" style="font-size:18px">{html.escape(str(s.get("main_macro_flag") or "not enough signal"))}</div></div>
</div>

<h2>Macro categories</h2>
<table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>{table_counts(s.get("macro_category_counts", {}))}</tbody></table>

<h2>Macro flags</h2>
<table><thead><tr><th>Flag</th><th>Count</th></tr></thead><tbody>{table_counts(s.get("macro_flag_counts", {}))}</tbody></table>

<h2>Opening actions</h2>
<table><thead><tr><th>Opening action</th><th>Count</th></tr></thead><tbody>{table_counts(s.get("opening_action_counts", {}))}</tbody></table>

<h2>Death phases</h2>
<table><thead><tr><th>Death phase</th><th>Count</th></tr></thead><tbody>{table_counts(s.get("death_phase_counts", {}))}</tbody></table>

<h2>Top priority macro rounds</h2>
<p class="muted">v0.2 — всё ещё auto-layer. Он не заменяет просмотр демки, но уже лучше отделяет entry/trade/post-plant/low-impact паттерны.</p>
<table>
<thead><tr><th>Round</th><th>Priority</th><th>Opening</th><th>Death phase</th><th>Categories</th><th>Flags</th><th>Notes</th><th>K/D/Dmg</th></tr></thead>
<tbody>{top_rows}</tbody>
</table>

<h2>All rounds</h2>
<table>
<thead><tr><th>Round</th><th>Result</th><th>Side</th><th>Winner</th><th>Opening</th><th>Death phase</th><th>Plant</th><th>Site</th><th>K/D/Dmg</th><th>Post-plant dmg</th><th>Categories</th><th>Flags</th><th>Notes</th></tr></thead>
<tbody>{all_rows}</tbody>
</table>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def write_manual_queue(payload: dict[str, Any], csv_path: Path) -> None:
    if csv_path.exists():
        print(f"[OK] Manual queue already exists, not overwriting: {csv_path}")
        return

    out = []
    for r in sorted(payload["rounds"], key=lambda x: (-x.get("priority_score", 0), x.get("round_num", 999))):
        if r.get("priority_score", 0) <= 0:
            continue
        if r.get("macro_flags") == ["positive_impact_round"]:
            continue

        out.append({
            "round_num": r.get("round_num"),
            "priority_score": r.get("priority_score"),
            "auto_categories": ",".join(r.get("macro_categories") or []),
            "auto_flags": ",".join(r.get("macro_flags") or []),
            "auto_notes": "; ".join(r.get("macro_notes") or []),
            "opening_action": r.get("opening_action"),
            "death_phase": r.get("death_phase"),
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

    pd.DataFrame(out).to_csv(csv_path, index=False, encoding="utf-8-sig")
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

    print("=== Round Macro Analyzer v0.2 ===")
    print(f"Match ID: {args.match_id}")
    print(f"Player: {args.player}")
    for k, v in paths.items():
        print(f"  {k}: {v if v else 'MISSING'}")

    rounds = read_parquet(paths["rounds"])
    bomb = read_parquet(paths["bomb"])
    kills = read_parquet(paths["kills"])
    damages = read_parquet(paths["damages"])

    if rounds.empty:
        raise SystemExit("rounds.parquet missing or empty")

    if "round_num" not in rounds.columns:
        rc = round_col(rounds)
        if not rc:
            raise SystemExit("No round number column in rounds table")
        rounds = rounds.rename(columns={rc: "round_num"})

    analyzed = []
    for _, row in rounds.sort_values("round_num").iterrows():
        analyzed.append(analyze_round(row, args.player, kills, damages, bomb))

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
        "summary": summarize(analyzed),
        "rounds": analyzed,
    }

    reports_dir = data_root / "reports" / args.match_id
    reviews_dir = data_root / "reviews" / args.match_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    json_path = reports_dir / f"round_macro_{args.player}_v0_2.json"
    html_path = reports_dir / f"round_macro_{args.player}_v0_2.html"
    csv_path = reviews_dir / f"macro_review_{args.player}_v0_2.csv"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(payload, html_path)
    write_manual_queue(payload, csv_path)

    print("")
    print("=== ROUND MACRO v0.2 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"Manual queue: {csv_path}")
    print("")
    print("Summary:")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
