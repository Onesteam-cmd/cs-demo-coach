from __future__ import annotations

import argparse
import html
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd


DELAYED_TICKS_DEFAULT = 48
MOVING_SPEED_DEFAULT = 40.0
LARGE_AIM_ERROR_DEFAULT = 8.0


CATEGORY_LABELS = {
    "late_shot": "Late shot / поздний первый выстрел",
    "moving_first": "Moving first / первый выстрел на скорости",
    "no_response": "No response / не ответил на контакт",
    "shot_first_lost": "Shot first but lost / выстрелил первым, но проиграл",
    "large_aim_error": "Large aim error / крупная ошибка наведения",
    "won_but_risky": "Won but risky / выиграл, но рискованно",
}


CATEGORY_HINTS = {
    "late_shot": "Проверить в демке: модель действительно была видна с contact tick или это шум FOV-модели? Если видна — тренировать ранний первый выстрел после появления цели.",
    "moving_first": "Проверить в демке: был ли A/D-пик, не был ли выстрел сделан до полной остановки. Если да — проблема counter-strafe / дисциплины первого bullet.",
    "no_response": "Проверить в демке: была ли граната, перезарядка, смена оружия, спина к контакту или реальная потеря реакции.",
    "shot_first_lost": "Проверить в демке: первый выстрел был неточный, на скорости, слишком поздний или дуэль проиграна уже после нормального opening.",
    "large_aim_error": "Проверить в демке: прицел был не на уровне цели, был плохой pre-aim или ошибка флика.",
    "won_but_risky": "Проверить в демке: момент выигран, но паттерн опасный и может ломаться против более сильных игроков.",
}


def repo_root() -> Path:
    # backend/reports/moments_review_v0_1.py -> project root
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


