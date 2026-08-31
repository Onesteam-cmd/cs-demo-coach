from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


TABLES = [
    "grenades",
    "smokes",
    "infernos",
    "damages",
    "kills",
    "rounds",
    "bomb",
]


def make_safe(value: Any) -> Any:
    try:
        if value is None:
            return None
        if pd.isna(value):
            return None
    except Exception:
        pass

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    if isinstance(value, (dict, list, str, int, float, bool)):
        return value

    return str(value)


def df_preview(df: pd.DataFrame, n: int = 8) -> list[dict[str, Any]]:
    rows = []
    for row in df.head(n).to_dict(orient="records"):
        rows.append({str(k): make_safe(v) for k, v in row.items()})
    return rows


def unique_preview(df: pd.DataFrame, col: str, n: int = 20) -> list[Any]:
    if col not in df.columns:
        return []

    values = []
    for v in df[col].dropna().unique()[:n]:
        values.append(make_safe(v))
    return values


def guess_interesting_columns(df: pd.DataFrame) -> dict[str, list[Any]]:
    interesting = {}

    candidates = [
        "player_name",
        "thrower",
        "thrower_name",
        "attacker_name",
        "victim_name",
        "grenade_type",
        "grenade",
        "weapon",
        "weapon_name",
        "event_type",
        "type",
        "team_name",
        "side",
        "round_num",
        "tick",
        "start_tick",
        "end_tick",
        "entity_id",
        "X",
        "Y",
        "Z",
        "x",
        "y",
        "z",
    ]

    lower_to_col = {str(c).lower(): c for c in df.columns}

    for candidate in candidates:
        col = lower_to_col.get(candidate.lower())
        if col is not None:
            interesting[str(col)] = unique_preview(df, col)

    return interesting


def analyze_table(parsed_dir: Path, name: str) -> dict[str, Any]:
    path = parsed_dir / f"{name}.parquet"

    result: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "rows": 0,
        "columns": [],
        "dtypes": {},
        "interesting_values": {},
        "preview": [],
        "error": None,
    }

    if not path.exists():
        return result

    try:
        df = pd.read_parquet(path)
        result["rows"] = int(len(df))
        result["columns"] = [str(c) for c in df.columns]
        result["dtypes"] = {str(c): str(t) for c, t in df.dtypes.items()}
        result["interesting_values"] = guess_interesting_columns(df)
        result["preview"] = df_preview(df)
    except Exception as exc:
        result["error"] = repr(exc)

    return result


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def render_preview_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="muted">Нет preview rows.</p>'

    cols = list(rows[0].keys())

    head = "".join(f"<th>{esc(c)}</th>" for c in cols)

    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{esc(row.get(c))}</td>" for c in cols)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"""
    <div class="table-wrap">
        <table>
            <thead><tr>{head}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
        </table>
    </div>
    """


def render_html(data: dict[str, Any]) -> str:
    sections = []

    for table in data["tables"]:
        columns = table["columns"]
        dtypes_rows = "".join(
            f"<tr><td>{esc(c)}</td><td>{esc(table['dtypes'].get(c))}</td></tr>"
            for c in columns
        )

        interesting = table.get("interesting_values", {})
        interesting_rows = "".join(
            f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
            for k, v in interesting.items()
        )

        sections.append(f"""
        <section>
            <h2>{esc(table["name"])}</h2>
            <p class="muted">
                Path: <code>{esc(table["path"])}</code><br>
                Exists: <b>{esc(table["exists"])}</b> ·
                Rows: <b>{esc(table["rows"])}</b> ·
                Error: <b>{esc(table["error"])}</b>
            </p>

            <h3>Columns / dtypes</h3>
            <table>
                <thead><tr><th>Column</th><th>Dtype</th></tr></thead>
                <tbody>{dtypes_rows}</tbody>
            </table>

            <h3>Interesting unique values</h3>
            <table>
                <thead><tr><th>Column</th><th>Values preview</th></tr></thead>
                <tbody>{interesting_rows}</tbody>
            </table>

            <h3>Preview</h3>
            {render_preview_table(table["preview"])}
        </section>
        """)

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Utility Schema Probe v0.1 — {esc(data["demo_name"])}</title>
    <style>
        body {{
            margin: 0;
            padding: 32px;
            font-family: Arial, sans-serif;
            background: #101214;
            color: #f2f2f2;
        }}
        h1, h2, h3 {{
            margin-bottom: 8px;
        }}
        .muted {{
            color: #a7adb5;
            font-size: 13px;
        }}
        code {{
            background: #1e2329;
            padding: 2px 5px;
            border-radius: 5px;
        }}
        section {{
            margin-top: 28px;
            background: #15181c;
            border: 1px solid #2b3138;
            border-radius: 14px;
            padding: 18px;
            overflow-x: auto;
        }}
        table {{
            border-collapse: collapse;
            margin-top: 10px;
            width: 100%;
            min-width: 700px;
        }}
        th, td {{
            border-bottom: 1px solid #2b3138;
            padding: 8px;
            text-align: left;
            vertical-align: top;
            font-size: 13px;
        }}
        th {{
            background: #1e2329;
            color: #cdd3db;
        }}
        .table-wrap {{
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    <h1>Utility Schema Probe v0.1</h1>
    <p class="muted">
        Demo: <code>{esc(data["demo_name"])}</code><br>
        Parsed dir: <code>{esc(data["parsed_dir"])}</code>
    </p>
    {''.join(sections)}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect parsed utility parquet schemas.")
    parser.add_argument("parsed_dir", type=Path)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    parsed_dir = args.parsed_dir

    if not parsed_dir.exists():
        raise FileNotFoundError(f"Parsed dir not found: {parsed_dir}")

    demo_name = parsed_dir.name
    report_dir = Path("data/reports") / demo_name
    report_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "version": "utility_schema_probe_v0_1",
        "demo_name": demo_name,
        "parsed_dir": str(parsed_dir),
        "tables": [analyze_table(parsed_dir, name) for name in TABLES],
    }

    json_path = report_dir / "utility_schema_probe_v0_1.json"
    html_path = report_dir / "utility_schema_probe_v0_1.html"

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")

    print("OK: Utility schema probe created")
    print(f"  Demo: {demo_name}")
    print(f"  JSON: {json_path}")
    print(f"  HTML: {html_path}")
    print("")
    print("Tables:")
    for table in data["tables"]:
        print(f"  {table['name']}: exists={table['exists']} rows={table['rows']} columns={len(table['columns'])} error={table['error']}")
        print(f"    columns: {', '.join(table['columns'][:30])}")

    if args.open:
        os.startfile(str(html_path))


if __name__ == "__main__":
    main()
