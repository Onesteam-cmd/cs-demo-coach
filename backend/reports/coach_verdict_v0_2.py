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
    "no_response_grenade_or_reload": [
        "После kill/flash/reload держать в голове второго игрока. Не перезаряжаться автоматически после первого контакта.",
        "После первого kill сначала проверить immediate trade timing, потом reload.",
    ],
    "overpeek": [
        "Не повторять тот же угол, если соперник уже ждёт репик.",
        "Менять тайминг, ширину пика или играть от тиммейта.",
    ],
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def top_roots(summary: dict[str, Any], key: str) -> list[tuple[str, int]]:
    roots = summary.get("counts", {}).get(key, {})
    items = [(str(k), int(v)) for k, v in roots.items() if k and k != "unknown"]
    items.sort(key=lambda x: x[1], reverse=True)
    return items


def find_player_focus(focus: dict[str, Any], player: str) -> dict[str, Any]:
    for p in focus.get("players", []):
        if str(p.get("name", "")).lower() == player.lower():
            return p
    players = focus.get("players", [])
    return players[0] if players else {}


def build_mechanics_block(match_id: str, player: str) -> dict[str, Any]:
    root = repo_root()
    report_dir = root / "data" / "reports" / match_id
    review_dir = root / "data" / "reviews" / match_id

    focus = read_json(report_dir / "player_focus_v0_3.json")
    manual_summary = read_json(review_dir / f"manual_review_summary_{player}_v0_1.json")
    manual_rows = read_csv_rows(review_dir / f"manual_review_{player}_v0_1.csv")

    player_focus = find_player_focus(focus, player)
    roots = top_roots(manual_summary, "root_cause_actionable")
    clean_roots = top_roots(manual_summary, "root_cause_clean_training")

    primary_root = roots[0][0] if roots else "unknown"
    primary_count = roots[0][1] if roots else 0

    auto_main = player_focus.get("main_diagnosis") or "—"
    calibrated_main = ROOT_LABELS.get(primary_root, primary_root)

    manual_stats = manual_summary.get("summary", {})

    interpretation = [
        f"Автоматический главный диагноз был: {auto_main}.",
        "После ручной проверки delayed-first-shot нужно понизить как главный диагноз: часть delay-моментов оказалась smoke/visibility/timing/no-response контекстом, а не чистой задержкой реакции.",
        f"Калиброванный главный mechanics-диагноз: {calibrated_main} ({primary_count} полезных manually reviewed моментов).",
        f"Manual review показал useful rate {manual_stats.get('useful_rate_yes_or_partial')}% и noise/not-real rate {manual_stats.get('not_real_or_noise_rate')}%.",
    ]

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
        training_plan.append({
            "root_cause": root_key,
            "label": ROOT_LABELS.get(root_key, root_key),
            "count": count,
            "drills": ROOT_TRAINING.get(root_key, []),
        })

    return {
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
    }


