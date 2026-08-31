from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


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
    if isinstance(value, list):
        value = ", ".join(str(x) for x in value)
    return html.escape("" if value is None else str(value))


def load_settings() -> dict[str, Any]:
    return read_json(Path("config/project_settings.json"))


def find_primary_player(players: list[dict[str, Any]], explicit: str | None) -> str:
    if explicit:
        return explicit

    settings = load_settings()
    aliases = [str(x).lower() for x in settings.get("primary_player_names", [])]

    by_lower = {
        str(p.get("name", "")).lower(): str(p.get("name"))
        for p in players
        if p.get("name")
    }

    for alias in aliases:
        if alias in by_lower:
            return by_lower[alias]

    if players:
        return str(players[0].get("name"))

    return "unknown"


def find_latest_report_dir(player: str | None) -> Path:
    if player:
        progress_path = Path("data/progress") / f"progress_{player}.json"
        data = read_json(progress_path)
        matches = data.get("matches", [])
        if matches:
            latest_demo = matches[-1].get("demo_name")
            if latest_demo:
                candidate = Path("data/reports") / str(latest_demo)
                if candidate.exists():
                    return candidate

    reports_root = Path("data/reports")
    dirs = [p for p in reports_root.iterdir() if p.is_dir()] if reports_root.exists() else []
    if not dirs:
        raise SystemExit("No report dirs found in data/reports")

    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0]


def load_primary_progress(player: str) -> dict[str, Any]:
    v2_html = Path("data/progress") / f"progress_{player}_v0_2.html"
    progress_json = Path("data/progress") / f"progress_{player}.json"
    return {
        "v2_html": v2_html,
        "json": progress_json,
        "data": read_json(progress_json),
    }


def build_metric_delta(first: dict[str, Any], latest: dict[str, Any], key: str, lower_is_better: bool, threshold: float) -> dict[str, Any]:
    first_v = n(first.get(key))
    latest_v = n(latest.get(key))
    delta = latest_v - first_v

    if abs(delta) < threshold:
        verdict = "без значимого изменения"
        tone = "neutral"
    else:
        improved = delta < 0 if lower_is_better else delta > 0
        verdict = "улучшение" if improved else "ухудшение"
        tone = "good" if improved else "bad"

    return {
        "first": first_v,
        "latest": latest_v,
        "delta": delta,
        "verdict": verdict,
        "tone": tone,
    }


