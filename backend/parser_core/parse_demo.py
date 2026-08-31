from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from awpy import Demo

app = typer.Typer(add_completion=False)
console = Console()


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except Exception:
        return None


def _to_dataframe(value: Any) -> pd.DataFrame | None:
    if value is None:
        return None

    if isinstance(value, pd.DataFrame):
        return value

    try:
        return value.to_pandas()
    except Exception:
        pass

    try:
        return pd.DataFrame(value)
    except Exception:
        return None


def _save_table(name: str, value: Any, out_dir: Path) -> dict[str, Any]:
    df = _to_dataframe(value)
    info: dict[str, Any] = {
        "name": name,
        "exists": value is not None,
        "rows": _safe_len(value),
        "saved": False,
        "columns": [],
    }

    if df is None:
        return info

    info["rows"] = len(df)
    info["columns"] = list(map(str, df.columns))

    if len(df) > 0:
        out_path = out_dir / f"{name}.parquet"
        df.to_parquet(out_path, index=False)
        info["saved"] = True
        info["path"] = str(out_path)

        preview_path = out_dir / f"{name}_preview.csv"
        df.head(50).to_csv(preview_path, index=False, encoding="utf-8-sig")
        info["preview_path"] = str(preview_path)

    return info


@app.command()
def parse(
    demo_path: Path = typer.Argument(..., help="Path to .dem file"),
    out_root: Path = typer.Option(Path("data/parsed"), help="Output folder"),
):
    """
    Parse CS2 demo and save available core tables.
    """
    if not demo_path.exists():
        console.print(f"[red]Demo file not found:[/red] {demo_path}")
        raise typer.Exit(1)

    demo_name = demo_path.stem
    out_dir = out_root / demo_name
    out_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Parsing demo:[/bold] {demo_path}")
    console.print(f"[bold]Output:[/bold] {out_dir}")

    demo = Demo(str(demo_path))
    demo.parse()

    table_names = [
        "rounds",
        "kills",
        "damages",
        "grenades",
        "smokes",
        "infernos",
        "bomb",
        "shots",
        "ticks",
    ]

    summary: dict[str, Any] = {
        "demo_path": str(demo_path),
        "demo_name": demo_name,
        "header": {},
        "tables": [],
    }

    try:
        summary["header"] = dict(demo.header)
    except Exception:
        summary["header"] = {"raw": str(getattr(demo, "header", None))}

    for name in table_names:
        value = getattr(demo, name, None)
        summary["tables"].append(_save_table(name, value, out_dir))

    summary_path = out_dir / "parse_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    table = Table(title="Parsed demo tables")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    table.add_column("Saved")
    table.add_column("Columns preview")

    for item in summary["tables"]:
        columns = item.get("columns", [])
        columns_preview = ", ".join(columns[:8])
        if len(columns) > 8:
            columns_preview += " ..."
        table.add_row(
            item["name"],
            str(item.get("rows")),
            "yes" if item.get("saved") else "no",
            columns_preview,
        )

    console.print(table)
    console.print(f"[green]Saved summary:[/green] {summary_path}")


if __name__ == "__main__":
    app()
