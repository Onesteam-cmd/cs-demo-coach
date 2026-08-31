import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


SCANNER_VERSION = "parsed_data_capabilities_scanner_v0_1"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def lower_columns(columns: List[str]) -> List[str]:
    return [str(c).lower() for c in columns]


def has_any(cols: List[str], needles: List[str]) -> bool:
    return any(any(n in c for n in needles) for c in cols)


def matching(cols_original: List[str], needles: List[str], limit: int = 30) -> List[str]:
    out = []
    for c in cols_original:
        lc = str(c).lower()
        if any(n in lc for n in needles):
            out.append(str(c))
    return out[:limit]


def read_parquet_meta(path: Path) -> Dict[str, Any]:
    try:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(path)
        columns = list(pf.schema.names)
        return {
            "ok": True,
            "engine": "pyarrow",
            "rows": int(pf.metadata.num_rows) if pf.metadata else None,
            "columns": columns,
            "error": None,
        }
    except Exception as e1:
        try:
            import pandas as pd
            df = pd.read_parquet(path)
            return {
                "ok": True,
                "engine": "pandas",
                "rows": int(len(df)),
                "columns": [str(c) for c in df.columns],
                "error": None,
            }
        except Exception as e2:
            return {
                "ok": False,
                "engine": None,
                "rows": None,
                "columns": [],
                "error": f"pyarrow={type(e1).__name__}: {e1}; pandas={type(e2).__name__}: {e2}",
            }


