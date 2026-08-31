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

from backend.dashboard.build_dashboard_v0_1 import (  # noqa: E402
    find_latest_report_dir,
    find_primary_player,
    make_dashboard,
)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def esc(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value))


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def rel_link(from_file: Path, to_file: Path) -> str:
    try:
        return os.path.relpath(to_file.resolve(), from_file.parent.resolve()).replace("\\", "/")
    except Exception:
        return str(to_file).replace("\\", "/")


def make_small_moment_rows(moments: list[dict[str, Any]]) -> str:
    if not moments:
        return '<tr><td colspan="8">Нет моментов для вывода.</td></tr>'

    rows: list[str] = []
    for m in moments[:8]:
        categories = ", ".join(str(x) for x in m.get("categories", []))
        rows.append(f"""
        <tr>
            <td>R{esc(m.get("round"))}</td>
            <td>{esc(m.get("tick"))}</td>
            <td>{esc(m.get("target"))}</td>
            <td>{esc(m.get("outcome"))}</td>
            <td>{esc(m.get("delay_ticks"))}</td>
            <td>{esc(fmt(m.get("first_shot_speed")))}</td>
            <td>{esc(fmt(m.get("aim_error_deg")))}</td>
            <td><b>{esc(fmt(m.get("importance_score")))}</b><br><span class="v2-muted">{esc(categories)}</span><br>{esc(m.get("comment"))}</td>
        </tr>
        """)
    return "\n".join(rows)


