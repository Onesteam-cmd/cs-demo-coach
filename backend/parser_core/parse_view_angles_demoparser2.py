from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def to_pandas(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value

    if hasattr(value, "to_pandas"):
        return value.to_pandas()

    if hasattr(value, "to_pandas_dataframe"):
        return value.to_pandas_dataframe()

    return pd.DataFrame(value)


def save_dataframe(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def try_parse_ticks(parser: Any, props: list[str]) -> tuple[pd.DataFrame | None, str | None]:
    try:
        result = parser.parse_ticks(props)
        df = to_pandas(result)
        return df, None
    except Exception as e:
        return None, str(e)


def main() -> None:
    argp = argparse.ArgumentParser()
    argp.add_argument("demo_path", type=Path)
    argp.add_argument("--out-dir", type=Path, default=Path("data/parsed/test"))
    args = argp.parse_args()

    if not args.demo_path.exists():
        raise SystemExit(f"Demo not found: {args.demo_path}")

    try:
        from demoparser2 import DemoParser
    except Exception as e:
        raise SystemExit(f"Failed to import demoparser2 DemoParser: {e}")

    print("=== demoparser2 view layer ===")
    print(f"Demo: {args.demo_path}")
    print(f"Out:  {args.out_dir}")

    parser = DemoParser(str(args.demo_path))

    # Наборы свойств специально идут от широкого к более безопасному.
    # У разных версий/типов демо доступные поля могут отличаться.
    prop_sets = [
        [
            "X", "Y", "Z",
            "pitch", "yaw",
            "velocity_X", "velocity_Y", "velocity_Z",
            "health", "armor_value",
            "is_alive",
            "active_weapon_name",
            "player_name", "steamid",
            "team_name",
        ],
        [
            "X", "Y", "Z",
            "pitch", "yaw",
            "health", "armor_value",
            "is_alive",
            "active_weapon_name",
            "player_name", "steamid",
        ],
        [
            "X", "Y", "Z",
            "pitch", "yaw",
            "health",
            "player_name", "steamid",
        ],
        [
            "X", "Y", "Z",
            "yaw",
            "player_name", "steamid",
        ],
        [
            "X", "Y", "Z",
            "player_name", "steamid",
        ],
    ]

    errors: list[dict[str, Any]] = []
    parsed_df: pd.DataFrame | None = None
    used_props: list[str] | None = None

    for props in prop_sets:
        print("")
        print("Trying props:")
        print(", ".join(props))

        df, err = try_parse_ticks(parser, props)

        if err:
            print("FAILED:")
            print(err[:1000])
            errors.append({"props": props, "error": err})
            continue

        if df is None or df.empty:
            print("FAILED: empty dataframe")
            errors.append({"props": props, "error": "empty dataframe"})
            continue

        parsed_df = df
        used_props = props
        print("OK")
        break

    if parsed_df is None:
        summary = {
            "ok": False,
            "demo_path": str(args.demo_path),
            "errors": errors,
        }
        summary_path = args.out_dir / "view_layer_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"Could not parse view layer. Summary saved: {summary_path}")

    out_path = args.out_dir / "view_ticks_demoparser2.parquet"
    preview_path = args.out_dir / "view_ticks_demoparser2_preview.csv"
    summary_path = args.out_dir / "view_layer_summary.json"

    save_dataframe(parsed_df, out_path)
    parsed_df.head(100).to_csv(preview_path, index=False, encoding="utf-8-sig")

    columns = list(map(str, parsed_df.columns))

    yaw_cols = [c for c in columns if "yaw" in c.lower()]
    pitch_cols = [c for c in columns if "pitch" in c.lower()]
    velocity_cols = [c for c in columns if "vel" in c.lower()]

    summary = {
        "ok": True,
        "demo_path": str(args.demo_path),
        "rows": int(len(parsed_df)),
        "columns": columns,
        "used_props": used_props,
        "has_yaw": len(yaw_cols) > 0,
        "has_pitch": len(pitch_cols) > 0,
        "yaw_columns": yaw_cols,
        "pitch_columns": pitch_cols,
        "velocity_columns": velocity_cols,
        "output_parquet": str(out_path),
        "preview_csv": str(preview_path),
        "errors_before_success": errors,
    }

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("")
    print("=== View layer parsed ===")
    print(f"Rows: {len(parsed_df)}")
    print(f"Columns: {columns}")
    print(f"Has yaw: {summary['has_yaw']} -> {yaw_cols}")
    print(f"Has pitch: {summary['has_pitch']} -> {pitch_cols}")
    print(f"Velocity columns: {velocity_cols}")
    print(f"Saved: {out_path}")
    print(f"Preview: {preview_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