def classify_table(name: str, columns: List[str]) -> Dict[str, Any]:
    cols = lower_columns(columns)

    signals = {
        "round_or_tick_timing": {
            "has_round": has_any(cols, ["round"]),
            "has_tick": has_any(cols, ["tick"]),
            "has_time_seconds": has_any(cols, ["time", "second", "clock"]),
            "matching_columns": matching(columns, ["round", "tick", "time", "second", "clock"]),
        },
        "actors": {
            "has_player_or_name": has_any(cols, ["player", "name", "steam", "user"]),
            "has_attacker": has_any(cols, ["attacker"]),
            "has_victim": has_any(cols, ["victim"]),
            "has_assister": has_any(cols, ["assist"]),
            "has_team_or_side": has_any(cols, ["team", "side", "ct", "t_"]),
            "matching_columns": matching(columns, ["player", "name", "steam", "attacker", "victim", "assist", "team", "side"]),
        },
        "positions": {
            "has_generic_xyz": has_any(cols, ["x", "y", "z"]),
            "has_position_words": has_any(cols, ["pos", "position", "place", "area", "site"]),
            "has_actor_positions": has_any(cols, ["attacker_x", "attacker_y", "victim_x", "victim_y", "player_x", "player_y"]),
            "matching_columns": matching(columns, ["x", "y", "z", "pos", "position", "place", "area", "site"]),
        },
        "view_and_aim": {
            "has_yaw_pitch": has_any(cols, ["yaw", "pitch"]),
            "has_view_angle": has_any(cols, ["view", "angle", "aim", "crosshair"]),
            "has_shots_or_fire": has_any(cols, ["shot", "fire", "weapon_fire", "bullet"]),
            "matching_columns": matching(columns, ["yaw", "pitch", "view", "angle", "aim", "crosshair", "shot", "fire", "bullet"]),
        },
        "movement": {
            "has_velocity": has_any(cols, ["vel", "velocity", "speed"]),
            "has_movement_flags": has_any(cols, ["duck", "jump", "ground", "move", "strafe"]),
            "matching_columns": matching(columns, ["vel", "velocity", "speed", "duck", "jump", "ground", "move", "strafe"]),
        },
        "utility_and_visibility": {
            "has_grenade": has_any(cols, ["grenade", "flash", "smoke", "inferno", "molotov", "hegrenade", "decoy"]),
            "has_flash": has_any(cols, ["flash", "blind"]),
            "has_smoke": has_any(cols, ["smoke"]),
            "has_inferno_fire": has_any(cols, ["inferno", "molotov", "fire"]),
            "matching_columns": matching(columns, ["grenade", "flash", "blind", "smoke", "inferno", "molotov", "fire", "hegrenade", "decoy"]),
        },
        "combat": {
            "has_damage": has_any(cols, ["damage", "dmg", "health", "armor"]),
            "has_weapon": has_any(cols, ["weapon"]),
            "has_headshot": has_any(cols, ["headshot", "head"]),
            "matching_columns": matching(columns, ["damage", "dmg", "health", "armor", "weapon", "headshot", "head"]),
        },
        "bomb_objective": {
            "has_bomb": has_any(cols, ["bomb", "plant", "defuse"]),
            "matching_columns": matching(columns, ["bomb", "plant", "defuse"]),
        },
        "sound_or_comm_proxy": {
            "has_sound": has_any(cols, ["sound", "footstep", "step", "noise"]),
            "has_chat_or_voice": has_any(cols, ["chat", "voice", "comm"]),
            "matching_columns": matching(columns, ["sound", "footstep", "step", "noise", "chat", "voice", "comm"]),
        }
    }

    capability_tags = []

    if signals["round_or_tick_timing"]["has_tick"] and signals["round_or_tick_timing"]["has_round"]:
        capability_tags.append("timeline_ready")

    if signals["actors"]["has_attacker"] and signals["actors"]["has_victim"]:
        capability_tags.append("combat_actor_ready")

    if signals["positions"]["has_actor_positions"] or (
        signals["positions"]["has_generic_xyz"] and signals["actors"]["has_player_or_name"]
    ):
        capability_tags.append("position_ready")

    if signals["view_and_aim"]["has_yaw_pitch"] or signals["view_and_aim"]["has_view_angle"]:
        capability_tags.append("view_angle_ready")

    if signals["view_and_aim"]["has_shots_or_fire"]:
        capability_tags.append("shot_timing_ready")

    if signals["movement"]["has_velocity"] or signals["movement"]["has_movement_flags"]:
        capability_tags.append("movement_ready")

    if signals["utility_and_visibility"]["has_flash"]:
        capability_tags.append("flash_context_ready")

    if signals["utility_and_visibility"]["has_smoke"]:
        capability_tags.append("smoke_context_ready")

    if signals["sound_or_comm_proxy"]["has_sound"]:
        capability_tags.append("sound_proxy_ready")

    if signals["bomb_objective"]["has_bomb"]:
        capability_tags.append("objective_ready")

    return {
        "table": name,
        "signals": signals,
        "capability_tags": capability_tags,
    }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    parsed_dir = root / "data" / "parsed" / match_id
    out_dir = root / "data" / "runs" / match_id

    errors: List[str] = []
    warnings: List[str] = []

    if not parsed_dir.exists():
        raise FileNotFoundError(f"MISSING parsed dir: {parsed_dir}")

    parquet_files = sorted(parsed_dir.glob("*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(f"MISSING parquet files in: {parsed_dir}")

    tables: Dict[str, Any] = {}

    global_tags = set()
    total_rows_known = 0
    readable_tables = 0

    for path in parquet_files:
        meta = read_parquet_meta(path)
        table_name = path.stem

        table_info = {
            "file": rel(path, root),
            "ok": meta["ok"],
            "engine": meta["engine"],
            "rows": meta["rows"],
            "columns_count": len(meta["columns"]),
            "columns": meta["columns"],
            "error": meta["error"],
        }

        if meta["ok"]:
            readable_tables += 1
            if isinstance(meta["rows"], int):
                total_rows_known += meta["rows"]

            classified = classify_table(table_name, meta["columns"])
            table_info["signals"] = classified["signals"]
            table_info["capability_tags"] = classified["capability_tags"]

            for tag in classified["capability_tags"]:
                global_tags.add(tag)
        else:
            warnings.append(f"could not read parquet metadata: {rel(path, root)}")

        tables[table_name] = table_info

    needed_for_deep_layers = {
        "canonical_info_state_v0_1": {
            "minimum": ["timeline_ready", "combat_actor_ready"],
            "better_with": ["position_ready", "objective_ready", "flash_context_ready", "smoke_context_ready", "sound_proxy_ready"],
        },
        "enemy_intent_inference_v0_1": {
            "minimum": ["timeline_ready", "combat_actor_ready", "objective_ready"],
            "better_with": ["position_ready", "smoke_context_ready", "flash_context_ready"],
        },
        "mechanics_deep_analyzer_v0_1": {
            "minimum": ["timeline_ready", "combat_actor_ready"],
            "better_with": ["view_angle_ready", "shot_timing_ready", "movement_ready", "flash_context_ready", "position_ready"],
        },
        "decision_context_v0_1": {
            "minimum": ["timeline_ready", "combat_actor_ready"],
            "better_with": ["position_ready", "objective_ready", "smoke_context_ready", "flash_context_ready"],
        },
    }

    layer_readiness = {}

    for layer, req in needed_for_deep_layers.items():
        minimum = req["minimum"]
        better_with = req["better_with"]

        missing_minimum = [x for x in minimum if x not in global_tags]
        present_better = [x for x in better_with if x in global_tags]
        missing_better = [x for x in better_with if x not in global_tags]

        if missing_minimum:
            status = "not_ready"
        elif len(present_better) >= max(1, len(better_with) // 2):
            status = "ready"
        else:
            status = "limited_ready"

        layer_readiness[layer] = {
            "status": status,
            "minimum_required": minimum,
            "missing_minimum": missing_minimum,
            "present_supporting_signals": present_better,
            "missing_supporting_signals": missing_better,
        }

    result = {
        "status": "ok",
        "scanner": SCANNER_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "match_id": match_id,
        "player": player,
        "parsed_dir": rel(parsed_dir, root),
        "tables_total": len(parquet_files),
        "readable_tables": readable_tables,
        "total_rows_known": total_rows_known,
        "global_capability_tags": sorted(global_tags),
        "layer_readiness": layer_readiness,
        "tables": tables,
        "warnings": warnings,
        "errors": errors,
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    root = project_root()
    result = build(args)

    out_dir = root / "data" / "runs" / args.match_id
    out_json = out_dir / f"parsed_data_capabilities_{args.player}_v0_1.json"
    out_current = out_dir / "parsed_data_capabilities_current.json"
    out_csv = out_dir / f"parsed_data_capabilities_{args.player}_v0_1.csv"

    write_json(out_json, result)
    write_json(out_current, result)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "table",
            "ok",
            "rows",
            "columns_count",
            "capability_tags",
            "important_columns"
        ])
        writer.writeheader()

        for table, info in result["tables"].items():
            important_cols = []
            for group in info.get("signals", {}).values():
                important_cols.extend(group.get("matching_columns", []))
            important_cols = list(dict.fromkeys(important_cols))[:40]

            writer.writerow({
                "table": table,
                "ok": str(info.get("ok")),
                "rows": str(info.get("rows")),
                "columns_count": str(info.get("columns_count")),
                "capability_tags": ",".join(info.get("capability_tags", [])),
                "important_columns": ",".join(important_cols),
            })

    compact = {
        "status": result["status"],
        "scanner": SCANNER_VERSION,
        "match_id": result["match_id"],
        "player": result["player"],
        "tables_total": result["tables_total"],
        "readable_tables": result["readable_tables"],
        "global_capability_tags": result["global_capability_tags"],
        "layer_readiness": result["layer_readiness"],
        "warnings": result["warnings"],
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "csv": rel(out_csv, root),
        }
    }

    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
