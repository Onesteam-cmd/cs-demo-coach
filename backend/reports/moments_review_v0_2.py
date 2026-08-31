from __future__ import annotations

import argparse
import html
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd


CATEGORY_LABELS = {
    "late_shot": "Late shot / поздний первый выстрел",
    "moving_first": "Moving first / первый выстрел на скорости",
    "no_response": "No response / не ответил на контакт",
    "shot_first_lost": "Shot first but lost / выстрелил первым, но проиграл",
    "large_aim_error": "Large first-shot error / крупная ошибка первого выстрела",
    "won_but_risky": "Won but risky / выиграл, но рискованно",
}

CATEGORY_HINTS = {
    "late_shot": "Проверить: delay настоящий или contact_start_tick сработал раньше реальной видимости.",
    "moving_first": "Проверить: был ли первый bullet до полной остановки после A/D-пика.",
    "no_response": "Проверить: спина, флешка, граната, перезарядка, неготовый угол или плохой тайминг.",
    "shot_first_lost": "Проверить: первый выстрел был неточный, на скорости, поздний, или дуэль была плохой по решению.",
    "large_aim_error": "Проверить: плохой pre-aim, недоведение флика, перефлик или лишняя микрокоррекция.",
    "won_but_risky": "Проверить: момент выигран, но паттерн может ломаться против более сильного соперника.",
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


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip().lower()


def text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    value = to_float(value, None)
    if value is None:
        return default
    try:
        return int(round(value))
    except Exception:
        return default


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    by_lower = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in by_lower:
            return by_lower[c.lower()]
    return None


def build_schema(df: pd.DataFrame) -> dict[str, str | None]:
    return {
        "player": find_col(df, ["viewer_name", "player_name", "player", "viewer"]),
        "target": find_col(df, ["target_name", "enemy_name", "opponent_name", "victim_name", "target"]),
        "round": find_col(df, ["round_num", "round", "round_number"]),
        "tick": find_col(df, ["contact_start_tick", "start_tick", "tick"]),
        "end_tick": find_col(df, ["contact_end_tick", "end_tick"]),
        "outcome": find_col(df, ["outcome"]),
        "first_shooter": find_col(df, ["first_shooter"]),
        "delay": find_col(df, ["viewer_shot_delay_ticks", "first_shot_delay_ticks", "delay_ticks"]),
        "speed": find_col(df, ["viewer_first_shot_speed", "first_shot_speed", "shot_speed"]),
        "aim_error": find_col(df, [
            "viewer_first_shot_error_min_deg",
            "first_shot_error_deg",
            "shot_error_deg",
            "aim_error_deg",
            "start_error",
        ]),
        "start_error": find_col(df, ["start_error", "min_error"]),
        "tags": find_col(df, ["strict_tags", "tags"]),
        "priority": find_col(df, ["priority_score_v3", "priority_score", "severity", "importance"]),
        "distance": find_col(df, ["start_distance", "distance", "contact_distance"]),
        "weapon": find_col(df, ["viewer_weapon_start", "viewer_weapon", "weapon", "active_weapon_name"]),
        "duration": find_col(df, ["duration_ticks"]),
        "note": find_col(df, ["player_note", "note", "comment"]),
    }


def get(row: pd.Series, schema: dict[str, str | None], key: str) -> Any:
    col = schema.get(key)
    if col and col in row.index:
        return row[col]
    return None


def has_tag(tags: str, tag: str) -> bool:
    return tag.lower() in tags.lower()


def outcome_is_won(outcome: str) -> bool:
    return outcome == "viewer_killed_target"


def outcome_is_lost(outcome: str) -> bool:
    return outcome == "target_killed_viewer"


def category_flags(row: pd.Series, schema: dict[str, str | None]) -> dict[str, bool]:
    tags = text(get(row, schema, "tags")).lower()
    outcome = norm(get(row, schema, "outcome"))
    first_shooter = norm(get(row, schema, "first_shooter"))

    delay = to_float(get(row, schema, "delay"), None)
    speed = to_float(get(row, schema, "speed"), None)
    aim_error = to_float(get(row, schema, "aim_error"), None)

    late = has_tag(tags, "strict_delayed_first_shot")
    if not late and delay is not None:
        late = delay >= 48

    moving = has_tag(tags, "viewer_first_shot_moving") or has_tag(tags, "viewer_first_shot_severe_moving")
    if not moving and speed is not None:
        moving = speed >= 40

    no_response = has_tag(tags, "strict_no_response")

    shot_first_lost = has_tag(tags, "viewer_shot_first_but_lost")
    if not shot_first_lost:
        shot_first_lost = first_shooter == "viewer" and outcome_is_lost(outcome)

    large_error = has_tag(tags, "viewer_large_first_shot_error") or has_tag(tags, "viewer_very_large_first_shot_error")
    if not large_error and aim_error is not None:
        large_error = aim_error >= 8

    won_but_risky = outcome_is_won(outcome) and (late or moving or large_error)

    return {
        "late_shot": late,
        "moving_first": moving,
        "no_response": no_response,
        "shot_first_lost": shot_first_lost,
        "large_aim_error": large_error,
        "won_but_risky": won_but_risky,
    }


def calc_importance(row: pd.Series, schema: dict[str, str | None], flags: dict[str, bool]) -> float:
    priority = to_float(get(row, schema, "priority"), None)
    if priority is not None:
        return round(priority, 1)

    score = 0.0
    if flags["no_response"]:
        score += 90
    if flags["shot_first_lost"]:
        score += 80
    if flags["late_shot"]:
        score += 45
    if flags["moving_first"]:
        score += 30
    if flags["large_aim_error"]:
        score += 35
    if flags["won_but_risky"]:
        score += 15

    delay = to_float(get(row, schema, "delay"), 0.0) or 0.0
    speed = to_float(get(row, schema, "speed"), 0.0) or 0.0
    aim_error = to_float(get(row, schema, "aim_error"), 0.0) or 0.0

    score += min(delay / 4.0, 35.0)
    score += min(speed / 8.0, 25.0)
    score += min(aim_error * 2.0, 35.0)

    return round(score, 1)


def make_comment(flags: dict[str, bool], row: pd.Series, schema: dict[str, str | None]) -> str:
    existing = text(get(row, schema, "note")).strip()
    if existing:
        return existing

    parts = []
    if flags["no_response"]:
        parts.append("получил урон/умер без выстрела")
    if flags["shot_first_lost"]:
        parts.append("выстрелил первым, но проиграл")
    if flags["late_shot"]:
        parts.append("поздний первый выстрел")
    if flags["moving_first"]:
        parts.append("первый выстрел на скорости")
    if flags["large_aim_error"]:
        parts.append("первый выстрел далеко от цели")
    if flags["won_but_risky"]:
        parts.append("момент выигран, но паттерн рискованный")
    return "; ".join(parts) if parts else "требует ручной проверки"


def make_moment(row: pd.Series, schema: dict[str, str | None], player: str, flags: dict[str, bool]) -> dict[str, Any]:
    categories = [k for k, v in flags.items() if v]
    tick = to_int(get(row, schema, "tick"), None)

    return {
        "round": to_int(get(row, schema, "round"), None),
        "tick": tick,
        "end_tick": to_int(get(row, schema, "end_tick"), None),
        "duration_ticks": to_int(get(row, schema, "duration"), None),
        "player": player,
        "target": text(get(row, schema, "target")) or None,
        "outcome": text(get(row, schema, "outcome")) or None,
        "first_shooter": text(get(row, schema, "first_shooter")) or None,
        "delay_ticks": to_int(get(row, schema, "delay"), None),
        "first_shot_speed": to_float(get(row, schema, "speed"), None),
        "first_shot_error_deg": to_float(get(row, schema, "aim_error"), None),
        "start_error_deg": to_float(get(row, schema, "start_error"), None),
        "distance": to_float(get(row, schema, "distance"), None),
        "weapon": text(get(row, schema, "weapon")) or None,
        "strict_tags": text(get(row, schema, "tags")) or None,
        "categories": categories,
        "importance_score": calc_importance(row, schema, flags),
        "comment": make_comment(flags, row, schema),
        "demo_hint": f"Открыть демку около tick {tick}" if tick is not None else "Открыть момент в демке",
    }


def build_review(match_id: str, player: str, top_n: int, reports_root: Path) -> dict[str, Any]:
    report_dir = reports_root / match_id
    contacts_path = report_dir / "contacts_v0_3_strict.parquet"
    focus_path = report_dir / "player_focus_v0_3.json"

    if not contacts_path.exists():
        raise FileNotFoundError(f"Strict contacts not found: {contacts_path}")

    contacts = pd.read_parquet(contacts_path)
    schema = build_schema(contacts)

    player_col = schema.get("player")
    if not player_col:
        raise RuntimeError("Не удалось найти колонку игрока. Ожидалась viewer_name/player_name/player.")

    player_rows = contacts[contacts[player_col].astype(str).str.strip().str.lower() == player.strip().lower()].copy()
    if player_rows.empty:
        available = contacts[player_col].dropna().astype(str).drop_duplicates().head(30).tolist()
        raise RuntimeError(f"Игрок {player!r} не найден. Найдены: {available}")

    all_moments: list[dict[str, Any]] = []
    categories: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORY_LABELS}

    for _, row in player_rows.iterrows():
        flags = category_flags(row, schema)
        if not any(flags.values()):
            continue

        moment = make_moment(row, schema, player, flags)
        all_moments.append(moment)

        for cat, enabled in flags.items():
            if enabled:
                categories[cat].append(moment)

    all_moments.sort(key=lambda x: x["importance_score"], reverse=True)

    for cat in categories:
        categories[cat].sort(key=lambda x: x["importance_score"], reverse=True)
        categories[cat] = categories[cat][:top_n]

    return {
        "version": "moments_review_v0_2",
        "match_id": match_id,
        "player": player,
        "source_files": {
            "contacts": str(contacts_path),
            "player_focus": str(focus_path),
        },
        "summary": {
            "strict_contact_rows_for_player": int(len(player_rows)),
            "flagged_moments_total": int(len(all_moments)),
            "top_n_per_category": int(top_n),
            "category_counts": {
                cat: int(sum(cat in m["categories"] for m in all_moments))
                for cat in CATEGORY_LABELS
            },
        },
        "schema_detected": schema,
        "player_focus_snapshot": read_json(focus_path),
        "categories": categories,
        "top_moments_overall": all_moments[:top_n],
    }


def fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "—"
        return f"{value:.{digits}f}"
    return str(value)


def esc(value: Any) -> str:
    return html.escape(fmt(value))


def render_rows(moments: list[dict[str, Any]]) -> str:
    if not moments:
        return '<tr><td colspan="13">Нет моментов.</td></tr>'

    rows = []
    for m in moments:
        cats = ", ".join(m.get("categories", []))
        rows.append(f"""
        <tr>
            <td>R{esc(m.get("round"))}</td>
            <td>{esc(m.get("tick"))}</td>
            <td>{esc(m.get("target"))}</td>
            <td>{esc(m.get("outcome"))}</td>
            <td>{esc(m.get("first_shooter"))}</td>
            <td>{esc(m.get("delay_ticks"))}</td>
            <td>{esc(m.get("first_shot_speed"))}</td>
            <td>{esc(m.get("first_shot_error_deg"))}</td>
            <td>{esc(m.get("start_error_deg"))}</td>
            <td>{esc(m.get("distance"))}</td>
            <td>{esc(m.get("weapon"))}</td>
            <td><b>{esc(m.get("importance_score"))}</b></td>
            <td>{esc(m.get("comment"))}<br><span class="muted">{esc(cats)}</span><br><span class="hint">{esc(m.get("demo_hint"))}</span></td>
        </tr>
        """)
    return "\n".join(rows)


