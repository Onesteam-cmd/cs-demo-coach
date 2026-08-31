from __future__ import annotations

import argparse
import csv
import html
import json
import os
from pathlib import Path
from typing import Any


MANUAL_FIELDS = [
    "review_status",
    "manual_visible",
    "real_issue",
    "noise_reason",
    "root_cause",
    "coach_note",
    "keep_for_training",
]

BASE_FIELDS = [
    "moment_id",
    "match_id",
    "player",
    "round",
    "tick",
    "end_tick",
    "target",
    "outcome",
    "first_shooter",
    "delay_ticks",
    "first_shot_speed",
    "first_shot_error_deg",
    "start_error_deg",
    "distance",
    "weapon",
    "importance_score",
    "categories",
    "comment",
    "demo_hint",
    "strict_tags",
]

ROOT_CAUSE_OPTIONS = [
    "",
    "true_late_shot",
    "bad_counter_strafe",
    "moving_first",
    "bad_pre_aim",
    "large_first_shot_error",
    "no_response_back_turned",
    "no_response_flash",
    "no_response_grenade_or_reload",
    "no_response_bad_timing",
    "bad_duel_choice",
    "overpeek",
    "enemy_timing",
    "visibility_noise",
    "wall_or_smoke_noise",
    "unknown",
]

