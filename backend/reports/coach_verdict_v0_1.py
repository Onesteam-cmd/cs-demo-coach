from __future__ import annotations

import argparse
import csv
import html
import json
import os
from pathlib import Path
from typing import Any


ROOT_LABELS = {
    "large_first_shot_error": "Качество первого выстрела / недовод или перефлик",
    "bad_pre_aim": "Pre-aim и ожидание позиции",
    "moving_first": "Первый выстрел на скорости",
    "bad_counter_strafe": "Counter-strafe / поздняя остановка",
    "no_response_grenade_or_reload": "Потеря готовности после флешки, kill или перезарядки",
    "overpeek": "Опасный повторный пик",
    "bad_duel_choice": "Плохой выбор дуэли",
    "enemy_timing": "Timing disadvantage / соперник увидел раньше",
    "visibility_noise": "Шум visibility/FOV-модели",
    "no_response_flash": "Blind-момент, не чистая механика",
    "unknown": "Неясная причина",
}


ROOT_TRAINING = {
    "large_first_shot_error": [
        "В DM играть короткими сериями 1–3 пули, не начинать спрей до попадания/микрокоррекции.",
        "Отдельно тренировать первый bullet: прицел → микродовод → выстрел, без панического зажима.",
        "В демках проверять: промах был из-за недовода, перефлика или плохой высоты прицела.",
    ],
    "bad_pre_aim": [
        "На карте пройти типовые маршруты и заранее поставить crosshair на вероятные позиции головы.",
        "Чекать углы не «для галочки», а с реальным ожиданием контакта.",
        "Отмечать позиции, где ты переводишься дальше до полной проверки угла.",
    ],
    "moving_first": [
        "10 минут A/D stop-shot: движение → полная остановка → одиночный выстрел.",
        "В DM запрещать себе стрелять в момент остановки, пока скорость ещё не погасла.",
    ],
    "bad_counter_strafe": [
        "Тренировать stop timing: A → D/stop → bullet. Цель — первый выстрел без остаточной скорости.",
    ],
    "no_response_grenade_or_reload": [
        "После kill/flash/reload держать в голове второго игрока. Не перезаряжаться автоматически после первого контакта.",
        "После первого kill сначала проверить immediate trade timing, потом reload.",
    ],
    "overpeek": [
        "Не повторять тот же угол, если соперник уже ждёт репик.",
        "Менять тайминг, ширину пика или играть от тиммейта.",
    ],
    "bad_duel_choice": [
        "Отдельно разбирать, где дуэль вообще не нужна: плохой репик, изоляция без трейда, пик в ожидающий прицел.",
    ],
    "enemy_timing": [
        "Не считать такие моменты чистой aim-ошибкой. Сравнивать, кто видел первым и у кого было позиционное преимущество.",
    ],
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
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


def top_roots(summary: dict[str, Any]) -> list[tuple[str, int]]:
    roots = summary.get("counts", {}).get("root_cause_actionable", {})
    items = [(str(k), int(v)) for k, v in roots.items() if k and k != "unknown"]
    items.sort(key=lambda x: x[1], reverse=True)
    return items


def top_clean_roots(summary: dict[str, Any]) -> list[tuple[str, int]]:
    roots = summary.get("counts", {}).get("root_cause_clean_training", {})
    items = [(str(k), int(v)) for k, v in roots.items() if k and k != "unknown"]
    items.sort(key=lambda x: x[1], reverse=True)
    return items


def find_player_focus(focus: dict[str, Any], player: str) -> dict[str, Any]:
    for p in focus.get("players", []):
        if str(p.get("name", "")).lower() == player.lower():
            return p
    players = focus.get("players", [])
    return players[0] if players else {}


def build_verdict(match_id: str, player: str) -> dict[str, Any]:
    root = repo_root()

    report_dir = root / "data" / "reports" / match_id
    review_dir = root / "data" / "reviews" / match_id

    focus = read_json(report_dir / "player_focus_v0_3.json")
    manual_summary = read_json(review_dir / f"manual_review_summary_{player}_v0_1.json")
    manual_rows = read_csv_rows(review_dir / f"manual_review_{player}_v0_1.csv")
    moments = read_json(report_dir / "moments_review_v0_2.json")

    player_focus = find_player_focus(focus, player)

    roots = top_roots(manual_summary)
    clean_roots = top_clean_roots(manual_summary)

    primary_root = roots[0][0] if roots else "unknown"
    primary_count = roots[0][1] if roots else 0

    auto_main = player_focus.get("main_diagnosis") or "—"
    manual_stats = manual_summary.get("summary", {})

    calibrated_main = ROOT_LABELS.get(primary_root, primary_root)

    useful_rate = manual_stats.get("useful_rate_yes_or_partial")
    noise_rate = manual_stats.get("not_real_or_noise_rate")

    interpretation = []

    interpretation.append(
        f"Автоматический главный диагноз был: {auto_main}."
    )

    if primary_root != "true_late_shot":
        interpretation.append(
            "После ручной проверки delayed-first-shot нужно понизить как главный диагноз: часть delay-моментов оказалась smoke/visibility/timing/no-response контекстом, а не чистой задержкой реакции."
        )

    interpretation.append(
        f"Калиброванный главный диагноз: {calibrated_main} ({primary_count} полезных manually reviewed моментов)."
    )

    interpretation.append(
        f"Manual review показал useful rate {useful_rate}% и noise/not-real rate {noise_rate}%. Значит strict layer полезен для поиска кандидатов, но финальный вывод должен учитывать manual/noise слой."
    )

    actionable_rows = [
        r for r in manual_rows
        if r.get("review_status") == "checked"
        and r.get("real_issue") in {"yes", "partial"}
        and r.get("keep_for_training") == "yes"
    ]

    clean_rows = [
        r for r in manual_rows
        if r.get("review_status") == "checked"
        and r.get("real_issue") == "yes"
        and r.get("manual_visible") == "yes"
        and r.get("noise_reason") == "not_noise"
        and r.get("keep_for_training") == "yes"
    ]

    actionable_rows.sort(key=lambda r: as_float(r.get("importance_score")), reverse=True)
    clean_rows.sort(key=lambda r: as_float(r.get("importance_score")), reverse=True)

    training_plan = []

    for root_key, count in roots[:5]:
        label = ROOT_LABELS.get(root_key, root_key)
        drills = ROOT_TRAINING.get(root_key, [])
        training_plan.append({
            "root_cause": root_key,
            "label": label,
            "count": count,
            "drills": drills,
        })

    algorithm_notes = [
        "Не использовать raw late_shot как главный диагноз без manual/noise фильтра.",
        "Понижать вес delay, если manual root cause у похожих моментов: visibility_noise, through_smoke, enemy_timing, no_response_flash, wrong_target.",
        "Повышать вес large_first_shot_error, если strict_tags содержит viewer_large_first_shot_error и manual review подтверждает yes/partial.",
        "Отдельно разделять механические ошибки и decision/macro контекст: overpeek, bad_duel_choice, enemy_timing.",
    ]

    return {
        "version": "coach_verdict_v0_1",
        "match_id": match_id,
        "player": player,
        "auto_main_diagnosis": auto_main,
        "calibrated_main_diagnosis": calibrated_main,
        "primary_root_cause": primary_root,
        "primary_root_count": primary_count,
        "manual_summary": manual_stats,
        "root_cause_actionable": dict(roots),
        "root_cause_clean": dict(clean_roots),
        "interpretation": interpretation,
        "training_plan": training_plan,
        "top_actionable_examples": actionable_rows[:12],
        "top_clean_examples": clean_rows[:12],
        "algorithm_notes": algorithm_notes,
        "source_files": {
            "player_focus": str(report_dir / "player_focus_v0_3.json"),
            "moments_review": str(report_dir / "moments_review_v0_2.json"),
            "manual_review_csv": str(review_dir / f"manual_review_{player}_v0_1.csv"),
            "manual_summary": str(review_dir / f"manual_review_summary_{player}_v0_1.json"),
        },
    }


def render_examples(rows: list[dict[str, str]], title: str) -> str:
    if not rows:
        body = '<tr><td colspan="8">Нет примеров.</td></tr>'
    else:
        body = "\n".join(f"""
        <tr>
            <td>R{esc(r.get("round"))}</td>
            <td>{esc(r.get("tick"))}</td>
            <td>{esc(r.get("target"))}</td>
            <td>{esc(r.get("outcome"))}</td>
            <td>{esc(r.get("importance_score"))}</td>
            <td>{esc(r.get("root_cause"))}</td>
            <td>{esc(r.get("categories"))}</td>
            <td>{esc(r.get("coach_note"))}</td>
        </tr>
        """ for r in rows)

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
                    <th>Auto categories</th>
                    <th>Coach note</th>
                </tr>
            </thead>
            <tbody>{body}</tbody>
        </table>
    </section>
    """


def render_training(plan: list[dict[str, Any]]) -> str:
    rows = []
    for p in plan:
        drills = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in p.get("drills", [])) + "</ul>"
        rows.append(f"""
        <tr>
            <td>{esc(p.get("label"))}<br><span class="muted">{esc(p.get("root_cause"))}</span></td>
            <td>{esc(p.get("count"))}</td>
            <td>{drills}</td>
        </tr>
        """)

    return f"""
    <section>
        <h2>Training plan</h2>
        <table>
            <thead><tr><th>Проблема</th><th>Count</th><th>Что делать</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


def render_html(data: dict[str, Any]) -> str:
    manual = data["manual_summary"]

    interpretation = "".join(f"<li>{esc(x)}</li>" for x in data["interpretation"])
    algorithm_notes = "".join(f"<li>{esc(x)}</li>" for x in data["algorithm_notes"])

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Coach Verdict v0.1 — {esc(data["match_id"])} — {esc(data["player"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 1000px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
        li {{ margin-bottom: 8px; }}
    </style>
</head>
<body>
    <h1>Coach Verdict v0.1</h1>
    <p class="muted">Match: <code>{esc(data["match_id"])}</code> · Player: <code>{esc(data["player"])}</code></p>

    <div class="grid">
        <div class="card">
            <div class="card-title">Auto diagnosis</div>
            <div class="card-value">{esc(data["auto_main_diagnosis"])}</div>
        </div>
        <div class="card">
            <div class="card-title">Calibrated diagnosis</div>
            <div class="card-value">{esc(data["calibrated_main_diagnosis"])}</div>
        </div>
        <div class="card">
            <div class="card-title">Actionable</div>
            <div class="card-value">{esc(manual.get("actionable_yes_or_partial_keep"))}</div>
        </div>
        <div class="card">
            <div class="card-title">Clean training</div>
            <div class="card-value">{esc(manual.get("clean_training_examples"))}</div>
        </div>
        <div class="card">
            <div class="card-title">Noise / not real</div>
            <div class="card-value">{esc(manual.get("not_real_or_noise"))}</div>
        </div>
    </div>

    <section>
        <h2>Verdict</h2>
        <ul>{interpretation}</ul>
    </section>

    {render_training(data["training_plan"])}

    <section>
        <h2>Algorithm notes</h2>
        <ul>{algorithm_notes}</ul>
    </section>

    {render_examples(data["top_actionable_examples"], "Top actionable examples")}
    {render_examples(data["top_clean_examples"], "Top clean training examples")}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    data = build_verdict(args.match_id, args.player)

    root = repo_root()
    out_dir = root / "data" / "reports" / args.match_id
    json_path = out_dir / f"coach_verdict_{args.player}_v0_1.json"
    html_path = out_dir / f"coach_verdict_{args.player}_v0_1.html"

    write_json(json_path, data)
    html_path.write_text(render_html(data), encoding="utf-8")

    print("OK: Coach Verdict v0.1 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {args.player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Verdict:")
    print(f"  Auto diagnosis: {data['auto_main_diagnosis']}")
    print(f"  Calibrated diagnosis: {data['calibrated_main_diagnosis']}")
    print(f"  Primary root cause: {data['primary_root_cause']} ({data['primary_root_count']})")
    print("")
    print("Training priorities:")
    for item in data["training_plan"][:5]:
        print(f"  - {item['root_cause']}: {item['count']}")

    if not args.no_open:
        os.startfile(str(html_path))
        print("")
        print(f"Opened HTML: {html_path}")


if __name__ == "__main__":
    main()
