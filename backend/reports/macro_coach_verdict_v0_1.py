from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing input JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verdict_text(summary: dict[str, Any]) -> dict[str, Any]:
    main_category = summary.get("main_macro_category") or ""
    main_flag = summary.get("main_macro_flag") or ""

    category_ru = {
        "trade_spacing": "размены и дистанция от тиммейтов",
        "entry_timing": "первые контакты и вход в раунд",
        "postplant_retake": "post-plant / retake решения",
        "low_impact": "низкий impact в проигранных раундах",
        "positive": "позитивные impact-раунды",
    }

    flag_ru = {
        "opening_death_untraded": "первый death раунда без быстрого размена",
        "death_untraded": "смерти без быстрого размена",
        "entry_kill_then_traded": "после kill тебя быстро разменивают",
        "postplant_death_untraded": "post-plant смерть без размена",
        "retake_no_impact": "retake без impact после plant",
        "postplant_no_impact": "post-plant без impact после plant",
        "low_impact_lost_round": "низкий impact в проигранных раундах",
        "died_before_plant_lost_round": "смерть до plant в проигранном раунде",
    }

    recommendations = []

    if main_category == "trade_spacing":
        recommendations.append("Главная macro-гипотеза: проблема не только в aim, а в дистанции размена. После контакта ты часто остаёшься в ситуации, где тиммейт не может быстро забрать refrag, либо тебя разменивают после собственного kill.")
        recommendations.append("Практический фокус: перед контактом понимать, кто тебя трейдит; после kill сразу менять позицию, уходить за укрытие или заставлять второго врага тратить время.")
    elif main_category == "entry_timing":
        recommendations.append("Главная macro-гипотеза: ранние контакты слишком часто ломают раунд. Особенно опасны opening deaths без размена и смерти до plant в проигранных раундах.")
        recommendations.append("Практический фокус: меньше одиночных ранних дуэлей без flash/тиммейта; чаще играть первый контакт так, чтобы тебя можно было разменять.")
    elif main_category == "postplant_retake":
        recommendations.append("Главная macro-гипотеза: часть value теряется после plant: post-plant/retake решения не дают стабильного impact.")
        recommendations.append("Практический фокус: после plant играть от времени, crossfire и безопасного контакта; на retake — не просто заходить, а создавать trade/utility условие.")
    elif main_category == "low_impact":
        recommendations.append("Главная macro-гипотеза: в части проигранных раундов не хватает раннего value: damage, kill, space или полезной utility.")
        recommendations.append("Практический фокус: найти 2–3 стабильных сценария, где ты почти каждый gun round даёшь measurable impact — flash, molly, damage, инфу или space.")
    else:
        recommendations.append("Macro-сигнал пока недостаточно чистый. Нужно проверить top priority rounds вручную и отделить настоящие ошибки от шумных ситуаций.")

    if main_flag:
        recommendations.append(f"Самый частый конкретный auto-флаг: {flag_ru.get(main_flag, main_flag)}.")

    return {
        "main_macro_category": main_category,
        "main_macro_category_ru": category_ru.get(main_category, main_category or "недостаточно данных"),
        "main_macro_flag": main_flag,
        "main_macro_flag_ru": flag_ru.get(main_flag, main_flag or "недостаточно данных"),
        "recommendations": recommendations,
    }


def render_html(payload: dict[str, Any], out_path: Path) -> None:
    summary = payload["source_summary"]
    verdict = payload["verdict"]

    top_rows = ""
    for r in summary.get("top_priority_rounds", []):
        top_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(', '.join(r.get('categories') or []))}</td>"
            f"<td>{html.escape(', '.join(r.get('flags') or []))}</td>"
            f"<td>{html.escape('; '.join(r.get('notes') or []))}</td>"
            f"<td>{html.escape(str(r.get('kd_damage') or ''))}</td>"
            "</tr>\n"
        )

    recs = "".join(f"<li>{html.escape(x)}</li>" for x in verdict.get("recommendations", []))

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Macro Coach Verdict v0.1</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif;
    background: #101114;
    color: #e9edf1;
    margin: 24px;
}}
.muted {{ color: #9aa3ad; }}
.card {{
    background: #181b20;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 16px;
    margin: 14px 0;
}}
.value {{
    font-size: 22px;
    font-weight: 700;
}}
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
li {{ margin-bottom: 8px; }}
</style>
</head>
<body>
<h1>Macro Coach Verdict v0.1</h1>
<div class="muted">Match: <code>{html.escape(payload["match_id"])}</code> · Player: <code>{html.escape(payload["player"])}</code></div>

<div class="card">
    <div class="muted">Главная macro-категория</div>
    <div class="value">{html.escape(verdict.get("main_macro_category_ru", ""))}</div>
</div>

<div class="card">
    <div class="muted">Главный auto-флаг</div>
    <div class="value">{html.escape(verdict.get("main_macro_flag_ru", ""))}</div>
</div>

<h2>Тренерский вывод</h2>
<ul>{recs}</ul>

<h2>Top priority rounds</h2>
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
    macro_json = data_root / "reports" / args.match_id / f"round_macro_{args.player}_v0_2.json"

    macro = load_json(macro_json)
    summary = macro.get("summary", {})
    verdict = verdict_text(summary)

    payload = {
        "version": "macro_coach_verdict_v0_1",
        "match_id": args.match_id,
        "player": args.player,
        "source_macro_json": str(macro_json),
        "source_summary": summary,
        "verdict": verdict,
    }

    out_dir = data_root / "reports" / args.match_id
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"macro_coach_verdict_{args.player}_v0_1.json"
    html_path = out_dir / f"macro_coach_verdict_{args.player}_v0_1.html"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html(payload, html_path)

    print("=== MACRO COACH VERDICT v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print("")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