NOISE_OPTIONS = [
    "",
    "not_noise",
    "contact_before_real_visibility",
    "through_wall",
    "through_smoke",
    "already_dead_or_unfair",
    "duplicate_same_fight",
    "wrong_target",
    "low_confidence",
    "unknown",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:
            return ""
        if abs(value - int(value)) < 0.0001:
            return str(int(value))
        return str(round(value, 3))
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return str(value)


def moment_id(match_id: str, player: str, moment: dict[str, Any]) -> str:
    parts = [
        match_id,
        player,
        safe_text(moment.get("round")),
        safe_text(moment.get("tick")),
        safe_text(moment.get("target")),
        safe_text(moment.get("outcome")),
    ]
    return "|".join(parts)


def load_existing(csv_path: Path) -> dict[str, dict[str, str]]:
    if not csv_path.exists():
        return {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = {}
        for row in reader:
            mid = row.get("moment_id")
            if mid:
                rows[mid] = row
        return rows


def flatten_moments(review: dict[str, Any], limit: int | None) -> list[dict[str, Any]]:
    moments = review.get("top_moments_overall", [])

    # If top_moments_overall is limited, collect from category buckets too.
    by_id: dict[str, dict[str, Any]] = {}

    for m in moments:
        key = json.dumps([
            m.get("round"),
            m.get("tick"),
            m.get("target"),
            m.get("outcome"),
        ], ensure_ascii=False)
        by_id[key] = m

    for bucket in review.get("categories", {}).values():
        if not isinstance(bucket, list):
            continue
        for m in bucket:
            key = json.dumps([
                m.get("round"),
                m.get("tick"),
                m.get("target"),
                m.get("outcome"),
            ], ensure_ascii=False)
            by_id[key] = m

    result = list(by_id.values())
    result.sort(key=lambda x: float(x.get("importance_score") or 0), reverse=True)

    if limit is not None and limit > 0:
        result = result[:limit]

    return result


def build_rows(review: dict[str, Any], existing: dict[str, dict[str, str]], limit: int | None) -> list[dict[str, str]]:
    match_id = str(review.get("match_id"))
    player = str(review.get("player"))

    rows: list[dict[str, str]] = []

    for m in flatten_moments(review, limit):
        mid = moment_id(match_id, player, m)
        prev = existing.get(mid, {})

        row: dict[str, str] = {}
        row["moment_id"] = mid
        row["match_id"] = match_id
        row["player"] = player

        for key in BASE_FIELDS:
            if key in {"moment_id", "match_id", "player"}:
                continue
            row[key] = safe_text(m.get(key))

        # Preserve human review fields on rerun.
        row["review_status"] = prev.get("review_status", "new")
        row["manual_visible"] = prev.get("manual_visible", "")
        row["real_issue"] = prev.get("real_issue", "")
        row["noise_reason"] = prev.get("noise_reason", "")
        row["root_cause"] = prev.get("root_cause", "")
        row["coach_note"] = prev.get("coach_note", "")
        row["keep_for_training"] = prev.get("keep_for_training", "")

        rows.append(row)

    return rows


def write_csv(csv_path: Path, rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = BASE_FIELDS + MANUAL_FIELDS

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def render_options(options: list[str]) -> str:
    return " / ".join(f"<code>{html.escape(x)}</code>" for x in options if x)


def render_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<tr><td colspan="14">Нет моментов.</td></tr>'

    out = []
    for r in rows:
        cats = r.get("categories", "")
        out.append(f"""
        <tr>
            <td>{esc(r.get("review_status"))}</td>
            <td>R{esc(r.get("round"))}</td>
            <td>{esc(r.get("tick"))}</td>
            <td>{esc(r.get("target"))}</td>
            <td>{esc(r.get("outcome"))}</td>
            <td>{esc(r.get("first_shooter"))}</td>
            <td>{esc(r.get("delay_ticks"))}</td>
            <td>{esc(r.get("first_shot_speed"))}</td>
            <td>{esc(r.get("first_shot_error_deg"))}</td>
            <td><b>{esc(r.get("importance_score"))}</b><br><span class="muted">{esc(cats)}</span></td>
            <td>{esc(r.get("comment"))}</td>
            <td>{esc(r.get("manual_visible"))}</td>
            <td>{esc(r.get("root_cause"))}</td>
            <td>{esc(r.get("coach_note"))}</td>
        </tr>
        """)
    return "\n".join(out)


def render_html(review: dict[str, Any], rows: list[dict[str, str]], csv_path: Path) -> str:
    summary = review.get("summary", {})
    counts = summary.get("category_counts", {})

    cards = "\n".join(
        f"""
        <div class="card">
            <div class="card-title">{esc(k)}</div>
            <div class="card-value">{esc(v)}</div>
        </div>
        """
        for k, v in counts.items()
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Manual Review Queue v0.1 — {esc(review.get("match_id"))} — {esc(review.get("player"))}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
        .muted {{ color: #a7adb5; font-size: 12px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 25px; font-weight: 700; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 1300px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        .warn {{ color: #ffd18a; }}
        .ok {{ color: #9de39d; }}
    </style>
</head>
<body>
    <h1>Manual Review Queue v0.1</h1>
    <p class="muted">
        Match: <code>{esc(review.get("match_id"))}</code> ·
        Player: <code>{esc(review.get("player"))}</code> ·
        CSV: <code>{esc(csv_path)}</code>
    </p>

    <div class="grid">{cards}</div>

    <section>
        <h2>Как заполнять CSV</h2>
        <p>
            Открой CSV в Excel/LibreOffice или любом редакторе таблиц. Не меняй <code>moment_id</code>.
            Заполняй только ручные колонки:
            <code>review_status</code>, <code>manual_visible</code>, <code>real_issue</code>,
            <code>noise_reason</code>, <code>root_cause</code>, <code>coach_note</code>, <code>keep_for_training</code>.
        </p>
        <p>
            <b>review_status:</b> <code>new</code> / <code>checked</code> / <code>skip</code><br>
            <b>manual_visible:</b> <code>yes</code> / <code>no</code> / <code>unclear</code><br>
            <b>real_issue:</b> <code>yes</code> / <code>no</code> / <code>partial</code><br>
            <b>keep_for_training:</b> <code>yes</code> / <code>no</code>
        </p>
        <p>
            <b>root_cause варианты:</b><br>{render_options(ROOT_CAUSE_OPTIONS)}
        </p>
        <p>
            <b>noise_reason варианты:</b><br>{render_options(NOISE_OPTIONS)}
        </p>
        <p class="warn">
            Это не финальный интерфейс. Это калибровочная очередь, чтобы отделить настоящие игровые ошибки от шума visibility/FOV-модели.
        </p>
    </section>

    <section>
        <h2>Review moments</h2>
        <table>
            <thead>
                <tr>
                    <th>Status</th>
                    <th>Round</th>
                    <th>Tick</th>
                    <th>Target</th>
                    <th>Outcome</th>
                    <th>First shooter</th>
                    <th>Delay</th>
                    <th>Speed</th>
                    <th>First err</th>
                    <th>Priority / categories</th>
                    <th>Auto comment</th>
                    <th>Manual visible</th>
                    <th>Root cause</th>
                    <th>Coach note</th>
                </tr>
            </thead>
            <tbody>
                {render_rows(rows)}
            </tbody>
        </table>
    </section>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed manual review queue from Moments Review v0.2.")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    review_path = root / "data" / "reports" / args.match_id / "moments_review_v0_2.json"

    if not review_path.exists():
        raise FileNotFoundError(f"Moments Review v0.2 not found: {review_path}")

    review = read_json(review_path)

    out_dir = root / "data" / "reviews" / args.match_id
    csv_path = out_dir / f"manual_review_{args.player}_v0_1.csv"
    html_path = out_dir / f"manual_review_{args.player}_v0_1.html"

    existing = load_existing(csv_path)
    rows = build_rows(review, existing, args.limit)

    write_csv(csv_path, rows)
    html_path.write_text(render_html(review, rows, csv_path), encoding="utf-8")

    checked = sum(1 for r in rows if r.get("review_status") == "checked")

    print("OK: Manual Review Queue v0.1 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {args.player}")
    print(f"  Rows: {len(rows)}")
    print(f"  Already checked: {checked}")
    print(f"  CSV: {csv_path}")
    print(f"  HTML: {html_path}")

    if not args.no_open:
        try:
            os.startfile(str(html_path))
            print(f"  Opened HTML: {html_path}")
        except Exception as exc:
            print(f"  Created but not opened automatically: {exc}")


if __name__ == "__main__":
    main()