def render_table(moments: list[dict[str, Any]]) -> str:
    return f"""
    <table>
        <thead>
            <tr>
                <th>Round</th>
                <th>Tick</th>
                <th>Target</th>
                <th>Outcome</th>
                <th>First shooter</th>
                <th>Delay</th>
                <th>Speed</th>
                <th>First shot err</th>
                <th>Start err</th>
                <th>Distance</th>
                <th>Weapon</th>
                <th>Priority</th>
                <th>Комментарий</th>
            </tr>
        </thead>
        <tbody>
            {render_rows(moments)}
        </tbody>
    </table>
    """


def render_html(review: dict[str, Any]) -> str:
    summary = review["summary"]
    counts = summary["category_counts"]

    cards = "\n".join(f"""
        <div class="card">
            <div class="card-title">{html.escape(CATEGORY_LABELS[k])}</div>
            <div class="card-value">{esc(v)}</div>
        </div>
    """ for k, v in counts.items())

    sections = [f"""
        <section>
            <h2>Top moments overall</h2>
            <p class="muted">Самые важные моменты по priority_score_v3 / strict tags. Это кандидаты для ручной проверки, а не финальный verdict.</p>
            {render_table(review["top_moments_overall"])}
        </section>
    """]

    for cat, moments in review["categories"].items():
        sections.append(f"""
        <section>
            <h2>{html.escape(CATEGORY_LABELS[cat])}</h2>
            <p class="muted">{html.escape(CATEGORY_HINTS[cat])}</p>
            {render_table(moments)}
        </section>
        """)

    schema_rows = "\n".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in review["schema_detected"].items()
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Moments Review v0.2 — {html.escape(review["match_id"])} — {html.escape(review["player"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 12px; }}
        .hint {{ color: #d0d6de; font-size: 12px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 22px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; min-height: 34px; }}
        .card-value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
        section {{ margin-top: 34px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 1250px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 9px 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ color: #cdd3db; background: #1e2329; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
    </style>
</head>
<body>
    <h1>Moments Review v0.2</h1>
    <p class="muted">
        Match: <code>{html.escape(review["match_id"])}</code> ·
        Player: <code>{html.escape(review["player"])}</code> ·
        Strict contact rows: <code>{summary["strict_contact_rows_for_player"]}</code> ·
        Flagged moments: <code>{summary["flagged_moments_total"]}</code>
    </p>
    <div class="grid">{cards}</div>
    {''.join(sections)}
    <section>
        <h2>Detected schema</h2>
        <table>
            <thead><tr><th>Field</th><th>Detected column</th></tr></thead>
            <tbody>{schema_rows}</tbody>
        </table>
    </section>
</body>
</html>
"""


def load_default_player(root: Path) -> str | None:
    settings = read_json(root / "config" / "project_settings.json")
    if settings.get("primary_player_display_name"):
        return str(settings["primary_player_display_name"])
    names = settings.get("primary_player_names")
    if isinstance(names, list) and names:
        return str(names[0])
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--reports-root", default=None)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    reports_root = Path(args.reports_root).resolve() if args.reports_root else root / "data" / "reports"
    player = args.player or load_default_player(root)

    if not player:
        raise RuntimeError("Player not provided and not found in config/project_settings.json")

    review = build_review(args.match_id, player, args.top_n, reports_root)

    out_dir = reports_root / args.match_id
    json_path = out_dir / "moments_review_v0_2.json"
    html_path = out_dir / "moments_review_v0_2.html"

    write_json(json_path, review)
    html_path.write_text(render_html(review), encoding="utf-8")

    print("OK: Moments Review v0.2 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Summary:")
    print(f"  Strict contact rows: {review['summary']['strict_contact_rows_for_player']}")
    print(f"  Flagged moments: {review['summary']['flagged_moments_total']}")
    print("  Category counts:")
    for k, v in review["summary"]["category_counts"].items():
        print(f"    {k}: {v}")
    print("")
    print("Detected schema:")
    for k, v in review["schema_detected"].items():
        print(f"  {k}: {v}")

    if not args.no_open:
        try:
            os.startfile(str(html_path))
            print("")
            print(f"Opened HTML: {html_path}")
        except Exception as exc:
            print("")
            print(f"HTML was created but was not opened automatically: {exc}")


if __name__ == "__main__":
    main()
