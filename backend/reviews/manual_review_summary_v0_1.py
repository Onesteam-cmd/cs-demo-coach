from __future__ import annotations

import argparse
import csv
import html
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def split_categories(value: str) -> list[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part * 100.0 / total, 1)


def counter_to_dict(counter: Counter) -> dict[str, int]:
    return {str(k): int(v) for k, v in counter.most_common()}


def is_checked(row: dict[str, str]) -> bool:
    return row.get("review_status") == "checked"


def is_actionable(row: dict[str, str]) -> bool:
    return (
        is_checked(row)
        and row.get("real_issue") in {"yes", "partial"}
        and row.get("keep_for_training") == "yes"
    )


def is_clean_training(row: dict[str, str]) -> bool:
    return (
        is_checked(row)
        and row.get("real_issue") == "yes"
        and row.get("manual_visible") == "yes"
        and row.get("noise_reason") == "not_noise"
        and row.get("keep_for_training") == "yes"
    )


def moment_short(row: dict[str, str]) -> dict[str, Any]:
    return {
        "round": row.get("round"),
        "tick": row.get("tick"),
        "target": row.get("target"),
        "outcome": row.get("outcome"),
        "first_shooter": row.get("first_shooter"),
        "priority": as_float(row.get("importance_score")),
        "categories": split_categories(row.get("categories", "")),
        "root_cause": row.get("root_cause"),
        "manual_visible": row.get("manual_visible"),
        "real_issue": row.get("real_issue"),
        "noise_reason": row.get("noise_reason"),
        "coach_note": row.get("coach_note"),
    }


def recommendation_for_root(root: str) -> str:
    mapping = {
        "large_first_shot_error": "Главная тренировка: качество первого bullet. Разбирать crosshair placement до контакта, микрофлик, недовод/перефлик, первый выстрел до спрея.",
        "moving_first": "Тренировка: A/D stop-shot и дисциплина первого выстрела. Стрелять только после стабилизации, особенно при репиках и мансах.",
        "bad_counter_strafe": "Тренировка: counter-strafe под дуэль. Цель — чтобы первый bullet не уходил в момент остаточной скорости.",
        "bad_pre_aim": "Работа по маршрутам pre-aim: чекать углы не формально, а с ожиданием реального контакта. Прицел заранее на вероятной голове/позиции.",
        "no_response_grenade_or_reload": "Правило готовности после kill/flash/reload: после контакта ожидать второго игрока, не отдавать timing на перезарядке/смене состояния.",
        "no_response_flash": "Отдельно размечать blind-моменты: это не чистая механика. Нужен будущий flash-state фильтр.",
        "overpeek": "Репики: не повторять один и тот же угол, если соперник уже ждёт. Менять тайминг/позицию или играть от тиммейта.",
        "bad_duel_choice": "Decision layer: не все проигранные дуэли являются aim-проблемой. Часть — плохой выбор перестрелки/репика.",
        "enemy_timing": "Timing layer: часть ошибок не тренируется aim-ом напрямую. Нужно учитывать scope delay, угол, кто видел первым и преимущество позиции.",
        "visibility_noise": "Фильтр модели: такие моменты не должны усиливать диагноз mechanics/reaction. Нужен noise/visibility suppression.",
        "unknown": "Не использовать как тренировочный паттерн без дополнительной проверки.",
    }
    return mapping.get(root, "Пока нет отдельной рекомендации для этой причины. Нужна ручная проверка большего числа примеров.")


