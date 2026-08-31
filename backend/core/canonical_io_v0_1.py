from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def norm(value: Any) -> str:
    return safe_str(value).strip().lower()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.columns:
            return name
    return None


def round_col(df: pd.DataFrame) -> str | None:
    return first_col(df, ["round_num", "round", "roundNumber"])


def filter_round(df: pd.DataFrame, round_num: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    rc = round_col(df)
    if not rc:
        return df.iloc[0:0].copy()
    return df[df[rc] == round_num].copy()


def find_parquet(data_root: Path, match_id: str, filename: str) -> Path | None:
    candidates = list(data_root.rglob(filename))
    if not candidates:
        return None

    matched = [p for p in candidates if match_id.lower() in str(p).lower()]
    if matched:
        candidates = matched

    def score(path: Path) -> tuple[int, int]:
        s = str(path).lower()
        preferred = 0 if any(x in s for x in ["parsed", "parquet", "processed", "data"]) else 1
        return (preferred, len(str(path)))

    return sorted(candidates, key=score)[0]


def read_parquet_optional(path: Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as e:
        print(f"[WARN] Could not read parquet {path}: {e}")
        return pd.DataFrame()


def normalize_grenade_type(value: Any) -> str:
    raw = safe_str(value).strip()
    low = raw.lower()

    if "flash" in low:
        return "flashbang"
    if "smoke" in low:
        return "smoke"
    if "molotov" in low:
        return "molotov"
    if "incendiary" in low:
        return "incendiary"
    if "hegrenade" in low or low in {"he", "grenade"}:
        return "he"
    if "decoy" in low:
        return "decoy"

    return low or raw


def to_builtin(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): to_builtin(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [to_builtin(x) for x in obj]

    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass

    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:
            pass

    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass

    return obj


def csv_ready_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        clean = {}
        for k, v in row.items():
            v = to_builtin(v)
            if isinstance(v, (dict, list)):
                clean[k] = json.dumps(v, ensure_ascii=False)
            else:
                clean[k] = v
        out.append(clean)
    return out


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_builtin(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(csv_ready_rows(rows)).to_csv(path, index=False, encoding="utf-8-sig")


def print_json(obj: Any) -> None:
    print(json.dumps(to_builtin(obj), ensure_ascii=False, indent=2))
