from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def safe(value: Any) -> Any:
    try:
        if value is None:
            return None
        if isinstance(value, dict):
            return {str(k): safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [safe(v) for v in value]
        if isinstance(value, np.ndarray):
            return [safe(v) for v in value.tolist()]
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            v = float(value)
            return v if math.isfinite(v) else None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        return value
    except Exception:
        return str(value)


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(safe(data), ensure_ascii=False, indent=2), encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def s(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def low(value: Any) -> str:
    return s(value).lower()


def n(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def cluster_key(x: float, y: float, cell: int = 250) -> str:
    cx = int(round(x / cell) * cell)
    cy = int(round(y / cell) * cell)
    return f"{cx}:{cy}"


def load_existing_manual(csv_path: Path) -> dict[str, dict[str, str]]:
    if not csv_path.exists():
        return {}

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = {}
        for row in csv.DictReader(f):
            event_id = row.get("event_id")
            if event_id:
                rows[event_id] = row
        return rows


def build_smoke_events(smokes: pd.DataFrame, player: str) -> list[dict[str, Any]]:
    if smokes.empty:
        return []

    events = []

    for _, row in smokes.iterrows():
        thrower = s(row.get("thrower_name")) or "unknown"
        if low(thrower) != low(player):
            continue

        start = int(n(row.get("start_tick"), 0))
        end = int(n(row.get("end_tick"), 0))
        x = round(n(row.get("X")), 1)
        y = round(n(row.get("Y")), 1)
        z = round(n(row.get("Z")), 1)

        event_id = f"smoke|R{int(n(row.get('round_num'), 0))}|{start}|{thrower}|{x}|{y}|{z}"

        events.append({
            "event_id": event_id,
            "utility_type": "smoke",
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": start,
            "end_tick": end,
            "duration_ticks": end - start,
            "thrower": thrower,
            "side": s(row.get("thrower_side")),
            "thrower_place": s(row.get("thrower_place")),
            "x": x,
            "y": y,
            "z": z,
            "cluster": cluster_key(x, y),
        })

    events.sort(key=lambda e: (e["round"], e["start_tick"]))
    return events


def build_inferno_events(infernos: pd.DataFrame, player: str) -> list[dict[str, Any]]:
    if infernos.empty:
        return []

    events = []

    for _, row in infernos.iterrows():
        thrower = s(row.get("thrower_name")) or "unknown"
        if low(thrower) != low(player):
            continue

        start = int(n(row.get("start_tick"), 0))
        end = int(n(row.get("end_tick"), 0))
        x = round(n(row.get("X")), 1)
        y = round(n(row.get("Y")), 1)
        z = round(n(row.get("Z")), 1)

        event_id = f"inferno|R{int(n(row.get('round_num'), 0))}|{start}|{thrower}|{x}|{y}|{z}"

        events.append({
            "event_id": event_id,
            "utility_type": "inferno",
            "round": int(n(row.get("round_num"), 0)),
            "start_tick": start,
            "end_tick": end,
            "duration_ticks": end - start,
            "thrower": thrower,
            "side": s(row.get("thrower_side")),
            "thrower_place": s(row.get("thrower_place")),
            "x": x,
            "y": y,
            "z": z,
            "cluster": cluster_key(x, y),
        })

    events.sort(key=lambda e: (e["round"], e["start_tick"]))
    return events


def build_clusters(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for e in events:
        key = (e["utility_type"], e["cluster"])
        groups.setdefault(key, []).append(e)

    clusters = []
    for (utility_type, key), items in groups.items():
        clusters.append({
            "utility_type": utility_type,
            "cluster": key,
            "count": len(items),
            "rounds": sorted(set(int(e["round"]) for e in items)),
            "avg_x": round(sum(float(e["x"]) for e in items) / len(items), 1),
            "avg_y": round(sum(float(e["y"]) for e in items) / len(items), 1),
            "avg_z": round(sum(float(e["z"]) for e in items) / len(items), 1),
            "examples": [e["event_id"] for e in items[:5]],
        })

    clusters.sort(key=lambda x: (x["utility_type"], -x["count"], x["cluster"]))
    return clusters


def build_csv_rows(events: list[dict[str, Any]], existing: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows = []

    for e in events:
        prev = existing.get(e["event_id"], {})

        rows.append({
            "event_id": str(e["event_id"]),
            "utility_type": str(e["utility_type"]),
            "round": str(e["round"]),
            "start_tick": str(e["start_tick"]),
            "end_tick": str(e["end_tick"]),
            "duration_ticks": str(e["duration_ticks"]),
            "thrower": str(e["thrower"]),
            "side": str(e["side"]),
            "thrower_place": str(e["thrower_place"]),
            "x": str(e["x"]),
            "y": str(e["y"]),
            "z": str(e["z"]),
            "cluster": str(e["cluster"]),
            "review_status": prev.get("review_status", "new"),
            "known_lineup": prev.get("known_lineup", ""),
            "intended_purpose": prev.get("intended_purpose", ""),
            "quality": prev.get("quality", ""),
            "problem": prev.get("problem", ""),
            "coach_note": prev.get("coach_note", ""),
            "keep_for_training": prev.get("keep_for_training", ""),
        })

    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "event_id",
        "utility_type",
        "round",
        "start_tick",
        "end_tick",
        "duration_ticks",
        "thrower",
        "side",
        "thrower_place",
        "x",
        "y",
        "z",
        "cluster",
        "review_status",
        "known_lineup",
        "intended_purpose",
        "quality",
        "problem",
        "coach_note",
        "keep_for_training",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_table(rows: list[dict[str, Any]], cols: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="muted">Нет данных.</p>'

    head = "".join(f"<th>{esc(label)}</th>" for _, label in cols)
    body = []

    for row in rows:
        body.append("<tr>" + "".join(f"<td>{esc(row.get(key))}</td>" for key, _ in cols) + "</tr>")

    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(data: dict[str, Any], csv_path: Path) -> str:
    smoke_events = data["smoke_events"]
    inferno_events = data["inferno_events"]
    clusters = data["clusters"]

    smoke_table = render_table(smoke_events, [
        ("round", "R"),
        ("start_tick", "Start"),
        ("duration_ticks", "Duration"),
        ("side", "Side"),
        ("thrower_place", "Thrower place"),
        ("x", "X"),
        ("y", "Y"),
        ("z", "Z"),
        ("cluster", "Cluster"),
    ])

    inferno_table = render_table(inferno_events, [
        ("round", "R"),
        ("start_tick", "Start"),
        ("duration_ticks", "Duration"),
        ("side", "Side"),
        ("thrower_place", "Thrower place"),
        ("x", "X"),
        ("y", "Y"),
        ("z", "Z"),
        ("cluster", "Cluster"),
    ])

    cluster_table = render_table(clusters, [
        ("utility_type", "Type"),
        ("cluster", "Cluster"),
        ("count", "Count"),
        ("rounds", "Rounds"),
        ("avg_x", "Avg X"),
        ("avg_y", "Avg Y"),
        ("avg_z", "Avg Z"),
        ("examples", "Examples"),
    ])

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Utility Map Review v0.1 — {esc(data["match_id"])}</title>
    <style>
        body {{ margin: 0; padding: 32px; font-family: Arial, sans-serif; background: #101214; color: #f2f2f2; }}
        h1, h2 {{ margin-bottom: 8px; }}
        .muted {{ color: #a7adb5; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 18px 0; }}
        .card {{ background: #1a1d21; border: 1px solid #2b3138; border-radius: 12px; padding: 14px; }}
        .card-title {{ color: #a7adb5; font-size: 13px; }}
        .card-value {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
        section {{ margin-top: 28px; background: #15181c; border: 1px solid #2b3138; border-radius: 14px; padding: 18px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 1000px; }}
        th, td {{ border-bottom: 1px solid #2b3138; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
        th {{ background: #1e2329; color: #cdd3db; }}
        code {{ background: #1e2329; padding: 2px 5px; border-radius: 5px; }}
        li {{ margin-bottom: 8px; }}
    </style>
</head>
<body>
    <h1>Utility Map Review v0.1</h1>
    <p class="muted">
        Match: <code>{esc(data["match_id"])}</code> · Player: <code>{esc(data["player"])}</code><br>
        CSV для ручной оценки качества utility: <code>{esc(csv_path)}</code>
    </p>

    <div class="grid">
        <div class="card"><div class="card-title">Smoke events</div><div class="card-value">{len(smoke_events)}</div></div>
        <div class="card"><div class="card-title">Inferno events</div><div class="card-value">{len(inferno_events)}</div></div>
        <div class="card"><div class="card-title">Position clusters</div><div class="card-value">{len(clusters)}</div></div>
    </div>

    <section>
        <h2>Как проверять</h2>
        <p>
            Открой демку около <code>start_tick</code> и проверь, куда лег utility.
            В CSV заполняй только ручные поля:
            <code>review_status</code>, <code>known_lineup</code>, <code>intended_purpose</code>,
            <code>quality</code>, <code>problem</code>, <code>coach_note</code>, <code>keep_for_training</code>.
        </p>
        <ul>
            <li><b>quality:</b> good / partial / bad / unknown</li>
            <li><b>problem:</b> missed_lineup / gap / too_late / too_early / no_value / wrong_place / unknown</li>
            <li><b>intended_purpose:</b> block_vision / stop_push / clear_angle / retake / postplant / fake / unknown</li>
        </ul>
    </section>

    <section>
        <h2>Smoke events by {esc(data["player"])}</h2>
        {smoke_table}
    </section>

    <section>
        <h2>Inferno events by {esc(data["player"])}</h2>
        {inferno_table}
    </section>

    <section>
        <h2>Position clusters</h2>
        {cluster_table}
    </section>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parsed_dir", type=Path)
    parser.add_argument("--match-id", default=None)
    parser.add_argument("--player", default="Player")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    parsed_dir = args.parsed_dir
    match_id = args.match_id or parsed_dir.name

    smokes = read_parquet(parsed_dir / "smokes.parquet")
    infernos = read_parquet(parsed_dir / "infernos.parquet")

    smoke_events = build_smoke_events(smokes, args.player)
    inferno_events = build_inferno_events(infernos, args.player)
    all_events = smoke_events + inferno_events
    clusters = build_clusters(all_events)

    out_report_dir = Path("data/reports") / match_id
    out_review_dir = Path("data/reviews") / match_id
    out_report_dir.mkdir(parents=True, exist_ok=True)
    out_review_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_review_dir / f"utility_map_review_{args.player}_v0_1.csv"
    existing = load_existing_manual(csv_path)
    csv_rows = build_csv_rows(all_events, existing)
    write_csv(csv_path, csv_rows)

    data = {
        "version": "utility_map_review_v0_1",
        "match_id": match_id,
        "player": args.player,
        "smoke_events": smoke_events,
        "inferno_events": inferno_events,
        "clusters": clusters,
        "csv_path": str(csv_path),
    }

    json_path = out_report_dir / "utility_map_review_v0_1.json"
    html_path = out_report_dir / "utility_map_review_v0_1.html"

    write_json(json_path, data)
    html_path.write_text(render_html(data, csv_path), encoding="utf-8")

    print("OK: Utility Map Review v0.1 created")
    print(f"  Match: {match_id}")
    print(f"  Player: {args.player}")
    print(f"  Smoke events: {len(smoke_events)}")
    print(f"  Inferno events: {len(inferno_events)}")
    print(f"  Clusters: {len(clusters)}")
    print(f"  CSV: {csv_path}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")

    print("")
    print("Smoke events:")
    for e in smoke_events:
        print(f"  R{e['round']} tick={e['start_tick']} place={e['thrower_place']} xyz=({e['x']}, {e['y']}, {e['z']}) cluster={e['cluster']}")

    print("")
    print("Inferno events:")
    for e in inferno_events:
        print(f"  R{e['round']} tick={e['start_tick']} place={e['thrower_place']} xyz=({e['x']}, {e['y']}, {e['z']}) cluster={e['cluster']}")

    if args.open:
        os.startfile(str(html_path))


if __name__ == "__main__":
    main()
