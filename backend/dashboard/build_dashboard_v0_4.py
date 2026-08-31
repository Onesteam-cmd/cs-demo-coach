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


def link_button(out_path: Path, target: Path, label: str) -> str:
    if not target.exists():
        return f'<span class="cv4-button cv4-disabled">{esc(label)} — нет файла</span>'
    return f'<a class="cv4-button" href="{esc(rel_link(out_path, target))}">{esc(label)}</a>'


def render_list(items: list[Any]) -> str:
    if not items:
        return "<li>Нет данных.</li>"
    return "".join(f"<li>{esc(x)}</li>" for x in items)


def render_training(plan: list[dict[str, Any]]) -> str:
    if not plan:
        return '<tr><td colspan="3">Нет mechanics training plan.</td></tr>'

    rows = []
    for item in plan[:6]:
        drills = item.get("drills", [])
        drill_html = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in drills[:3]) + "</ul>" if drills else "—"

        rows.append(f"""
        <tr>
            <td>
                <b>{esc(item.get("label"))}</b><br>
                <span class="cv4-muted">{esc(item.get("root_cause"))}</span>
            </td>
            <td>{esc(item.get("count"))}</td>
            <td>{drill_html}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_utility_recommendations(recs: list[dict[str, Any]]) -> str:
    if not recs:
        return '<tr><td colspan="3">Нет utility recommendations.</td></tr>'

    rows = []
    for item in recs[:8]:
        rows.append(f"""
        <tr>
            <td>{esc(item.get("problem"))}</td>
            <td>{esc(item.get("count"))}</td>
            <td>{esc(item.get("recommendation"))}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_examples(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="7">Нет примеров.</td></tr>'

    out = []
    for row in rows[:8]:
        out.append(f"""
        <tr>
            <td>R{esc(row.get("round"))}</td>
            <td>{esc(row.get("tick") or row.get("start_tick"))}</td>
            <td>{esc(row.get("target") or row.get("utility_type"))}</td>
            <td>{esc(row.get("outcome") or row.get("quality"))}</td>
            <td>{esc(row.get("root_cause") or row.get("problem"))}</td>
            <td>{esc(row.get("categories") or row.get("intended_purpose"))}</td>
            <td>{esc(row.get("coach_note"))}</td>
        </tr>
        """)

    return "\n".join(out)


def choose_verdict(report_dir: Path, player: str) -> tuple[Path, Path, dict[str, Any]]:
    v2_json = report_dir / f"coach_verdict_{player}_v0_2.json"
    v2_html = report_dir / f"coach_verdict_{player}_v0_2.html"
    v1_json = report_dir / f"coach_verdict_{player}_v0_1.json"
    v1_html = report_dir / f"coach_verdict_{player}_v0_1.html"

    if v2_json.exists():
        return v2_json, v2_html, read_json(v2_json)

    return v1_json, v1_html, read_json(v1_json)


def build_v4_panel(report_dir: Path, player: str, out_path: Path) -> str:
    verdict_json, verdict_html, data = choose_verdict(report_dir, player)

    utility_html = report_dir / "utility_analyzer_v0_2.html"
    utility_map_html = report_dir / "utility_map_review_v0_1.html"
    utility_map_summary_html = report_dir / "utility_map_summary_v0_1.html"
    moments_html = report_dir / "moments_review_v0_2.html"
    manual_summary_html = ROOT / "data" / "reviews" / report_dir.name / f"manual_review_summary_{player}_v0_1.html"
    progress_html = ROOT / "data" / "progress" / f"progress_{player}_v0_2.html"

    if not data:
        return f"""
        <section class="cv4-panel">
            <h1 class="cv4-title">Coach Dashboard v0.4</h1>
            <p class="cv4-muted">Coach Verdict не найден: <code>{esc(verdict_json)}</code></p>
        </section>
        """

    # v0.2 shape
    mechanics = data.get("mechanics", {})
    utility = data.get("utility", {})

    # v0.1 fallback
    if not mechanics:
        mechanics = {
            "auto_main_diagnosis": data.get("auto_main_diagnosis"),
            "calibrated_main_diagnosis": data.get("calibrated_main_diagnosis"),
            "primary_root_cause": data.get("primary_root_cause"),
            "primary_root_count": data.get("primary_root_count"),
            "manual_summary": data.get("manual_summary", {}),
            "training_plan": data.get("training_plan", []),
            "top_actionable_examples": data.get("top_actionable_examples", []),
        }

    if not utility:
        utility = {
            "calibrated_utility_diagnosis": "Utility слой ещё не подключён",
            "utility_rank": None,
            "players_total": None,
            "primary_player_summary": {},
            "map_summary": {},
            "recommendations": [],
            "useful_examples": [],
        }

    manual = mechanics.get("manual_summary", {})
    utility_primary = utility.get("primary_player_summary", {})
    map_summary = utility.get("map_summary", {})

    final_summary = data.get("final_summary") or data.get("interpretation") or []

    return f"""
    <style>
        .cv4-panel {{
            margin: 0 0 28px 0;
            padding: 22px;
            border: 1px solid #2b3138;
            border-radius: 16px;
            background: #12161b;
        }}
        .cv4-title {{
            margin: 0 0 8px 0;
            font-size: 30px;
            color: #f2f2f2;
        }}
        .cv4-muted {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .cv4-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 16px 0;
        }}
        .cv4-button {{
            display: inline-block;
            padding: 9px 12px;
            border-radius: 10px;
            background: #2b5cff;
            color: white;
            text-decoration: none;
            font-weight: 700;
            font-size: 13px;
        }}
        .cv4-disabled {{
            background: #3a3f48;
            color: #a7adb5;
        }}
        .cv4-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 12px;
            margin: 18px 0;
        }}
        .cv4-card {{
            background: #1a1d21;
            border: 1px solid #2b3138;
            border-radius: 12px;
            padding: 14px;
        }}
        .cv4-card-title {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .cv4-card-value {{
            margin-top: 8px;
            font-size: 22px;
            font-weight: 700;
            line-height: 1.2;
        }}
        .cv4-good {{
            color: #b7f5bd;
        }}
        .cv4-warn {{
            color: #ffd18a;
        }}
        .cv4-subsection {{
            margin-top: 20px;
            background: #15181c;
            border: 1px solid #2b3138;
            border-radius: 14px;
            padding: 16px;
            overflow-x: auto;
        }}
        .cv4-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            min-width: 980px;
        }}
        .cv4-table th, .cv4-table td {{
            border-bottom: 1px solid #2b3138;
            padding: 8px;
            text-align: left;
            vertical-align: top;
            font-size: 13px;
        }}
        .cv4-table th {{
            background: #1e2329;
            color: #cdd3db;
        }}
        .cv4-panel li {{
            margin-bottom: 8px;
        }}
    </style>

    <section class="cv4-panel">
        <h1 class="cv4-title">Coach Dashboard v0.4 — финальный обзор</h1>
        <p class="cv4-muted">
            Match: <code>{esc(report_dir.name)}</code> · Player: <code>{esc(player)}</code><br>
            Главный экран теперь объединяет mechanics, utility, manual review и калиброванные выводы.
        </p>

        <div class="cv4-buttons">
            {link_button(out_path, verdict_html, "Coach Verdict v0.2")}
            {link_button(out_path, utility_html, "Utility Analyzer")}
            {link_button(out_path, utility_map_html, "Utility Map Review")}
            {link_button(out_path, utility_map_summary_html, "Utility Map Summary")}
            {link_button(out_path, moments_html, "Moments Review")}
            {link_button(out_path, manual_summary_html, "Manual Summary")}
            {link_button(out_path, progress_html, "Progress")}
        </div>

        <div class="cv4-grid">
            <div class="cv4-card">
                <div class="cv4-card-title">Mechanics diagnosis</div>
                <div class="cv4-card-value cv4-good">{esc(mechanics.get("calibrated_main_diagnosis"))}</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Utility diagnosis</div>
                <div class="cv4-card-value cv4-warn">{esc(utility.get("calibrated_utility_diagnosis"))}</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Primary mechanics root</div>
                <div class="cv4-card-value">{esc(mechanics.get("primary_root_cause"))} ({esc(mechanics.get("primary_root_count"))})</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Utility rank</div>
                <div class="cv4-card-value">{esc(utility.get("utility_rank"))}/{esc(utility.get("players_total"))}</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Utility damage</div>
                <div class="cv4-card-value">{esc(utility_primary.get("utility_damage_dealt"))}</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Utility map quality</div>
                <div class="cv4-card-value">good {esc(map_summary.get("good"))} · partial {esc(map_summary.get("partial"))} · bad {esc(map_summary.get("bad"))}</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Mechanics actionable</div>
                <div class="cv4-card-value">{esc(manual.get("actionable_yes_or_partial_keep"))}</div>
            </div>
            <div class="cv4-card">
                <div class="cv4-card-title">Mechanics noise/not real</div>
                <div class="cv4-card-value">{esc(manual.get("not_real_or_noise"))}</div>
            </div>
        </div>

        <div class="cv4-subsection">
            <h2>Final summary</h2>
            <ul>{render_list(final_summary)}</ul>
        </div>

        <div class="cv4-subsection">
            <h2>Mechanics training plan</h2>
            <table class="cv4-table">
                <thead><tr><th>Проблема</th><th>Count</th><th>Что делать</th></tr></thead>
                <tbody>{render_training(mechanics.get("training_plan", []))}</tbody>
            </table>
        </div>

        <div class="cv4-subsection">
            <h2>Utility recommendations</h2>
            <table class="cv4-table">
                <thead><tr><th>Problem</th><th>Count</th><th>Recommendation</th></tr></thead>
                <tbody>{render_utility_recommendations(utility.get("recommendations", []))}</tbody>
            </table>
        </div>

        <div class="cv4-subsection">
            <h2>Top mechanics examples</h2>
            <table class="cv4-table">
                <thead><tr><th>Round</th><th>Tick</th><th>Target</th><th>Outcome</th><th>Root/problem</th><th>Tags/purpose</th><th>Coach note</th></tr></thead>
                <tbody>{render_examples(mechanics.get("top_actionable_examples", []))}</tbody>
            </table>
        </div>

        <div class="cv4-subsection">
            <h2>Top utility examples</h2>
            <table class="cv4-table">
                <thead><tr><th>Round</th><th>Tick</th><th>Type</th><th>Quality</th><th>Problem</th><th>Purpose</th><th>Coach note</th></tr></thead>
                <tbody>{render_examples(utility.get("useful_examples", []))}</tbody>
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
    parser = argparse.ArgumentParser(description="Build Dashboard v0.4 unified coach dashboard.")
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
    player = find_primary_player(focus.get("players", []), args.player)

    out_path = Path(args.out).resolve() if args.out else ROOT / "data" / "dashboard" / "dashboard_v0_4.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

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

    base_html = out_path.read_text(encoding="utf-8")
    panel = build_v4_panel(report_dir, player, out_path)
    out_path.write_text(inject_after_body(base_html, panel), encoding="utf-8")

    print("OK: Dashboard v0.4 created")
    print(f"  Player: {player}")
    print(f"  Report dir: {report_dir}")
    print(f"  HTML: {out_path}")

    if not args.no_open:
        os.startfile(str(out_path))
        print(f"  Opened: {out_path}")


if __name__ == "__main__":
    main()
