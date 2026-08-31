from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


MOVING_SHOT_SPEED = 40.0
SEVERE_MOVING_SHOT_SPEED = 90.0
DELAYED_SHOT_TICKS = 32
LARGE_FIRST_SHOT_ERROR_DEG = 4.0
VERY_LARGE_FIRST_SHOT_ERROR_DEG = 8.0


def make_json_safe(value: Any) -> Any:
    try:
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(k): make_json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [make_json_safe(v) for v in value]
        if isinstance(value, np.ndarray):
            return [make_json_safe(v) for v in value.tolist()]
        if isinstance(value, pd.Series):
            return [make_json_safe(v) for v in value.tolist()]
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            value = float(value)
            return value if math.isfinite(value) else None
        if isinstance(value, np.bool_):
            return bool(value)
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        return value
    except Exception:
        return str(value)


def records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []
    if limit is not None:
        df = df.head(limit)
    return make_json_safe(df.to_dict(orient="records"))


def is_present(value: Any) -> bool:
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return True


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def i(value: Any) -> int:
    return int(n(value, 0))


def fmt(value: Any, ndigits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except Exception:
        pass

    if isinstance(value, (int, float, np.integer, np.floating)):
        value = float(value)
        if not math.isfinite(value):
            return "—"
        if abs(value - int(value)) < 0.0001:
            return str(int(value))
        return str(round(value, ndigits))

    return str(value)


def esc(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(x) for x in value)
    return html.escape("" if value is None else str(value))


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return [str(x) for x in value.tolist()]
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value]
    try:
        if pd.isna(value):
            return []
    except Exception:
        pass

    text = str(value).strip()
    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        cleaned = text.strip("[]").replace("'", "").replace('"', "")
        if "," in cleaned:
            return [x.strip() for x in cleaned.split(",") if x.strip()]
        return [x.strip() for x in cleaned.split() if x.strip()]

    return [x.strip() for x in text.split(",") if x.strip()]


def prepare_contacts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    numeric_cols = [
        "round_num",
        "contact_start_tick",
        "contact_end_tick",
        "duration_ticks",
        "samples",
        "start_distance",
        "min_distance",
        "start_error",
        "min_error",
        "viewer_speed_start",
        "viewer_speed_avg",
        "viewer_first_shot_tick",
        "target_first_shot_tick",
        "viewer_shot_delay_ticks",
        "viewer_shots_after_contact",
        "target_shots_after_contact",
        "viewer_damage_events_to_target",
        "target_damage_events_to_viewer",
        "viewer_kill_tick",
        "target_kill_tick",
        "viewer_first_shot_speed",
        "viewer_first_shot_error_min_deg",
        "viewer_first_shot_error_head_deg",
        "viewer_first_shot_error_body_deg",
        "target_first_shot_speed",
        "target_first_shot_error_min_deg",
        "priority_score",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in [
        "viewer_shots_after_contact",
        "target_shots_after_contact",
        "viewer_damage_events_to_target",
        "target_damage_events_to_viewer",
    ]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0)

    df["viewer_has_shot"] = df["viewer_first_shot_tick"].notna()
    df["target_has_shot"] = df["target_first_shot_tick"].notna()

    df["has_confirmed_result"] = df["outcome"].astype(str).isin([
        "viewer_killed_target",
        "target_killed_viewer",
        "viewer_damaged_target",
        "target_damaged_viewer",
    ])

    df["has_any_action"] = (
        df["has_confirmed_result"]
        | (df["viewer_shots_after_contact"] > 0)
        | (df["target_shots_after_contact"] > 0)
        | (df["viewer_damage_events_to_target"] > 0)
        | (df["target_damage_events_to_viewer"] > 0)
    )

    return df


