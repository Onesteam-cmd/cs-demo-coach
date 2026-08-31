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

    macro_json = data_root / "reports" / args.match_id / f"round_macro_{args.player}_v0_2.json"
    verdict_json = data_root / "reports" / args.match_id / f"macro_coach_verdict_{args.player}_v0_1.json"

    macro = load_json(macro_json)
    verdict_payload = load_json(verdict_json)

    summary = macro.get("summary", {})
    verdict = verdict_payload.get("verdict", {})

    out_path = data_root / "dashboard" / "dashboard_v0_6.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    category_rows = ""
    for k, v in sorted(summary.get("macro_category_counts", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        category_rows += f"<tr><td><code>{html.escape(str(k))}</code></td><td>{v}</td></tr>"

    top_rows = ""
    for r in summary.get("top_priority_rounds", []):
        top_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(', '.join(r.get('categories') or []))}</td>"
            f"<td>{html.escape(', '.join(r.get('flags') or []))}</td>"
            f"<td>{html.escape('; '.join(r.get('notes') or []))}</td>"
            "</tr>"
        )

    recs = "".join(f"<li>{html.escape(x)}</li>" for x in verdict.get("recommendations", []))

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach Dashboard v0.6</title>
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
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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
    font-size: 24px;
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
iframe {{
    width: 100%;
    height: 720px;
    border: 0;
    background: white;
}}
li {{ margin-bottom: 8px; }}
</style>
</head>
<body>
<div class="top">
    <h1>CS Demo Coach Dashboard v0.6</h1>
    <div class="muted">Match: <code>{html.escape(args.match_id)}</code> · Player: <code>{html.escape(args.player)}</code></div>

    <div class="buttons">
        <a class="button" href="../reports/{html.escape(args.match_id)}/round_macro_{html.escape(args.player)}_v0_2.html">Round Macro v0.2</a>
        <a class="button" href="../reports/{html.escape(args.match_id)}/macro_coach_verdict_{html.escape(args.player)}_v0_1.html">Macro Coach Verdict</a>
        <a class="button" href="dashboard_v0_5.html">Dashboard v0.5</a>
        <a class="button" href="dashboard_v0_4.html">Dashboard v0.4</a>
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Macro rounds</div><div class="value">{summary.get("rounds_total", "n/a")}</div></div>
        <div class="card"><div class="muted">Plant rounds</div><div class="value">{summary.get("plant_rounds", "n/a")}</div></div>
        <div class="card"><div class="muted">Main category</div><div class="value" style="font-size:18px">{html.escape(str(verdict.get("main_macro_category_ru") or summary.get("main_macro_category") or "n/a"))}</div></div>
        <div class="card"><div class="muted">Main flag</div><div class="value" style="font-size:18px">{html.escape(str(verdict.get("main_macro_flag_ru") or summary.get("main_macro_flag") or "n/a"))}</div></div>
    </div>
</div>

<div class="section">
    <h2>Macro Coach Verdict</h2>
    <ul>{recs}</ul>

    <h2>Macro category counts</h2>
    <table>
        <thead><tr><th>Category</th><th>Count</th></tr></thead>
        <tbody>{category_rows}</tbody>
    </table>

    <h2>Top priority macro rounds</h2>
    <table>
        <thead><tr><th>Round</th><th>Priority</th><th>Categories</th><th>Flags</th><th>Notes</th></tr></thead>
        <tbody>{top_rows}</tbody>
    </table>
</div>

<div class="section">
    <h2>Round Macro v0.2 preview</h2>
    <iframe src="../reports/{html.escape(args.match_id)}/round_macro_{html.escape(args.player)}_v0_2.html"></iframe>
</div>
</body>
</html>
"""

    out_path.write_text(html_text, encoding="utf-8")

    print("=== DASHBOARD v0.6 COMPLETE ===")
    print(f"Dashboard v0.6: {out_path}")


if __name__ == "__main__":
    main()
