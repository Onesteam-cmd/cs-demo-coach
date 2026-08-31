from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def safe_load_json(path: Path) -> dict[str, Any]:
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

    old_dashboard = data_root / "dashboard" / "dashboard_v0_4.html"
    out_dashboard = data_root / "dashboard" / "dashboard_v0_5.html"
    out_dashboard.parent.mkdir(parents=True, exist_ok=True)

    macro_json = data_root / "reports" / args.match_id / f"round_macro_{args.player}_v0_1.json"
    macro_html = data_root / "reports" / args.match_id / f"round_macro_{args.player}_v0_1.html"
    macro = safe_load_json(macro_json)
    summary = macro.get("summary", {})

    flag_rows = ""
    for k, v in sorted(summary.get("macro_flag_counts", {}).items(), key=lambda kv: (-kv[1], kv[0])):
        flag_rows += f"<tr><td><code>{html.escape(str(k))}</code></td><td>{v}</td></tr>\n"

    top_rows = ""
    for r in summary.get("top_priority_rounds", []):
        top_rows += (
            "<tr>"
            f"<td>R{r.get('round_num')}</td>"
            f"<td>{r.get('priority_score')}</td>"
            f"<td>{html.escape(', '.join(r.get('flags', [])))}</td>"
            f"<td>{html.escape('; '.join(r.get('notes', [])))}</td>"
            "</tr>\n"
        )

    old_exists = old_dashboard.exists()
    macro_exists = macro_html.exists()

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach Dashboard v0.5</title>
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
    th {{
        color: #c6d2df;
        background: #181b20;
    }}
    iframe {{
        width: 100%;
        height: 900px;
        border: 0;
        background: white;
    }}
    .section {{
        padding: 20px 24px;
    }}
    code {{ color: #d7e7ff; }}
</style>
</head>
<body>
<div class="top">
    <h1>CS Demo Coach Dashboard v0.5</h1>
    <div class="muted">
        Match: <code>{html.escape(args.match_id)}</code> · Player: <code>{html.escape(args.player)}</code>
    </div>

    <div class="buttons">
        {"<a class='button' href='../reports/" + html.escape(args.match_id) + "/round_macro_" + html.escape(args.player) + "_v0_1.html'>Round Macro Analyzer</a>" if macro_exists else ""}
        {"<a class='button' href='dashboard_v0_4.html'>Dashboard v0.4</a>" if old_exists else ""}
        <a class='button' href='../reports/{html.escape(args.match_id)}'>Reports folder</a>
        <a class='button' href='../reviews/{html.escape(args.match_id)}'>Reviews folder</a>
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Macro rounds</div><div class="value">{summary.get("rounds_total", "n/a")}</div></div>
        <div class="card"><div class="muted">Plant rounds</div><div class="value">{summary.get("plant_rounds", "n/a")}</div></div>
        <div class="card"><div class="muted">Win / loss</div><div class="value">{summary.get("win_loss", {}).get("wins", 0)} / {summary.get("win_loss", {}).get("losses", 0)}</div></div>
        <div class="card"><div class="muted">Main macro problem</div><div class="value" style="font-size:18px">{html.escape(str(summary.get("main_macro_problem") or "not enough signal"))}</div></div>
    </div>
</div>

<div class="section">
    <h2>Round Macro Summary</h2>
    <p class="muted">v0.5 добавляет первый macro-layer поверх стабильного dashboard v0.4. Старые отчёты не изменены.</p>

    <h3>Flag counts</h3>
    <table>
        <thead><tr><th>Flag</th><th>Count</th></tr></thead>
        <tbody>{flag_rows}</tbody>
    </table>

    <h3>Top priority macro rounds</h3>
    <table>
        <thead><tr><th>Round</th><th>Priority</th><th>Flags</th><th>Notes</th></tr></thead>
        <tbody>{top_rows}</tbody>
    </table>
</div>

<div class="section">
    <h2>Previous stable dashboard v0.4</h2>
    {"<iframe src='dashboard_v0_4.html'></iframe>" if old_exists else "<p class='muted'>dashboard_v0_4.html not found.</p>"}
</div>
</body>
</html>
"""

    out_dashboard.write_text(html_text, encoding="utf-8")
    print("=== DASHBOARD v0.5 COMPLETE ===")
    print(f"Dashboard v0.5: {out_dashboard}")
    print(f"Macro JSON: {macro_json}")
    print(f"Macro HTML: {macro_html}")


if __name__ == "__main__":
    main()
