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
STRICT_DELAYED_SHOT_TICKS = 48
LARGE_FIRST_SHOT_ERROR_DEG = 4.0
VERY_LARGE_FIRST_SHOT_ERROR_DEG = 8.0

MAX_STRICT_DISTANCE_FOR_SHOT_PAIR = 1800.0
MAX_STRICT_START_ERROR_FOR_SHOT_PAIR = 10.0


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


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def i(value: Any) -> int:
    return int(n(value, 0))


def yes(value: Any) -> bool:
    try:
        if value is None or pd.isna(value):
            return False
    except Exception:
        pass
    return bool(value)


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


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    numeric_cols = [
        "round_num",
        "contact_start_tick",
        "contact_end_tick",
        "duration_ticks",
        "start_distance",
        "min_distance",
        "start_error",
        "min_error",
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

    df["viewer_killed_target"] = df["outcome"].astype(str).eq("viewer_killed_target")
    df["target_killed_viewer"] = df["outcome"].astype(str).eq("target_killed_viewer")
    df["viewer_damaged_target"] = df["outcome"].astype(str).eq("viewer_damaged_target")
    df["target_damaged_viewer"] = df["outcome"].astype(str).eq("target_damaged_viewer")

    df["has_kill"] = df["viewer_killed_target"] | df["target_killed_viewer"]
    df["has_damage"] = (
        (df["viewer_damage_events_to_target"] > 0)
        | (df["target_damage_events_to_viewer"] > 0)
        | df["viewer_damaged_target"]
        | df["target_damaged_viewer"]
    )
    df["both_shot"] = df["viewer_has_shot"] & df["target_has_shot"]

    df["strict_shot_pair"] = (
        df["both_shot"]
        & (df["start_distance"].fillna(99999) <= MAX_STRICT_DISTANCE_FOR_SHOT_PAIR)
        & (df["min_error"].fillna(99999) <= MAX_STRICT_START_ERROR_FOR_SHOT_PAIR)
    )

    df["strict_reliable"] = df["has_kill"] | df["has_damage"] | df["strict_shot_pair"]

    return df


def strict_tags(row: pd.Series) -> list[str]:
    tags: list[str] = []

    outcome = str(row.get("outcome", ""))
    first_shooter = str(row.get("first_shooter", ""))

    viewer_has_shot = bool(row.get("viewer_has_shot", False))
    target_has_shot = bool(row.get("target_has_shot", False))

    if row.get("viewer_killed_target") is True:
        tags.append("strict_contact_won")

    if row.get("target_killed_viewer") is True:
        tags.append("strict_contact_lost")

    if row.get("viewer_damaged_target") is True or i(row.get("viewer_damage_events_to_target")) > 0:
        tags.append("viewer_confirmed_damage")

    if row.get("target_damaged_viewer") is True or i(row.get("target_damage_events_to_viewer")) > 0:
        tags.append("target_confirmed_damage")

    # Очень важное изменение:
    # no response только если враг реально нанёс урон / убил / стрелял, а viewer не выстрелил.
    if (
        not viewer_has_shot
        and (
            row.get("target_killed_viewer") is True
            or row.get("target_damaged_viewer") is True
            or i(row.get("target_damage_events_to_viewer")) > 0
        )
    ):
        tags.append("strict_no_response")

    if (
        viewer_has_shot
        and n(row.get("viewer_shot_delay_ticks")) > STRICT_DELAYED_SHOT_TICKS
        and (
            row.get("has_damage") is True
            or row.get("has_kill") is True
            or target_has_shot
        )
    ):
        tags.append("strict_delayed_first_shot")

    if viewer_has_shot and n(row.get("viewer_first_shot_speed")) > MOVING_SHOT_SPEED:
        tags.append("viewer_first_shot_moving")

    if viewer_has_shot and n(row.get("viewer_first_shot_speed")) > SEVERE_MOVING_SHOT_SPEED:
        tags.append("viewer_first_shot_severe_moving")

    if viewer_has_shot and n(row.get("viewer_first_shot_error_min_deg")) > LARGE_FIRST_SHOT_ERROR_DEG:
        tags.append("viewer_large_first_shot_error")

    if viewer_has_shot and n(row.get("viewer_first_shot_error_min_deg")) > VERY_LARGE_FIRST_SHOT_ERROR_DEG:
        tags.append("viewer_very_large_first_shot_error")

    if first_shooter == "viewer" and row.get("target_killed_viewer") is True:
        tags.append("viewer_shot_first_but_lost")

    if first_shooter == "target" and row.get("target_killed_viewer") is True:
        tags.append("target_shot_first_and_won")

    if first_shooter == "viewer":
        tags.append("viewer_shot_first")

    if first_shooter == "target":
        tags.append("target_shot_first")

    if row.get("strict_shot_pair") is True:
        tags.append("strict_shot_pair")

    if n(row.get("min_error"), 999) <= 2.0:
        tags.append("good_crosshair_alignment_proxy")

    return tags


def priority(row: pd.Series) -> int:
    tags = row.get("strict_tags", [])
    if not isinstance(tags, list):
        tags = []

    score = 0

    if "strict_contact_lost" in tags:
        score += 35
    if "strict_no_response" in tags:
        score += 35
    if "viewer_shot_first_but_lost" in tags:
        score += 35
    if "target_shot_first_and_won" in tags:
        score += 20
    if "strict_delayed_first_shot" in tags:
        score += 18
    if "viewer_first_shot_moving" in tags:
        score += 16
    if "viewer_large_first_shot_error" in tags:
        score += 16
    if "viewer_very_large_first_shot_error" in tags:
        score += 8
    if "strict_contact_won" in tags:
        score += 4

    if n(row.get("duration_ticks")) <= 0:
        score -= 6

    return max(0, int(score))


def note(row: pd.Series) -> str:
    tags = row.get("strict_tags", [])
    if not isinstance(tags, list):
        tags = []

    parts = []

    if "strict_no_response" in tags:
        parts.append("подтверждённый контакт без ответа: игрок получил урон/умер и не сделал выстрел")

    if "viewer_shot_first_but_lost" in tags:
        parts.append("игрок выстрелил первым, но проиграл: проверить первый выстрел, остановку, микрокоррекцию и спрей")

    if "target_shot_first_and_won" in tags:
        parts.append("враг выстрелил первым и выиграл: проверить готовность к углу и тайминг")

    if "strict_delayed_first_shot" in tags:
        parts.append("первый выстрел был поздним относительно подтверждённого контакта")

    if "viewer_first_shot_moving" in tags:
        parts.append("первый выстрел был на скорости")

    if "viewer_large_first_shot_error" in tags:
        parts.append("первый выстрел был далеко от цели по rough angle")

    if "strict_contact_won" in tags and not parts:
        parts.append("выигранный подтверждённый контакт")

    if not parts:
        parts.append("строгий подтверждённый контакт: открыть момент и проверить вручную")

    return "; ".join(parts)


def build_strict(df: pd.DataFrame) -> pd.DataFrame:
    df = prepare(df)
    strict = df[df["strict_reliable"] == True].copy()

    if strict.empty:
        return strict

    strict["strict_tags"] = strict.apply(strict_tags, axis=1)
    strict["strict_tags_text"] = strict["strict_tags"].map(lambda x: ", ".join(x))
    strict["priority_score_v3"] = strict.apply(priority, axis=1)
    strict["strict_note"] = strict.apply(note, axis=1)

    strict = strict.sort_values(
        ["priority_score_v3", "round_num", "contact_start_tick"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    return strict


def has_tag(value: Any, tag: str) -> bool:
    if isinstance(value, list):
        return tag in value
    return tag in str(value)


def player_summary(strict: pd.DataFrame) -> pd.DataFrame:
    rows = []

    if strict.empty:
        return pd.DataFrame()

    for pid, g in strict.groupby("viewer_pid"):
        name = g["viewer_name"].dropna().astype(str).iloc[-1] if g["viewer_name"].notna().any() else str(pid)

        total = len(g)
        won = int((g["viewer_killed_target"] == True).sum())
        lost = int((g["target_killed_viewer"] == True).sum())
        dmg_dealt = int((g["viewer_damage_events_to_target"] > 0).sum())
        dmg_taken = int((g["target_damage_events_to_viewer"] > 0).sum())

        no_response = int(g["strict_tags"].map(lambda x: has_tag(x, "strict_no_response")).sum())
        delayed = int(g["strict_tags"].map(lambda x: has_tag(x, "strict_delayed_first_shot")).sum())
        moving = int(g["strict_tags"].map(lambda x: has_tag(x, "viewer_first_shot_moving")).sum())
        large_err = int(g["strict_tags"].map(lambda x: has_tag(x, "viewer_large_first_shot_error")).sum())
        shot_first_lost = int(g["strict_tags"].map(lambda x: has_tag(x, "viewer_shot_first_but_lost")).sum())
        target_first_won = int(g["strict_tags"].map(lambda x: has_tag(x, "target_shot_first_and_won")).sum())

        delays = pd.to_numeric(g["viewer_shot_delay_ticks"], errors="coerce").dropna()
        avg_delay = float(delays.mean()) if len(delays) else None

        # Оценка по долям, а не грубо по количеству. Поэтому у всех не должно быть 0.
        total_safe = max(total, 1)
        lost_rate = lost / total_safe
        no_response_rate = no_response / total_safe
        delayed_rate = delayed / total_safe
        moving_rate = moving / total_safe
        large_err_rate = large_err / total_safe
        shot_first_lost_rate = shot_first_lost / total_safe

        score = 100.0
        score -= lost_rate * 28
        score -= no_response_rate * 35
        score -= shot_first_lost_rate * 28
        score -= delayed_rate * 18
        score -= moving_rate * 14
        score -= large_err_rate * 14
        score = round(max(0.0, min(100.0, score)), 1)

        flags = []
        if no_response_rate >= 0.18 and no_response >= 2:
            flags.append("подтверждённые контакты без ответа")
        if shot_first_lost_rate >= 0.12 and shot_first_lost >= 2:
            flags.append("стреляет первым, но проигрывает часть контактов")
        if delayed_rate >= 0.35 and delayed >= 4:
            flags.append("часто поздний первый выстрел")
        if moving_rate >= 0.35 and moving >= 4:
            flags.append("часто первый выстрел на скорости")
        if large_err_rate >= 0.35 and large_err >= 4:
            flags.append("часто первый выстрел далеко от цели")

        rows.append({
            "player_pid": pid,
            "name": name,
            "strict_contacts": int(total),
            "won": won,
            "lost": lost,
            "damage_dealt_contacts": dmg_dealt,
            "damage_taken_contacts": dmg_taken,
            "strict_no_response": no_response,
            "strict_delayed": delayed,
            "first_shot_moving": moving,
            "large_first_shot_error": large_err,
            "shot_first_but_lost": shot_first_lost,
            "target_shot_first_and_won": target_first_won,
            "avg_delay": None if avg_delay is None else round(avg_delay, 1),
            "lost_rate": round(lost_rate * 100, 1),
            "no_response_rate": round(no_response_rate * 100, 1),
            "delayed_rate": round(delayed_rate * 100, 1),
            "moving_rate": round(moving_rate * 100, 1),
            "large_err_rate": round(large_err_rate * 100, 1),
            "strict_contact_score": score,
            "flags": flags,
        })

    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["strict_contact_score", "lost", "strict_no_response"],
        ascending=[True, False, False],
    ).reset_index(drop=True)

    return result


def make_html(report: dict[str, Any], out_path: Path) -> None:
    summary = report["summary"]
    players = report["player_strict_contact_summary"]
    moments = report["priority_strict_contacts"]

    player_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(p.get('name'))}</td>
            <td>{esc(p.get('strict_contacts'))}</td>
            <td>{esc(p.get('won'))}</td>
            <td>{esc(p.get('lost'))}</td>
            <td>{esc(p.get('lost_rate'))}%</td>
            <td>{esc(p.get('strict_no_response'))}</td>
            <td>{esc(p.get('no_response_rate'))}%</td>
            <td>{esc(p.get('strict_delayed'))}</td>
            <td>{esc(p.get('delayed_rate'))}%</td>
            <td>{esc(p.get('first_shot_moving'))}</td>
            <td>{esc(p.get('moving_rate'))}%</td>
            <td>{esc(p.get('large_first_shot_error'))}</td>
            <td>{esc(p.get('large_err_rate'))}%</td>
            <td>{esc(p.get('shot_first_but_lost'))}</td>
            <td>{esc(p.get('avg_delay'))}</td>
            <td>{esc(p.get('strict_contact_score'))}</td>
            <td>{esc(p.get('flags'))}</td>
        </tr>
        """
        for p in players
    )

    moment_rows = "\n".join(
        f"""
        <tr>
            <td>{esc(m.get('priority_score_v3'))}</td>
            <td>R{esc(m.get('round_num'))}</td>
            <td>{esc(m.get('contact_start_tick'))}</td>
            <td>{esc(m.get('viewer_name'))}</td>
            <td>{esc(m.get('target_name'))}</td>
            <td>{esc(m.get('outcome'))}</td>
            <td>{esc(m.get('first_shooter'))}</td>
            <td>{esc(fmt(m.get('duration_ticks')))}</td>
            <td>{esc(fmt(m.get('start_distance')))}</td>
            <td>{esc(fmt(m.get('min_error'), 2))}</td>
            <td>{esc(fmt(m.get('viewer_shot_delay_ticks')))}</td>
            <td>{esc(fmt(m.get('viewer_first_shot_speed')))}</td>
            <td>{esc(fmt(m.get('viewer_first_shot_error_min_deg'), 2))}</td>
            <td>{esc(m.get('strict_tags_text'))}</td>
            <td>{esc(m.get('strict_note'))}</td>
        </tr>
        """
        for m in moments
    )

    html_text = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>CS Demo Coach — Contact Visibility v0.3 Strict</title>
<style>
    body {{
        margin: 0;
        font-family: Inter, Segoe UI, Arial, sans-serif;
        background: #070b10;
        color: #e8eef5;
    }}
    .wrap {{
        max-width: 1620px;
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
    <h1>CS Demo Coach — Contact Visibility v0.3 Strict</h1>
    <p class="muted">Строгий слой: только подтверждённые контакты — kill, damage или близкая перестрелка двух игроков.</p>

    <div class="notice">
        Это ещё не raycast по геометрии карты, но no response и delayed теперь считаются значительно строже. Этот слой лучше подходит для персонального отчёта.
    </div>

    <div class="grid">
        <div class="card"><div class="muted">Demo</div><div class="metric">{esc(summary.get('demo_name'))}</div></div>
        <div class="card"><div class="muted">Raw v0.2</div><div class="metric">{esc(summary.get('v2_contacts'))}</div></div>
        <div class="card"><div class="muted">Strict</div><div class="metric">{esc(summary.get('strict_contacts'))}</div></div>
        <div class="card"><div class="muted">Priority</div><div class="metric">{esc(summary.get('priority_contacts'))}</div></div>
        <div class="card"><div class="muted">Reduction</div><div class="metric">{esc(summary.get('reduction_from_v2_percent'))}%</div></div>
    </div>

    <h2>Сводка игроков по strict contacts</h2>
    <table>
        <thead>
            <tr>
                <th>Игрок</th>
                <th>Strict</th>
                <th>Won</th>
                <th>Lost</th>
                <th>Lost%</th>
                <th>No response</th>
                <th>No response%</th>
                <th>Delayed</th>
                <th>Delayed%</th>
                <th>Moving</th>
                <th>Moving%</th>
                <th>Large err</th>
                <th>Large err%</th>
                <th>Shot first lost</th>
                <th>Avg delay</th>
                <th>Score</th>
                <th>Flags</th>
            </tr>
        </thead>
        <tbody>{player_rows}</tbody>
    </table>

    <h2>Приоритетные strict contact-моменты</h2>
    <table>
        <thead>
            <tr>
                <th>Priority</th>
                <th>Round</th>
                <th>Start</th>
                <th>Viewer</th>
                <th>Target</th>
                <th>Outcome</th>
                <th>First shooter</th>
                <th>Duration</th>
                <th>Distance</th>
                <th>Min err</th>
                <th>Delay</th>
                <th>Shot speed</th>
                <th>Shot err</th>
                <th>Tags</th>
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
    parser.add_argument("report_dir", type=Path)
    args = parser.parse_args()

    report_dir = args.report_dir
    if not report_dir.exists():
        raise SystemExit(f"Report dir not found: {report_dir}")

    source_path = report_dir / "contacts_v0_2.parquet"
    if not source_path.exists():
        raise SystemExit(f"contacts_v0_2.parquet not found: {source_path}")

    print("=== Load Contact Visibility v0.2 contacts ===")
    v2 = pd.read_parquet(source_path)
    print(f"v0.2 contacts: {len(v2)}")

    print("=== Build strict contacts v0.3 ===")
    strict = build_strict(v2)
    players = player_summary(strict)

    priority_contacts = strict[strict["priority_score_v3"] > 0].head(160).copy() if not strict.empty else pd.DataFrame()

    v2_count = int(len(v2))
    strict_count = int(len(strict))
    reduction = 0.0
    if v2_count > 0:
        reduction = round(100.0 * (1.0 - strict_count / v2_count), 1)

    summary = {
        "demo_name": report_dir.name,
        "v2_contacts": v2_count,
        "strict_contacts": strict_count,
        "priority_contacts": int(len(priority_contacts)),
        "players": int(len(players)),
        "reduction_from_v2_percent": reduction,
        "model": "contact_visibility_v0_3_strict",
        "strict_rules": [
            "keep if kill",
            "keep if damage",
            "keep if both players shot and distance/error filters pass",
            "no response only if viewer took damage/died and did not shoot",
        ],
    }

    report = make_json_safe({
        "summary": summary,
        "player_strict_contact_summary": records(players),
        "priority_strict_contacts": records(priority_contacts),
    })

    json_path = report_dir / "contact_visibility_v0_3_strict.json"
    html_path = report_dir / "contact_visibility_v0_3_strict.html"
    parquet_path = report_dir / "contacts_v0_3_strict.parquet"
    csv_path = report_dir / "priority_contacts_v0_3_strict.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    make_html(report, html_path)

    if not strict.empty:
        save = strict.copy()
        save["strict_tags"] = save["strict_tags_text"]
        save.to_parquet(parquet_path, index=False)

    if not priority_contacts.empty:
        save_priority = priority_contacts.copy()
        save_priority["strict_tags"] = save_priority["strict_tags_text"]
        save_priority.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print("")
    print("=== CS Demo Coach Contact Visibility v0.3 Strict ===")
    print(f"Report dir: {report_dir}")
    print(f"v0.2 contacts: {v2_count}")
    print(f"Strict contacts: {strict_count}")
    print(f"Reduction from v0.2: {reduction}%")
    print(f"Priority contacts: {len(priority_contacts)}")
    print(f"Players: {len(players)}")
    print(f"Report JSON: {json_path}")
    print(f"Report HTML: {html_path}")
    print(f"Strict contacts parquet: {parquet_path}")
    print(f"Priority CSV: {csv_path}")

    print("")
    print("Player strict contact summary:")
    if players.empty:
        print("  No players.")
    else:
        cols = [
            "name",
            "strict_contacts",
            "won",
            "lost",
            "lost_rate",
            "strict_no_response",
            "no_response_rate",
            "strict_delayed",
            "delayed_rate",
            "first_shot_moving",
            "moving_rate",
            "large_first_shot_error",
            "large_err_rate",
            "shot_first_but_lost",
            "strict_contact_score",
        ]
        print(players[cols].to_string(index=False))

    print("")
    print("Next: open contact_visibility_v0_3_strict.html in browser.")


if __name__ == "__main__":
    main()
