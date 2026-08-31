from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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



def make_json_safe(value: Any) -> Any:
    """
    Recursively convert numpy/pandas objects to plain JSON-safe Python values.
    """
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

        if isinstance(value, pd.DataFrame):
            return [make_json_safe(row) for row in value.to_dict(orient="records")]

        if isinstance(value, np.integer):
            return int(value)

        if isinstance(value, np.floating):
            value = float(value)
            if math.isfinite(value):
                return value
            return None

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



def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)

    return [
        {str(k): safe_value(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, np.ndarray):
        return [str(x) for x in value.tolist()]

    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value]

    try:
        if pd.isna(value):
            return []
    except Exception:
        pass

    text = str(value).strip()
    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass

        # fallback for numpy-like string: ['a' 'b']
        cleaned = text.strip("[]")
        cleaned = cleaned.replace("'", "").replace('"', "")
        parts = [x.strip() for x in cleaned.replace(",", " ").split() if x.strip()]
        return parts

    return [x.strip() for x in text.split(",") if x.strip()]

def num(value: Any, default: float = 0.0) -> float:
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
        if abs(value - int(value)) < 0.00001:
            return str(int(value))
        return str(round(value, ndigits))

    return str(value)


def esc(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(x) for x in value)
    return html.escape("" if value is None else str(value))


def issue(
    key: str,
    title: str,
    severity: float,
    count: int,
    explanation: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "severity": round(float(severity), 1),
        "count": int(count),
        "explanation": explanation,
        "recommendation": recommendation,
    }


def build_issues(
    basic: dict[str, Any],
    mech: dict[str, Any],
    duel: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    died_no_shot = int(num(duel.get("died_without_firing")))
    shot_first_lost = int(num(duel.get("lost_after_shooting_first")))
    death_first_moving = int(num(duel.get("death_first_shot_moving")))
    death_large_error = int(num(duel.get("death_large_first_error")))

    first_moving_pct = num(mech.get("first_bullet_moving_percent"))
    moving_pct = num(mech.get("moving_shot_percent"))
    bad_cs = int(num(mech.get("bad_counter_strafe_candidates")))
    p90_speed = num(mech.get("p90_shot_speed"))
    damage_events_per_100 = num(basic.get("damage_events_per_100_firearm_shots"))

    opening_kills = int(num(basic.get("opening_kills")))
    opening_deaths = int(num(basic.get("opening_deaths")))

    if shot_first_lost > 0:
        severity = min(100, shot_first_lost * 12 + death_first_moving * 5 + death_large_error * 4)
        issues.append(
            issue(
                "shot_first_lost",
                "Проигрыш дуэлей после первого выстрела",
                severity,
                shot_first_lost,
                "Игрок успевал открыть стрельбу первым, но всё равно проигрывал контакт. Это часто указывает не на реакцию, а на качество первого выстрела, остановку, спрей или выбор дуэли.",
                "Открыть эти моменты в демке. Проверять последовательность: остановка → первый выстрел → микрокоррекция → спрей. Тренировка: deathmatch с запретом на ранний спрей, только первый точный выстрел после остановки.",
            )
        )

    if died_no_shot > 0:
        severity = min(100, died_no_shot * 14)
        issues.append(
            issue(
                "died_without_firing",
                "Смерти без выстрела",
                severity,
                died_no_shot,
                "Игрок умер и не сделал выстрел в окне дуэли. Причина может быть в плохой готовности к контакту, смерти в спину, ослеплении, неправильной позиции или позднем понимании угрозы.",
                "Открыть моменты и разделить их на категории: смерть в спину, неготовый угол, ослепление, плохой тайминг, плохая позиция. Для тренировки — pre-aim маршруты и разбор типовых позиций смерти.",
            )
        )

    if death_first_moving > 0 or first_moving_pct >= 35:
        severity = min(100, death_first_moving * 12 + first_moving_pct * 0.8 + bad_cs * 3)
        issues.append(
            issue(
                "first_bullet_moving",
                "Первый выстрел часто делается на скорости",
                severity,
                max(death_first_moving, int(num(mech.get("first_bullet_moving")))),
                "Первый выстрел на скорости ломает точность. Если это происходит в проигранных дуэлях, проблема ближе к counter-strafe и дисциплине первого выстрела, а не просто к aim.",
                "Тренировка: counter-strafe drill. Движение → полная остановка → пауза 80–120 мс → одиночный выстрел. В DM играть сериями по 1–3 пули, не зажимать сразу.",
            )
        )

    if bad_cs >= 4:
        severity = min(100, bad_cs * 8)
        issues.append(
            issue(
                "bad_counter_strafe",
                "Кандидаты на плохой counter-strafe",
                severity,
                bad_cs,
                "Перед первыми выстрелами часто была высокая скорость, а в момент выстрела игрок ещё не успевал нормально остановиться.",
                "Тренировка: 10 минут перед матчем — A/D stop-shot на ботах. Цель: стрелять только когда модель полностью остановлена. В отчётах смотреть снижение Bad CS.",
            )
        )

    if death_large_error > 0:
        severity = min(100, death_large_error * 10)
        issues.append(
            issue(
                "large_first_shot_error",
                "Первый выстрел в проигранных дуэлях часто далеко от цели",
                severity,
                death_large_error,
                "Rough angle error показывает, что в части проигранных дуэлей первый выстрел был заметно не туда. Это может быть недоведение прицела, резкий перевод, плохой pre-aim или неверная высота прицела.",
                "Открыть моменты с высоким aim error. Сравнить: прицел стоял не на уровне головы заранее или промах появился уже во время флика.",
            )
        )

    if moving_pct >= 32:
        severity = min(100, moving_pct * 1.8)
        issues.append(
            issue(
                "high_moving_shot_rate",
                "Высокая доля выстрелов в движении",
                severity,
                int(num(mech.get("moving_shots"))),
                "Общая доля moving shots высокая. Это не всегда ошибка: сюда могут попадать прострелы, добивания и хаотичные размены. Но если вместе с этим есть плохой counter-strafe, проблема подтверждается.",
                "Не делать вывод только по этой метрике. Использовать её вместе с дуэлями. Цель прогресса — снижать first moving и bad CS, а не любой moving shot.",
            )
        )

    if damage_events_per_100 > 0 and damage_events_per_100 < 20:
        severity = min(100, (20 - damage_events_per_100) * 4)
        issues.append(
            issue(
                "low_damage_per_shots",
                "Много стрельбы с низкой результативностью",
                severity,
                int(num(basic.get("firearm_shots"))),
                "Damage events / 100 shots низкий. Это не точная accuracy, но ранний индикатор, что много выстрелов не приводят к урону.",
                "Проверить, откуда идут лишние выстрелы: спамы, плохие спреи, паническая стрельба, стрельба на движении. Сравнить с priority moments.",
            )
        )

    if opening_deaths > opening_kills and opening_deaths >= 2:
        severity = min(100, opening_deaths * 12)
        issues.append(
            issue(
                "weak_opening_duels",
                "Минусовые opening duels",
                severity,
                opening_deaths,
                "Игрок чаще проигрывал первые контакты раунда, чем выигрывал. Это сильно влияет на шанс команды выиграть раунд.",
                "Разобрать только opening deaths: был ли пик нужным, была ли флешка, был ли трейд, был ли игрок готов к углу.",
            )
        )

    issues.sort(key=lambda x: x["severity"], reverse=True)
    return issues


def build_player_focus(
    player_names: list[str],
    basic_stats: list[dict[str, Any]],
    mechanics: list[dict[str, Any]],
    duel_summary: list[dict[str, Any]],
    duels: pd.DataFrame,
) -> list[dict[str, Any]]:
    basic_by_name = {str(x.get("name")): x for x in basic_stats}
    mech_by_name = {str(x.get("name")): x for x in mechanics}
    duel_by_name = {str(x.get("name")): x for x in duel_summary}

    reports = []

    for name in player_names:
        basic = basic_by_name.get(name, {})
        mech = mech_by_name.get(name, {})
        duel = duel_by_name.get(name, {})

        issues = build_issues(basic, mech, duel)

        player_duels = pd.DataFrame()
        if not duels.empty:
            player_duels = duels[
                (duels.get("victim_name", "").astype(str) == name)
                | (duels.get("attacker_name", "").astype(str) == name)
            ].copy()

        if not player_duels.empty:
            def priority(row: pd.Series) -> int:
                tags = as_list(row.get("tags"))
                score = 0

                if row.get("victim_name") == name:
                    score += 20
                    if "victim_died_without_firing" in tags:
                        score += 40
                    if row.get("first_shooter") == "victim":
                        score += 35
                    if "victim_first_shot_moving" in tags:
                        score += 25
                    if "victim_large_first_shot_error" in tags:
                        score += 25
                    if "victim_blind_death" in tags:
                        score += 15

                if row.get("attacker_name") == name:
                    score += 8
                    if "attacker_first_shot_moving" in tags:
                        score += 12
                    if "attacker_large_first_shot_error" in tags:
                        score += 10
                    if "kill_through_smoke" in tags:
                        score += 10

                return score

            player_duels["priority_score"] = player_duels.apply(priority, axis=1)
            player_duels = player_duels.sort_values(
                ["priority_score", "round_num", "kill_tick"],
                ascending=[False, True, True],
            )

        moment_cols = [
            "priority_score",
            "round_num",
            "kill_tick",
            "victim_name",
            "attacker_name",
            "weapon",
            "first_shooter",
            "victim_shots_in_window",
            "attacker_shots_in_window",
            "victim_first_shot_speed",
            "victim_first_shot_error_head_deg",
            "attacker_first_shot_speed",
            "attacker_first_shot_error_head_deg",
            "tags",
            "practical_note",
        ]

        if not player_duels.empty:
            moment_cols = [c for c in moment_cols if c in player_duels.columns]
            moments = records(player_duels[moment_cols].head(20))
        else:
            moments = []

        top_issue_titles = [x["title"] for x in issues[:3]]

        if issues:
            main_focus = issues[0]["recommendation"]
        else:
            main_focus = "Грубые повторяющиеся проблемы по текущим метрикам не выделились. Нужны следующие слои: visibility, utility, rotation и economy."

        reports.append(
            {
                "name": name,
                "basic": basic,
                "mechanics": mech,
                "duel": duel,
                "issues": issues,
                "top_issue_titles": top_issue_titles,
                "main_focus": main_focus,
                "moments": moments,
            }
        )

    reports.sort(
        key=lambda r: (
            r["issues"][0]["severity"] if r["issues"] else 0,
            num(r["duel"].get("duel_deaths")),
        ),
        reverse=True,
    )

    return reports


def make_html_report(report: dict[str, Any], out_path: Path) -> None:
    players = report.get("players", [])

    nav = "\n".join(
        f'<a href="#player-{i}">{esc(p["name"])}</a>'
        for i, p in enumerate(players)
    )

    player_sections = []

    for i, p in enumerate(players):
        basic = p.get("basic", {})
        mech = p.get("mechanics", {})
        duel = p.get("duel", {})
        issues = p.get("issues", [])
        moments = p.get("moments", [])

        issue_cards = "\n".join(
            f"""
            <div class="issue">
                <div class="issue-top">
                    <span class="pill">severity {esc(issue.get('severity'))}</span>
                    <span class="pill">count {esc(issue.get('count'))}</span>
                </div>
                <h3>{esc(issue.get('title'))}</h3>
                <p>{esc(issue.get('explanation'))}</p>
                <p><b>Что делать:</b> {esc(issue.get('recommendation'))}</p>
            </div>
            """
            for issue in issues[:5]
        )

        if not issue_cards:
            issue_cards = '<div class="issue"><h3>Явных повторяющихся проблем пока не выделено</h3><p>Нужно больше демок или следующие слои анализа.</p></div>'

        moment_rows = "\n".join(
            f"""
            <tr>
                <td>{esc(m.get('priority_score'))}</td>
                <td>R{esc(m.get('round_num'))}</td>
                <td>{esc(m.get('kill_tick'))}</td>
                <td>{esc(m.get('victim_name'))}</td>
                <td>{esc(m.get('attacker_name'))}</td>
                <td>{esc(m.get('weapon'))}</td>
                <td>{esc(m.get('first_shooter'))}</td>
                <td>{esc(fmt(m.get('victim_first_shot_speed')))}</td>
                <td>{esc(fmt(m.get('victim_first_shot_error_head_deg'), 2))}</td>
                <td>{esc(m.get('tags'))}</td>
                <td>{esc(m.get('practical_note'))}</td>
            </tr>
            """
            for m in moments
        )

        if not moment_rows:
            moment_rows = '<tr><td colspan="11">Нет приоритетных моментов для этого игрока.</td></tr>'

        section = f"""
        <section class="player" id="player-{i}">
            <h2>{esc(p.get('name'))}</h2>
            <p class="muted">{esc(p.get('main_focus'))}</p>

            <div class="grid metrics">
                <div class="card"><div class="muted">K/D</div><div class="metric">{esc(fmt(basic.get('kills')))} / {esc(fmt(basic.get('deaths')))}</div></div>
                <div class="card"><div class="muted">ADR</div><div class="metric">{esc(fmt(basic.get('adr')))}</div></div>
                <div class="card"><div class="muted">Opening K/D</div><div class="metric">{esc(fmt(basic.get('opening_kills')))} / {esc(fmt(basic.get('opening_deaths')))}</div></div>
                <div class="card"><div class="muted">First moving</div><div class="metric">{esc(fmt(mech.get('first_bullet_moving_percent')))}%</div></div>
                <div class="card"><div class="muted">Bad CS</div><div class="metric">{esc(fmt(mech.get('bad_counter_strafe_candidates')))}</div></div>
                <div class="card"><div class="muted">Died no shot</div><div class="metric">{esc(fmt(duel.get('died_without_firing')))}</div></div>
                <div class="card"><div class="muted">Shot first lost</div><div class="metric">{esc(fmt(duel.get('lost_after_shooting_first')))}</div></div>
                <div class="card"><div class="muted">Death aim err</div><div class="metric">{esc(fmt(duel.get('death_large_first_error')))}</div></div>
            </div>

            <h3>Главные проблемы</h3>
            <div class="issues">
                {issue_cards}
            </div>

            <h3>Моменты для просмотра</h3>
            <table>
                <thead>
                    <tr>
                        <th>Priority</th>
                        <th>Round</th>
                        <th>Tick</th>
                        <th>Умер</th>
                        <th>Убил</th>
                        <th>Оружие</th>
                        <th>First shooter</th>
                        <th>Victim speed</th>
                        <th>Victim aim err</th>
                        <th>Tags</th>
                        <th>Практический смысл</th>
                    </tr>
                </thead>
                <tbody>{moment_rows}</tbody>
            </table>
        </section>
        """
        player_sections.append(section)

    sections_html = "\n".join(player_sections)

    summary = report.get("summary", {})

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Player Focus v0.1</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1480px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{
        margin: 0 0 12px;
    }}
    .muted {{
        color: #93a4b7;
    }}
    .nav {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 20px 0;
    }}
    .nav a {{
        color: #9fc3ff;
        text-decoration: none;
        background: #121c29;
        border: 1px solid #223043;
        border-radius: 999px;
        padding: 8px 12px;
    }}
    .notice {{
        border: 1px solid #36557e;
        background: #101b2a;
        color: #c7d9f0;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 20px 0;
    }}
    .player {{
        margin-top: 42px;
        padding-top: 24px;
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
    .card {{
        background: linear-gradient(180deg, #121c29, #0f1722);
        border: 1px solid #223043;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,.22);
    }}
    .metric {{
        font-size: 26px;
        font-weight: 800;
    }}
    .issues {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
        margin: 16px 0 28px;
    }}
    .issue {{
        background: #101721;
        border: 1px solid #223043;
        border-radius: 16px;
        padding: 16px;
    }}
    .issue-top {{
        display: flex;
        gap: 8px;
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
    <h1>CS Demo Coach — Player Focus Report v0.1</h1>
    <p class="muted">Персональный отчёт по каждому игроку: базовая статистика, механика, дуэли, главные проблемы и моменты для просмотра.</p>

    <div class="notice">
        Это ещё не финальный тренерский verdict. Отчёт использует kill-based duel model и rough aim error. Следующий слой должен добавить visibility/contact model, чтобы находить контакты не только по убийствам.
    </div>

    <div class="grid metrics">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Игроков</div><div class="metric">{esc(summary.get('players'))}</div></div>
        <div class="card"><div class="muted">Источник</div><div class="metric">v0.1</div></div>
        <div class="card"><div class="muted">Формат</div><div class="metric">персональный</div></div>
    </div>

    <h2>Игроки</h2>
    <div class="nav">{nav}</div>

    {sections_html}
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir", type=Path, help="Path to data/reports/<demo_name>")
    args = parser.parse_args()

    report_dir: Path = args.report_dir
    if not report_dir.exists():
        raise SystemExit(f"Report dir not found: {report_dir}")

    basic_report = read_json(report_dir / "report_v1_1.json")
    mechanics_report = read_json(report_dir / "mechanics_v0_1.json")
    duel_report = read_json(report_dir / "duel_model_v0_1.json")
    duels = read_parquet(report_dir / "kill_duels_v0_1.parquet")

    basic_stats = basic_report.get("player_stats", [])
    mechanics = mechanics_report.get("player_mechanics", [])
    duel_summary = duel_report.get("player_duel_summary", [])

    names = sorted(
        set(str(x.get("name")) for x in basic_stats if x.get("name"))
        | set(str(x.get("name")) for x in mechanics if x.get("name"))
        | set(str(x.get("name")) for x in duel_summary if x.get("name"))
    )

    if not names:
        raise SystemExit("No player names found in reports.")

    players = build_player_focus(
        player_names=names,
        basic_stats=basic_stats,
        mechanics=mechanics,
        duel_summary=duel_summary,
        duels=duels,
    )

    report = {
        "summary": {
            "demo_name": report_dir.name,
            "players": len(players),
            "sources": [
                "report_v1_1.json",
                "mechanics_v0_1.json",
                "duel_model_v0_1.json",
                "kill_duels_v0_1.parquet",
            ],
            "notes": [
                "Player Focus v0.1 combines basic stats, mechanics and kill-based duel model.",
                "Scores are directional and not final calibration.",
            ],
        },
        "players": players,
    }

    json_path = report_dir / "player_focus_v0_1.json"
    html_path = report_dir / "player_focus_v0_1.html"

    report = make_json_safe(report)

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html_report(report, html_path)

    print("=== CS Demo Coach Player Focus v0.1 ===")
    print(f"Report dir: {report_dir}")
    print(f"Players: {len(players)}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")

    print("")
    print("Top player issues:")
    for p in players:
        issues = p.get("issues", [])
        top = issues[0]["title"] if issues else "no clear issue"
        sev = issues[0]["severity"] if issues else 0
        print(f"  - {p['name']}: {top} | severity={sev}")

    print("")
    print("Next: open player_focus_v0_1.html in browser.")


if __name__ == "__main__":
    main()