def calibrated_tags(row: pd.Series) -> list[str]:
    tags: list[str] = []

    outcome = str(row.get("outcome", ""))
    first_shooter = str(row.get("first_shooter", ""))

    viewer_has_shot = bool(row.get("viewer_has_shot", False))
    target_has_shot = bool(row.get("target_has_shot", False))

    viewer_shots = i(row.get("viewer_shots_after_contact"))
    target_shots = i(row.get("target_shots_after_contact"))

    viewer_damage = i(row.get("viewer_damage_events_to_target"))
    target_damage = i(row.get("target_damage_events_to_viewer"))

    if outcome == "viewer_killed_target":
        tags.append("contact_won")

    if outcome == "target_killed_viewer":
        tags.append("contact_lost")

    if outcome == "viewer_damaged_target":
        tags.append("viewer_damaged_target")

    if outcome == "target_damaged_viewer":
        tags.append("target_damaged_viewer")

    # В v0.2 no shot считаем только если есть подтверждённое действие от врага.
    if (
        not viewer_has_shot
        and (
            outcome in {"target_killed_viewer", "target_damaged_viewer"}
            or target_has_shot
            or target_shots > 0
            or target_damage > 0
        )
    ):
        tags.append("viewer_no_response_confirmed")

    # delayed считаем только если viewer реально стрелял и контакт был actionable.
    if viewer_has_shot and n(row.get("viewer_shot_delay_ticks")) > DELAYED_SHOT_TICKS:
        if row.get("has_any_action") is True or bool(row.get("has_any_action")):
            tags.append("delayed_first_shot_after_actionable_contact")

    if viewer_has_shot and n(row.get("viewer_first_shot_speed")) > MOVING_SHOT_SPEED:
        tags.append("viewer_first_shot_moving")

    if viewer_has_shot and n(row.get("viewer_first_shot_speed")) > SEVERE_MOVING_SHOT_SPEED:
        tags.append("viewer_first_shot_severe_moving")

    if viewer_has_shot and n(row.get("viewer_first_shot_error_min_deg")) > LARGE_FIRST_SHOT_ERROR_DEG:
        tags.append("viewer_large_first_shot_error")

    if viewer_has_shot and n(row.get("viewer_first_shot_error_min_deg")) > VERY_LARGE_FIRST_SHOT_ERROR_DEG:
        tags.append("viewer_very_large_first_shot_error")

    if first_shooter == "viewer" and outcome == "target_killed_viewer":
        tags.append("viewer_shot_first_but_lost")

    if first_shooter == "target" and outcome == "target_killed_viewer":
        tags.append("target_shot_first_and_won")

    if n(row.get("start_error"), 999) <= 2.0:
        tags.append("good_initial_crosshair_alignment")

    if viewer_has_shot and target_has_shot and first_shooter == "viewer":
        tags.append("viewer_shot_first")

    if viewer_has_shot and target_has_shot and first_shooter == "target":
        tags.append("target_shot_first")

    return tags


def calibrated_priority(row: pd.Series) -> int:
    tags = row.get("tags_v2", [])
    if not isinstance(tags, list):
        tags = as_list(tags)

    score = 0

    if "contact_lost" in tags:
        score += 35
    if "viewer_no_response_confirmed" in tags:
        score += 35
    if "viewer_shot_first_but_lost" in tags:
        score += 35
    if "target_shot_first_and_won" in tags:
        score += 20
    if "delayed_first_shot_after_actionable_contact" in tags:
        score += 22
    if "viewer_first_shot_moving" in tags:
        score += 18
    if "viewer_large_first_shot_error" in tags:
        score += 18
    if "viewer_very_large_first_shot_error" in tags:
        score += 10
    if "good_initial_crosshair_alignment" in tags and "viewer_shot_first_but_lost" in tags:
        score += 12
    if "contact_won" in tags:
        score += 5

    # Слишком короткие angle-only контакты не должны доминировать.
    if n(row.get("duration_ticks")) <= 0 and score > 0:
        score -= 8

    return max(0, int(score))


def player_note(row: pd.Series) -> str:
    tags = row.get("tags_v2", [])
    if not isinstance(tags, list):
        tags = as_list(tags)

    parts: list[str] = []

    if "viewer_no_response_confirmed" in tags:
        parts.append("подтверждённый контакт без ответа: враг стрелял/нанёс урон/убил, а игрок не сделал выстрел")

    if "viewer_shot_first_but_lost" in tags:
        parts.append("игрок выстрелил первым, но проиграл: смотреть первый выстрел, остановку и продолжение спрея")

    if "target_shot_first_and_won" in tags:
        parts.append("враг начал стрельбу первым и выиграл контакт: проверить готовность к углу и тайминг")

    if "delayed_first_shot_after_actionable_contact" in tags:
        parts.append("первый выстрел после контакта был поздним")

    if "viewer_first_shot_moving" in tags:
        parts.append("первый выстрел был на скорости")

    if "viewer_large_first_shot_error" in tags:
        parts.append("первый выстрел был далеко от цели по rough angle")

    if "contact_won" in tags and not parts:
        parts.append("выигранный контакт; можно использовать как позитивный пример")

    if not parts:
        parts.append("actionable contact: открыть момент и проверить вручную")

    return "; ".join(parts)


