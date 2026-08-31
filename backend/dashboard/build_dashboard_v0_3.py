from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


ROOT = repo_root()
sys.path.insert(0, str(ROOT))

from backend.dashboard.build_dashboard_v0_2 import main as build_v02_main  # noqa: E402
from backend.dashboard.build_dashboard_v0_1 import find_latest_report_dir, find_primary_player  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def rel_link(from_file: Path, to_file: Path) -> str:
    try:
        return os.path.relpath(to_file.resolve(), from_file.parent.resolve()).replace("\\", "/")
    except Exception:
        return str(to_file).replace("\\", "/")


def render_training(plan: list[dict[str, Any]]) -> str:
    if not plan:
        return '<tr><td colspan="3">Coach Verdict ещё не содержит training plan.</td></tr>'

    rows = []

    for item in plan[:5]:
        drills = item.get("drills", [])
        drill_html = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in drills[:3]) + "</ul>" if drills else "—"

        rows.append(f"""
        <tr>
            <td>
                <b>{esc(item.get("label"))}</b><br>
                <span class="cv-muted">{esc(item.get("root_cause"))}</span>
            </td>
            <td>{esc(item.get("count"))}</td>
            <td>{drill_html}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_examples(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return '<tr><td colspan="7">Нет примеров.</td></tr>'

    rows = []

    for row in examples[:8]:
        rows.append(f"""
        <tr>
            <td>R{esc(row.get("round"))}</td>
            <td>{esc(row.get("tick"))}</td>
            <td>{esc(row.get("target"))}</td>
            <td>{esc(row.get("outcome"))}</td>
            <td>{esc(row.get("importance_score"))}</td>
            <td>{esc(row.get("root_cause"))}</td>
            <td>{esc(row.get("coach_note"))}</td>
        </tr>
        """)

    return "\n".join(rows)


def build_coach_verdict_panel(report_dir: Path, player: str, out_path: Path) -> str:
    verdict_path_v2 = report_dir / f"coach_verdict_{player}_v0_2.json"
    verdict_html_v2 = report_dir / f"coach_verdict_{player}_v0_2.html"
    verdict_path_v1 = report_dir / f"coach_verdict_{player}_v0_1.json"
    verdict_html_v1 = report_dir / f"coach_verdict_{player}_v0_1.html"

    verdict_path = verdict_path_v2 if verdict_path_v2.exists() else verdict_path_v1
    verdict_html = verdict_html_v2 if verdict_html_v2.exists() else verdict_html_v1
    utility_html = report_dir / "utility_analyzer_v0_2.html"
    utility_map_html = report_dir / "utility_map_review_v0_1.html"
    utility_map_summary_html = report_dir / "utility_map_summary_v0_1.html"

    if not verdict_path.exists():
        return f"""
        <section class="cv-panel">
            <h1 class="cv-title">Coach Verdict</h1>
            <p class="cv-muted">Coach Verdict ещё не создан: <code>{esc(verdict_path)}</code></p>
        </section>
        """

    data = read_json(verdict_path)

    verdict_link = rel_link(out_path, verdict_html) if verdict_html.exists() else "#"

    interpretation = "".join(
        f"<li>{esc(x)}</li>"
        for x in data.get("interpretation", []) or data.get("final_summary", [])
    )

    manual = data.get("manual_summary", {}) or data.get("mechanics", {}).get("manual_summary", {})

    return f"""
    <style>
        .cv-panel {{
            margin: 0 0 28px 0;
            padding: 22px;
            border: 1px solid #2b3138;
            border-radius: 16px;
            background: #12161b;
        }}
        .cv-title {{
            margin: 0 0 8px 0;
            font-size: 28px;
            color: #f2f2f2;
        }}
        .cv-muted {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .cv-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 12px;
            margin: 18px 0;
        }}
        .cv-card {{
            background: #1a1d21;
            border: 1px solid #2b3138;
            border-radius: 12px;
            padding: 14px;
        }}
        .cv-card-title {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .cv-card-value {{
            margin-top: 8px;
            font-size: 22px;
            font-weight: 700;
            line-height: 1.2;
        }}
        .cv-good {{
            color: #b7f5bd;
        }}
        .cv-warn {{
            color: #ffd18a;
        }}
        .cv-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            min-width: 980px;
        }}
        .cv-table th, .cv-table td {{
            border-bottom: 1px solid #2b3138;
            padding: 8px;
            text-align: left;
            vertical-align: top;
            font-size: 13px;
        }}
        .cv-table th {{
            background: #1e2329;
            color: #cdd3db;
        }}
        .cv-subsection {{
            margin-top: 20px;
            background: #15181c;
            border: 1px solid #2b3138;
            border-radius: 14px;
            padding: 16px;
            overflow-x: auto;
        }}
        .cv-button {{
            display: inline-block;
            margin-top: 10px;
            padding: 9px 12px;
            border-radius: 10px;
            background: #2b5cff;
            color: white;
            text-decoration: none;
            font-weight: 700;
        }}
    </style>

    <section class="cv-panel">
        <h1 class="cv-title">Coach Verdict — калиброванный тренерский вывод</h1>
        <p class="cv-muted">
            Этот блок учитывает автоматический анализ, Moments Review и твою ручную проверку.
            <a class="cv-button" href="{esc(verdict_link)}">Открыть полный Coach Verdict</a>
            <a class="cv-button" href="{esc(rel_link(out_path, utility_html))}">Открыть Utility Analyzer</a>
            <a class="cv-button" href="{esc(rel_link(out_path, utility_map_html))}">Открыть Utility Map Review</a>
            <a class="cv-button" href="{esc(rel_link(out_path, utility_map_summary_html))}">Открыть Utility Map Summary</a>
        </p>

        <div class="cv-grid">
            <div class="cv-card">
                <div class="cv-card-title">Auto diagnosis</div>
                <div class="cv-card-value cv-warn">{esc(data.get("auto_main_diagnosis") or data.get("mechanics", {}).get("auto_main_diagnosis"))}</div>
            </div>
            <div class="cv-card">
                <div class="cv-card-title">Calibrated diagnosis</div>
                <div class="cv-card-value cv-good">{esc(data.get("calibrated_main_diagnosis") or data.get("mechanics", {}).get("calibrated_main_diagnosis"))}</div>
            </div>
            <div class="cv-card">
                <div class="cv-card-title">Primary root cause</div>
                <div class="cv-card-value">{esc(data.get("primary_root_cause") or data.get("mechanics", {}).get("primary_root_cause"))} ({esc(data.get("primary_root_count") or data.get("mechanics", {}).get("primary_root_count"))})</div>
            </div>
            <div class="cv-card">
                <div class="cv-card-title">Actionable</div>
                <div class="cv-card-value">{esc(manual.get("actionable_yes_or_partial_keep"))}</div>
            </div>
            <div class="cv-card">
                <div class="cv-card-title">Clean training</div>
                <div class="cv-card-value">{esc(manual.get("clean_training_examples"))}</div>
            </div>
            <div class="cv-card">
                <div class="cv-card-title">Noise / not real</div>
                <div class="cv-card-value">{esc(manual.get("not_real_or_noise"))}</div>
            </div>
        </div>

        <div class="cv-subsection">
            <h2>Короткий вывод</h2>
            <ul>{interpretation}</ul>
        </div>

        <div class="cv-subsection">
            <h2>Главные тренировки</h2>
            <table class="cv-table">
                <thead>
                    <tr>
                        <th>Проблема</th>
                        <th>Count</th>
                        <th>Что делать</th>
                    </tr>
                </thead>
                <tbody>
                    {render_training(data.get("training_plan", []) or data.get("mechanics", {}).get("training_plan", []))}
                </tbody>
            </table>
        </div>

        <div class="cv-subsection">
            <h2>Лучшие примеры для разбора</h2>
            <table class="cv-table">
                <thead>
                    <tr>
                        <th>Round</th>
                        <th>Tick</th>
                        <th>Target</th>
                        <th>Outcome</th>
                        <th>Priority</th>
                        <th>Root cause</th>
                        <th>Coach note</th>
                    </tr>
                </thead>
                <tbody>
                    {render_examples(data.get("top_actionable_examples", []) or data.get("mechanics", {}).get("top_actionable_examples", []))}
                </tbody>
            </table>
        </div>
    </section>
    """


def inject_after_body(html_text: str, panel: str) -> str:
    marker = "<body>"
    idx = html_text.lower().find(marker)
    if idx >= 0:
        insert_at = idx + len(marker)
        return html_text[:insert_at] + "\n" + panel + "\n" + html_text[insert_at:]

    return panel + "\n" + html_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Dashboard v0.3 with Coach Verdict as main block.")
    parser.add_argument("--match-id", default=None)
    parser.add_argument("--player", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if args.match_id:
        report_dir = ROOT / "data" / "reports" / args.match_id
    else:
        report_dir = find_latest_report_dir(args.player)

    if not report_dir.exists():
        raise SystemExit(f"Report dir not found: {report_dir}")

    focus = read_json(report_dir / "player_focus_v0_3.json")
    players = focus.get("players", [])
    player = find_primary_player(players, args.player)

    out_path = Path(args.out).resolve() if args.out else ROOT / "data" / "dashboard" / "dashboard_v0_3.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build v0.2 first into the v0.3 output file.
    old_argv = sys.argv[:]
    sys.argv = [
        "build_dashboard_v0_2.py",
        "--match-id",
        report_dir.name,
        "--player",
        player,
        "--out",
        str(out_path),
        "--no-open",
    ]
    try:
        build_v02_main()
    finally:
        sys.argv = old_argv

    html_text = out_path.read_text(encoding="utf-8")
    panel = build_coach_verdict_panel(report_dir, player, out_path)
    final_html = inject_after_body(html_text, panel)
    out_path.write_text(final_html, encoding="utf-8")

    print("OK: Dashboard v0.3 created")
    print(f"  Player: {player}")
    print(f"  Report dir: {report_dir}")
    print(f"  HTML: {out_path}")

    if not args.no_open:
        try:
            os.startfile(str(out_path))
            print(f"  Opened: {out_path}")
        except Exception as exc:
            print(f"  Created but not opened automatically: {exc}")


if __name__ == "__main__":
    main()