def build_utility_block(match_id: str, player: str) -> dict[str, Any]:
    root = repo_root()
    report_dir = root / "data" / "reports" / match_id

    utility = read_json(report_dir / "utility_analyzer_v0_2.json")
    map_summary = read_json(report_dir / "utility_map_summary_v0_1.json")

    primary = utility.get("primary_player_summary") or {}
    players = utility.get("players") or []

    rank = None
    for i, row in enumerate(players, 1):
        if str(row.get("player", "")).lower() == player.lower():
            rank = i
            break

    summary = map_summary.get("summary", {})
    counts = map_summary.get("counts", {})
    findings = map_summary.get("findings", [])
    recommendations = map_summary.get("recommendations", [])

    quality = counts.get("quality", {})
    problems = counts.get("problem", {})

    good = int(quality.get("good", 0))
    partial = int(quality.get("partial", 0))
    bad = int(quality.get("bad", 0))
    too_late = int(problems.get("too_late", 0))

    if too_late:
        calibrated_utility = "Utility тайминг / позиция броска"
    elif bad > good:
        calibrated_utility = "Качество utility lineups / placement"
    elif partial > good:
        calibrated_utility = "Utility даёт value, но часто неполный"
    else:
        calibrated_utility = "Utility в целом рабочий"

    interpretation = [
        f"Utility rank: {rank}/{len(players)} по грубой оценке utility analyzer.",
        f"Проверено utility map events: checked={summary.get('checked')}, good={good}, partial={partial}, bad={bad}.",
        f"Калиброванный utility-диагноз: {calibrated_utility}.",
    ]

    if too_late:
        interpretation.append(
            f"Главная повторяющаяся utility-проблема — too_late={too_late}: гранаты часто попадают по месту, но приходят не в лучший тайминг."
        )

    if primary.get("flash_assists") == 0:
        interpretation.append(
            "Flash assists не найдены. Это не доказывает плохие флешки, но показывает, что в этой демке флешки не конвертировались в assisted kills."
        )

    return {
        "calibrated_utility_diagnosis": calibrated_utility,
        "utility_rank": rank,
        "players_total": len(players),
        "primary_player_summary": primary,
        "map_summary": summary,
        "map_counts": counts,
        "findings": findings,
        "interpretation": interpretation,
        "recommendations": recommendations,
        "useful_examples": map_summary.get("useful_examples", []),
        "bad_examples": map_summary.get("bad_examples", []),
    }


def build_verdict(match_id: str, player: str) -> dict[str, Any]:
    mechanics = build_mechanics_block(match_id, player)
    utility = build_utility_block(match_id, player)

    combined_priority = [
        {
            "area": "mechanics",
            "title": mechanics["calibrated_main_diagnosis"],
            "reason": f"{mechanics['primary_root_cause']} ({mechanics['primary_root_count']})",
        },
        {
            "area": "utility",
            "title": utility["calibrated_utility_diagnosis"],
            "reason": f"checked={utility.get('map_summary', {}).get('checked')} good={utility.get('map_summary', {}).get('good')} partial={utility.get('map_summary', {}).get('partial')} bad={utility.get('map_summary', {}).get('bad')}",
        },
    ]

    final_summary = [
        f"Главный mechanics-приоритет: {mechanics['calibrated_main_diagnosis']}.",
        f"Главный utility-приоритет: {utility['calibrated_utility_diagnosis']}.",
        "Общая картина: механика первого выстрела сейчас важнее как повторяющийся чистый тренировочный паттерн, а utility требует улучшения тайминга/позиции и нескольких заготовленных сценариев.",
    ]

    return {
        "version": "coach_verdict_v0_2",
        "match_id": match_id,
        "player": player,
        "mechanics": mechanics,
        "utility": utility,
        "combined_priority": combined_priority,
        "final_summary": final_summary,
    }


