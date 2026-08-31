from __future__ import annotations

import argparse
import csv
import html
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def count(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    c = Counter((r.get(field) or "EMPTY") for r in rows)
    return {k: int(v) for k, v in c.most_common()}


def useful_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("review_status") == "checked"
        and r.get("quality") in {"good", "partial"}
        and r.get("keep_for_training") == "yes"
    ]


def bad_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        r for r in rows
        if r.get("review_status") == "checked"
        and r.get("quality") == "bad"
    ]


def build_findings(rows: list[dict[str, str]]) -> list[str]:
    checked = [r for r in rows if r.get("review_status") == "checked"]
    q = Counter(r.get("quality") for r in checked)
    p = Counter(r.get("problem") for r in checked)
    purpose = Counter(r.get("intended_purpose") for r in checked)
    lineup = Counter(r.get("known_lineup") for r in checked)

    findings = []

    findings.append(
        f"Проверено {len(checked)} utility-событий: good={q.get('good', 0)}, partial={q.get('partial', 0)}, bad={q.get('bad', 0)}."
    )

    if q.get("partial", 0) > q.get("good", 0):
        findings.append(
            "Большая часть utility не провальная, но неполная: чаще это partial-value, а не полный miss."
        )

    if p.get("too_late", 0):
        findings.append(
            f"Главная повторяющаяся проблема — поздний utility: too_late={p.get('too_late', 0)}. Это значит, что часто граната попадает по месту, но приходит не в лучший тайминг."
        )

    if p.get("gap", 0):
        findings.append(
            f"Есть gap-проблема: gap={p.get('gap', 0)}. Такие молики/смоки требуют отдельного lineups/placement слоя."
        )

    if lineup.get("no", 0) > lineup.get("yes", 0):
        findings.append(
            "Большинство отмеченных utility-событий были без готового lineup. Зона роста — заготовить несколько стабильных гранат под частые сценарии."
        )

    if purpose.get("stop_push", 0) >= purpose.get("block_vision", 0):
        findings.append(
            "Utility чаще использовался для stop-push, чем для vision-block. Нужно проверять, насколько эти молики реально задерживают пуш, а не просто тратятся по просьбе/ложной инфе."
        )

    return findings