def build_v2_panel(report_dir: Path, player_name: str, out_path: Path) -> str:
    moments_html_v2 = report_dir / "moments_review_v0_2.html"
    moments_json_v2 = report_dir / "moments_review_v0_2.json"
    moments_html_v1 = report_dir / "moments_review_v0_1.html"
    moments_json_v1 = report_dir / "moments_review_v0_1.json"

    moments_html = moments_html_v2 if moments_html_v2.exists() else moments_html_v1
    moments_json = moments_json_v2 if moments_json_v2.exists() else moments_json_v1
    player_focus_html = report_dir / "player_focus_v0_3.html"
    strict_html = report_dir / "contact_visibility_v0_3_strict.html"
    coach_verdict_html = report_dir / f"coach_verdict_{player_name}_v0_1.html"
    progress_html = ROOT / "data" / "progress" / f"progress_{player_name}_v0_2.html"
    manual_review_html = ROOT / "data" / "reviews" / report_dir.name / f"manual_review_{player_name}_v0_1.html"
    manual_summary_html = ROOT / "data" / "reviews" / report_dir.name / f"manual_review_summary_{player_name}_v0_1.html"

    moments = read_json(moments_json)
    summary = moments.get("summary", {})
    counts = summary.get("category_counts", {})
    top_moments = moments.get("top_moments_overall", [])

    def link_card(title: str, path: Path, note: str) -> str:
        if path.exists():
            href = rel_link(out_path, path)
            return f'<a class="v2-link-card" href="{html.escape(href)}"><b>{html.escape(title)}</b><span>{html.escape(note)}</span></a>'
        return f'<div class="v2-link-card v2-disabled"><b>{html.escape(title)}</b><span>Файл пока не найден: {html.escape(str(path))}</span></div>'

    cards = []
    for key, title in [
        ("late_shot", "Late shot"),
        ("moving_first", "Moving first"),
        ("no_response", "No response"),
        ("shot_first_lost", "Shot first lost"),
        ("large_aim_error", "Large aim error"),
        ("won_but_risky", "Won but risky"),
    ]:
        cards.append(f"""
        <div class="v2-stat">
            <div class="v2-stat-title">{html.escape(title)}</div>
            <div class="v2-stat-value">{esc(counts.get(key, 0))}</div>
        </div>
        """)

    return f"""
    <style>
        .v2-panel {{
            margin: 18px 0 28px 0;
            padding: 18px;
            border: 1px solid #2b3138;
            border-radius: 14px;
            background: #14181d;
        }}
        .v2-title {{
            margin: 0 0 8px 0;
            font-size: 24px;
            color: #f2f2f2;
        }}
        .v2-muted {{
            color: #a7adb5;
            font-size: 12px;
        }}
        .v2-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 10px;
            margin: 16px 0;
        }}
        .v2-stat {{
            border: 1px solid #2b3138;
            background: #1b2026;
            border-radius: 12px;
            padding: 12px;
        }}
        .v2-stat-title {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .v2-stat-value {{
            margin-top: 8px;
            font-size: 26px;
            font-weight: 700;
            color: #f2f2f2;
        }}
        .v2-links {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 10px;
            margin: 16px 0;
        }}
        .v2-link-card {{
            display: block;
            text-decoration: none;
            border: 1px solid #2b3138;
            background: #1b2026;
            border-radius: 12px;
            padding: 12px;
            color: #f2f2f2;
        }}
        .v2-link-card span {{
            display: block;
            margin-top: 6px;
            color: #a7adb5;
            font-size: 12px;
        }}
        .v2-disabled {{
            opacity: 0.55;
        }}
        .v2-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            min-width: 900px;
        }}
        .v2-table th, .v2-table td {{
            border-bottom: 1px solid #2b3138;
            padding: 8px;
            text-align: left;
            vertical-align: top;
            font-size: 13px;
        }}
        .v2-table th {{
            background: #20262d;
            color: #cdd3db;
        }}
    </style>

    <section class="v2-panel">
        <h1 class="v2-title">Dashboard v0.2 — быстрый тренерский обзор</h1>
        <div class="v2-muted">
            Игрок: <b>{html.escape(player_name)}</b> ·
            Report dir: <code>{html.escape(str(report_dir))}</code> ·
            Flagged moments: <b>{esc(summary.get("flagged_moments_total"))}</b> /
            Strict contacts: <b>{esc(summary.get("strict_contact_rows_for_player"))}</b>
        </div>

        <div class="v2-links">
            {link_card("Coach Verdict", coach_verdict_html, "Итоговый калиброванный тренерский вывод")}
            {link_card("Moments Review", moments_html, "Ручная проверка late/moving/no response/shot first lost моментов")}
            {link_card("Manual Review Queue", manual_review_html, "CSV/HTML очередь для ручной разметки спорных моментов")}
            {link_card("Manual Review Summary", manual_summary_html, "Итоги ручной разметки: реальные ошибки, шум, root cause")}
            {link_card("Player Focus v0.3", player_focus_html, "Персональный отчёт по игроку")}
            {link_card("Progress v0.2", progress_html, "Динамика по нескольким демкам")}
            {link_card("Strict Contacts v0.3", strict_html, "Технический strict contact layer")}
        </div>

        <div class="v2-grid">
            {''.join(cards)}
        </div>

        <h2>Top moments from Moments Review</h2>
        <div class="v2-muted">Это не финальный verdict, а лучшие кандидаты для проверки в демке.</div>

        <div style="overflow-x:auto;">
            <table class="v2-table">
                <thead>
                    <tr>
                        <th>Round</th>
                        <th>Tick</th>
                        <th>Target</th>
                        <th>Outcome</th>
                        <th>Delay</th>
                        <th>Speed</th>
                        <th>Aim error</th>
                        <th>Score / tags</th>
                    </tr>
                </thead>
                <tbody>
                    {make_small_moment_rows(top_moments)}
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

    end = html_text.lower().rfind("</body>")
    if end >= 0:
        return html_text[:end] + "\n" + panel + "\n" + html_text[end:]

    return panel + "\n" + html_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Dashboard v0.2 with Moments Review block.")
    parser.add_argument("--match-id", default=None, help="Report directory name inside data/reports, e.g. example_match")
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
    player_name = find_primary_player(players, args.player)

    out_path = Path(args.out).resolve() if args.out else ROOT / "data" / "dashboard" / "dashboard_v0_2.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    make_dashboard(report_dir, player_name, out_path)

    base_html = out_path.read_text(encoding="utf-8")
    panel = build_v2_panel(report_dir, player_name, out_path)
    final_html = inject_after_body(base_html, panel)
    out_path.write_text(final_html, encoding="utf-8")

    print("OK: Dashboard v0.2 created")
    print(f"  Player: {player_name}")
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