def render_examples(rows: list[dict[str, str]], title: str) -> str:
    if not rows:
        body = '<tr><td colspan="8">Нет примеров.</td></tr>'
    else:
        body = "\n".join(f"""
        <tr>
            <td>R{esc(r.get("round"))}</td>
            <td>{esc(r.get("tick") or r.get("start_tick"))}</td>
            <td>{esc(r.get("target") or r.get("utility_type"))}</td>
            <td>{esc(r.get("outcome") or r.get("quality"))}</td>
            <td>{esc(r.get("importance_score") or r.get("problem"))}</td>
            <td>{esc(r.get("root_cause") or r.get("intended_purpose"))}</td>
            <td>{esc(r.get("categories") or r.get("known_lineup"))}</td>
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
                    <th>Target/type</th>
                    <th>Outcome/quality</th>
                    <th>Score/problem</th>
                    <th>Root/purpose</th>
                    <th>Tags/lineup</th>
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
        drills = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in p.get("drills", [])[:3]) + "</ul>"
        rows.append(f"""
        <tr>
            <td>{esc(p.get("label"))}<br><span class="muted">{esc(p.get("root_cause"))}</span></td>
            <td>{esc(p.get("count"))}</td>
            <td>{drills}</td>
        </tr>
        """)

    return f"""
    <section>
        <h2>Mechanics training plan</h2>
        <table>
            <thead><tr><th>Проблема</th><th>Count</th><th>Что делать</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </section>
    """


def render_utility_recommendations(recs: list[dict[str, Any]]) -> str:
    rows = "\n".join(f"""
    <tr>
        <td>{esc(r.get("problem"))}</td>
        <td>{esc(r.get("count"))}</td>
        <td>{esc(r.get("recommendation"))}</td>
    </tr>
    """ for r in recs)

    return f"""
    <section>
        <h2>Utility recommendations</h2>
        <table>
            <thead><tr><th>Problem</th><th>Count</th><th>Recommendation</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </section>
    """


def render_html(data: dict[str, Any]) -> str:
    m = data["mechanics"]
    u = data["utility"]

    final_summary = "".join(f"<li>{esc(x)}</li>" for x in data["final_summary"])
    mechanics_notes = "".join(f"<li>{esc(x)}</li>" for x in m["interpretation"])
    utility_notes = "".join(f"<li>{esc(x)}</li>" for x in u["interpretation"])

    primary = u.get("primary_player_summary") or {}

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Coach Verdict v0.2 — {esc(data["match_id"])} — {esc(data["player"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 22px; font-weight: 700; line-height: 1.2; }}
        .good {{ color: #b7f5bd; }}
        .warn {{ color: #ffd18a; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 1000px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
        li {{ margin-bottom: 8px; }}
    </style>
</head>
<body>
    <h1>Coach Verdict v0.2</h1>
    <p class="muted">Match: <code>{esc(data["match_id"])}</code> · Player: <code>{esc(data["player"])}</code></p>

    <div class="grid">
        <div class="card">
            <div class="card-title">Mechanics diagnosis</div>
            <div class="card-value good">{esc(m["calibrated_main_diagnosis"])}</div>
        </div>
        <div class="card">
            <div class="card-title">Utility diagnosis</div>
            <div class="card-value warn">{esc(u["calibrated_utility_diagnosis"])}</div>
        </div>
        <div class="card">
            <div class="card-title">Utility rank</div>
            <div class="card-value">{esc(u.get("utility_rank"))}/{esc(u.get("players_total"))}</div>
        </div>
        <div class="card">
            <div class="card-title">Utility damage</div>
            <div class="card-value">{esc(primary.get("utility_damage_dealt"))}</div>
        </div>
        <div class="card">
            <div class="card-title">Utility map quality</div>
            <div class="card-value">good {esc(u["map_summary"].get("good"))} · partial {esc(u["map_summary"].get("partial"))} · bad {esc(u["map_summary"].get("bad"))}</div>
        </div>
    </div>

    <section>
        <h2>Final summary</h2>
        <ul>{final_summary}</ul>
    </section>

    <section>
        <h2>Mechanics interpretation</h2>
        <ul>{mechanics_notes}</ul>
    </section>

    <section>
        <h2>Utility interpretation</h2>
        <ul>{utility_notes}</ul>
    </section>

    {render_training(m["training_plan"])}
    {render_utility_recommendations(u["recommendations"])}
    {render_examples(m["top_actionable_examples"], "Top mechanics examples")}
    {render_examples(u["useful_examples"], "Top utility examples")}
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
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"coach_verdict_{args.player}_v0_2.json"
    html_path = out_dir / f"coach_verdict_{args.player}_v0_2.html"

    write_json(json_path, data)
    html_path.write_text(render_html(data), encoding="utf-8")

    print("OK: Coach Verdict v0.2 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {args.player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")

    print("")
    print("Verdict:")
    print(f"  Mechanics: {data['mechanics']['calibrated_main_diagnosis']}")
    print(f"  Utility: {data['utility']['calibrated_utility_diagnosis']}")
    print(f"  Utility rank: {data['utility'].get('utility_rank')}/{data['utility'].get('players_total')}")

    print("")
    print("Final summary:")
    for item in data["final_summary"]:
        print(f"  - {item}")

    if not args.no_open:
        os.startfile(str(html_path))
        print("")
        print(f"Opened HTML: {html_path}")


if __name__ == "__main__":
    main()