def build_summary(rows: list[dict[str, str]], match_id: str, player: str) -> dict[str, Any]:
    checked_rows = [r for r in rows if is_checked(r)]
    actionable_rows = [r for r in rows if is_actionable(r)]
    clean_training_rows = [r for r in rows if is_clean_training(r)]
    noise_rows = [r for r in checked_rows if r.get("real_issue") == "no" or r.get("noise_reason") not in {"", "not_noise"}]

    status_counts = Counter(r.get("review_status", "") for r in rows)
    visible_counts = Counter(r.get("manual_visible", "") for r in checked_rows)
    issue_counts = Counter(r.get("real_issue", "") for r in checked_rows)
    noise_counts = Counter(r.get("noise_reason", "") for r in checked_rows)
    root_counts_all = Counter(r.get("root_cause", "") for r in checked_rows)
    root_counts_actionable = Counter(r.get("root_cause", "") for r in actionable_rows)
    root_counts_clean = Counter(r.get("root_cause", "") for r in clean_training_rows)

    category_stats: dict[str, Counter] = defaultdict(Counter)
    for r in checked_rows:
        for cat in split_categories(r.get("categories", "")):
            category_stats[cat][r.get("real_issue", "")] += 1

    category_summary = {}
    for cat, counter in category_stats.items():
        total = sum(counter.values())
        category_summary[cat] = {
            "total": total,
            "yes": counter.get("yes", 0),
            "partial": counter.get("partial", 0),
            "no": counter.get("no", 0),
            "useful_rate_yes_or_partial": pct(counter.get("yes", 0) + counter.get("partial", 0), total),
            "false_or_not_issue_rate": pct(counter.get("no", 0), total),
        }

    top_training_examples = sorted(
        [moment_short(r) for r in actionable_rows],
        key=lambda x: x["priority"],
        reverse=True,
    )[:15]

    top_noise_examples = sorted(
        [moment_short(r) for r in noise_rows],
        key=lambda x: x["priority"],
        reverse=True,
    )[:15]

    recommendations = []
    for root, count in root_counts_actionable.most_common():
        if not root:
            continue
        recommendations.append({
            "root_cause": root,
            "count": int(count),
            "recommendation": recommendation_for_root(root),
        })

    high_level = []

    total_checked = len(checked_rows)
    useful = issue_counts.get("yes", 0) + issue_counts.get("partial", 0)
    real_yes = issue_counts.get("yes", 0)
    false_no = issue_counts.get("no", 0)

    high_level.append(
        f"Из {total_checked} проверенных моментов полезными оказались {useful}: "
        f"{real_yes} настоящих ошибок и {issue_counts.get('partial', 0)} частичных."
    )

    if false_no:
        high_level.append(
            f"{false_no} моментов не стоит использовать как ошибки. Это важный сигнал: strict model уже полезная, но без manual/noise слоя будет завышать часть диагнозов."
        )

    if root_counts_actionable:
        root, count = root_counts_actionable.most_common(1)[0]
        high_level.append(
            f"Главный подтверждённый root cause по ручной разметке: {root} ({count} полезных моментов)."
        )

    if root_counts_clean:
        root, count = root_counts_clean.most_common(1)[0]
        high_level.append(
            f"Самый чистый тренировочный паттерн: {root} ({count} clean examples)."
        )

    return {
        "version": "manual_review_summary_v0_1",
        "match_id": match_id,
        "player": player,
        "summary": {
            "rows_total": len(rows),
            "checked": len(checked_rows),
            "actionable_yes_or_partial_keep": len(actionable_rows),
            "clean_training_examples": len(clean_training_rows),
            "not_real_or_noise": len(noise_rows),
            "useful_rate_yes_or_partial": pct(useful, total_checked),
            "clean_training_rate": pct(len(clean_training_rows), total_checked),
            "not_real_or_noise_rate": pct(len(noise_rows), total_checked),
        },
        "counts": {
            "review_status": counter_to_dict(status_counts),
            "manual_visible": counter_to_dict(visible_counts),
            "real_issue": counter_to_dict(issue_counts),
            "noise_reason": counter_to_dict(noise_counts),
            "root_cause_all_checked": counter_to_dict(root_counts_all),
            "root_cause_actionable": counter_to_dict(root_counts_actionable),
            "root_cause_clean_training": counter_to_dict(root_counts_clean),
        },
        "category_calibration": category_summary,
        "high_level_findings": high_level,
        "recommendations": recommendations,
        "top_training_examples": top_training_examples,
        "top_noise_examples": top_noise_examples,
    }


def render_cards(summary: dict[str, Any]) -> str:
    s = summary["summary"]
    cards = [
        ("Checked", s["checked"]),
        ("Actionable", s["actionable_yes_or_partial_keep"]),
        ("Clean training", s["clean_training_examples"]),
        ("Noise / not real", s["not_real_or_noise"]),
        ("Useful rate", f"{s['useful_rate_yes_or_partial']}%"),
        ("Noise rate", f"{s['not_real_or_noise_rate']}%"),
    ]

    return "\n".join(f"""
    <div class="card">
        <div class="card-title">{esc(title)}</div>
        <div class="card-value">{esc(value)}</div>
    </div>
    """ for title, value in cards)


def render_counter_table(title: str, data: dict[str, int]) -> str:
    rows = "\n".join(
        f"<tr><td>{esc(k if k else 'EMPTY')}</td><td>{esc(v)}</td></tr>"
        for k, v in data.items()
    )
    return f"""
    <section>
        <h2>{esc(title)}</h2>
        <table>
            <thead><tr><th>Value</th><th>Count</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </section>
    """


