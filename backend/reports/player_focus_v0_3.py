from __future__ import annotations

import argparse
import html
import json
import math
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
        if isinstance(value, pd.DataFrame):
            return [make_json_safe(x) for x in value.to_dict(orient="records")]
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


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


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
    if isinstance(value, list):
        value = ", ".join(str(x) for x in value)
    return html.escape("" if value is None else str(value))


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)
    return make_json_safe(df.to_dict(orient="records"))


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
        cleaned = text.strip("[]").replace("'", "").replace('"', "")
        if "," in cleaned:
            return [x.strip() for x in cleaned.split(",") if x.strip()]
        return [x.strip() for x in cleaned.split() if x.strip()]
    return [x.strip() for x in text.split(",") if x.strip()]


def severity_level(score: float) -> str:
    if score >= 80:
        return "критично"
    if score >= 60:
        return "серьёзно"
    if score >= 35:
        return "средне"
    if score > 0:
        return "лёгкий сигнал"
    return "нет сигнала"


def issue(
    key: str,
    title: str,
    score: float,
    count: int,
    explanation: str,
    recommendation: str,
    source: str,
) -> dict[str, Any]:
    score = round(max(0.0, min(100.0, float(score))), 1)
    return {
        "key": key,
        "title": title,
        "severity": score,
        "level": severity_level(score),
        "count": int(count),
        "source": source,
        "explanation": explanation,
        "recommendation": recommendation,
    }


def by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(x.get("name")): x for x in items if x.get("name")}