def build_progress_summary(progress_data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matches = progress_data.get("matches", [])

    if not matches:
        return [], []

    first = matches[0]
    latest = matches[-1]

    specs = [
        ("Strict score", "strict_contact_score", False, 1.0, ""),
        ("ADR", "adr", False, 5.0, ""),
        ("Lost%", "strict_lost_rate", True, 2.0, "%"),
        ("No response%", "strict_no_response_rate", True, 2.0, "%"),
        ("Delayed%", "strict_delayed_rate", True, 3.0, "%"),
        ("Moving first%", "strict_moving_rate", True, 3.0, "%"),
        ("Bad CS", "bad_counter_strafe_candidates", True, 1.0, ""),
    ]

    rows = []
    for label, key, lower, threshold, unit in specs:
        item = build_metric_delta(first, latest, key, lower, threshold)
        item.update({"label": label, "unit": unit})
        rows.append(item)

    insights = []

    adr = build_metric_delta(first, latest, "adr", False, 5.0)
    moving = build_metric_delta(first, latest, "strict_moving_rate", True, 3.0)
    badcs = build_metric_delta(first, latest, "bad_counter_strafe_candidates", True, 1.0)
    delayed = build_metric_delta(first, latest, "strict_delayed_rate", True, 3.0)
    score = build_metric_delta(first, latest, "strict_contact_score", False, 1.0)

    if adr["tone"] == "good":
        insights.append({
            "title": "Impact вырос",
            "text": f"ADR: {fmt(adr['first'])} → {fmt(adr['latest'])}. Во второй демке пользы по урону стало заметно больше.",
            "tone": "good",
        })

    if moving["tone"] == "good":
        insights.append({
            "title": "Первый выстрел на скорости улучшился",
            "text": f"Moving first%: {fmt(moving['first'])}% → {fmt(moving['latest'])}%. Это главный механический прогресс.",
            "tone": "good",
        })

    if badcs["tone"] == "good":
        insights.append({
            "title": "Counter-strafe стал чище",
            "text": f"Bad CS: {fmt(badcs['first'])} → {fmt(badcs['latest'])}. Это подтверждает улучшение дисциплины первого выстрела.",
            "tone": "good",
        })

    if delayed["tone"] == "neutral" and n(latest.get("strict_delayed_rate")) >= 55:
        insights.append({
            "title": "Поздний первый выстрел всё ещё проблема",
            "text": f"Delayed% остаётся высоким: {fmt(latest.get('strict_delayed_rate'))}%. Следующий детальный разбор нужно строить вокруг delay-moments.",
            "tone": "bad",
        })

    if score["tone"] == "neutral":
        insights.append({
            "title": "Strict score почти не изменился",
            "text": "Рост impact и улучшение moving first не дали сильного роста strict score. Значит часть проблем осталась в реакции, выборе контактов или no response.",
            "tone": "neutral",
        })

    return rows, insights


def html_table_rows_player_moments(moments: list[dict[str, Any]]) -> str:
    if not moments:
        return '<tr><td colspan="12">Нет моментов.</td></tr>'

    rows = []
    for m in moments[:18]:
        rows.append(f"""
        <tr>
            <td>{esc(m.get('priority_score_v3'))}</td>
            <td>R{esc(m.get('round_num'))}</td>
            <td>{esc(m.get('contact_start_tick'))}</td>
            <td>{esc(m.get('target_name'))}</td>
            <td>{esc(m.get('outcome'))}</td>
            <td>{esc(m.get('first_shooter'))}</td>
            <td>{esc(fmt(m.get('start_distance')))}</td>
            <td>{esc(fmt(m.get('min_error'), 2))}</td>
            <td>{esc(fmt(m.get('viewer_shot_delay_ticks')))}</td>
            <td>{esc(fmt(m.get('viewer_first_shot_speed')))}</td>
            <td>{esc(fmt(m.get('viewer_first_shot_error_min_deg'), 2))}</td>
            <td>{esc(m.get('player_note'))}</td>
        </tr>
        """)
    return "\n".join(rows)


def make_dashboard(report_dir: Path, player_name: str, out_path: Path) -> None:
    focus = read_json(report_dir / "player_focus_v0_3.json")
    contact = read_json(report_dir / "contact_visibility_v0_3_strict.json")
    progress = load_primary_progress(player_name)

    players = focus.get("players", [])
    player = None
    for p in players:
        if str(p.get("name")) == player_name:
            player = p
            break
    player = player or (players[0] if players else {})

    basic = player.get("basic", {})
    mechanics = player.get("mechanics", {})
    duel = player.get("duel", {})
    strict = player.get("contact", {})
    issues = player.get("top_issues", player.get("issues", []))
    training = player.get("training_plan", [])
    moments = player.get("moments", [])

    progress_rows, progress_insights = build_progress_summary(progress["data"])

    contact_summary = contact.get("summary", {})

    report_links = [
        ("Player Focus", report_dir / "player_focus_v0_3.html"),
        ("Progress v0.2", progress["v2_html"]),
        ("Strict Contacts", report_dir / "contact_visibility_v0_3_strict.html"),
        ("Mechanics", report_dir / "mechanics_v0_1.html"),
        ("Duel Model", report_dir / "duel_model_v0_1.html"),
        ("Match Report", report_dir / "report_v1_1.html"),
    ]

    links_html = "\n".join(
        f'<a class="linkcard" href="{esc(str(path.resolve()))}">{esc(title)}</a>'
        for title, path in report_links
        if path.exists()
    )

    issue_cards = "\n".join(
        f"""
        <div class="card issue">
            <div class="pillrow">
                <span class="pill">{esc(issue.get('level'))}</span>
                <span class="pill">severity {esc(issue.get('severity'))}</span>
                <span class="pill">{esc(issue.get('source'))}</span>
            </div>
            <h3>{esc(issue.get('title'))}</h3>
            <p>{esc(issue.get('explanation'))}</p>
            <p><b>Что делать:</b> {esc(issue.get('recommendation'))}</p>
        </div>
        """
        for issue in issues[:5]
    )

    training_html = "\n".join(f"<li>{esc(x)}</li>" for x in training)

    progress_insights_html = "\n".join(
        f"""
        <div class="card insight {esc(item['tone'])}">
            <h3>{esc(item['title'])}</h3>
            <p>{esc(item['text'])}</p>
        </div>
        """
        for item in progress_insights
    )

    progress_rows_html = "\n".join(
        f"""
        <tr>
            <td>{esc(r['label'])}</td>
            <td>{esc(fmt(r['first']))}{esc(r['unit'])}</td>
            <td>{esc(fmt(r['latest']))}{esc(r['unit'])}</td>
            <td>{esc('+' if r['delta'] > 0 else '')}{esc(fmt(r['delta']))}{esc(r['unit'])}</td>
            <td><span class="pill {esc(r['tone'])}">{esc(r['verdict'])}</span></td>
        </tr>
        """
        for r in progress_rows
    )

    player_nav = "\n".join(
        f'<span class="playerchip">#{esc(i + 1)} {esc(p.get("name"))}</span>'
        for i, p in enumerate(players[:10])
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Dashboard v0.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1640px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .tabs {{
        position: sticky;
        top: 0;
        z-index: 10;
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        background: rgba(7,11,16,.92);
        backdrop-filter: blur(8px);
        padding: 14px 0;
        border-bottom: 1px solid #1d2a3c;
    }}
    .tabs a {{
        color: #9fc3ff;
        text-decoration: none;
        background: #121c29;
        border: 1px solid #223043;
        border-radius: 999px;
        padding: 8px 12px;
    }}
    section {{
        margin-top: 38px;
        padding-top: 20px;
        border-top: 1px solid #223043;
    }}
    .grid {{
        display: grid;
        gap: 14px;
    }}
    .metrics {{
        grid-template-columns: repeat(4, minmax(0, 1fr));
        margin: 18px 0 26px;
    }}
    .two {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .three {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .card, .plan {{
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
    .pillrow {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 8px;
    }}
    .pill {{
        display: inline-block;
        color: #9fc3ff;
        background: #16243a;
        border: 1px solid #28466f;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 12px;
    }}
    .pill.good, .insight.good {{ border-color: #2f7047; }}
    .pill.bad, .insight.bad {{ border-color: #7a3a3a; }}
    .pill.neutral, .insight.neutral {{ border-color: #36557e; }}
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
    .linkgrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
    }}
    .linkcard {{
        display: block;
        color: #dceaff;
        text-decoration: none;
        background: #121c29;
        border: 1px solid #223043;
        border-radius: 16px;
        padding: 16px;
    }}
    .playerchip {{
        display: inline-block;
        margin: 0 8px 8px 0;
        color: #9fc3ff;
        background: #121c29;
        border: 1px solid #223043;
        border-radius: 999px;
        padding: 6px 10px;
        font-size: 13px;
    }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Dashboard v0.1</h1>
    <p class="muted">Матч: {esc(report_dir.name)}. Основной игрок: {esc(player_name)}. Один экран для текущего матча, персонального разбора, прогресса и моментов.</p>

    <div class="tabs">
        <a href="#overview">Обзор</a>
        <a href="#player">Игрок</a>
        <a href="#progress">Прогресс</a>
        <a href="#moments">Моменты</a>
        <a href="#reports">Отчёты</a>
    </div>

    <section id="overview">
        <h2>Обзор матча</h2>
        <div class="grid metrics">
            <div class="card"><div class="muted">K/D</div><div class="metric">{esc(fmt(basic.get('kills')))} / {esc(fmt(basic.get('deaths')))}</div></div>
            <div class="card"><div class="muted">ADR</div><div class="metric">{esc(fmt(basic.get('adr')))}</div></div>
            <div class="card"><div class="muted">Strict score</div><div class="metric">{esc(fmt(strict.get('strict_contact_score')))}</div></div>
            <div class="card"><div class="muted">Главная проблема</div><div class="metric" style="font-size:18px">{esc(player.get('main_diagnosis'))}</div></div>

            <div class="card"><div class="muted">Strict contacts</div><div class="metric">{esc(fmt(strict.get('strict_contacts')))}</div></div>
            <div class="card"><div class="muted">Strict contacts all</div><div class="metric">{esc(fmt(contact_summary.get('strict_contacts')))}</div></div>
            <div class="card"><div class="muted">Priority moments</div><div class="metric">{esc(fmt(contact_summary.get('priority_contacts')))}</div></div>
            <div class="card"><div class="muted">Players</div><div class="metric">{esc(fmt(contact_summary.get('players')))}</div></div>
        </div>

        <h3>Игроки в отчёте</h3>
        <div>{player_nav}</div>
    </section>

    <section id="player">
        <h2>Персональный разбор: {esc(player_name)}</h2>
        <div class="grid metrics">
            <div class="card"><div class="muted">Lost%</div><div class="metric">{esc(fmt(strict.get('lost_rate')))}%</div></div>
            <div class="card"><div class="muted">No response%</div><div class="metric">{esc(fmt(strict.get('no_response_rate')))}%</div></div>
            <div class="card"><div class="muted">Delayed%</div><div class="metric">{esc(fmt(strict.get('delayed_rate')))}%</div></div>
            <div class="card"><div class="muted">Moving%</div><div class="metric">{esc(fmt(strict.get('moving_rate')))}%</div></div>

            <div class="card"><div class="muted">Bad CS</div><div class="metric">{esc(fmt(mechanics.get('bad_counter_strafe_candidates')))}</div></div>
            <div class="card"><div class="muted">First moving general</div><div class="metric">{esc(fmt(mechanics.get('first_bullet_moving_percent')))}%</div></div>
            <div class="card"><div class="muted">Duel no shot</div><div class="metric">{esc(fmt(duel.get('died_without_firing')))}</div></div>
            <div class="card"><div class="muted">Duel shot first lost</div><div class="metric">{esc(fmt(duel.get('lost_after_shooting_first')))}</div></div>
        </div>

        <h3>Главные проблемы</h3>
        <div class="grid two">{issue_cards}</div>

        <h3>План тренировки / проверки</h3>
        <div class="plan"><ol>{training_html}</ol></div>
    </section>

    <section id="progress">
        <h2>Прогресс</h2>
        <div class="grid three">{progress_insights_html}</div>

        <table>
            <thead>
                <tr>
                    <th>Метрика</th>
                    <th>Baseline</th>
                    <th>Сейчас</th>
                    <th>Изменение</th>
                    <th>Вердикт</th>
                </tr>
            </thead>
            <tbody>{progress_rows_html}</tbody>
        </table>
    </section>

    <section id="moments">
        <h2>Strict contact моменты для просмотра</h2>
        <table>
            <thead>
                <tr>
                    <th>Priority</th>
                    <th>Round</th>
                    <th>Tick</th>
                    <th>Target</th>
                    <th>Outcome</th>
                    <th>First shooter</th>
                    <th>Distance</th>
                    <th>Min err</th>
                    <th>Delay</th>
                    <th>Speed</th>
                    <th>Shot err</th>
                    <th>Комментарий</th>
                </tr>
            </thead>
            <tbody>{html_table_rows_player_moments(moments)}</tbody>
        </table>
    </section>

    <section id="reports">
        <h2>Ссылки на подробные отчёты</h2>
        <div class="linkgrid">{links_html}</div>
    </section>
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--player", type=str, default=None)
    args = parser.parse_args()

    settings = load_settings()
    fallback_player = None
    aliases = settings.get("primary_player_names", [])
    if aliases:
        fallback_player = str(aliases[0])

    report_dir = args.report_dir or find_latest_report_dir(args.player or fallback_player)

    focus = read_json(report_dir / "player_focus_v0_3.json")
    players = focus.get("players", [])

    player_name = find_primary_player(players, args.player)

    out_path = Path("data/dashboard") / "dashboard_v0_1.html"
    make_dashboard(report_dir, player_name, out_path)

    print("=== CS Demo Coach Dashboard v0.1 ===")
    print(f"Report dir: {report_dir}")
    print(f"Primary player: {player_name}")
    print(f"Dashboard: {out_path}")

    player = None
    for p in players:
        if str(p.get("name")) == player_name:
            player = p
            break

    if player:
        print("")
        print("Dashboard summary:")
        print(f"  K/D: {player.get('basic', {}).get('kills')} / {player.get('basic', {}).get('deaths')}")
        print(f"  ADR: {player.get('basic', {}).get('adr')}")
        print(f"  Strict score: {player.get('contact', {}).get('strict_contact_score')}")
        print(f"  Main diagnosis: {player.get('main_diagnosis')}")

    print("")
    print("Next: open dashboard_v0_1.html")


if __name__ == "__main__":
    main()