def build_v2_contacts(df: pd.DataFrame) -> pd.DataFrame:
    df = prepare_contacts(df)

    # Основной фильтр v0.2: оставляем только контакты, где было действие.
    filtered = df[df["has_any_action"] == True].copy()

    if filtered.empty:
        return filtered

    filtered["tags_v2"] = filtered.apply(calibrated_tags, axis=1)
    filtered["tags_v2_text"] = filtered["tags_v2"].map(lambda x: ", ".join(x))
    filtered["priority_score_v2"] = filtered.apply(calibrated_priority, axis=1)
    filtered["practical_note_v2"] = filtered.apply(player_note, axis=1)

    filtered = filtered.sort_values(
        ["priority_score_v2", "round_num", "contact_start_tick"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    return filtered


def has_tag(series_value: Any, tag: str) -> bool:
    tags = series_value
    if not isinstance(tags, list):
        tags = as_list(tags)
    return tag in tags


def build_player_summary(contacts: pd.DataFrame) -> pd.DataFrame:
    if contacts.empty:
        return pd.DataFrame()

    rows = []

    for pid, g in contacts.groupby("viewer_pid"):
        name = g["viewer_name"].dropna().astype(str).iloc[-1] if g["viewer_name"].notna().any() else str(pid)

        total = int(len(g))
        won = int((g["outcome"] == "viewer_killed_target").sum())
        lost = int((g["outcome"] == "target_killed_viewer").sum())
        damaged = int((g["outcome"] == "viewer_damaged_target").sum())
        got_damaged = int((g["outcome"] == "target_damaged_viewer").sum())

        no_response = int(g["tags_v2"].map(lambda x: has_tag(x, "viewer_no_response_confirmed")).sum())
        delayed = int(g["tags_v2"].map(lambda x: has_tag(x, "delayed_first_shot_after_actionable_contact")).sum())
        moving = int(g["tags_v2"].map(lambda x: has_tag(x, "viewer_first_shot_moving")).sum())
        large_err = int(g["tags_v2"].map(lambda x: has_tag(x, "viewer_large_first_shot_error")).sum())
        shot_first_lost = int(g["tags_v2"].map(lambda x: has_tag(x, "viewer_shot_first_but_lost")).sum())
        target_first_won = int(g["tags_v2"].map(lambda x: has_tag(x, "target_shot_first_and_won")).sum())

        delays = pd.to_numeric(g["viewer_shot_delay_ticks"], errors="coerce").dropna()
        avg_delay = float(delays.mean()) if len(delays) else None
        p75_delay = float(delays.quantile(0.75)) if len(delays) else None

        # Score v0.2: считаем не по сырому числу angle-контактов, а по actionable событиям.
        score = 100.0
        score -= no_response * 6.0
        score -= shot_first_lost * 7.0
        score -= target_first_won * 4.0
        score -= delayed * 3.5
        score -= moving * 2.0
        score -= large_err * 2.0
        score = round(max(0.0, min(100.0, score)), 1)

        flags = []
        if no_response >= 3:
            flags.append("подтверждённые контакты без ответа")
        if delayed >= 4:
            flags.append("часто поздний первый выстрел")
        if shot_first_lost >= 3:
            flags.append("стреляет первым, но проигрывает часть контактов")
        if moving >= 5:
            flags.append("часто первый выстрел на скорости")
        if large_err >= 5:
            flags.append("часто первый выстрел далеко от цели")

        rows.append({
            "player_pid": pid,
            "name": name,
            "actionable_contacts": total,
            "won": won,
            "lost": lost,
            "viewer_damaged_target": damaged,
            "target_damaged_viewer": got_damaged,
            "confirmed_no_response": no_response,
            "delayed_first_shot": delayed,
            "first_shot_moving": moving,
            "large_first_shot_error": large_err,
            "shot_first_but_lost": shot_first_lost,
            "target_shot_first_and_won": target_first_won,
            "avg_delay": None if avg_delay is None else round(avg_delay, 1),
            "p75_delay": None if p75_delay is None else round(p75_delay, 1),
            "contact_score_v2": score,
            "flags": flags,
        })

    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["lost", "confirmed_no_response", "shot_first_but_lost", "delayed_first_shot"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    return result


def make_html(report: dict[str, Any], out_path: Path) -> None:
    summary = report["summary"]
    players = report["player_contact_summary_v2"]
    moments = report["priority_contacts_v2"]

    player_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(p.get('name'))}</td>
            <td>{esc(p.get('actionable_contacts'))}</td>
            <td>{esc(p.get('won'))}</td>
            <td>{esc(p.get('lost'))}</td>
            <td>{esc(p.get('viewer_damaged_target'))}</td>
            <td>{esc(p.get('target_damaged_viewer'))}</td>
            <td>{esc(p.get('confirmed_no_response'))}</td>
            <td>{esc(p.get('delayed_first_shot'))}</td>
            <td>{esc(p.get('first_shot_moving'))}</td>
            <td>{esc(p.get('large_first_shot_error'))}</td>
            <td>{esc(p.get('shot_first_but_lost'))}</td>
            <td>{esc(p.get('avg_delay'))}</td>
            <td>{esc(p.get('contact_score_v2'))}</td>
            <td>{esc(p.get('flags'))}</td>
        </tr>
        """
        for p in players
    )

    moment_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(m.get('priority_score_v2'))}</td>
            <td>R{esc(m.get('round_num'))}</td>
            <td>{esc(m.get('contact_start_tick'))}</td>
            <td>{esc(m.get('contact_end_tick'))}</td>
            <td>{esc(m.get('viewer_name'))}</td>
            <td>{esc(m.get('target_name'))}</td>
            <td>{esc(fmt(m.get('duration_ticks')))}</td>
            <td>{esc(fmt(m.get('start_error'), 2))}</td>
            <td>{esc(fmt(m.get('min_error'), 2))}</td>
            <td>{esc(fmt(m.get('start_distance')))}</td>
            <td>{esc(m.get('first_shooter'))}</td>
            <td>{esc(m.get('outcome'))}</td>
            <td>{esc(fmt(m.get('viewer_shot_delay_ticks')))}</td>
            <td>{esc(fmt(m.get('viewer_first_shot_speed')))}</td>
            <td>{esc(fmt(m.get('viewer_first_shot_error_min_deg'), 2))}</td>
            <td>{esc(m.get('tags_v2_text'))}</td>
            <td>{esc(m.get('practical_note_v2'))}</td>
        </tr>
        """
        for m in moments
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Contact Visibility v0.2</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1580px;
        margin: 0 auto;
        padding: 32px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .muted {{ color: #93a4b7; }}
    .notice {{
        border: 1px solid #36557e;
        background: #101b2a;
        color: #c7d9f0;
        border-radius: 14px;
        padding: 14px 16px;
        margin: 20px 0;
    }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 14px;
        margin: 20px 0 30px;
    }}
    .card {{
        background: linear-gradient(180deg, #121c29, #0f1722);
        border: 1px solid #223043;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,.22);
    }}
    .metric {{
        font-size: 28px;
        font-weight: 800;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0 34px;
        background: #101721;
        border-radius: 14px;
        overflow: hidden;
    }}
    th, td {{
        padding: 10px 12px;
        border-bottom: 1px solid #223043;
        text-align: left;
        font-size: 13px;
        vertical-align: top;
    }}
    th {{
        background: #172232;
        color: #bfd0e4;
    }}
    tr:hover td {{
        background: #142033;
    }}
</style>
</head>
<body>
<div class="wrap">
    <h1>CS Demo Coach — Contact Visibility v0.2</h1>
    <p class="muted">Пост-фильтр v0.1: оставлены только actionable contacts — контакты с выстрелами, уроном, киллом или подтверждённым действием.</p>

    <div class="notice">
        Это всё ещё angle/FOV proxy без raycast по стенам и дымам. Но v0.2 уже сильно уменьшает мусор: no shot считается только когда есть подтверждённое действие от врага.
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Raw contacts</div><div class="metric">{esc(summary.get('raw_contacts'))}</div></div>
        <div class="card"><div class="muted">Actionable</div><div class="metric">{esc(summary.get('actionable_contacts'))}</div></div>
        <div class="card"><div class="muted">Priority</div><div class="metric">{esc(summary.get('priority_contacts'))}</div></div>
        <div class="card"><div class="muted">Reduction</div><div class="metric">{esc(summary.get('reduction_percent'))}%</div></div>
    </div>

    <h2>Сводка игроков по actionable contacts</h2>
    <table>
        <thead>
            <tr>
                <th>Игрок</th>
                <th>Actionable</th>
                <th>Won</th>
                <th>Lost</th>
                <th>Dmg dealt</th>
                <th>Dmg taken</th>
                <th>No response</th>
                <th>Delayed</th>
                <th>Moving first</th>
                <th>Large err</th>
                <th>Shot first lost</th>
                <th>Avg delay</th>
                <th>Score</th>
                <th>Flags</th>
            </tr>
        </thead>
        <tbody>{player_rows}</tbody>
    </table>

    <h2>Приоритетные actionable contact-моменты</h2>
    <table>
        <thead>
            <tr>
                <th>Priority</th>
                <th>Round</th>
                <th>Start</th>
                <th>End</th>
                <th>Viewer</th>
                <th>Target</th>
                <th>Duration</th>
                <th>Start err</th>
                <th>Min err</th>
                <th>Distance</th>
                <th>First shooter</th>
                <th>Outcome</th>
                <th>Shot delay</th>
                <th>Shot speed</th>
                <th>Shot err</th>
                <th>Tags v2</th>
                <th>Практический смысл</th>
            </tr>
        </thead>
        <tbody>{moment_rows}</tbody>
    </table>
</div>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir", type=Path, help="Path to data/reports/<demo_name>")
    args = parser.parse_args()

    report_dir = args.report_dir
    if not report_dir.exists():
        raise SystemExit(f"Report dir not found: {report_dir}")

    contacts_path = report_dir / "contacts_v0_1.parquet"
    if not contacts_path.exists():
        raise SystemExit(f"contacts_v0_1.parquet not found: {contacts_path}")

    print("=== Load Contact Visibility v0.1 contacts ===")
    raw = pd.read_parquet(contacts_path)

    print(f"Raw contacts: {len(raw)}")

    print("=== Build Contact Visibility v0.2 ===")
    contacts_v2 = build_v2_contacts(raw)

    priority = contacts_v2[contacts_v2["priority_score_v2"] > 0].head(180).copy() if not contacts_v2.empty else pd.DataFrame()
    players = build_player_summary(contacts_v2)

    raw_count = int(len(raw))
    actionable_count = int(len(contacts_v2))
    reduction = 0.0
    if raw_count > 0:
        reduction = round(100.0 * (1.0 - actionable_count / raw_count), 1)

    summary = {
        "demo_name": report_dir.name,
        "raw_contacts": raw_count,
        "actionable_contacts": actionable_count,
        "priority_contacts": int(len(priority)),
        "players": int(len(players)),
        "reduction_percent": reduction,
        "source": "contacts_v0_1.parquet",
        "model": "contact_visibility_v0_2_post_filter",
        "notes": [
            "v0.2 keeps only contacts with shots, damage, kills or confirmed action.",
            "No response is counted only when opponent action is confirmed.",
            "Still not true geometry visibility; raycast/smoke handling is future work.",
        ],
    }

    report = make_json_safe({
        "summary": summary,
        "player_contact_summary_v2": records(players),
        "priority_contacts_v2": records(priority),
    })

    json_path = report_dir / "contact_visibility_v0_2.json"
    html_path = report_dir / "contact_visibility_v0_2.html"
    contacts_v2_path = report_dir / "contacts_v0_2.parquet"
    priority_path = report_dir / "priority_contacts_v0_2.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html(report, html_path)

    if not contacts_v2.empty:
        save_df = contacts_v2.copy()
        save_df["tags_v2"] = save_df["tags_v2_text"]
        save_df.to_parquet(contacts_v2_path, index=False)

    if not priority.empty:
        save_priority = priority.copy()
        save_priority["tags_v2"] = save_priority["tags_v2_text"]
        save_priority.to_csv(priority_path, index=False, encoding="utf-8-sig")

    print("")
    print("=== CS Demo Coach Contact Visibility v0.2 ===")
    print(f"Report dir: {report_dir}")
    print(f"Raw contacts: {raw_count}")
    print(f"Actionable contacts: {actionable_count}")
    print(f"Reduction: {reduction}%")
    print(f"Priority contacts: {len(priority)}")
    print(f"Players: {len(players)}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")
    print(f"Contacts v0.2 parquet: {contacts_v2_path}")
    print(f"Priority CSV: {priority_path}")

    print("")
    print("Player contact summary v0.2:")
    if players.empty:
        print("  No players.")
    else:
        cols = [
            "name",
            "actionable_contacts",
            "won",
            "lost",
            "confirmed_no_response",
            "delayed_first_shot",
            "first_shot_moving",
            "large_first_shot_error",
            "shot_first_but_lost",
            "avg_delay",
            "contact_score_v2",
        ]
        print(players[cols].to_string(index=False))

    print("")
    print("Next: open contact_visibility_v0_2.html in browser.")


if __name__ == "__main__":
    main()
