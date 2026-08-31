from __future__ import annotations

import argparse
import html
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def integer(value: Any) -> int:
    return int(n(value, 0))


def fmt(value: Any, ndigits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except Exception:
        pass
    if isinstance(value, (int, float, np.integer, np.floating)):
        value = float(value)
        if not math.isfinite(value):
            return "—"
        if abs(value - int(value)) < 0.0001:
            return str(int(value))
        return str(round(value, ndigits))
    return str(value)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(x.get("name")): x for x in items if x.get("name")}


def load_settings(root: Path) -> dict[str, Any]:
    path = root / "config" / "project_settings.json"
    if not path.exists():
        return {
            "primary_player_names": [],
            "primary_player_display_name": "",
        }
    return read_json(path)


def find_primary_name(available_names: list[str], aliases: list[str]) -> str | None:
    lower_to_name = {x.lower(): x for x in available_names}
    for alias in aliases:
        if alias.lower() in lower_to_name:
            return lower_to_name[alias.lower()]
    return None


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    try:
        con.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            demo_name TEXT NOT NULL,
            report_dir TEXT NOT NULL,
            ingested_at TEXT NOT NULL
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS player_match_metrics (
            match_id TEXT NOT NULL,
            player_name TEXT NOT NULL,

            kills REAL,
            deaths REAL,
            kd REAL,
            adr REAL,
            opening_kills REAL,
            opening_deaths REAL,

            firearm_shots REAL,
            moving_shot_percent REAL,
            first_bullet_moving_percent REAL,
            bad_counter_strafe_candidates REAL,

            duel_kills REAL,
            duel_deaths REAL,
            died_without_firing REAL,
            lost_after_shooting_first REAL,
            death_first_shot_moving REAL,
            death_large_first_error REAL,

            strict_contacts REAL,
            strict_won REAL,
            strict_lost REAL,
            strict_lost_rate REAL,
            strict_no_response REAL,
            strict_no_response_rate REAL,
            strict_delayed REAL,
            strict_delayed_rate REAL,
            strict_first_shot_moving REAL,
            strict_moving_rate REAL,
            strict_large_first_shot_error REAL,
            strict_large_err_rate REAL,
            strict_shot_first_but_lost REAL,
            strict_contact_score REAL,

            main_diagnosis TEXT,
            top_issue_key TEXT,
            top_issue_severity REAL,

            raw_json TEXT,

            PRIMARY KEY (match_id, player_name)
        )
        """)

        con.commit()
    finally:
        con.close()


def extract_metrics(report_dir: Path, player_name: str) -> dict[str, Any]:
    basic_report = read_json(report_dir / "report_v1_1.json")
    mechanics_report = read_json(report_dir / "mechanics_v0_1.json")
    duel_report = read_json(report_dir / "duel_model_v0_1.json")
    contact_report = read_json(report_dir / "contact_visibility_v0_3_strict.json")
    focus_report = read_json(report_dir / "player_focus_v0_3.json")

    basic_by = by_name(basic_report.get("player_stats", []))
    mech_by = by_name(mechanics_report.get("player_mechanics", []))
    duel_by = by_name(duel_report.get("player_duel_summary", []))
    contact_by = by_name(contact_report.get("player_strict_contact_summary", []))
    focus_by = by_name(focus_report.get("players", []))

    basic = basic_by.get(player_name, {})
    mech = mech_by.get(player_name, {})
    duel = duel_by.get(player_name, {})
    contact = contact_by.get(player_name, {})
    focus = focus_by.get(player_name, {})

    top_issue = None
    top_issues = focus.get("top_issues", [])
    if isinstance(top_issues, list) and top_issues:
        top_issue = top_issues[0]

    if top_issue is None:
        issues = focus.get("issues", [])
        if isinstance(issues, list) and issues:
            top_issue = issues[0]

    top_issue = top_issue or {}

    metrics = {
        "player_name": player_name,

        "kills": n(basic.get("kills")),
        "deaths": n(basic.get("deaths")),
        "kd": n(basic.get("kd")),
        "adr": n(basic.get("adr")),
        "opening_kills": n(basic.get("opening_kills")),
        "opening_deaths": n(basic.get("opening_deaths")),

        "firearm_shots": n(mech.get("firearm_shots")),
        "moving_shot_percent": n(mech.get("moving_shot_percent")),
        "first_bullet_moving_percent": n(mech.get("first_bullet_moving_percent")),
        "bad_counter_strafe_candidates": n(mech.get("bad_counter_strafe_candidates")),

        "duel_kills": n(duel.get("duel_kills")),
        "duel_deaths": n(duel.get("duel_deaths")),
        "died_without_firing": n(duel.get("died_without_firing")),
        "lost_after_shooting_first": n(duel.get("lost_after_shooting_first")),
        "death_first_shot_moving": n(duel.get("death_first_shot_moving")),
        "death_large_first_error": n(duel.get("death_large_first_error")),

        "strict_contacts": n(contact.get("strict_contacts")),
        "strict_won": n(contact.get("won")),
        "strict_lost": n(contact.get("lost")),
        "strict_lost_rate": n(contact.get("lost_rate")),
        "strict_no_response": n(contact.get("strict_no_response")),
        "strict_no_response_rate": n(contact.get("no_response_rate")),
        "strict_delayed": n(contact.get("strict_delayed")),
        "strict_delayed_rate": n(contact.get("delayed_rate")),
        "strict_first_shot_moving": n(contact.get("first_shot_moving")),
        "strict_moving_rate": n(contact.get("moving_rate")),
        "strict_large_first_shot_error": n(contact.get("large_first_shot_error")),
        "strict_large_err_rate": n(contact.get("large_err_rate")),
        "strict_shot_first_but_lost": n(contact.get("shot_first_but_lost")),
        "strict_contact_score": n(contact.get("strict_contact_score")),

        "main_diagnosis": str(focus.get("main_diagnosis", "")),
        "top_issue_key": str(top_issue.get("key", "")),
        "top_issue_severity": n(top_issue.get("severity")),
    }

    metrics["raw_json"] = json.dumps(make_json_safe({
        "basic": basic,
        "mechanics": mech,
        "duel": duel,
        "contact": contact,
        "focus": focus,
    }), ensure_ascii=False)

    return metrics


def upsert_match(db_path: Path, match_id: str, demo_name: str, report_dir: Path, metrics: dict[str, Any]) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute("""
        INSERT OR REPLACE INTO matches (match_id, demo_name, report_dir, ingested_at)
        VALUES (?, ?, ?, ?)
        """, (
            match_id,
            demo_name,
            str(report_dir),
            datetime.now().isoformat(timespec="seconds"),
        ))

        cols = [
            "match_id",
            "player_name",

            "kills",
            "deaths",
            "kd",
            "adr",
            "opening_kills",
            "opening_deaths",

            "firearm_shots",
            "moving_shot_percent",
            "first_bullet_moving_percent",
            "bad_counter_strafe_candidates",

            "duel_kills",
            "duel_deaths",
            "died_without_firing",
            "lost_after_shooting_first",
            "death_first_shot_moving",
            "death_large_first_error",

            "strict_contacts",
            "strict_won",
            "strict_lost",
            "strict_lost_rate",
            "strict_no_response",
            "strict_no_response_rate",
            "strict_delayed",
            "strict_delayed_rate",
            "strict_first_shot_moving",
            "strict_moving_rate",
            "strict_large_first_shot_error",
            "strict_large_err_rate",
            "strict_shot_first_but_lost",
            "strict_contact_score",

            "main_diagnosis",
            "top_issue_key",
            "top_issue_severity",
            "raw_json",
        ]

        row = {"match_id": match_id, **metrics}
        placeholders = ", ".join(["?"] * len(cols))
        col_sql = ", ".join(cols)

        con.execute(f"""
        INSERT OR REPLACE INTO player_match_metrics ({col_sql})
        VALUES ({placeholders})
        """, [row.get(c) for c in cols])

        con.commit()
    finally:
        con.close()


def load_history(db_path: Path, player_name: str) -> pd.DataFrame:
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("""
        SELECT
            m.ingested_at,
            m.demo_name,
            p.*
        FROM player_match_metrics p
        JOIN matches m ON m.match_id = p.match_id
        WHERE p.player_name = ?
        ORDER BY m.ingested_at ASC
        """, con, params=(player_name,))
        return df
    finally:
        con.close()


def trend_text(history: pd.DataFrame, col: str, label: str, lower_is_better: bool = False) -> str:
    if history.empty or len(history) < 2 or col not in history.columns:
        return f"{label}: baseline, нужна вторая демка для тренда."

    first = n(history.iloc[0][col])
    last = n(history.iloc[-1][col])
    delta = last - first

    if abs(delta) < 0.01:
        return f"{label}: без изменений ({fmt(last)})."

    improved = delta < 0 if lower_is_better else delta > 0
    sign = "+" if delta > 0 else ""

    if improved:
        return f"{label}: улучшение {sign}{fmt(delta)} → сейчас {fmt(last)}."
    return f"{label}: ухудшение {sign}{fmt(delta)} → сейчас {fmt(last)}."


def make_progress_html(history: pd.DataFrame, player_name: str, out_path: Path) -> None:
    latest = history.iloc[-1].to_dict() if not history.empty else {}

    rows = ""
    for _, r in history.iterrows():
        rows += f"""
        <tr>
            <td>{esc(r.get('ingested_at'))}</td>
            <td>{esc(r.get('demo_name'))}</td>
            <td>{esc(fmt(r.get('kills')))} / {esc(fmt(r.get('deaths')))}</td>
            <td>{esc(fmt(r.get('adr')))}</td>
            <td>{esc(fmt(r.get('strict_contact_score')))}</td>
            <td>{esc(fmt(r.get('strict_lost_rate')))}%</td>
            <td>{esc(fmt(r.get('strict_no_response_rate')))}%</td>
            <td>{esc(fmt(r.get('strict_delayed_rate')))}%</td>
            <td>{esc(fmt(r.get('strict_moving_rate')))}%</td>
            <td>{esc(fmt(r.get('bad_counter_strafe_candidates')))}</td>
            <td>{esc(r.get('main_diagnosis'))}</td>
        </tr>
        """

    trends = [
        trend_text(history, "strict_contact_score", "Strict score", lower_is_better=False),
        trend_text(history, "strict_lost_rate", "Lost%", lower_is_better=True),
        trend_text(history, "strict_no_response_rate", "No response%", lower_is_better=True),
        trend_text(history, "strict_delayed_rate", "Delayed%", lower_is_better=True),
        trend_text(history, "strict_moving_rate", "Moving first%", lower_is_better=True),
        trend_text(history, "bad_counter_strafe_candidates", "Bad CS", lower_is_better=True),
        trend_text(history, "adr", "ADR", lower_is_better=False),
    ]

    trend_cards = "\n".join(f"<div class='card'><p>{esc(x)}</p></div>" for x in trends)

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Progress v0.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1500px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
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
    tr:hover td {{ background: #142033; }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Progress Tracking v0.1</h1>
    <p class="muted">История матчей для игрока: {esc(player_name)}. Сейчас это baseline; настоящий тренд появится после второй демки.</p>

    <div class="grid">
        <div class="card"><div class="muted">Матчей</div><div class="metric">{esc(len(history))}</div></div>
        <div class="card"><div class="muted">Последний K/D</div><div class="metric">{esc(fmt(latest.get('kills')))} / {esc(fmt(latest.get('deaths')))}</div></div>
        <div class="card"><div class="muted">Strict score</div><div class="metric">{esc(fmt(latest.get('strict_contact_score')))}</div></div>
        <div class="card"><div class="muted">Главная проблема</div><div class="metric" style="font-size:18px">{esc(latest.get('main_diagnosis'))}</div></div>
    </div>

    <h2>Тренды</h2>
    <div class="grid">{trend_cards}</div>

    <h2>История матчей</h2>
    <table>
        <thead>
            <tr>
                <th>Дата</th>
                <th>Demo</th>
                <th>K/D</th>
                <th>ADR</th>
                <th>Strict score</th>
                <th>Lost%</th>
                <th>No response%</th>
                <th>Delayed%</th>
                <th>Moving%</th>
                <th>Bad CS</th>
                <th>Main diagnosis</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir", type=Path, help="Path to data/reports/<demo_name>")
    parser.add_argument("--match-id", type=str, default=None)
    parser.add_argument("--player", type=str, default=None)
    args = parser.parse_args()

    root = Path(".").resolve()
    report_dir = args.report_dir

    if not report_dir.exists():
        raise SystemExit(f"Report dir not found: {report_dir}")

    settings = load_settings(root)

    focus_report = read_json(report_dir / "player_focus_v0_3.json")
    available_names = [
        str(x.get("name"))
        for x in focus_report.get("players", [])
        if x.get("name")
    ]

    aliases = settings.get("primary_player_names", [])
    player_name = args.player or find_primary_name(available_names, aliases)

    if not player_name:
        raise SystemExit(
            "Primary player not found. Available names: "
            + ", ".join(available_names)
            + ". Set --player or edit config/project_settings.json."
        )

    match_id = args.match_id or report_dir.name
    demo_name = report_dir.name

    db_path = Path("data/progress/progress.sqlite")
    init_db(db_path)

    metrics = extract_metrics(report_dir, player_name)
    upsert_match(db_path, match_id, demo_name, report_dir, metrics)

    history = load_history(db_path, player_name)

    out_html = Path("data/progress") / f"progress_{player_name}.html"
    make_progress_html(history, player_name, out_html)

    out_json = Path("data/progress") / f"progress_{player_name}.json"
    payload = make_json_safe({
        "player_name": player_name,
        "matches": history.to_dict(orient="records"),
    })
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== CS Demo Coach Progress Tracking v0.1 ===")
    print(f"Player: {player_name}")
    print(f"Match ID: {match_id}")
    print(f"DB: {db_path}")
    print(f"Matches in history: {len(history)}")
    print(f"HTML: {out_html}")
    print(f"JSON: {out_json}")

    print("")
    print("Latest metrics:")
    latest = history.iloc[-1].to_dict()
    cols = [
        "kills",
        "deaths",
        "adr",
        "strict_contact_score",
        "strict_lost_rate",
        "strict_no_response_rate",
        "strict_delayed_rate",
        "strict_moving_rate",
        "bad_counter_strafe_candidates",
        "main_diagnosis",
    ]
    for c in cols:
        print(f"  {c}: {latest.get(c)}")

    print("")
    print("Next: open progress HTML.")


if __name__ == "__main__":
    main()
