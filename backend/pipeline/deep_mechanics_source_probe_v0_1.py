import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow.parquet as pq


PROBE_VERSION = "deep_mechanics_source_probe_v0_1"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def lower_columns(columns: List[str]) -> List[str]:
    return [str(c).lower() for c in columns]


def matching(columns: List[str], needles: List[str], limit: int = 80) -> List[str]:
    out = []
    for c in columns:
        lc = str(c).lower()
        if any(n in lc for n in needles):
            out.append(str(c))
    return out[:limit]


def choose_columns(columns: List[str], groups: Dict[str, List[str]], limit: int = 36) -> List[str]:
    selected = []
    for needles in groups.values():
        for c in matching(columns, needles, limit=20):
            if c not in selected:
                selected.append(c)
            if len(selected) >= limit:
                return selected
    return selected


def sample_first_rows(path: Path, selected_columns: List[str], max_rows: int = 3) -> List[Dict[str, Any]]:
    if not selected_columns:
        return []

    try:
        pf = pq.ParquetFile(path)
        if pf.num_row_groups <= 0:
            return []

        table = pf.read_row_group(0, columns=selected_columns)
        df = table.to_pandas()
        df = df.head(max_rows)

        rows = []
        for _, row in df.iterrows():
            item = {}
            for col in selected_columns:
                value = row.get(col)
                try:
                    if hasattr(value, "item"):
                        value = value.item()
                except Exception:
                    pass
                item[col] = None if str(value) in ("nan", "NaT", "<NA>") else value
            rows.append(item)

        return rows

    except Exception as e:
        return [{"sample_error": f"{type(e).__name__}: {e}"}]


def inspect_table(path: Path) -> Dict[str, Any]:
    groups = {
        "timeline": ["round", "tick", "time", "second", "clock"],
        "identity": ["player", "name", "steam", "user", "attacker", "victim"],
        "team_side": ["team", "side", "ct", "terrorist"],
        "position": ["x", "y", "z", "pos", "position", "place", "area", "site"],
        "view_aim": ["yaw", "pitch", "view", "angle", "aim", "crosshair"],
        "shot_fire": ["shot", "fire", "weapon_fire", "bullet", "ammo"],
        "movement": ["vel", "velocity", "speed", "duck", "jump", "ground", "move", "strafe", "buttons"],
        "combat": ["weapon", "damage", "dmg", "health", "armor", "headshot", "hitgroup"],
        "flash_visibility": ["flash", "blind", "visible", "visibility", "spotted"],
        "objective": ["bomb", "plant", "defuse"],
    }

    if not path.exists():
        return {
            "exists": False,
            "file": str(path),
            "rows": None,
            "columns_count": 0,
            "columns": [],
            "key_columns": {},
            "selected_sample_columns": [],
            "sample_rows": [],
            "error": "file does not exist",
        }

    try:
        pf = pq.ParquetFile(path)
        columns = list(pf.schema.names)
        selected = choose_columns(columns, groups)

        key_columns = {
            group: matching(columns, needles)
            for group, needles in groups.items()
        }

        return {
            "exists": True,
            "file": str(path),
            "rows": int(pf.metadata.num_rows) if pf.metadata else None,
            "row_groups": int(pf.num_row_groups),
            "columns_count": len(columns),
            "columns": columns,
            "key_columns": key_columns,
            "selected_sample_columns": selected,
            "sample_rows": sample_first_rows(path, selected),
            "error": None,
        }

    except Exception as e:
        return {
            "exists": True,
            "file": str(path),
            "rows": None,
            "columns_count": 0,
            "columns": [],
            "key_columns": {},
            "selected_sample_columns": [],
            "sample_rows": [],
            "error": f"{type(e).__name__}: {e}",
        }


