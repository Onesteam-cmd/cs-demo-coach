from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


VERSION = "unified_coach_verdict_v0_3"


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Could not read JSON {path}: {e}")
        return {}


def as_text(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        return str(payload)


def find_known_mechanics(coach: dict[str, Any], manual: dict[str, Any]) -> str:
    text = as_text(coach).lower() + "\n" + as_text(manual).lower()

    if "качество первого выстрела" in text or "large_first_shot_error" in text:
        return "Качество первого выстрела / недовод или перефлик"

    if "поздний первый выстрел" in text or "late_shot" in text:
        return "Поздний первый выстрел в подтверждённых контактах"

    if "moving_first" in text:
        return "Первый выстрел в движении / плохой counter-strafe"

    return "Недостаточно данных"


def find_known_utility(coach: dict[str, Any], utility_map: dict[str, Any], utility_analyzer: dict[str, Any]) -> str:
    text = as_text(coach).lower() + "\n" + as_text(utility_map).lower() + "\n" + as_text(utility_analyzer).lower()

    if "utility тайминг" in text or "too_late" in text:
        return "Utility тайминг / позиция броска"

    if "gap" in text:
        return "Utility placement / gap-проблемы"

    if "flash assists" in text or "нет flash assists" in text:
        return "Недостаточная командная value от flash"

    return "Недостаточно данных"


def get_nested(payload: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cur: Any = payload
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def build_unified(
    match_id: str,
    player: str,
    coach: dict[str, Any],
    manual: dict[str, Any],
    utility_analyzer: dict[str, Any],
    utility_map: dict[str, Any],
    macro: dict[str, Any],
    macro_verdict: dict[str, Any],
) -> dict[str, Any]:
    mechanics_diagnosis = find_known_mechanics(coach, manual)
    utility_diagnosis = find_known_utility(coach, utility_map, utility_analyzer)

    macro_summary = macro.get("summary", {})
    macro_v = macro_verdict.get("verdict", {})

    macro_category = macro_v.get("main_macro_category_ru") or macro_summary.get("main_macro_category") or "Недостаточно данных"
    macro_flag = macro_v.get("main_macro_flag_ru") or macro_summary.get("main_macro_flag") or "Недостаточно данных"

    manual_summary = manual.get("summary", manual)
    mechanics_actionable = (
        manual_summary.get("actionable_yes_or_partial_keep")
        or manual_summary.get("clean_training_examples")
        or manual_summary.get("checked")
        or None
    )

    utility_map_summary = utility_map.get("summary", utility_map)
    utility_good = utility_map_summary.get("good")
    utility_partial = utility_map_summary.get("partial")
    utility_bad = utility_map_summary.get("bad")

    utility_damage = (
        utility_analyzer.get("player", {}).get("utility_damage_dealt")
        if isinstance(utility_analyzer.get("player"), dict)
        else utility_analyzer.get("utility_damage_dealt")
    )

    macro_counts = macro_summary.get("macro_category_counts", {})
    macro_trade_spacing = macro_counts.get("trade_spacing", 0)
    macro_entry_timing = macro_counts.get("entry_timing", 0)
    macro_low_impact = macro_counts.get("low_impact", 0)
    macro_postplant = macro_counts.get("postplant_retake", 0)

    priority_order = [
        {
            "rank": 1,
            "area": "Mechanics",
            "title": mechanics_diagnosis,
            "why": "Ранее ручная проверка mechanics показала, что самый чистый повторяющийся тренировочный паттерн связан с качеством первого выстрела.",
            "training_focus": [
                "Перед первым bullet доводить прицел до цели, а не стрелять на полпути.",
                "Отдельно тренировать micro-correction: недовод, перефлик, pre-aim на уровне головы.",
                "В демках проверять не только kill/death, а где именно был crosshair в момент первого выстрела.",
            ],
        },
        {
            "rank": 2,
            "area": "Macro",
            "title": macro_category,
            "why": f"Macro-layer v0.2 чаще всего подсвечивает trade/spacing-сигнал: trade_spacing={macro_trade_spacing}, entry_timing={macro_entry_timing}, low_impact={macro_low_impact}, postplant_retake={macro_postplant}.",
            "training_focus": [
                "Перед контактом понимать, кто тебя сможет разменять.",
                "После kill не оставаться на той же линии бесплатно: уйти за укрытие, сменить угол или заставить второго врага потратить время.",
                "Не путать хороший kill с хорошим решением: если тебя сразу разменивают без пользы для команды, value может быть ниже, чем кажется.",
            ],
        },
        {
            "rank": 3,
            "area": "Utility",
            "title": utility_diagnosis,
            "why": f"Utility-map review показывает, что проблема чаще не в полном miss, а в partial-value: good={utility_good}, partial={utility_partial}, bad={utility_bad}.",
            "training_focus": [
                "Заготовить несколько стабильных смоков/молотов под частые сценарии.",
                "Проверять не только место приземления, но и тайминг: граната может быть правильной, но поздней.",
                "Отдельно собрать lineups/area-layer, чтобы оценивать gaps и закрытие конкретных проходов.",
            ],
        },
    ]

    final_summary = [
        f"Главный mechanics-приоритет: {mechanics_diagnosis}.",
        f"Главный macro-приоритет: {macro_category}; конкретный auto-флаг: {macro_flag}.",
        f"Главный utility-приоритет: {utility_diagnosis}.",
        "Общий вывод: сейчас отчёт начинает видеть не только aim-ошибки, но и контекст раунда. Для практического тренерского продукта следующий важный шаг — ручная калибровка macro top rounds и добавление round-loss patterns.",
    ]

    return {
        "version": VERSION,
        "match_id": match_id,
        "player": player,
        "diagnoses": {
            "mechanics": mechanics_diagnosis,
            "macro": macro_category,
            "macro_flag": macro_flag,
            "utility": utility_diagnosis,
        },
        "signals": {
            "mechanics_actionable": mechanics_actionable,
            "utility_damage": utility_damage,
            "utility_map_quality": {
                "good": utility_good,
                "partial": utility_partial,
                "bad": utility_bad,
            },
            "macro_category_counts": macro_counts,
            "macro_flag_counts": macro_summary.get("macro_flag_counts", {}),
            "macro_top_priority_rounds": macro_summary.get("top_priority_rounds", []),
        },
        "priority_order": priority_order,
        "final_summary": final_summary,
    }


def render_html(payload: dict[str, Any], out_path: Path) -> None:
    diagnoses = payload["diagnoses"]
    signals = payload["signals"]

    priority_cards = ""
    for item in payload["priority_order"]:
        focus = "".join(f"<li>{html.escape(x)}</li>" for x in item.get("training_focus", []))
        priority_cards += f"""
        <div class="card priority">
            <div class="rank">#{item.get("rank")} · {html.escape(item.get("area", ""))}</div>
            <h3>{html.escape(item.get("title", ""))}</h3>
            <p>{html.escape(item.get("why", ""))}</p>
            <ul>{focus}</ul>
        </div>
        """

    final_summary = "".join(f"<li>{html.escape(x)}</li>" for x in payload.get("final_summary", []))

    macro_cat_rows = ""
    for k, v in sorted(signals.get("macro_category_counts", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        macro_cat_rows += f"<tr><td><code>{html.escape(str(k))}</code></td><td>{v}</td></tr>"

    macro_flag_rows = ""
    for k, v in sorted(signals.get("macro_flag_counts", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        macro_flag_rows += f"<tr><td><code>{html.escape(str(k))}</code></td><td>{v}</td></tr>"

    top_rows = ""
    for r in signals.get("macro_top_priority_rounds", [])[:12]:
        top_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(', '.join(r.get('categories') or []))}</td>"
            f"<td>{html.escape(', '.join(r.get('flags') or []))}</td>"
            f"<td>{html.escape('; '.join(r.get('notes') or []))}</td>"
            f"<td>{html.escape(str(r.get('kd_damage') or ''))}</td>"
            "</tr>"
        )

    q = signals.get("utility_map_quality", {})

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Unified Coach Verdict v0.3</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif;
    background: #101114;
    color: #e9edf1;
    margin: 24px;
}}
.muted {{ color: #9aa3ad; }}
.grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
    margin: 18px 0;
}}
.card {{
    background: #181b20;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 16px;
}}
.value {{
    font-size: 19px;
    font-weight: 700;
    margin-top: 6px;
}}
.priority h3 {{ margin-top: 6px; }}
.rank {{ color: #9ec1ff; font-weight: 700; }}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
    font-size: 14px;
}}
th, td {{
    border-bottom: 1px solid #2b3139;
    padding: 8px;
    text-align: left;
    vertical-align: top;
}}
th {{ background: #181b20; color: #c6d2df; }}
code {{ color: #d7e7ff; }}
li {{ margin-bottom: 7px; }}
</style>
</head>
<body>
<h1>Unified Coach Verdict v0.3</h1>
<div class="muted">Match: <code>{html.escape(payload["match_id"])}</code> · Player: <code>{html.escape(payload["player"])}</code></div>

<div class="grid">
    <div class="card"><div class="muted">Mechanics</div><div class="value">{html.escape(diagnoses.get("mechanics", ""))}</div></div>
    <div class="card"><div class="muted">Macro</div><div class="value">{html.escape(diagnoses.get("macro", ""))}</div></div>
    <div class="card"><div class="muted">Macro flag</div><div class="value">{html.escape(diagnoses.get("macro_flag", ""))}</div></div>
    <div class="card"><div class="muted">Utility</div><div class="value">{html.escape(diagnoses.get("utility", ""))}</div></div>
</div>

<h2>Final summary</h2>
<ul>{final_summary}</ul>

<h2>Training priority order</h2>
<div class="grid">{priority_cards}</div>

<h2>Signal details</h2>
<div class="grid">
    <div class="card"><div class="muted">Mechanics actionable</div><div class="value">{html.escape(str(signals.get("mechanics_actionable") or "n/a"))}</div></div>
    <div class="card"><div class="muted">Utility damage</div><div class="value">{html.escape(str(signals.get("utility_damage") or "n/a"))}</div></div>
    <div class="card"><div class="muted">Utility map quality</div><div class="value">good {html.escape(str(q.get("good")))} · partial {html.escape(str(q.get("partial")))} · bad {html.escape(str(q.get("bad")))}</div></div>
</div>

<h2>Macro category counts</h2>
<table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>{macro_cat_rows}</tbody></table>

<h2>Macro flag counts</h2>
<table><thead><tr><th>Flag</th><th>Count</th></tr></thead><tbody>{macro_flag_rows}</tbody></table>

<h2>Top priority macro rounds</h2>
<table>
<thead><tr><th>Round</th><th>Priority</th><th>Categories</th><th>Flags</th><th>Notes</th><th>K/D/Dmg</th></tr></thead>
<tbody>{top_rows}</tbody>
</table>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir
    reports = data_root / "reports" / args.match_id
    reviews = data_root / "reviews" / args.match_id

    paths = {
        "coach_verdict": reports / f"coach_verdict_{args.player}_v0_2.json",
        "manual_summary": reviews / f"manual_review_summary_{args.player}_v0_1.json",
        "utility_analyzer": reports / "utility_analyzer_v0_2.json",
        "utility_map_summary": reports / "utility_map_summary_v0_1.json",
        "macro": reports / f"round_macro_{args.player}_v0_2.json",
        "macro_verdict": reports / f"macro_coach_verdict_{args.player}_v0_1.json",
    }

    print("=== Unified Coach Verdict v0.3 ===")
    for name, path in paths.items():
        print(f"{name}: {path} exists={path.exists()}")

    coach = load_json_optional(paths["coach_verdict"])
    manual = load_json_optional(paths["manual_summary"])
    utility_analyzer = load_json_optional(paths["utility_analyzer"])
    utility_map = load_json_optional(paths["utility_map_summary"])
    macro = load_json_optional(paths["macro"])
    macro_verdict = load_json_optional(paths["macro_verdict"])

    payload = build_unified(
        args.match_id,
        args.player,
        coach,
        manual,
        utility_analyzer,
        utility_map,
        macro,
        macro_verdict,
    )

    reports.mkdir(parents=True, exist_ok=True)
    json_path = reports / f"unified_coach_verdict_{args.player}_v0_3.json"
    html_path = reports / f"unified_coach_verdict_{args.player}_v0_3.html"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(payload, html_path)

    print("")
    print("=== UNIFIED COACH VERDICT v0.3 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print("")
    print(json.dumps(payload["diagnoses"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
