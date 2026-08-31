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
    return html.escape("" if value is None else str(value))


def load_player_from_config() -> str:
    path = Path("config/project_settings.json")
    if not path.exists():
        return "Player"

    data = read_json(path)
    names = data.get("primary_player_names", [])
    if names:
        return str(names[0])

    return str(data.get("primary_player_display_name") or "Player")


def direction_text(delta: float, lower_is_better: bool, threshold: float, big_threshold: float) -> tuple[str, str]:
    if abs(delta) < threshold:
        return "neutral", "без значимого изменения"

    improved = delta < 0 if lower_is_better else delta > 0

    if improved:
        if abs(delta) >= big_threshold:
            return "good", "сильное улучшение"
        return "good", "улучшение"

    if abs(delta) >= big_threshold:
        return "bad", "сильное ухудшение"
    return "bad", "ухудшение"


def build_metric_rows(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not matches:
        return []

    first = matches[0]
    latest = matches[-1]
    prev = matches[-2] if len(matches) >= 2 else None

    specs = [
        {
            "label": "Strict score",
            "key": "strict_contact_score",
            "lower_is_better": False,
            "threshold": 1.0,
            "big_threshold": 5.0,
            "unit": "",
        },
        {
            "label": "ADR",
            "key": "adr",
            "lower_is_better": False,
            "threshold": 5.0,
            "big_threshold": 15.0,
            "unit": "",
        },
        {
            "label": "Lost%",
            "key": "strict_lost_rate",
            "lower_is_better": True,
            "threshold": 2.0,
            "big_threshold": 8.0,
            "unit": "%",
        },
        {
            "label": "No response%",
            "key": "strict_no_response_rate",
            "lower_is_better": True,
            "threshold": 2.0,
            "big_threshold": 8.0,
            "unit": "%",
        },
        {
            "label": "Delayed%",
            "key": "strict_delayed_rate",
            "lower_is_better": True,
            "threshold": 3.0,
            "big_threshold": 10.0,
            "unit": "%",
        },
        {
            "label": "Moving first%",
            "key": "strict_moving_rate",
            "lower_is_better": True,
            "threshold": 3.0,
            "big_threshold": 10.0,
            "unit": "%",
        },
        {
            "label": "Bad CS",
            "key": "bad_counter_strafe_candidates",
            "lower_is_better": True,
            "threshold": 1.0,
            "big_threshold": 3.0,
            "unit": "",
        },
    ]

    rows = []

    for spec in specs:
        key = spec["key"]
        first_value = n(first.get(key))
        latest_value = n(latest.get(key))
        total_delta = latest_value - first_value

        prev_delta = None
        if prev is not None:
            prev_delta = latest_value - n(prev.get(key))

        tone, verdict = direction_text(
            total_delta,
            spec["lower_is_better"],
            spec["threshold"],
            spec["big_threshold"],
        )

        rows.append({
            "label": spec["label"],
            "first": first_value,
            "latest": latest_value,
            "total_delta": total_delta,
            "prev_delta": prev_delta,
            "unit": spec["unit"],
            "tone": tone,
            "verdict": verdict,
        })

    return rows


def build_insights(matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    if len(matches) < 2:
        return [{
            "title": "Нужна вторая демка",
            "text": "Сейчас есть только baseline. Тренды появятся после следующего матча.",
            "tone": "neutral",
        }]

    first = matches[0]
    latest = matches[-1]

    insights: list[dict[str, str]] = []

    adr_delta = n(latest.get("adr")) - n(first.get("adr"))
    moving_delta = n(latest.get("strict_moving_rate")) - n(first.get("strict_moving_rate"))
    bad_cs_delta = n(latest.get("bad_counter_strafe_candidates")) - n(first.get("bad_counter_strafe_candidates"))
    delayed_delta = n(latest.get("strict_delayed_rate")) - n(first.get("strict_delayed_rate"))
    no_response_delta = n(latest.get("strict_no_response_rate")) - n(first.get("strict_no_response_rate"))
    score_delta = n(latest.get("strict_contact_score")) - n(first.get("strict_contact_score"))

    if adr_delta >= 10:
        insights.append({
            "title": "Impact заметно вырос",
            "text": f"ADR вырос на {fmt(adr_delta)}. Это сильный позитивный сигнал: во второй демке ты нанёс намного больше пользы.",
            "tone": "good",
        })

    if moving_delta <= -10:
        insights.append({
            "title": "Первый выстрел на скорости стал лучше",
            "text": f"Moving first% снизился на {fmt(abs(moving_delta))} п.п. Это главный механический прогресс между демками.",
            "tone": "good",
        })

    if bad_cs_delta <= -1:
        insights.append({
            "title": "Counter-strafe стал чище",
            "text": f"Bad CS снизился на {fmt(abs(bad_cs_delta))}. Это совпадает с падением Moving first%, значит улучшение похоже не случайное.",
            "tone": "good",
        })

    if abs(score_delta) < 1:
        insights.append({
            "title": "Общий strict score почти не изменился",
            "text": "Несмотря на рост ADR и улучшение Moving first%, общий strict score почти такой же. Значит часть проблем осталась в другом месте: поздний первый выстрел, no response или выбор контактов.",
            "tone": "neutral",
        })

    if abs(delayed_delta) < 3 and n(latest.get("strict_delayed_rate")) >= 55:
        insights.append({
            "title": "Поздний первый выстрел остаётся главной проблемой",
            "text": f"Delayed% почти не изменился и всё ещё высокий: {fmt(latest.get('strict_delayed_rate'))}%. Следующий разбор нужно сфокусировать на моментах с большим delay.",
            "tone": "bad",
        })

    if no_response_delta >= 2:
        insights.append({
            "title": "No response слегка ухудшился",
            "text": f"No response% вырос на {fmt(no_response_delta)} п.п. Это не катастрофа, но нужно проверить смерти/урон без ответа в strict moments.",
            "tone": "bad",
        })

    if not insights:
        insights.append({
            "title": "Тренд пока нейтральный",
            "text": "Существенных изменений мало. Нужны ещё 2–3 демки, чтобы отделить стабильный паттерн от случайности.",
            "tone": "neutral",
        })

    return insights


def make_html(player_name: str, matches: list[dict[str, Any]], out_path: Path) -> None:
    metric_rows = build_metric_rows(matches)
    insights = build_insights(matches)

    latest = matches[-1] if matches else {}

    insight_cards = "\n".join(
        f"""
        <div class="card insight {esc(item['tone'])}">
            <h3>{esc(item['title'])}</h3>
            <p>{esc(item['text'])}</p>
        </div>
        """
        for item in insights
    )

    metric_table_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(row['label'])}</td>
            <td>{esc(fmt(row['first']))}{esc(row['unit'])}</td>
            <td>{esc(fmt(row['latest']))}{esc(row['unit'])}</td>
            <td>{esc('+' if row['total_delta'] > 0 else '')}{esc(fmt(row['total_delta']))}{esc(row['unit'])}</td>
            <td><span class="pill {esc(row['tone'])}">{esc(row['verdict'])}</span></td>
        </tr>
        """
        for row in metric_rows
    )

    history_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(m.get('ingested_at'))}</td>
            <td>{esc(m.get('demo_name'))}</td>
            <td>{esc(fmt(m.get('kills')))} / {esc(fmt(m.get('deaths')))}</td>
            <td>{esc(fmt(m.get('adr')))}</td>
            <td>{esc(fmt(m.get('strict_contact_score')))}</td>
            <td>{esc(fmt(m.get('strict_lost_rate')))}%</td>
            <td>{esc(fmt(m.get('strict_no_response_rate')))}%</td>
            <td>{esc(fmt(m.get('strict_delayed_rate')))}%</td>
            <td>{esc(fmt(m.get('strict_moving_rate')))}%</td>
            <td>{esc(fmt(m.get('bad_counter_strafe_candidates')))}</td>
            <td>{esc(m.get('main_diagnosis'))}</td>
        </tr>
        """
        for m in matches
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Progress v0.2</title>
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
    .insight.good {{ border-color: #2f7047; }}
    .insight.bad {{ border-color: #7a3a3a; }}
    .insight.neutral {{ border-color: #36557e; }}
    .pill {{
        display: inline-block;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 12px;
        border: 1px solid #28466f;
        background: #16243a;
        color: #9fc3ff;
    }}
    .pill.good {{ color: #b8ffd0; background: #14361f; border-color: #2f7047; }}
    .pill.bad {{ color: #ffd2d2; background: #3a1616; border-color: #7a3a3a; }}
    .pill.neutral {{ color: #cfe2ff; background: #17263d; border-color: #31527f; }}
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
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Progress Tracking v0.2</h1>
    <p class="muted">Игрок: {esc(player_name)}. Версия v0.2 отделяет значимые изменения от статистического шума.</p>

    <div class="grid">
        <div class="card"><div class="muted">Матчей</div><div class="metric">{esc(len(matches))}</div></div>
        <div class="card"><div class="muted">Последний K/D</div><div class="metric">{esc(fmt(latest.get('kills')))} / {esc(fmt(latest.get('deaths')))}</div></div>
        <div class="card"><div class="muted">Strict score</div><div class="metric">{esc(fmt(latest.get('strict_contact_score')))}</div></div>
        <div class="card"><div class="muted">Главная проблема</div><div class="metric" style="font-size:18px">{esc(latest.get('main_diagnosis'))}</div></div>
    </div>

    <h2>Главные выводы</h2>
    <div class="grid">{insight_cards}</div>

    <h2>Сравнение baseline → последняя демка</h2>
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
        <tbody>{metric_table_rows}</tbody>
    </table>

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
        <tbody>{history_rows}</tbody>
    </table>
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", type=str, default=None)
    args = parser.parse_args()

    player = args.player or load_player_from_config()

    progress_path = Path("data/progress") / f"progress_{player}.json"
    if not progress_path.exists():
        raise SystemExit(f"Progress JSON not found: {progress_path}")

    data = read_json(progress_path)
    matches = data.get("matches", [])

    if not matches:
        raise SystemExit(f"No matches found in {progress_path}")

    out_path = Path("data/progress") / f"progress_{player}_v0_2.html"
    make_html(player, matches, out_path)

    print("=== CS Demo Coach Progress Tracking v0.2 ===")
    print(f"Player: {player}")
    print(f"Matches: {len(matches)}")
    print(f"HTML: {out_path}")

    print("")
    print("Key comparison:")
    rows = build_metric_rows(matches)
    for row in rows:
        sign = "+" if row["total_delta"] > 0 else ""
        print(f"  {row['label']}: {row['verdict']} | {fmt(row['first'])} -> {fmt(row['latest'])} ({sign}{fmt(row['total_delta'])}{row['unit']})")

    print("")
    print("Insights:")
    for item in build_insights(matches):
        print(f"  - {item['title']}: {item['text']}")


if __name__ == "__main__":
    main()
