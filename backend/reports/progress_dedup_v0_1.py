from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def dedup_json(progress_path: Path) -> dict[str, Any]:
    data = read_json(progress_path)
    matches = data.get("matches", [])

    if not isinstance(matches, list):
        return {
            "path": str(progress_path),
            "exists": progress_path.exists(),
            "before": 0,
            "after": 0,
            "removed": 0,
            "status": "no_matches_list",
        }

    before = len(matches)

    # Keep last occurrence for each logical match.
    # Prefer match_id; fallback to demo_name; final fallback to list index.
    latest_by_key: dict[str, tuple[int, dict[str, Any]]] = {}

    for idx, match in enumerate(matches):
        if not isinstance(match, dict):
            key = f"__raw_index_{idx}"
        else:
            match_id = match.get("match_id")
            demo_name = match.get("demo_name")
            key = str(match_id or demo_name or f"__index_{idx}")

        latest_by_key[key] = (idx, match)

    deduped_pairs = sorted(latest_by_key.values(), key=lambda x: x[0])
    deduped = [m for _, m in deduped_pairs]

    data["matches"] = deduped
    after = len(deduped)

    if progress_path.exists() and before != after:
        backup = progress_path.with_suffix(progress_path.suffix + ".bak")
        backup.write_text(progress_path.read_text(encoding="utf-8"), encoding="utf-8")
        write_json(progress_path, data)

    return {
        "path": str(progress_path),
        "exists": progress_path.exists(),
        "before": before,
        "after": after,
        "removed": before - after,
        "status": "ok",
    }


def sqlite_tables(con: sqlite3.Connection) -> list[str]:
    cur = con.cursor()
    return [
        str(r[0])
        for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ]


def has_columns(con: sqlite3.Connection, table: str, columns: list[str]) -> bool:
    cur = con.cursor()
    existing = [str(r[1]) for r in cur.execute(f"PRAGMA table_info({table})")]
    return all(c in existing for c in columns)


def count_rows(con: sqlite3.Connection, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def dedup_sqlite(db_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(db_path),
        "exists": db_path.exists(),
        "tables": {},
        "status": "ok",
    }

    if not db_path.exists():
        result["status"] = "missing"
        return result

    con = sqlite3.connect(db_path)
    try:
        tables = sqlite_tables(con)

        if "matches" in tables:
            before = count_rows(con, "matches")

            if has_columns(con, "matches", ["match_id"]):
                con.execute("""
                    DELETE FROM matches
                    WHERE rowid NOT IN (
                        SELECT MAX(rowid)
                        FROM matches
                        GROUP BY match_id
                    )
                """)

            after = count_rows(con, "matches")
            result["tables"]["matches"] = {
                "before": before,
                "after": after,
                "removed": before - after,
            }

        if "player_match_metrics" in tables:
            before = count_rows(con, "player_match_metrics")

            if has_columns(con, "player_match_metrics", ["match_id", "player_name"]):
                con.execute("""
                    DELETE FROM player_match_metrics
                    WHERE rowid NOT IN (
                        SELECT MAX(rowid)
                        FROM player_match_metrics
                        GROUP BY match_id, player_name
                    )
                """)

            after = count_rows(con, "player_match_metrics")
            result["tables"]["player_match_metrics"] = {
                "before": before,
                "after": after,
                "removed": before - after,
            }

        con.commit()
    finally:
        con.close()

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate CS Demo Coach progress history.")
    parser.add_argument("--player", required=True)
    parser.add_argument("--progress-dir", default="data/progress")
    args = parser.parse_args()

    progress_dir = Path(args.progress_dir)
    progress_json = progress_dir / f"progress_{args.player}.json"
    progress_sqlite = progress_dir / "progress.sqlite"

    json_result = dedup_json(progress_json)
    sqlite_result = dedup_sqlite(progress_sqlite)

    print("OK: Progress dedup complete")
    print("")
    print("JSON:")
    print(f"  path: {json_result['path']}")
    print(f"  before: {json_result['before']}")
    print(f"  after: {json_result['after']}")
    print(f"  removed: {json_result['removed']}")

    print("")
    print("SQLite:")
    print(f"  path: {sqlite_result['path']}")
    for table, info in sqlite_result.get("tables", {}).items():
        print(f"  {table}: {info['before']} -> {info['after']} | removed={info['removed']}")


if __name__ == "__main__":
    main()
