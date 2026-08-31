from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    verdict_json = data_root / "reports" / args.match_id / f"unified_coach_verdict_{args.player}_v0_3.json"
    verdict = load_json(verdict_json)

    diagnoses = verdict.get("diagnoses", {})
    signals = verdict.get("signals", {})
    priority = verdict.get("priority_order", [])
    summary = verdict.get("final_summary", [])

    out_path = data_root / "dashboard" / "dashboard_v0_7.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary_html = "".join(f"<li>{html.escape(x)}</li>" for x in summary)

    priority_rows = ""
    for p in priority:
        focus = "<br>".join(html.escape(x) for x in p.get("training_focus", []))
        priority_rows += (
            "<tr>"
            f"<td>#{p.get('rank')}</td>"
            f"<td>{html.escape(p.get('area', ''))}</td>"
            f"<td>{html.escape(p.get('title', ''))}</td>"
            f"<td>{html.escape(p.get('why', ''))}</td>"
            f"<td>{focus}</td>"
            "</tr>"
        )

    macro_top = signals.get("macro_top_priority_rounds", [])
    macro_rows = ""
    for r in macro_top[:10]:
        macro_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(', '.join(r.get('categories') or []))}</td>"
            f"<td>{html.escape(', '.join(r.get('flags') or []))}</td>"
            f"<td>{html.escape('; '.join(r.get('notes') or []))}</td>"
            "</tr>"
        )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach Dashboard v0.7</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif;
    margin: 0;
    background: #0f1115;
    color: #e9edf1;
}}
.top {{
    padding: 20px 24px;
    border-bottom: 1px solid #2b3139;
    background: #141820;
}}
.section {{ padding: 20px 24px; }}
.muted {{ color: #9aa3ad; }}
.buttons {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 14px;
}}
a.button {{
    display: inline-block;
    padding: 10px 12px;
    border-radius: 10px;
    background: #202734;
    border: 1px solid #354052;
    color: #dbe9ff;
    text-decoration: none;
}}
.grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
    margin-top: 16px;
}}
.card {{
    background: #191e27;
    border: 1px solid #2f3847;
    border-radius: 12px;
    padding: 14px;
}}
.value {{
    font-size: 19px;
    font-weight: 700;
    margin-top: 5px;
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
li {{ margin-bottom: 7px; }}
iframe {{
    width: 100%;
    height: 760px;
    border: 0;
    background: white;
}}
</style>
</head>
<body>
<div class="top">
    <h1>CS Demo Coach Dashboard v0.7</h1>
    <div class="muted">Match: <code>{html.escape(args.match_id)}</code> · Player: <code>{html.escape(args.player)}</code></div>

    <div class="buttons">
        <a class="button" href="../reports/{html.escape(args.match_id)}/unified_coach_verdict_{html.escape(args.player)}_v0_3.html">Unified Coach Verdict</a>
        <a class="button" href="../reports/{html.escape(args.match_id)}/round_macro_{html.escape(args.player)}_v0_2.html">Round Macro v0.2</a>
        <a class="button" href="../reports/{html.escape(args.match_id)}/macro_coach_verdict_{html.escape(args.player)}_v0_1.html">Macro Coach Verdict</a>
        <a class="button" href="dashboard_v0_6.html">Dashboard v0.6</a>
        <a class="button" href="dashboard_v0_4.html">Dashboard v0.4 stable</a>
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Mechanics</div><div class="value">{html.escape(str(diagnoses.get("mechanics", "n/a")))}</div></div>
        <div class="card"><div class="muted">Macro</div><div class="value">{html.escape(str(diagnoses.get("macro", "n/a")))}</div></div>
        <div class="card"><div class="muted">Utility</div><div class="value">{html.escape(str(diagnoses.get("utility", "n/a")))}</div></div>
        <div class="card"><div class="muted">Macro flag</div><div class="value">{html.escape(str(diagnoses.get("macro_flag", "n/a")))}</div></div>
    </div>
</div>

<div class="section">
    <h2>Final Coach Summary</h2>
    <ul>{summary_html}</ul>

    <h2>Training Priority Order</h2>
    <table>
        <thead><tr><th>Rank</th><th>Area</th><th>Diagnosis</th><th>Why</th><th>Training focus</th></tr></thead>
        <tbody>{priority_rows}</tbody>
    </table>

    <h2>Macro top priority rounds</h2>
    <table>
        <thead><tr><th>Round</th><th>Priority</th><th>Categories</th><th>Flags</th><th>Notes</th></tr></thead>
        <tbody>{macro_rows}</tbody>
    </table>
</div>

<div class="section">
    <h2>Unified Verdict Preview</h2>
    <iframe src="../reports/{html.escape(args.match_id)}/unified_coach_verdict_{html.escape(args.player)}_v0_3.html"></iframe>
</div>
</body>
</html>
"""

    out_path.write_text(html_text, encoding="utf-8")

    print("=== DASHBOARD v0.7 COMPLETE ===")
    print(f"Dashboard v0.7: {out_path}")


if __name__ == "__main__":
    main()