def build_issues(
    basic: dict[str, Any],
    mechanics: dict[str, Any],
    duel: dict[str, Any],
    contact: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    kills = integer(basic.get("kills"))
    deaths = integer(basic.get("deaths"))
    adr = n(basic.get("adr"))
    opening_kills = integer(basic.get("opening_kills"))
    opening_deaths = integer(basic.get("opening_deaths"))

    bad_cs = integer(mechanics.get("bad_counter_strafe_candidates"))
    first_moving_pct_general = n(mechanics.get("first_bullet_moving_percent"))
    moving_pct_general = n(mechanics.get("moving_shot_percent"))

    died_no_shot_duel = integer(duel.get("died_without_firing"))
    shot_first_lost_duel = integer(duel.get("lost_after_shooting_first"))
    duel_deaths = max(integer(duel.get("duel_deaths")), 1)

    strict_contacts = max(integer(contact.get("strict_contacts")), 1)
    strict_lost = integer(contact.get("lost"))
    lost_rate = n(contact.get("lost_rate"))
    strict_no_response = integer(contact.get("strict_no_response"))
    no_response_rate = n(contact.get("no_response_rate"))
    strict_delayed = integer(contact.get("strict_delayed"))
    delayed_rate = n(contact.get("delayed_rate"))
    strict_moving = integer(contact.get("first_shot_moving"))
    moving_rate = n(contact.get("moving_rate"))
    strict_large_err = integer(contact.get("large_first_shot_error"))
    large_err_rate = n(contact.get("large_err_rate"))
    strict_shot_first_lost = integer(contact.get("shot_first_but_lost"))
    strict_score = n(contact.get("strict_contact_score"), 100)

    if strict_lost >= 7 or lost_rate >= 25:
        score = 22 + lost_rate * 0.9 + strict_lost * 1.8
        issues.append(issue(
            "strict_contact_losses",
            "Много проигранных подтверждённых контактов",
            score,
            strict_lost,
            "По строгому contact-слою игрок часто проигрывал подтверждённые контакты: kill, damage или близкая перестрелка. Это надёжнее, чем сырой FOV-слой.",
            "Открыть strict-моменты с outcome target_killed_viewer. Сначала разделить причины: враг выстрелил первым, игрок выстрелил первым и проиграл, первый выстрел на скорости, первый выстрел далеко от цели.",
            "strict_contacts",
        ))

    if strict_no_response >= 3 or no_response_rate >= 12:
        score = 18 + no_response_rate * 1.5 + strict_no_response * 4.0
        issues.append(issue(
            "strict_no_response",
            "Подтверждённые контакты без ответа",
            score,
            strict_no_response,
            "Игрок получал урон или умирал в подтверждённом контакте, но не делал выстрел. Это может быть неготовый угол, смерть в спину, плохой тайминг, флешка или позднее понимание контакта.",
            "Эти моменты смотреть первыми. Для каждого поставить категорию: смерть в спину, неготовый угол, плохой тайминг, под флешкой, выход без pre-aim. Тренировка зависит от категории.",
            "strict_contacts",
        ))

    if strict_shot_first_lost >= 3 or shot_first_lost_duel >= 5:
        rate = strict_shot_first_lost / strict_contacts
        duel_rate = shot_first_lost_duel / duel_deaths
        score = 18 + rate * 45 + duel_rate * 30 + strict_shot_first_lost * 3.0
        issues.append(issue(
            "shot_first_but_lost",
            "Выстреливает первым, но проигрывает часть контактов",
            score,
            max(strict_shot_first_lost, shot_first_lost_duel),
            "Игрок успевал начать стрельбу первым, но контакт всё равно заканчивался плохо. Это обычно проблема не реакции, а качества первого выстрела, остановки, микрокоррекции, спрея или выбранной дуэли.",
            "В моменте смотреть последовательность: был ли игрок остановлен, где был первый выстрел, не начался ли ранний спрей, была ли лишняя микрокоррекция после промаха.",
            "duel + strict_contacts",
        ))

    if strict_delayed >= 8 or delayed_rate >= 45:
        score = 12 + delayed_rate * 0.75 + strict_delayed * 1.1
        issues.append(issue(
            "delayed_first_shot",
            "Поздний первый выстрел в подтверждённых контактах",
            score,
            strict_delayed,
            "Между первым contact-сегментом и первым выстрелом часто проходит много тиков. Часть этого может быть шумом FOV-модели, но на strict-контактах это уже полезный сигнал.",
            "Открыть моменты с большим delay. Проверить: игрок реально видел модель, был ли зажат угол, была ли граната/перезарядка, не был ли контакт через стену. После ручной проверки решим, ужесточать ли фильтр delay.",
            "strict_contacts",
        ))

    if strict_moving >= 8 or moving_rate >= 35:
        score = 14 + moving_rate * 0.9 + strict_moving * 1.0 + bad_cs * 1.2
        issues.append(issue(
            "first_shot_moving",
            "Первый выстрел часто на скорости",
            score,
            strict_moving,
            "В подтверждённых контактах первый выстрел часто делался до нормальной остановки. Если это совпадает с Bad CS, проблема ближе к counter-strafe и дисциплине первого выстрела.",
            "Тренировка: A/D stop-shot. Движение → полная остановка → одиночный выстрел. В DM играть короткими сериями 1–3 пули, не стрелять в момент остановки.",
            "mechanics + strict_contacts",
        ))

    if bad_cs >= 5:
        score = 16 + bad_cs * 4.5 + first_moving_pct_general * 0.35
        issues.append(issue(
            "bad_counter_strafe",
            "Кандидаты на плохой counter-strafe",
            score,
            bad_cs,
            "Перед первыми выстрелами часто была высокая скорость, и в момент выстрела игрок мог ещё не успеть стабилизироваться.",
            "Следить за снижением Bad CS от демки к демке. Если Bad CS падает, но дуэли не улучшаются, следующая проблема — aim placement или выбор дуэлей.",
            "mechanics",
        ))

    if strict_large_err >= 8 or large_err_rate >= 25:
        score = 14 + large_err_rate * 0.85 + strict_large_err * 1.4
        issues.append(issue(
            "large_first_shot_error",
            "Первый выстрел часто далеко от цели",
            score,
            strict_large_err,
            "Rough angle показывает, что в части подтверждённых контактов первый выстрел был заметно далеко от головы/тела цели. Это может быть плохой pre-aim, недоведение флика, перефлик или лишняя коррекция.",
            "Открыть моменты с high shot err. Разделить на две группы: прицел заранее стоял не там или ошибка появилась во время резкого перевода.",
            "strict_contacts",
        ))

    if opening_deaths > opening_kills and opening_deaths >= 2:
        score = 14 + (opening_deaths - opening_kills) * 9 + opening_deaths * 2
        issues.append(issue(
            "weak_openings",
            "Минусовые opening duels",
            score,
            opening_deaths,
            "Игрок чаще проигрывал первые контакты раунда, чем выигрывал. Это сильно влияет на шанс команды выиграть раунд.",
            "Разобрать только opening deaths: был ли пик нужен, была ли флешка, была ли возможность трейда, был ли игрок готов к углу.",
            "basic_stats",
        ))

    if strict_score >= 70 and kills >= deaths and adr >= 80:
        issues.append(issue(
            "positive_context",
            "Контекст: игрок полезен по impact",
            12,
            kills,
            "Несмотря на найденные проблемы, у игрока нормальный impact по базовым метрикам. Ошибки могут быть связаны с агрессивной ролью и большим количеством контактов.",
            "Не оценивать игрока только по ошибкам. Сравнить проблемы с ролью, opening duels и ADR.",
            "context",
        ))

    issues.sort(key=lambda x: x["severity"], reverse=True)
    return issues


def training_plan(issues: list[dict[str, Any]]) -> list[str]:
    keys = [x["key"] for x in issues[:4]]
    plan: list[str] = []

    if "strict_no_response" in keys:
        plan.append("Разобрать все strict no response: отдельно пометить смерть в спину, флешку, неготовый угол, плохой тайминг.")
    if "first_shot_moving" in keys or "bad_counter_strafe" in keys:
        plan.append("10 минут A/D stop-shot: движение → полная остановка → одиночный выстрел. Цель — снижать Bad CS и Moving first.")
    if "shot_first_but_lost" in keys:
        plan.append("DM 10 минут без раннего спрея: первый точный выстрел, затем короткая серия 1–3 пули.")
    if "large_first_shot_error" in keys:
        plan.append("Открыть high shot err моменты и разделить: плохой pre-aim или ошибка флика. Для pre-aim — маршруты по карте; для флика — microflick drill.")
    if "weak_openings" in keys:
        plan.append("Разобрать opening deaths: был ли пик оправдан, была ли флешка, был ли трейд.")

    if not plan:
        plan.append("Явной одной проблемы нет: смотреть priority moments и копить историю по нескольким демкам.")

    return plan[:4]


def contact_note(row: pd.Series, player_name: str) -> str:
    tags = as_list(row.get("strict_tags"))
    outcome = str(row.get("outcome"))
    first = str(row.get("first_shooter"))

    parts = []

    if "strict_no_response" in tags:
        parts.append("получил урон/умер без выстрела")
    if "viewer_shot_first_but_lost" in tags:
        parts.append("выстрелил первым, но проиграл")
    if "target_shot_first_and_won" in tags:
        parts.append("враг выстрелил первым и выиграл")
    if "strict_delayed_first_shot" in tags:
        parts.append("поздний первый выстрел")
    if "viewer_first_shot_moving" in tags:
        parts.append("первый выстрел на скорости")
    if "viewer_large_first_shot_error" in tags:
        parts.append("первый выстрел далеко от цели")
    if outcome == "viewer_killed_target" and not parts:
        parts.append("выигранный подтверждённый контакт")

    if not parts:
        parts.append("подтверждённый контакт для ручной проверки")

    return "; ".join(parts)


def build_player_reports(
    names: list[str],
    basic_stats: list[dict[str, Any]],
    mechanics_stats: list[dict[str, Any]],
    duel_stats: list[dict[str, Any]],
    contact_stats: list[dict[str, Any]],
    strict_contacts: pd.DataFrame,
) -> list[dict[str, Any]]:
    basic_by = by_name(basic_stats)
    mech_by = by_name(mechanics_stats)
    duel_by = by_name(duel_stats)
    contact_by = by_name(contact_stats)

    result = []

    for name in names:
        basic = basic_by.get(name, {})
        mechanics = mech_by.get(name, {})
        duel = duel_by.get(name, {})
        contact = contact_by.get(name, {})

        issues = build_issues(basic, mechanics, duel, contact)
        top_issues = [x for x in issues if x["key"] != "positive_context"][:4]
        plan = training_plan(top_issues)

        player_contacts = pd.DataFrame()
        if not strict_contacts.empty and "viewer_name" in strict_contacts.columns:
            player_contacts = strict_contacts[strict_contacts["viewer_name"].astype(str) == name].copy()

        if not player_contacts.empty:
            if "priority_score_v3" in player_contacts.columns:
                player_contacts = player_contacts.sort_values(
                    ["priority_score_v3", "round_num", "contact_start_tick"],
                    ascending=[False, True, True],
                )
            player_contacts["player_note"] = player_contacts.apply(lambda r: contact_note(r, name), axis=1)

        moment_cols = [
            "priority_score_v3",
            "round_num",
            "contact_start_tick",
            "contact_end_tick",
            "viewer_name",
            "target_name",
            "outcome",
            "first_shooter",
            "duration_ticks",
            "start_distance",
            "min_error",
            "viewer_shot_delay_ticks",
            "viewer_first_shot_speed",
            "viewer_first_shot_error_min_deg",
            "strict_tags",
            "player_note",
        ]
        if not player_contacts.empty:
            moment_cols = [c for c in moment_cols if c in player_contacts.columns]
            moments = records(player_contacts[moment_cols].head(18))
        else:
            moments = []

        if top_issues:
            main_diagnosis = top_issues[0]["title"]
            main_recommendation = top_issues[0]["recommendation"]
        else:
            main_diagnosis = "Явная главная проблема не выделена"
            main_recommendation = "Нужно больше демок или следующий слой анализа: utility, rotations, post-plant."

        result.append({
            "name": name,
            "basic": basic,
            "mechanics": mechanics,
            "duel": duel,
            "contact": contact,
            "issues": issues,
            "top_issues": top_issues,
            "training_plan": plan,
            "main_diagnosis": main_diagnosis,
            "main_recommendation": main_recommendation,
            "moments": moments,
        })

    result.sort(
        key=lambda p: (
            p["top_issues"][0]["severity"] if p["top_issues"] else 0,
            n(p["contact"].get("strict_contacts")),
        ),
        reverse=True,
    )
    return result


def make_html(report: dict[str, Any], out_path: Path) -> None:
    players = report["players"]

    nav = "\n".join(
        f'<a href="#player-{idx}">{esc(p["name"])}</a>'
        for idx, p in enumerate(players)
    )

    sections = []

    for idx, p in enumerate(players):
        basic = p["basic"]
        mechanics = p["mechanics"]
        duel = p["duel"]
        contact = p["contact"]
        issues = p["issues"]
        moments = p["moments"]
        plan = p["training_plan"]

        issue_cards = "\n".join(
            f"""
            <div class="issue">
                <div class="issue-top">
                    <span class="pill {esc(issue.get('level'))}">{esc(issue.get('level'))}</span>
                    <span class="pill">severity {esc(issue.get('severity'))}</span>
                    <span class="pill">count {esc(issue.get('count'))}</span>
                    <span class="pill">{esc(issue.get('source'))}</span>
                </div>
                <h3>{esc(issue.get('title'))}</h3>
                <p>{esc(issue.get('explanation'))}</p>
                <p><b>Что делать:</b> {esc(issue.get('recommendation'))}</p>
            </div>
            """
            for issue in issues[:5]
        )

        plan_items = "\n".join(f"<li>{esc(x)}</li>" for x in plan)

        moment_rows = "\n".join(
            f"""
            <tr>
                <td>{esc(m.get('priority_score_v3'))}</td>
                <td>R{esc(m.get('round_num'))}</td>
                <td>{esc(m.get('contact_start_tick'))}</td>
                <td>{esc(m.get('target_name'))}</td>
                <td>{esc(m.get('outcome'))}</td>
                <td>{esc(m.get('first_shooter'))}</td>
                <td>{esc(fmt(m.get('duration_ticks')))}</td>
                <td>{esc(fmt(m.get('start_distance')))}</td>
                <td>{esc(fmt(m.get('min_error'), 2))}</td>
                <td>{esc(fmt(m.get('viewer_shot_delay_ticks')))}</td>
                <td>{esc(fmt(m.get('viewer_first_shot_speed')))}</td>
                <td>{esc(fmt(m.get('viewer_first_shot_error_min_deg'), 2))}</td>
                <td>{esc(m.get('strict_tags'))}</td>
                <td>{esc(m.get('player_note'))}</td>
            </tr>
            """
            for m in moments
        )

        if not moment_rows:
            moment_rows = '<tr><td colspan="14">Нет strict contact моментов для игрока.</td></tr>'

        sections.append(f"""
        <section class="player" id="player-{idx}">
            <h2>{esc(p["name"])}</h2>
            <p class="muted"><b>Главный диагноз:</b> {esc(p["main_diagnosis"])}</p>
            <p class="muted">{esc(p["main_recommendation"])}</p>

            <div class="grid metrics">
                <div class="card"><div class="muted">K/D</div><div class="metric">{esc(fmt(basic.get('kills')))} / {esc(fmt(basic.get('deaths')))}</div></div>
                <div class="card"><div class="muted">ADR</div><div class="metric">{esc(fmt(basic.get('adr')))}</div></div>
                <div class="card"><div class="muted">Opening</div><div class="metric">{esc(fmt(basic.get('opening_kills')))} / {esc(fmt(basic.get('opening_deaths')))}</div></div>
                <div class="card"><div class="muted">Strict score</div><div class="metric">{esc(fmt(contact.get('strict_contact_score')))}</div></div>

                <div class="card"><div class="muted">Strict contacts</div><div class="metric">{esc(fmt(contact.get('strict_contacts')))}</div></div>
                <div class="card"><div class="muted">Lost%</div><div class="metric">{esc(fmt(contact.get('lost_rate')))}%</div></div>
                <div class="card"><div class="muted">No response%</div><div class="metric">{esc(fmt(contact.get('no_response_rate')))}%</div></div>
                <div class="card"><div class="muted">Moving%</div><div class="metric">{esc(fmt(contact.get('moving_rate')))}%</div></div>

                <div class="card"><div class="muted">Bad CS</div><div class="metric">{esc(fmt(mechanics.get('bad_counter_strafe_candidates')))}</div></div>
                <div class="card"><div class="muted">First moving general</div><div class="metric">{esc(fmt(mechanics.get('first_bullet_moving_percent')))}%</div></div>
                <div class="card"><div class="muted">Duel no shot</div><div class="metric">{esc(fmt(duel.get('died_without_firing')))}</div></div>
                <div class="card"><div class="muted">Duel shot first lost</div><div class="metric">{esc(fmt(duel.get('lost_after_shooting_first')))}</div></div>
            </div>

            <h3>Главные проблемы</h3>
            <div class="issues">{issue_cards}</div>

            <h3>План тренировки / проверки</h3>
            <div class="plan">
                <ol>{plan_items}</ol>
            </div>

            <h3>Strict contact моменты для просмотра</h3>
            <table>
                <thead>
                    <tr>
                        <th>Priority</th>
                        <th>Round</th>
                        <th>Tick</th>
                        <th>Target</th>
                        <th>Outcome</th>
                        <th>First shooter</th>
                        <th>Duration</th>
                        <th>Distance</th>
                        <th>Min err</th>
                        <th>Delay</th>
                        <th>Speed</th>
                        <th>Shot err</th>
                        <th>Tags</th>
                        <th>Комментарий</th>
                    </tr>
                </thead>
                <tbody>{moment_rows}</tbody>
            </table>
        </section>
        """)

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Player Focus v0.3</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1620px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .notice {{
        border: 1px solid #36557e;
        background: #101b2a;
        color: #c7d9f0;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 20px 0;
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
    .player {{
        margin-top: 46px;
        padding-top: 28px;
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
    .card, .issue, .plan {{
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
    .issue-top {{
        display: flex;
        gap: 8px;
        margin-bottom: 8px;
        flex-wrap: wrap;
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
    .pill.критично {{ color: #ffd2d2; background: #3a1616; border-color: #6f2828; }}
    .pill.серьёзно {{ color: #ffe0a6; background: #332611; border-color: #6b4b1e; }}
    .pill.средне {{ color: #cfe2ff; background: #17263d; border-color: #31527f; }}
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
    <h1>CS Demo Coach — Player Focus Report v0.3</h1>
    <p class="muted">Единый персональный отчёт: basic stats + mechanics + kill duels + strict contact visibility.</p>

    <div class="notice">
        Это лучший текущий слой для чтения человеком. Он всё ещё не использует полноценный raycast по карте, но strict contacts уже достаточно чистые для практического разбора.
    </div>

    <h2>Игроки</h2>
    <div class="nav">{nav}</div>

    {''.join(sections)}
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir", type=Path)
    args = parser.parse_args()

    report_dir = args.report_dir
    if not report_dir.exists():
        raise SystemExit(f"Report dir not found: {report_dir}")

    basic_report = read_json(report_dir / "report_v1_1.json")
    mechanics_report = read_json(report_dir / "mechanics_v0_1.json")
    duel_report = read_json(report_dir / "duel_model_v0_1.json")
    contact_report = read_json(report_dir / "contact_visibility_v0_3_strict.json")
    strict_contacts = read_parquet(report_dir / "contacts_v0_3_strict.parquet")

    basic_stats = basic_report.get("player_stats", [])
    mechanics_stats = mechanics_report.get("player_mechanics", [])
    duel_stats = duel_report.get("player_duel_summary", [])
    contact_stats = contact_report.get("player_strict_contact_summary", [])

    names = sorted(
        set(str(x.get("name")) for x in basic_stats if x.get("name"))
        | set(str(x.get("name")) for x in mechanics_stats if x.get("name"))
        | set(str(x.get("name")) for x in duel_stats if x.get("name"))
        | set(str(x.get("name")) for x in contact_stats if x.get("name"))
    )

    players = build_player_reports(
        names=names,
        basic_stats=basic_stats,
        mechanics_stats=mechanics_stats,
        duel_stats=duel_stats,
        contact_stats=contact_stats,
        strict_contacts=strict_contacts,
    )

    report = make_json_safe({
        "summary": {
            "demo_name": report_dir.name,
            "players": len(players),
            "version": "player_focus_v0_3",
            "sources": [
                "report_v1_1.json",
                "mechanics_v0_1.json",
                "duel_model_v0_1.json",
                "contact_visibility_v0_3_strict.json",
                "contacts_v0_3_strict.parquet",
            ],
        },
        "players": players,
    })

    json_path = report_dir / "player_focus_v0_3.json"
    html_path = report_dir / "player_focus_v0_3.html"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html(report, html_path)

    print("=== CS Demo Coach Player Focus v0.3 ===")
    print(f"Report dir: {report_dir}")
    print(f"Players: {len(players)}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")

    print("")
    print("Top diagnoses:")
    for p in players:
        top = p["top_issues"][0] if p["top_issues"] else None
        if top:
            print(f"  - {p['name']}: {top['title']} | severity={top['severity']} | source={top['source']}")
        else:
            print(f"  - {p['name']}: no clear issue")

    print("")
    print("Next: open player_focus_v0_3.html in browser.")


if __name__ == "__main__":
    main()