def norm_name(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def is_missing(value: Any) -> bool:
    try:
        return pd.isna(value)
    except Exception:
        return value is None


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    f = to_float(value, None)
    if f is None:
        return default
    try:
        return int(round(f))
    except Exception:
        return default


def to_bool(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0

    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "да", "истина"}


def get_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def colmap(df: pd.DataFrame) -> dict[str, str]:
    return {str(c).strip().lower(): c for c in df.columns}


def find_col(df: pd.DataFrame, candidates: list[str], contains: list[str] | None = None) -> str | None:
    cmap = colmap(df)

    for c in candidates:
        key = c.strip().lower()
        if key in cmap:
            return cmap[key]

    if contains:
        for needle in contains:
            needle_l = needle.lower()
            for key, original in cmap.items():
                if needle_l in key:
                    return original

    return None


def infer_player_col(df: pd.DataFrame, player: str) -> str | None:
    direct = find_col(
        df,
        [
            "player",
            "player_name",
            "viewer",
            "viewer_name",
            "subject",
            "subject_name",
            "attacker",
            "attacker_name",
        ],
        contains=["viewer", "player"],
    )
    if direct is not None:
        return direct

    player_l = norm_name(player)
    best_col = None
    best_hits = 0

    for col in df.columns:
        if not pd.api.types.is_object_dtype(df[col]) and not pd.api.types.is_string_dtype(df[col]):
            continue
        sample = df[col].dropna().astype(str)
        if sample.empty:
            continue
        hits = int((sample.str.strip().str.lower() == player_l).sum())
        if hits > best_hits:
            best_hits = hits
            best_col = col

    return best_col if best_hits > 0 else None


def infer_target_col(df: pd.DataFrame, player_col: str | None) -> str | None:
    target = find_col(
        df,
        [
            "target",
            "target_name",
            "enemy",
            "enemy_name",
            "opponent",
            "opponent_name",
            "victim",
            "victim_name",
        ],
        contains=["target", "enemy", "opponent", "victim"],
    )
    if target is not None and target != player_col:
        return target

    return None


def first_existing(row: pd.Series, cols: list[str | None]) -> Any:
    for c in cols:
        if c is None:
            continue
        if c in row.index:
            value = row[c]
            if not is_missing(value):
                return value
    return None


def build_schema(df: pd.DataFrame, player: str) -> dict[str, str | None]:
    player_col = infer_player_col(df, player)

    schema = {
        "player": player_col,
        "target": infer_target_col(df, player_col),
        "round": find_col(df, ["round", "round_num", "round_number", "round_id"], contains=["round"]),
        "tick": find_col(
            df,
            ["start_tick", "contact_start_tick", "first_tick", "contact_tick", "tick"],
            contains=["tick"],
        ),
        "end_tick": find_col(df, ["end_tick", "contact_end_tick", "last_tick"]),
        "outcome": find_col(
            df,
            ["outcome", "result", "viewer_outcome", "contact_outcome"],
            contains=["outcome", "result"],
        ),
        "first_shooter": find_col(
            df,
            ["first_shooter", "first_shot_by", "shot_first_by", "first_actor"],
            contains=["first_shooter", "first_shot_by"],
        ),
        "delay": find_col(
            df,
            [
                "delay_ticks",
                "first_shot_delay_ticks",
                "viewer_first_shot_delay_ticks",
                "response_delay_ticks",
                "shot_delay_ticks",
            ],
            contains=["delay"],
        ),
        "speed": find_col(
            df,
            [
                "viewer_first_shot_speed",
                "first_shot_speed",
                "shot_speed",
                "player_first_shot_speed",
                "speed",
            ],
            contains=["shot_speed"],
        ),
        "aim_error": find_col(
            df,
            [
                "first_shot_error_deg",
                "shot_error_deg",
                "aim_error_deg",
                "rough_aim_error_deg",
                "start_error_deg",
                "start_error",
            ],
            contains=["error"],
        ),
        "moving": find_col(
            df,
            [
                "moving_first",
                "viewer_first_moving",
                "first_shot_moving",
                "is_moving_first",
                "moving",
            ],
            contains=["moving"],
        ),
        "no_response": find_col(
            df,
            [
                "no_response",
                "viewer_no_response",
                "did_not_shoot",
                "no_shot",
                "died_without_firing",
            ],
            contains=["no_response", "no_shot"],
        ),
        "lost": find_col(
            df,
            ["lost", "viewer_lost", "is_lost", "loss", "contact_lost"],
            contains=["lost"],
        ),
        "shot_first_lost": find_col(
            df,
            ["shot_first_lost", "viewer_shot_first_lost", "first_shot_lost"],
            contains=["shot_first"],
        ),
        "bad_cs": find_col(
            df,
            [
                "bad_counter_strafe",
                "bad_cs",
                "counter_strafe_bad",
                "bad_counter_strafe_candidate",
            ],
            contains=["counter", "bad_cs"],
        ),
        "tags": find_col(df, ["tags", "tag", "issues", "flags", "labels"], contains=["tag", "issue", "flag"]),
        "severity": find_col(
            df,
            ["severity", "priority", "priority_score", "importance", "score_penalty"],
            contains=["severity", "priority", "importance"],
        ),
        "distance": find_col(df, ["distance", "start_distance", "contact_distance"], contains=["distance"]),
        "weapon": find_col(df, ["weapon", "active_weapon_name", "viewer_weapon", "weapon_name"], contains=["weapon"]),
    }

    return schema


def tags_text(row: pd.Series, schema: dict[str, str | None]) -> str:
    parts = []

    for key in ["tags", "outcome"]:
        col = schema.get(key)
        if col and col in row.index:
            text = get_text(row[col]).strip()
            if text:
                parts.append(text)

    return " ".join(parts).lower()


def outcome_text(row: pd.Series, schema: dict[str, str | None]) -> str:
    outcome_col = schema.get("outcome")
    if outcome_col and outcome_col in row.index:
        return get_text(row[outcome_col]).strip().lower()
    return ""


def outcome_is_lost(row: pd.Series, schema: dict[str, str | None]) -> bool:
    col = schema.get("lost")
    if col and col in row.index and to_bool(row[col]):
        return True

    text = outcome_text(row, schema)

    # Current strict contact convention:
    # viewer = analyzed player, target = enemy.
    if text in {"target_killed_viewer", "target_damaged_viewer"}:
        return text == "target_killed_viewer"

    lost_words = ["viewer_died", "viewer_dead", "viewer_killed_by_target", "lost", "loss", "dead", "died", "death", "проиг"]
    return any(w in text for w in lost_words)


def outcome_is_won(row: pd.Series, schema: dict[str, str | None]) -> bool:
    text = outcome_text(row, schema)

    # Current strict contact convention:
    # viewer_killed_target = analyzed player won.
    # target_killed_viewer = analyzed player lost.
    if text == "viewer_killed_target":
        return True
    if text == "target_killed_viewer":
        return False

    win_words = ["viewer_killed_target", "viewer_won", "won", "win", "frag", "выиг", "убил"]
    lose_words = ["target_killed_viewer", "viewer_died", "viewer_dead", "lost", "loss", "dead", "died", "death", "проиг"]

    return any(w in text for w in win_words) and not any(w in text for w in lose_words)


def first_shooter_is_player(row: pd.Series, schema: dict[str, str | None], player: str) -> bool:
    col = schema.get("first_shooter")
    if not col or col not in row.index:
        return False

    value = get_text(row[col]).strip()
    if not value:
        return False

    value_l = norm_name(value)
    player_l = norm_name(player)

    if value_l == player_l:
        return True

    # Some models store viewer/target instead of names.
    return value_l in {"viewer", "player", "self", "subject"}


def category_flags(
    row: pd.Series,
    schema: dict[str, str | None],
    player: str,
    delayed_ticks: int,
    moving_speed: float,
    large_aim_error: float,
) -> dict[str, bool]:
    text = tags_text(row, schema)

    delay = to_float(row[schema["delay"]], None) if schema.get("delay") in row.index else None
    speed = to_float(row[schema["speed"]], None) if schema.get("speed") in row.index else None
    error = to_float(row[schema["aim_error"]], None) if schema.get("aim_error") in row.index else None

    no_response = False
    if schema.get("no_response") in row.index:
        no_response = to_bool(row[schema["no_response"]])
    no_response = no_response or "no_response" in text or "no response" in text or "no_shot" in text

    late = False
    if delay is not None:
        late = delay >= delayed_ticks
    late = late or "delayed" in text or "late" in text or "позд" in text

    moving = False
    if schema.get("moving") in row.index:
        moving = to_bool(row[schema["moving"]])
    if speed is not None:
        moving = moving or speed >= moving_speed
    moving = moving or "moving" in text or "counter" in text

    shot_first_lost = False
    if schema.get("shot_first_lost") in row.index:
        shot_first_lost = to_bool(row[schema["shot_first_lost"]])
    shot_first_lost = shot_first_lost or (
        first_shooter_is_player(row, schema, player) and outcome_is_lost(row, schema)
    )
    shot_first_lost = shot_first_lost or "shot_first_lost" in text or "shot first lost" in text

    large_error = False
    if error is not None:
        large_error = error >= large_aim_error
    large_error = large_error or "large_error" in text or "large aim" in text or "aim_error" in text

    bad_cs = False
    if schema.get("bad_cs") in row.index:
        bad_cs = to_bool(row[schema["bad_cs"]])
    bad_cs = bad_cs or "bad_cs" in text or "bad counter" in text

    won_risky = outcome_is_won(row, schema) and (late or moving or large_error or bad_cs)

    return {
        "late_shot": late,
        "moving_first": moving,
        "no_response": no_response,
        "shot_first_lost": shot_first_lost,
        "large_aim_error": large_error,
        "won_but_risky": won_risky,
    }


def moment_score(
    row: pd.Series,
    schema: dict[str, str | None],
    flags: dict[str, bool],
) -> float:
    score = 0.0

    if flags.get("no_response"):
        score += 100
    if flags.get("shot_first_lost"):
        score += 70
    if flags.get("late_shot"):
        score += 45
    if flags.get("moving_first"):
        score += 30
    if flags.get("large_aim_error"):
        score += 30
    if flags.get("won_but_risky"):
        score += 15

    if outcome_is_lost(row, schema):
        score += 25

    delay_col = schema.get("delay")
    if delay_col and delay_col in row.index:
        delay = to_float(row[delay_col], 0.0) or 0.0
        score += min(max(delay, 0.0) / 2.0, 45.0)

    speed_col = schema.get("speed")
    if speed_col and speed_col in row.index:
        speed = to_float(row[speed_col], 0.0) or 0.0
        score += min(max(speed, 0.0) / 6.0, 30.0)

    error_col = schema.get("aim_error")
    if error_col and error_col in row.index:
        error = to_float(row[error_col], 0.0) or 0.0
        score += min(max(error, 0.0) * 3.0, 45.0)

    severity_col = schema.get("severity")
    if severity_col and severity_col in row.index:
        severity = to_float(row[severity_col], None)
        if severity is not None:
            score += min(max(severity, 0.0), 100.0)

    return round(score, 2)


def build_comment(flags: dict[str, bool]) -> str:
    parts = []

    if flags.get("no_response"):
        parts.append("нет ответа на подтверждённый контакт")
    if flags.get("late_shot"):
        parts.append("поздний первый выстрел")
    if flags.get("moving_first"):
        parts.append("первый выстрел на скорости")
    if flags.get("shot_first_lost"):
        parts.append("выстрелил первым, но проиграл")
    if flags.get("large_aim_error"):
        parts.append("крупная ошибка наведения")
    if flags.get("won_but_risky"):
        parts.append("момент выигран, но паттерн рискованный")

    if not parts:
        return "момент требует ручной проверки"

    return "; ".join(parts)


def make_moment(
    row: pd.Series,
    schema: dict[str, str | None],
    player: str,
    flags: dict[str, bool],
    score: float,
) -> dict[str, Any]:
    def v(key: str) -> Any:
        col = schema.get(key)
        if col and col in row.index:
            return row[col]
        return None

    categories = [name for name, enabled in flags.items() if enabled]

    tick = to_int(v("tick"), None)
    round_num = to_int(v("round"), None)
    target = get_text(v("target")) or None

    return {
        "round": round_num,
        "tick": tick,
        "end_tick": to_int(v("end_tick"), None),
        "player": player,
        "target": target,
        "outcome": get_text(v("outcome")) or None,
        "first_shooter": get_text(v("first_shooter")) or None,
        "delay_ticks": to_int(v("delay"), None),
        "first_shot_speed": to_float(v("speed"), None),
        "aim_error_deg": to_float(v("aim_error"), None),
        "distance": to_float(v("distance"), None),
        "weapon": get_text(v("weapon")) or None,
        "tags_raw": get_text(v("tags")) or None,
        "categories": categories,
        "importance_score": score,
        "comment": build_comment(flags),
        "demo_hint": f"Открыть демку около tick {tick}" if tick is not None else "Открыть соответствующий момент в демке",
    }


def filter_player_rows(df: pd.DataFrame, player: str, player_col: str | None) -> pd.DataFrame:
    if player_col is None:
        raise RuntimeError(
            "Не удалось определить колонку игрока в contacts parquet. "
            "Нужны колонки вроде player/viewer/viewer_name/player_name."
        )

    mask = df[player_col].astype(str).str.strip().str.lower() == norm_name(player)
    result = df[mask].copy()

    if result.empty:
        available = (
            df[player_col]
            .dropna()
            .astype(str)
            .drop_duplicates()
            .head(30)
            .tolist()
        )
        raise RuntimeError(
            f"Для игрока '{player}' не найдено строк в колонке '{player_col}'. "
            f"Первые найденные значения: {available}"
        )

    return result


def build_review(
    match_id: str,
    player: str,
    top_n: int,
    delayed_ticks: int,
    moving_speed: float,
    large_aim_error: float,
    reports_root: Path,
) -> dict[str, Any]:
    report_dir = reports_root / match_id
    contacts_path = report_dir / "contacts_v0_3_strict.parquet"
    focus_path = report_dir / "player_focus_v0_3.json"

    if not report_dir.exists():
        raise FileNotFoundError(f"Папка отчёта не найдена: {report_dir}")

    if not contacts_path.exists():
        raise FileNotFoundError(f"Не найден strict contacts parquet: {contacts_path}")

    contacts = pd.read_parquet(contacts_path)
    if contacts.empty:
        raise RuntimeError(f"Файл contacts пустой: {contacts_path}")

    focus = read_json(focus_path)
    schema = build_schema(contacts, player)
    player_rows = filter_player_rows(contacts, player, schema["player"])

    all_moments: list[dict[str, Any]] = []
    category_buckets: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORY_LABELS}

    for _, row in player_rows.iterrows():
        flags = category_flags(
            row=row,
            schema=schema,
            player=player,
            delayed_ticks=delayed_ticks,
            moving_speed=moving_speed,
            large_aim_error=large_aim_error,
        )

        if not any(flags.values()):
            continue

        score = moment_score(row, schema, flags)
        moment = make_moment(row, schema, player, flags, score)
        all_moments.append(moment)

        for cat, enabled in flags.items():
            if enabled:
                category_buckets[cat].append(moment)

    for cat in category_buckets:
        category_buckets[cat].sort(key=lambda m: m["importance_score"], reverse=True)
        category_buckets[cat] = category_buckets[cat][:top_n]

    all_moments.sort(key=lambda m: m["importance_score"], reverse=True)

    return {
        "version": "moments_review_v0_1",
        "match_id": match_id,
        "player": player,
        "source_files": {
            "contacts": str(contacts_path),
            "player_focus": str(focus_path),
        },
        "thresholds": {
            "delayed_ticks": delayed_ticks,
            "moving_speed": moving_speed,
            "large_aim_error_deg": large_aim_error,
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
        "player_focus_snapshot": focus,
        "categories": category_buckets,
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


def render_moment_row(moment: dict[str, Any]) -> str:
    cats = ", ".join(CATEGORY_LABELS.get(c, c) for c in moment.get("categories", []))

    return f"""
        <tr>
            <td>{esc(moment.get("round"))}</td>
            <td>{esc(moment.get("tick"))}</td>
            <td>{esc(moment.get("target"))}</td>
            <td>{esc(moment.get("outcome"))}</td>
            <td>{esc(moment.get("first_shooter"))}</td>
            <td>{esc(moment.get("delay_ticks"))}</td>
            <td>{esc(moment.get("first_shot_speed"))}</td>
            <td>{esc(moment.get("aim_error_deg"))}</td>
            <td>{esc(moment.get("distance"))}</td>
            <td>{esc(moment.get("weapon"))}</td>
            <td>{esc(moment.get("importance_score"))}</td>
            <td>{html.escape(moment.get("comment") or "")}<br><span class="muted">{html.escape(cats)}</span><br><span class="hint">{html.escape(moment.get("demo_hint") or "")}</span></td>
        </tr>
    """


def render_table(moments: list[dict[str, Any]]) -> str:
    if not moments:
        return '<p class="muted">Нет моментов в этой категории.</p>'

    rows = "\n".join(render_moment_row(m) for m in moments)

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
                    <th>Aim error</th>
                    <th>Distance</th>
                    <th>Weapon</th>
                    <th>Score</th>
                    <th>Комментарий</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    """


def render_html(review: dict[str, Any]) -> str:
    summary = review["summary"]
    category_counts = summary["category_counts"]

    cards = "\n".join(
        f"""
        <div class="card">
            <div class="card-title">{html.escape(CATEGORY_LABELS[cat])}</div>
            <div class="card-value">{count}</div>
        </div>
        """
        for cat, count in category_counts.items()
    )

    sections = []

    sections.append(f"""
        <section>
            <h2>Top moments overall</h2>
            <p class="muted">Самые важные моменты по общей оценке. Это кандидаты для ручной проверки в демке.</p>
            {render_table(review["top_moments_overall"])}
        </section>
    """)

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
    <title>Moments Review v0.1 — {html.escape(review["match_id"])} — {html.escape(review["player"])}</title>
    <style>
        body {{
            margin: 0;
            padding: 32px;
            font-family: Arial, sans-serif;
            background: #101214;
            color: #f2f2f2;
        }}
        h1, h2 {{
            margin-bottom: 8px;
        }}
        .muted {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .hint {{
            color: #d0d6de;
            font-size: 12px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
            gap: 12px;
            margin: 22px 0;
        }}
        .card {{
            background: #1a1d21;
            border: 1px solid #2b3138;
            border-radius: 12px;
            padding: 14px;
        }}
        .card-title {{
            color: #a7adb5;
            font-size: 13px;
            min-height: 34px;
        }}
        .card-value {{
            font-size: 28px;
            font-weight: 700;
            margin-top: 8px;
        }}
        section {{
            margin-top: 34px;
            background: #15181c;
            border: 1px solid #2b3138;
            border-radius: 14px;
            padding: 18px;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            min-width: 1100px;
        }}
        th, td {{
            border-bottom: 1px solid #2b3138;
            padding: 9px 8px;
            text-align: left;
            vertical-align: top;
            font-size: 13px;
        }}
        th {{
            color: #cdd3db;
            background: #1e2329;
            position: sticky;
            top: 0;
        }}
        td {{
            color: #f2f2f2;
        }}
        .footer {{
            margin-top: 30px;
            color: #a7adb5;
            font-size: 12px;
        }}
        code {{
            background: #1e2329;
            padding: 2px 5px;
            border-radius: 5px;
        }}
    </style>
</head>
<body>
    <h1>Moments Review v0.1</h1>
    <p class="muted">
        Match: <code>{html.escape(review["match_id"])}</code> ·
        Player: <code>{html.escape(review["player"])}</code> ·
        Strict contact rows: <code>{summary["strict_contact_rows_for_player"]}</code> ·
        Flagged moments: <code>{summary["flagged_moments_total"]}</code>
    </p>

    <div class="grid">
        {cards}
    </div>

    {''.join(sections)}

    <section>
        <h2>Detected schema</h2>
        <p class="muted">Какие колонки скрипт автоматически нашёл в strict contacts parquet. Если категория выглядит странно, сначала смотреть сюда.</p>
        <table>
            <thead>
                <tr><th>Field</th><th>Detected column</th></tr>
            </thead>
            <tbody>
                {schema_rows}
            </tbody>
        </table>
    </section>

    <div class="footer">
        Generated by moments_review_v0_1.py. Это review-экран для ручной проверки кандидатов, а не финальный verdict по демке.
    </div>
</body>
</html>
"""


def load_default_player(root: Path) -> str | None:
    config_path = root / "config" / "project_settings.json"
    config = read_json(config_path)

    display = config.get("primary_player_display_name")
    if display:
        return str(display)

    names = config.get("primary_player_names")
    if isinstance(names, list) and names:
        return str(names[0])

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Moments Review v0.1 for strict contact moments.")
    parser.add_argument("--match-id", required=True, help="Report directory name inside data/reports, e.g. example_match")
    parser.add_argument("--player", default=None, help="Player name. If omitted, config/project_settings.json is used.")
    parser.add_argument("--top-n", type=int, default=10, help="Top moments per category.")
    parser.add_argument("--delayed-ticks", type=int, default=DELAYED_TICKS_DEFAULT)
    parser.add_argument("--moving-speed", type=float, default=MOVING_SPEED_DEFAULT)
    parser.add_argument("--large-aim-error", type=float, default=LARGE_AIM_ERROR_DEFAULT)
    parser.add_argument("--reports-root", default=None, help="Optional custom reports root. Default: data/reports")
    parser.add_argument("--no-open", action="store_true", help="Do not open generated HTML automatically.")

    args = parser.parse_args()

    root = repo_root()
    reports_root = Path(args.reports_root).resolve() if args.reports_root else root / "data" / "reports"

    player = args.player or load_default_player(root)
    if not player:
        raise RuntimeError(
            "Игрок не указан и не найден в config/project_settings.json. "
            "Передай --player \"Player\"."
        )

    review = build_review(
        match_id=args.match_id,
        player=player,
        top_n=args.top_n,
        delayed_ticks=args.delayed_ticks,
        moving_speed=args.moving_speed,
        large_aim_error=args.large_aim_error,
        reports_root=reports_root,
    )

    report_dir = reports_root / args.match_id
    json_path = report_dir / "moments_review_v0_1.json"
    html_path = report_dir / "moments_review_v0_1.html"

    write_json(json_path, review)
    html_path.write_text(render_html(review), encoding="utf-8")

    print("OK: Moments Review v0.1 created")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {player}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Summary:")
    print(f"  Strict contact rows: {review['summary']['strict_contact_rows_for_player']}")
    print(f"  Flagged moments: {review['summary']['flagged_moments_total']}")
    print("  Category counts:")
    for cat, count in review["summary"]["category_counts"].items():
        print(f"    {cat}: {count}")
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


