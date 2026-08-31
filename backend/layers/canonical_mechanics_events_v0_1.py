from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "canonical_mechanics_events_v0_1"


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Could not read JSON {path}: {e}")
        return {}


def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        try:
            return pd.read_csv(path, encoding="utf-8")
        except Exception as e:
            print(f"[WARN] Could not read CSV {path}: {e}")
            return pd.DataFrame()


def norm_col(value: Any) -> str:
    return safe_str(value).strip().lower().replace(" ", "_").replace("-", "_")


def get_by_alias(row: pd.Series, aliases: list[str], default: Any = None) -> Any:
    cols = {norm_col(c): c for c in row.index}
    for alias in aliases:
        key = norm_col(alias)
        if key in cols:
            value = row.get(cols[key])
            try:
                if pd.isna(value):
                    return default
            except Exception:
                pass
            return value
    return default


def truthy_yes(value: Any) -> bool:
    text = safe_str(value).strip().lower()
    return text in {"yes", "true", "1", "y", "да", "partial", "частично"}


def is_partial(value: Any) -> bool:
    text = safe_str(value).strip().lower()
    return text in {"partial", "частично"}


def find_list_of_dicts(obj: Any) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []

    def visit(x: Any) -> None:
        nonlocal best

        if isinstance(x, list):
            dicts = [item for item in x if isinstance(item, dict)]
            if len(dicts) > len(best):
                best = dicts
            for item in x:
                visit(item)
        elif isinstance(x, dict):
            for value in x.values():
                visit(value)

    visit(obj)
    return best


def auto_value(row: dict[str, Any], aliases: list[str], default: Any = None) -> Any:
    keys = {norm_col(k): k for k in row.keys()}
    for alias in aliases:
        key = norm_col(alias)
        if key in keys:
            return row.get(keys[key])
    return default


def parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [safe_str(x) for x in value if safe_str(x)]
    text = safe_str(value)
    if not text:
        return []

    for sep in ["|", ",", ";"]:
        if sep in text:
            return [x.strip() for x in text.split(sep) if x.strip()]

    return [text]