def build_recommendations(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    problem_counts = Counter(r.get("problem") for r in rows if r.get("review_status") == "checked")
    recs = []

    if problem_counts.get("too_late", 0):
        recs.append({
            "problem": "too_late",
            "count": str(problem_counts.get("too_late", 0)),
            "recommendation": "Тренировать не только сам lineup, но и позицию/тайминг броска: граната должна приходить до контакта, а не после первого пика врага."
        })

    if problem_counts.get("wrong_place", 0):
        recs.append({
            "problem": "wrong_place",
            "count": str(problem_counts.get("wrong_place", 0)),
            "recommendation": "Для stop-push моликов проверить глубину броска: если молик ложится неглубоко, он не режет пуш и даёт сопернику пространство."
        })

    if problem_counts.get("no_value", 0):
        recs.append({
            "problem": "no_value",
            "count": str(problem_counts.get("no_value", 0)),
            "recommendation": "Не кидать utility автоматически по просьбе/панике. Сначала понимать цель: остановить пуш, закрыть вижен, выкурить угол или выиграть время."
        })

    if problem_counts.get("gap", 0):
        recs.append({
            "problem": "gap",
            "count": str(problem_counts.get("gap", 0)),
            "recommendation": "Для gap-сценариев нужны заготовленные lineups. Импровизированный молик/смок в такой позиции почти гарантированно оставит окно."
        })

    recs.append({
        "problem": "next_layer",
        "count": "-",
        "recommendation": "Следующий алгоритмический слой должен сопоставлять координаты smoke/inferno с зонами карты: palace, jungle, short, apps, kitchen/window и т.д."
    })

    return recs


def render_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="muted">Нет данных.</p>'

    head = "".join(f"<th>{esc(label)}</th>" for _, label in cols)
    body = []

    for row in rows:
        body.append("<tr>" + "".join(f"<td>{esc(row.get(key))}</td>" for key, _ in cols) + "</tr>")

    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_counter(title: str, data: dict[str, int]) -> str:
    rows = [{"value": k, "count": v} for k, v in data.items()]
    return f"""
    <section>
        <h2>{esc(title)}</h2>
        {render_table(rows, [("value", "Value"), ("count", "Count")])}
    </section>
    """


def render_html(data: dict[str, Any]) -> str:
    findings = "".join(f"<li>{esc(x)}</li>" for x in data["findings"])

    rec_rows = data["recommendations"]
    useful = data["useful_examples"]
    bad = data["bad_examples"]

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Utility Map Summary v0.1 — {esc(data["match_id"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 950px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
        li {{ margin-bottom: 8px; }}
    </style>
</head>
<body>
    <h1>Utility Map Summary v0.1</h1>
    <p class="muted">Match: <code>{esc(data["match_id"])}</code> · Player: <code>{esc(data["player"])}</code></p>

    <div class="grid">
        <div class="card"><div class="card-title">Checked</div><div class="card-value">{esc(data["summary"]["checked"])}</div></div>
        <div class="card"><div class="card-title">Good</div><div class="card-value">{esc(data["summary"]["good"])}</div></div>
        <div class="card"><div class="card-title">Partial</div><div class="card-value">{esc(data["summary"]["partial"])}</div></div>
        <div class="card"><div class="card-title">Bad</div><div class="card-value">{esc(data["summary"]["bad"])}</div></div>
        <div class="card"><div class="card-title">Useful</div><div class="card-value">{esc(data["summary"]["useful"])}</div></div>
    </div>

    <section>
        <h2>Findings</h2>
        <ul>{findings}</ul>
    </section>

    <section>
        <h2>Recommendations</h2>
        {render_table(rec_rows, [("problem", "Problem"), ("count", "Count"), ("recommendation", "Recommendation")])}
    </section>

    <section>
        <h2>Useful examples</h2>
        {render_table(useful, [
            ("utility_type", "Type"),
            ("round", "R"),
            ("start_tick", "Tick"),
            ("quality", "Quality"),
            ("problem", "Problem"),
            ("intended_purpose", "Purpose"),
            ("known_lineup", "Lineup"),
            ("coach_note", "Coach note"),
        ])}
    </section>

    <section>
        <h2>Bad examples</h2>
        {render_table(bad, [
            ("utility_type", "Type"),
            ("round", "R"),
            ("start_tick", "Tick"),
            ("quality", "Quality"),
            ("problem", "Problem"),
            ("coach_note", "Coach note"),
        ])}
    </section>

    {render_counter("Quality counts", data["counts"]["quality"])}
    {render_counter("Problem counts", data["counts"]["problem"])}
    {render_counter("Purpose counts", data["counts"]["intended_purpose"])}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    csv_path = root / "data" / "reviews" / args.match_id / f"utility_map_review_{args.player}_v0_1.csv"

    rows = read_rows(csv_path)
    checked = [r for r in rows if r.get("review_status") == "checked"]

    useful = useful_rows(rows)
    bad = bad_rows(rows)

    data = {
        "version": "utility_map_summary_v0_1",
        "match_id": args.match_id,
        "player": args.player,
        "source_csv": str(csv_path),
        "summary": {
            "rows_total": len(rows),
            "checked": len(checked),
            "good": sum(1 for r in checked if r.get("quality") == "good"),
            "partial": sum(1 for r in checked if r.get("quality") == "partial"),
            "bad": sum(1 for r in checked if r.get("quality") == "bad"),
            "useful": len(useful),
        },
        "counts": {
            "quality": count(checked, "quality"),
            "problem": count(checked, "problem"),
            "intended_purpose": count(checked, "intended_purpose"),
            "known_lineup": count(checked, "known_lineup"),
        },
        "findings": build_findings(rows),
        "recommendations": build_recommendations(rows),
        "useful_examples": useful,
        "bad_examples": bad,
    }

    out_dir = root / "data" / "reports" / args.match_id
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "utility_map_summary_v0_1.json"
    html_path = out_dir / "utility_map_summary_v0_1.html"

    write_json(json_path, data)
    html_path.write_text(render_html(data), encoding="utf-8")

    print("OK: Utility Map Summary v0.1 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {args.player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Summary:")
    for k, v in data["summary"].items():
        print(f"  {k}: {v}")

    print("")
    print("Counts:")
    for group, values in data["counts"].items():
        print(f"  {group}: {values}")

    print("")
    print("Findings:")
    for item in data["findings"]:
        print(f"  - {item}")

    if args.open:
        os.startfile(str(html_path))


if __name__ == "__main__":
    main()
