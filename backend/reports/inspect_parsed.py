from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def inspect(parsed_dir: Path = typer.Argument(..., help="Folder from data/parsed/<demo_name>")):
    summary_path = parsed_dir / "parse_summary.json"

    if not summary_path.exists():
        console.print(f"[red]parse_summary.json not found:[/red] {summary_path}")
        raise typer.Exit(1)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    console.print(f"[bold]Demo:[/bold] {summary.get('demo_name')}")
    console.print(f"[bold]Path:[/bold] {summary.get('demo_path')}")

    table = Table(title="Available parsed tables")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    table.add_column("Saved")
    table.add_column("Columns")

    for item in summary.get("tables", []):
        columns = item.get("columns", [])
        table.add_row(
            item.get("name", ""),
            str(item.get("rows", "")),
            "yes" if item.get("saved") else "no",
            str(len(columns)),
        )

    console.print(table)


if __name__ == "__main__":
    app()