def build_from_manual(manual_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if manual_df.empty:
        return rows

    for idx, r in manual_df.iterrows():
        round_num = safe_int(get_by_alias(r, ["round_num", "round", "r"]))
        tick = safe_int(get_by_alias(r, ["contact_start_tick", "tick", "start_tick", "event_tick"]))
        end_tick = safe_int(get_by_alias(r, ["contact_end_tick", "end_tick"]))

        real_issue = safe_str(get_by_alias(r, ["real_issue"]))
        keep = safe_str(get_by_alias(r, ["keep_for_training"]))
        root = safe_str(get_by_alias(r, ["root_cause"])) or "unknown"
        review_status = safe_str(get_by_alias(r, ["review_status"])) or "unknown"

        is_real = truthy_yes(real_issue)
        is_keep = truthy_yes(keep)
        actionable = (is_real or is_partial(real_issue)) and is_keep
        clean = safe_str(real_issue).strip().lower() == "yes" and is_keep
        noise = safe_str(real_issue).strip().lower() == "no" or safe_str(keep).strip().lower() == "no"

        priority = safe_float(get_by_alias(r, ["priority_score_v3", "priority_score", "priority"], 0.0))

        rows.append({
            "event_id": f"manual_{idx + 1}",
            "source": "manual_review",
            "round_num": round_num,
            "tick": tick,
            "end_tick": end_tick,
            "target": safe_str(get_by_alias(r, ["target", "target_name"])),
            "outcome": safe_str(get_by_alias(r, ["outcome"])),
            "weapon": safe_str(get_by_alias(r, ["weapon", "viewer_weapon_start"])),
            "first_shooter": safe_str(get_by_alias(r, ["first_shooter"])),
            "delay_ticks": safe_int(get_by_alias(r, ["delay", "viewer_shot_delay_ticks"])),
            "speed": safe_float(get_by_alias(r, ["speed", "viewer_first_shot_speed"])),
            "aim_error_deg": safe_float(get_by_alias(r, ["aim_error", "viewer_first_shot_error_min_deg"])),
            "distance": safe_float(get_by_alias(r, ["distance", "start_distance"])),
            "strict_tags": parse_tags(get_by_alias(r, ["strict_tags", "tags"])),
            "review_status": review_status,
            "manual_visible": safe_str(get_by_alias(r, ["manual_visible"])),
            "real_issue": real_issue,
            "noise_reason": safe_str(get_by_alias(r, ["noise_reason"])),
            "root_cause": root,
            "keep_for_training": keep,
            "manual_note": safe_str(get_by_alias(r, ["manual_note", "note"])),
            "is_actionable": actionable,
            "is_clean_training_example": clean,
            "is_noise_or_not_real": noise,
            "priority_score": priority,
        })

    return rows


def build_from_auto(moments_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = find_list_of_dicts(moments_payload)
    out: list[dict[str, Any]] = []

    for idx, row in enumerate(raw_rows):
        round_num = safe_int(auto_value(row, ["round_num", "round"]))
        tick = safe_int(auto_value(row, ["contact_start_tick", "tick", "start_tick"]))

        if round_num is None and tick is None:
            continue

        tags = parse_tags(auto_value(row, ["strict_tags", "tags"]))
        root = "unknown"
        if "large_aim_error" in tags or "large_first_shot_error" in tags:
            root = "large_first_shot_error"
        elif "moving_first" in tags:
            root = "moving_first"
        elif "late_shot" in tags:
            root = "late_shot"
        elif "no_response" in tags:
            root = "no_response"

        priority = safe_float(auto_value(row, ["priority_score_v3", "priority_score", "priority"], 0.0))

        out.append({
            "event_id": f"auto_{idx + 1}",
            "source": "moments_review_auto",
            "round_num": round_num,
            "tick": tick,
            "end_tick": safe_int(auto_value(row, ["contact_end_tick", "end_tick"])),
            "target": safe_str(auto_value(row, ["target_name", "target"])),
            "outcome": safe_str(auto_value(row, ["outcome"])),
            "weapon": safe_str(auto_value(row, ["viewer_weapon_start", "weapon"])),
            "first_shooter": safe_str(auto_value(row, ["first_shooter"])),
            "delay_ticks": safe_int(auto_value(row, ["viewer_shot_delay_ticks", "delay"])),
            "speed": safe_float(auto_value(row, ["viewer_first_shot_speed", "speed"])),
            "aim_error_deg": safe_float(auto_value(row, ["viewer_first_shot_error_min_deg", "aim_error"])),
            "distance": safe_float(auto_value(row, ["start_distance", "distance"])),
            "strict_tags": tags,
            "review_status": "auto",
            "manual_visible": "",
            "real_issue": "",
            "noise_reason": "",
            "root_cause": root,
            "keep_for_training": "",
            "manual_note": "",
            "is_actionable": False,
            "is_clean_training_example": False,
            "is_noise_or_not_real": False,
            "priority_score": priority,
        })

    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts = Counter(r.get("source") for r in rows)
    status_counts = Counter(r.get("review_status") or "unknown" for r in rows)
    real_counts = Counter(r.get("real_issue") or "unknown" for r in rows)
    root_counts = Counter(r.get("root_cause") or "unknown" for r in rows)
    noise_counts = Counter(r.get("noise_reason") or "unknown" for r in rows)

    actionable = [r for r in rows if r.get("is_actionable")]
    clean = [r for r in rows if r.get("is_clean_training_example")]
    noise = [r for r in rows if r.get("is_noise_or_not_real")]

    main_root = ""
    useful_roots = Counter(r.get("root_cause") for r in actionable if r.get("root_cause") and r.get("root_cause") != "unknown")
    if useful_roots:
        main_root = useful_roots.most_common(1)[0][0]
    elif root_counts:
        main_root = root_counts.most_common(1)[0][0]

    top_training = []
    for r in sorted(actionable, key=lambda x: -safe_float(x.get("priority_score")))[:12]:
        top_training.append({
            "event_id": r.get("event_id"),
            "round_num": r.get("round_num"),
            "tick": r.get("tick"),
            "root_cause": r.get("root_cause"),
            "real_issue": r.get("real_issue"),
            "keep_for_training": r.get("keep_for_training"),
            "priority_score": r.get("priority_score"),
        })

    return {
        "version": VERSION,
        "events_total": len(rows),
        "source_counts": dict(source_counts),
        "review_status_counts": dict(status_counts),
        "real_issue_counts": dict(real_counts),
        "root_cause_counts": dict(root_counts),
        "noise_reason_counts": dict(noise_counts),
        "actionable_count": len(actionable),
        "clean_training_examples": len(clean),
        "noise_or_not_real_count": len(noise),
        "main_root_cause": main_root,
        "top_training_examples": top_training,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    moments_json = data_root / "reports" / args.match_id / "moments_review_v0_2.json"
    manual_csv = data_root / "reviews" / args.match_id / f"manual_review_{args.player}_v0_1.csv"

    print("=== Canonical Mechanics Events v0.1 ===")
    print(f"Moments JSON: {moments_json} exists={moments_json.exists()}")
    print(f"Manual CSV:   {manual_csv} exists={manual_csv.exists()}")

    moments_payload = load_json_optional(moments_json)
    manual_df = read_csv_optional(manual_csv)

    manual_rows = build_from_manual(manual_df)
    auto_rows = build_from_auto(moments_payload)

    if manual_rows:
        rows = manual_rows
    else:
        rows = auto_rows

    rows = sorted(rows, key=lambda r: (
        safe_int(r.get("round_num"), 9999) or 9999,
        safe_int(r.get("tick"), 999999999) or 999999999,
        safe_str(r.get("event_id")),
    ))

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "moments_json": str(moments_json),
            "manual_csv": str(manual_csv),
        },
        "summary": summarize(rows),
        "rows": rows,
    }

    out_dir = data_root / "layers" / args.match_id
    json_path = out_dir / f"canonical_mechanics_events_{args.player}_v0_1.json"
    csv_path = out_dir / f"canonical_mechanics_events_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows)

    print("")
    print("=== CANONICAL MECHANICS EVENTS v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