def render_examples(title: str, examples: list[dict[str, Any]]) -> str:
    if not examples:
        body = '<tr><td colspan="9">Нет примеров.</td></tr>'
    else:
        body = "\n".join(f"""
        <tr>
            <td>R{esc(e.get("round"))}</td>
            <td>{esc(e.get("tick"))}</td>
            <td>{esc(e.get("target"))}</td>
            <td>{esc(e.get("outcome"))}</td>
            <td>{esc(e.get("priority"))}</td>
            <td>{esc(e.get("root_cause"))}</td>
            <td>{esc(e.get("real_issue"))}</td>
            <td>{esc(", ".join(e.get("categories", [])))}</td>
            <td>{esc(e.get("coach_note"))}</td>
        </tr>
        """ for e in examples)

    return f"""
    <section>
        <h2>{esc(title)}</h2>
        <table>
            <thead>
                <tr>
                    <th>Round</th>
                    <th>Tick</th>
                    <th>Target</th>
                    <th>Outcome</th>
                    <th>Priority</th>
                    <th>Root cause</th>
                    <th>Issue</th>
                    <th>Auto categories</th>
                    <th>Coach note</th>
                </tr>
            </thead>
            <tbody>{body}</tbody>
        </table>
    </section>
    """


def render_category_calibration(data: dict[str, Any]) -> str:
    rows = "\n".join(f"""
    <tr>
        <td>{esc(cat)}</td>
        <td>{esc(v.get("total"))}</td>
        <td>{esc(v.get("yes"))}</td>
        <td>{esc(v.get("partial"))}</td>
        <td>{esc(v.get("no"))}</td>
        <td>{esc(v.get("useful_rate_yes_or_partial"))}%</td>
        <td>{esc(v.get("false_or_not_issue_rate"))}%</td>
    </tr>
    """ for cat, v in sorted(data.items()))

    return f"""
    <section>
        <h2>Auto category calibration</h2>
        <p class="muted">Насколько auto-категории совпали с ручной оценкой.</p>
        <table>
            <thead>
                <tr>
                    <th>Auto category</th>
                    <th>Total</th>
                    <th>Yes</th>
                    <th>Partial</th>
                    <th>No</th>
                    <th>Useful %</th>
                    <th>False/not issue %</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </section>
    """


def render_recommendations(recs: list[dict[str, Any]]) -> str:
    rows = "\n".join(f"""
    <tr>
        <td>{esc(r.get("root_cause"))}</td>
        <td>{esc(r.get("count"))}</td>
        <td>{esc(r.get("recommendation"))}</td>
    </tr>
    """ for r in recs)

    return f"""
    <section>
        <h2>Training / algorithm recommendations</h2>
        <table>
            <thead><tr><th>Root cause</th><th>Count</th><th>Recommendation</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </section>
    """


def render_html(data: dict[str, Any]) -> str:
    findings = "\n".join(f"<li>{esc(x)}</li>" for x in data["high_level_findings"])

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Manual Review Summary v0.1 — {esc(data["match_id"])} — {esc(data["player"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 27px; font-weight: 700; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 900px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
        li {{ margin-bottom: 8px; }}
    </style>
</head>
<body>
    <h1>Manual Review Summary v0.1</h1>
    <p class="muted">Match: <code>{esc(data["match_id"])}</code> · Player: <code>{esc(data["player"])}</code></p>

    <div class="grid">{render_cards(data)}</div>

    <section>
        <h2>High-level findings</h2>
        <ul>{findings}</ul>
    </section>

    {render_recommendations(data["recommendations"])}
    {render_category_calibration(data["category_calibration"])}
    {render_examples("Top training examples", data["top_training_examples"])}
    {render_examples("Top noise / not-real examples", data["top_noise_examples"])}
    {render_counter_table("Root causes — actionable", data["counts"]["root_cause_actionable"])}
    {render_counter_table("Noise reasons", data["counts"]["noise_reason"])}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build summary from manual review CSV.")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    csv_path = root / "data" / "reviews" / args.match_id / f"manual_review_{args.player}_v0_1.csv"

    rows = read_csv_rows(csv_path)
    summary = build_summary(rows, args.match_id, args.player)

    out_dir = csv_path.parent
    json_path = out_dir / f"manual_review_summary_{args.player}_v0_1.json"
    html_path = out_dir / f"manual_review_summary_{args.player}_v0_1.html"

    write_json(json_path, summary)
    html_path.write_text(render_html(summary), encoding="utf-8")

    print("OK: Manual Review Summary v0.1 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {args.player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Summary:")
    for k, v in summary["summary"].items():
        print(f"  {k}: {v}")

    print("")
    print("Top actionable root causes:")
    for k, v in summary["counts"]["root_cause_actionable"].items():
        print(f"  {k}: {v}")

    print("")
    print("High-level findings:")
    for item in summary["high_level_findings"]:
        print(f"  - {item}")

    if not args.no_open:
        try:
            os.startfile(str(html_path))
            print("")
            print(f"Opened HTML: {html_path}")
        except Exception as exc:
            print("")
            print(f"Created but not opened automatically: {exc}")


if __name__ == "__main__":
    main()