def score_capability(table_info: Dict[str, Any]) -> Dict[str, Any]:
    kc = table_info.get("key_columns", {})

    def has(group: str) -> bool:
        return bool(kc.get(group))

    return {
        "timeline": has("timeline"),
        "identity": has("identity"),
        "position": has("position"),
        "view_aim": has("view_aim"),
        "shot_fire": has("shot_fire"),
        "movement": has("movement"),
        "combat": has("combat"),
        "flash_visibility": has("flash_visibility"),
        "objective": has("objective"),
    }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    parsed_dir = root / "data" / "parsed" / match_id
    out_dir = root / "data" / "runs" / match_id

    target_tables = [
        "shots",
        "ticks",
        "view_ticks_demoparser2",
        "kills",
        "damages",
        "bomb",
        "grenades",
        "smokes",
        "infernos",
    ]

    tables = {}
    capability_matrix = {}

    for name in target_tables:
        path = parsed_dir / f"{name}.parquet"
        info = inspect_table(path)
        info["file"] = rel(path, root)
        tables[name] = info
        capability_matrix[name] = score_capability(info)

    deep_mechanics_readiness = {
        "has_view_source": any(capability_matrix[t]["view_aim"] for t in ["view_ticks_demoparser2", "ticks"]),
        "has_shot_source": capability_matrix["shots"]["shot_fire"] or capability_matrix["shots"]["timeline"],
        "has_movement_source": any(capability_matrix[t]["movement"] for t in ["ticks", "view_ticks_demoparser2", "shots"]),
        "has_position_source": any(capability_matrix[t]["position"] for t in ["ticks", "view_ticks_demoparser2", "shots", "kills", "damages"]),
        "has_flash_visibility_source": any(capability_matrix[t]["flash_visibility"] for t in ["ticks", "view_ticks_demoparser2", "shots", "damages"]),
        "has_combat_link": capability_matrix["kills"]["combat"] or capability_matrix["damages"]["combat"],
    }

    ready_count = sum(1 for v in deep_mechanics_readiness.values() if v)

    if ready_count >= 5:
        readiness_status = "ready"
    elif ready_count >= 3:
        readiness_status = "limited_ready"
    else:
        readiness_status = "not_ready"

    result = {
        "status": "ok",
        "probe": PROBE_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "match_id": match_id,
        "player": player,
        "parsed_dir": rel(parsed_dir, root),
        "deep_mechanics_readiness": {
            "status": readiness_status,
            "signals": deep_mechanics_readiness,
            "ready_signals_count": ready_count,
        },
        "capability_matrix": capability_matrix,
        "tables": tables,
        "next_layer_notes": [
            "Use shots for fire timing if it has player/tick/weapon columns.",
            "Use view_ticks_demoparser2 or ticks for yaw/pitch around fight windows.",
            "Use ticks/view source for velocity and movement state if available.",
            "Link fight windows from kills/damages/manual mechanics events.",
            "Do not label aim errors if view/movement/visibility context is unavailable."
        ],
    }

    out_json = out_dir / f"deep_mechanics_source_probe_{player}_v0_1.json"
    out_current = out_dir / "deep_mechanics_source_probe_current.json"
    out_csv = out_dir / f"deep_mechanics_source_probe_{player}_v0_1.csv"

    write_json(out_json, result)
    write_json(out_current, result)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "table",
            "rows",
            "columns_count",
            "timeline",
            "identity",
            "position",
            "view_aim",
            "shot_fire",
            "movement",
            "combat",
            "flash_visibility",
            "objective",
            "important_columns"
        ])
        writer.writeheader()

        for table, info in tables.items():
            caps = capability_matrix.get(table, {})
            important = []
            for group in ["timeline", "identity", "position", "view_aim", "shot_fire", "movement", "combat", "flash_visibility"]:
                important.extend(info.get("key_columns", {}).get(group, []))
            important = list(dict.fromkeys(important))[:50]

            writer.writerow({
                "table": table,
                "rows": info.get("rows"),
                "columns_count": info.get("columns_count"),
                "timeline": caps.get("timeline"),
                "identity": caps.get("identity"),
                "position": caps.get("position"),
                "view_aim": caps.get("view_aim"),
                "shot_fire": caps.get("shot_fire"),
                "movement": caps.get("movement"),
                "combat": caps.get("combat"),
                "flash_visibility": caps.get("flash_visibility"),
                "objective": caps.get("objective"),
                "important_columns": ",".join(important),
            })

    compact_result = {
        "status": result["status"],
        "probe": PROBE_VERSION,
        "match_id": match_id,
        "player": player,
        "deep_mechanics_readiness": result["deep_mechanics_readiness"],
        "capability_matrix": result["capability_matrix"],
        "table_summaries": {
            name: {
                "rows": info.get("rows"),
                "columns_count": info.get("columns_count"),
                "key_columns": info.get("key_columns"),
                "selected_sample_columns": info.get("selected_sample_columns"),
                "sample_rows": info.get("sample_rows"),
                "error": info.get("error"),
            }
            for name, info in tables.items()
        },
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "csv": rel(out_csv, root),
        }
    }

    print(json.dumps(compact_result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    build(args)


if __name__ == "__main__":
    main()
