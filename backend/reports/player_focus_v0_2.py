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


def num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def integer(value: Any) -> int:
    return int(num(value, 0))


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


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)
    return make_json_safe(df.to_dict(orient="records"))


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
) -> dict[str, Any]:
    score = round(max(0.0, min(100.0, float(score))), 1)
    return {
        "key": key,
        "title": title,
        "severity": score,
        "level": severity_level(score),
        "count": int(count),
        "explanation": explanation,
        "recommendation": recommendation,
    }


def build_issues(basic: dict[str, Any], mech: dict[str, Any], duel: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    kills = integer(basic.get("kills"))
    deaths = integer(basic.get("deaths"))
    adr = num(basic.get("adr"))
    firearm_shots = integer(basic.get("firearm_shots"))
    damage_events_per_100 = num(basic.get("damage_events_per_100_firearm_shots"))
    opening_kills = integer(basic.get("opening_kills"))
    opening_deaths = integer(basic.get("opening_deaths"))

    first_moving_pct = num(mech.get("first_bullet_moving_percent"))
    moving_pct = num(mech.get("moving_shot_percent"))
    bad_cs = integer(mech.get("bad_counter_strafe_candidates"))
    first_moving_count = integer(mech.get("first_bullet_moving"))

    died_no_shot = integer(duel.get("died_without_firing"))
    shot_first_lost = integer(duel.get("lost_after_shooting_first"))
    death_first_moving = integer(duel.get("death_first_shot_moving"))
    death_large_error = integer(duel.get("death_large_first_error"))
    duel_deaths = max(integer(duel.get("duel_deaths")), 1)

    # Более мягкая шкала: не превращаем 5-8 событий сразу в 100.
    if shot_first_lost > 0:
        rate = shot_first_lost / duel_deaths
        score = 18 + shot_first_lost * 5.5 + rate * 26 + death_large_error * 2.0 + death_first_moving * 1.5
        issues.append(issue(
            "shot_first_lost",
            "Проигрывает часть дуэлей после первого выстрела",
            score,
            shot_first_lost,
            "Игрок успевал выстрелить первым, но всё равно проигрывал контакт. Это обычно связано не с реакцией, а с качеством первого выстрела, остановкой, микрокоррекцией, спреем или выбором самой дуэли.",
            "Открыть эти моменты в демке. Сначала смотреть не на kill/death, а на последовательность: был ли игрок остановлен, куда пришёл первый выстрел, была ли лишняя микрокоррекция, начался ли ранний спрей."
        ))

    if died_no_shot > 0:
        rate = died_no_shot / duel_deaths
        score = 14 + died_no_shot * 6.5 + rate * 24
        issues.append(issue(
            "died_without_firing",
            "Смерти без выстрела",
            score,
            died_no_shot,
            "Игрок умер и не сделал выстрел в окне контакта. Это может быть смерть в спину, плохой тайминг, ослепление, неготовый угол, неверная позиция или позднее понимание угрозы.",
            "Разделить эти смерти на категории: в спину, под флешкой, неготовый угол, плохая позиция, слишком поздний выход. Тренировка зависит от категории, поэтому эти моменты лучше смотреть первыми."
        ))

    if death_first_moving > 0:
        rate = death_first_moving / duel_deaths
        score = 16 + death_first_moving * 6 + rate * 26 + bad_cs * 1.5
        issues.append(issue(
            "death_first_moving",
            "Первый выстрел в проигранных дуэлях часто на скорости",
            score,
            death_first_moving,
            "В части проигранных дуэлей первый выстрел был сделан до нормальной остановки. Это сильнее связано с counter-strafe и дисциплиной первого выстрела, чем с чистой скоростью реакции.",
            "Тренировка: A/D stop-shot. Движение → полная остановка → одиночный выстрел. В DM играть короткими сериями 1–3 пули и сознательно не стрелять в момент остановки."
        ))

    if bad_cs >= 3:
        score = 12 + bad_cs * 5.2 + first_moving_pct * 0.35
        issues.append(issue(
            "bad_counter_strafe",
            "Кандидаты на плохой counter-strafe",
            score,
            bad_cs,
            "Перед первыми выстрелами часто была высокая скорость, а в момент выстрела игрок ещё не успевал стабилизироваться.",
            "Следить за снижением Bad CS от демки к демке. Если метрика падает, но K/D не растёт, значит дальше проблема уже в aim placement или выборе дуэлей."
        ))

    if death_large_error > 0:
        rate = death_large_error / duel_deaths
        score = 12 + death_large_error * 5.5 + rate * 22
        issues.append(issue(
            "large_first_shot_error",
            "Первый выстрел в проигранных дуэлях часто далеко от цели",
            score,
            death_large_error,
            "Rough aim error показывает, что в части проигранных дуэлей первый выстрел был заметно не по голове/телу цели. Это может быть плохой pre-aim, резкий перевод, недоведение или лишняя коррекция.",
            "Открыть моменты с большим aim error и разделить: прицел заранее стоял не там или ошибка появилась во время флика. Это разные тренировки."
        ))

    if first_moving_pct >= 35 and first_moving_count >= 8:
        score = 10 + first_moving_pct * 0.9 + first_moving_count * 1.2
        issues.append(issue(
            "general_first_moving",
            "Общая проблема с дисциплиной первого выстрела",
            score,
            first_moving_count,
            "В общей механике много первых выстрелов серий сделано на скорости. Это шире, чем только проигранные дуэли: туда могут попадать спамы, добивания и хаотичные размены.",
            "Не лечить это как единственную проблему. Главная цель — снижать first moving именно в проигранных дуэлях и Bad CS, а не полностью запрещать стрельбу в движении."
        ))

    if moving_pct >= 35:
        score = 8 + moving_pct * 0.9
        issues.append(issue(
            "high_moving_shots",
            "Высокая доля выстрелов в движении",
            score,
            integer(mech.get("moving_shots")),
            "Общая доля moving shots высокая. Сама по себе метрика спорная, потому что включает прострелы, добивания и неважные выстрелы.",
            "Использовать только как фоновый индикатор. Приоритетнее смотреть death_first_moving, bad_cs и shot_first_lost."
        ))

    if damage_events_per_100 > 0 and damage_events_per_100 < 20 and firearm_shots >= 80:
        score = 10 + (20 - damage_events_per_100) * 2.8 + min(firearm_shots / 20, 12)
        issues.append(issue(
            "low_damage_per_shots",
            "Много стрельбы с низкой результативностью",
            score,
            firearm_shots,
            "Игрок много стрелял, но damage-событий на 100 firearm-выстрелов мало. Это не точная accuracy, но полезный индикатор лишних или некачественных выстрелов.",
            "Открыть моменты с длинными сериями и проигранными дуэлями: искать ранний спрей, плохой spray transfer, стрельбу через дым и стрельбу без остановки."
        ))

    if opening_deaths > opening_kills and opening_deaths >= 2:
        score = 15 + (opening_deaths - opening_kills) * 10 + opening_deaths * 3
        issues.append(issue(
            "weak_openings",
            "Минусовые opening duels",
            score,
            opening_deaths,
            "Игрок чаще проигрывал первые контакты раунда, чем выигрывал. Это сильно влияет на шанс команды выиграть раунд.",
            "Разбирать только opening deaths: был ли пик оправдан, была ли флешка, был ли трейд, был ли игрок готов к углу."
        ))

    # Контекстная подсказка, не как ошибка.
    if kills >= deaths and adr >= 80:
        issues.append(issue(
            "positive_context",
            "Контекст: игрок всё равно был полезен по impact",
            18,
            kills,
            "Несмотря на найденные ошибки, базовая статистика не провальная. Значит часть проблем может быть связана с агрессивной ролью или высоким количеством контактов.",
            "Не оценивать игрока только по ошибкам. Сравнивать проблемы с ролью, количеством opening duels и ADR."
        ))

    issues = sorted(issues, key=lambda x: x["severity"], reverse=True)
    return issues


def practical_note_for_player(row: pd.Series, player_name: str) -> str:
    tags = as_list(row.get("tags"))
    victim = str(row.get("victim_name"))
    attacker = str(row.get("attacker_name"))

    if victim == player_name:
        parts = []
        if "victim_died_without_firing" in tags:
            parts.append("смерть без выстрела: проверить, почему игрок не был готов к контакту")
        if row.get("first_shooter") == "victim":
            parts.append("игрок выстрелил первым, но проиграл: смотреть первый выстрел, остановку и спрей")
        if "victim_first_shot_moving" in tags:
            parts.append("первый выстрел был на скорости: возможная проблема counter-strafe")
        if "victim_large_first_shot_error" in tags:
            parts.append("первый выстрел далеко от цели: проверить pre-aim или флик")
        if "victim_blind_death" in tags:
            parts.append("смерть под флешкой: проверить позицию и антифлеш")
        if not parts:
            parts.append("проигранная дуэль: открыть момент и проверить готовность, позицию и первый выстрел")
        return "; ".join(parts)

    if attacker == player_name:
        parts = []
        if "attacker_first_shot_moving" in tags:
            parts.append("выигранная дуэль, но первый выстрел на скорости: рискованный паттерн")
        if "attacker_large_first_shot_error" in tags:
            parts.append("выигранная дуэль с большим rough aim error: возможно, добор спреем или неточная модель цели")
        if "kill_through_smoke" in tags:
            parts.append("килл через дым: проверить, был ли это осознанный спам или случайный фраг")
        if not parts:
            parts.append("выигранная дуэль без явной грубой ошибки; можно использовать как позитивный пример")
        return "; ".join(parts)

    return str(row.get("practical_note", ""))


def build_player_focus(
    names: list[str],
    basic_stats: list[dict[str, Any]],
    mechanics: list[dict[str, Any]],
    duel_summary: list[dict[str, Any]],
    duels: pd.DataFrame,
) -> list[dict[str, Any]]:
    basic_by = {str(x.get("name")): x for x in basic_stats}
    mech_by = {str(x.get("name")): x for x in mechanics}
    duel_by = {str(x.get("name")): x for x in duel_summary}

    result = []

    for name in names:
        basic = basic_by.get(name, {})
        mech = mech_by.get(name, {})
        duel = duel_by.get(name, {})
        issues = build_issues(basic, mech, duel)

        player_duels = pd.DataFrame()
        if not duels.empty:
            player_duels = duels[
                (duels["victim_name"].astype(str) == name)
                | (duels["attacker_name"].astype(str) == name)
            ].copy()

        if not player_duels.empty:
            def priority(row: pd.Series) -> int:
                tags = as_list(row.get("tags"))
                victim = str(row.get("victim_name"))
                attacker = str(row.get("attacker_name"))
                score = 0

                if victim == name:
                    score += 30
                    if "victim_died_without_firing" in tags:
                        score += 35
                    if row.get("first_shooter") == "victim":
                        score += 30
                    if "victim_first_shot_moving" in tags:
                        score += 22
                    if "victim_large_first_shot_error" in tags:
                        score += 22
                    if "victim_blind_death" in tags:
                        score += 12

                if attacker == name:
                    score += 6
                    if "attacker_first_shot_moving" in tags:
                        score += 8
                    if "attacker_large_first_shot_error" in tags:
                        score += 8
                    if "kill_through_smoke" in tags:
                        score += 10

                return score

            player_duels["priority_score"] = player_duels.apply(priority, axis=1)
            player_duels["player_role_in_moment"] = player_duels.apply(
                lambda r: "victim" if str(r.get("victim_name")) == name else "attacker",
                axis=1,
            )
            player_duels["player_practical_note"] = player_duels.apply(
                lambda r: practical_note_for_player(r, name),
                axis=1,
            )
            player_duels = player_duels.sort_values(
                ["priority_score", "player_role_in_moment", "round_num", "kill_tick"],
                ascending=[False, False, True, True],
            )

        moment_cols = [
            "priority_score",
            "round_num",
            "kill_tick",
            "player_role_in_moment",
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
            "player_practical_note",
        ]

        if not player_duels.empty:
            moment_cols = [c for c in moment_cols if c in player_duels.columns]
            moments = records(player_duels[moment_cols].head(18))
        else:
            moments = []

        top_issues = [x for x in issues if x["key"] != "positive_context"][:3]
        if top_issues:
            main_focus = top_issues[0]["recommendation"]
        else:
            main_focus = "По текущим слоям нет одной явной главной проблемы. Нужны следующие слои: visibility/contact, utility, rotation и economy."

        result.append({
            "name": name,
            "basic": basic,
            "mechanics": mech,
            "duel": duel,
            "issues": issues,
            "top_issues": top_issues,
            "main_focus": main_focus,
            "moments": moments,
        })

    result.sort(
        key=lambda p: (
            p["top_issues"][0]["severity"] if p["top_issues"] else 0,
            num(p["duel"].get("duel_deaths")),
        ),
        reverse=True,
    )
    return result


def make_html(report: dict[str, Any], out_path: Path) -> None:
    players = report["players"]

    nav = "\n".join(
        f'<a href="#player-{i}">{esc(p["name"])}</a>'
        for i, p in enumerate(players)
    )

    sections = []

    for i, p in enumerate(players):
        basic = p["basic"]
        mech = p["mechanics"]
        duel = p["duel"]
        issues = p["issues"]
        moments = p["moments"]

        issue_cards = "\n".join(
            f"""
            <div class="issue">
                <div class="issue-top">
                    <span class="pill {esc(issue.get('level'))}">{esc(issue.get('level'))}</span>
                    <span class="pill">severity {esc(issue.get('severity'))}</span>
                    <span class="pill">count {esc(issue.get('count'))}</span>
                </div>
                <h3>{esc(issue.get('title'))}</h3>
                <p>{esc(issue.get('explanation'))}</p>
                <p><b>Что смотреть / тренировать:</b> {esc(issue.get('recommendation'))}</p>
            </div>
            """
            for issue in issues[:5]
        )

        moment_rows = "\n".join(
            f"""
            <tr>
                <td>{esc(m.get('priority_score'))}</td>
                <td>R{esc(m.get('round_num'))}</td>
                <td>{esc(m.get('kill_tick'))}</td>
                <td>{esc(m.get('player_role_in_moment'))}</td>
                <td>{esc(m.get('victim_name'))}</td>
                <td>{esc(m.get('attacker_name'))}</td>
                <td>{esc(m.get('weapon'))}</td>
                <td>{esc(m.get('first_shooter'))}</td>
                <td>{esc(fmt(m.get('victim_first_shot_speed')))}</td>
                <td>{esc(fmt(m.get('victim_first_shot_error_head_deg'), 2))}</td>
                <td>{esc(fmt(m.get('attacker_first_shot_speed')))}</td>
                <td>{esc(fmt(m.get('attacker_first_shot_error_head_deg'), 2))}</td>
                <td>{esc(m.get('tags'))}</td>
                <td>{esc(m.get('player_practical_note'))}</td>
            </tr>
            """
            for m in moments
        )

        if not moment_rows:
            moment_rows = '<tr><td colspan="14">Нет приоритетных моментов.</td></tr>'

        sections.append(f"""
        <section class="player" id="player-{i}">
            <h2>{esc(p["name"])}</h2>
            <p class="muted">{esc(p["main_focus"])}</p>

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

            <h3>Главные проблемы и практический смысл</h3>
            <div class="issues">{issue_cards}</div>

            <h3>Моменты для просмотра</h3>
            <table>
                <thead>
                    <tr>
                        <th>Priority</th>
                        <th>Round</th>
                        <th>Tick</th>
                        <th>Role</th>
                        <th>Умер</th>
                        <th>Убил</th>
                        <th>Оружие</th>
                        <th>First shooter</th>
                        <th>Victim speed</th>
                        <th>Victim aim err</th>
                        <th>Attacker speed</th>
                        <th>Attacker aim err</th>
                        <th>Tags</th>
                        <th>Комментарий именно для игрока</th>
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
<title>CS Demo Coach — Player Focus v0.2</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1540px;
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
        margin-top: 44px;
        padding-top: 26px;
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
    .card, .issue {{
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
    <h1>CS Demo Coach — Player Focus Report v0.2</h1>
    <p class="muted">Откалиброванная персональная версия: мягче severity, меньше повторов, отдельный комментарий для игрока в каждом моменте.</p>

    <div class="notice">
        Это всё ещё не финальный тренерский verdict. Текущая модель основана на kill-based duel model. Следующий крупный слой — Contact Visibility: контакты до убийств, видимость, реакция, первый осознанный выстрел, underflick/overflick-кандидаты.
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
    duels = read_parquet(report_dir / "kill_duels_v0_1.parquet")

    basic_stats = basic_report.get("player_stats", [])
    mechanics = mechanics_report.get("player_mechanics", [])
    duel_summary = duel_report.get("player_duel_summary", [])

    names = sorted(
        set(str(x.get("name")) for x in basic_stats if x.get("name"))
        | set(str(x.get("name")) for x in mechanics if x.get("name"))
        | set(str(x.get("name")) for x in duel_summary if x.get("name"))
    )

    players = build_player_focus(names, basic_stats, mechanics, duel_summary, duels)

    report = make_json_safe({
        "summary": {
            "demo_name": report_dir.name,
            "players": len(players),
            "version": "player_focus_v0_2",
            "notes": [
                "Severity is recalibrated to avoid everything becoming 100.",
                "Moment notes are player-specific: victim and attacker cases are separated.",
            ],
        },
        "players": players,
    })

    json_path = report_dir / "player_focus_v0_2.json"
    html_path = report_dir / "player_focus_v0_2.html"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html(report, html_path)

    print("=== CS Demo Coach Player Focus v0.2 ===")
    print(f"Report dir: {report_dir}")
    print(f"Players: {len(players)}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")

    print("")
    print("Top calibrated issues:")
    for p in players:
        top = p["top_issues"][0] if p["top_issues"] else None
        if top:
            print(f"  - {p['name']}: {top['title']} | severity={top['severity']} | level={top['level']}")
        else:
            print(f"  - {p['name']}: no clear issue")

    print("")
    print("Next: open player_focus_v0_2.html in browser.")


if __name__ == "__main__":
    main()
