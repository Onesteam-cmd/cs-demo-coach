from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "mechanics_problem_analyzer_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def group_root(root: str) -> str:
    root = safe_str(root).strip().lower()

    if root in {"large_first_shot_error", "bad_pre_aim", "large_aim_error"}:
        return "first_shot_accuracy"

    if root in {"moving_first", "bad_counter_strafe"}:
        return "movement_shooting"

    if root.startswith("no_response"):
        return "no_response"

    if root in {"bad_duel_choice", "overpeek", "enemy_timing"}:
        return "duel_decision"

    if root in {"visibility_noise"}:
        return "visibility_noise"

    if not root:
        return "unknown"

    return root


def title_for_group(group: str) -> str:
    return {
        "first_shot_accuracy": "Качество первого выстрела / доводка crosshair",
        "movement_shooting": "Первый выстрел в движении / counter-strafe",
        "no_response": "No-response моменты",
        "duel_decision": "Выбор дуэли / overpeek / timing",
        "visibility_noise": "Шум видимости",
        "unknown": "Неопределённая mechanics-причина",
    }.get(group, group)


def build_issues(mech_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = mech_payload.get("rows", [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        if not bool(row.get("is_actionable")):
            continue
        group = group_root(row.get("root_cause"))
        grouped[group].append(row)

    issues = []

    for group, items in grouped.items():
        clean_count = sum(1 for r in items if bool(r.get("is_clean_training_example")))
        partial_count = len(items) - clean_count
        avg_priority = round(sum(safe_float(r.get("priority_score")) for r in items) / max(1, len(items)), 2)

        score = 20 + len(items) * 6 + clean_count * 4
        if group == "first_shot_accuracy":
            score += 15
        if group == "visibility_noise":
            score -= 20

        score = max(0, min(100, score))

        if score >= 75:
            severity = "critical"
        elif score >= 55:
            severity = "high"
        elif score >= 35:
            severity = "medium"
        else:
            severity = "low"

        confidence = "high" if clean_count >= 3 else "medium" if len(items) >= 3 else "low"

        top_events = []
        for r in sorted(items, key=lambda x: -safe_float(x.get("priority_score")))[:10]:
            top_events.append({
                "event_id": r.get("event_id"),
                "round_num": r.get("round_num"),
                "tick": r.get("tick"),
                "root_cause": r.get("root_cause"),
                "real_issue": r.get("real_issue"),
                "keep_for_training": r.get("keep_for_training"),
                "priority_score": r.get("priority_score"),
            })

        issues.append({
            "issue_id": f"mechanics.{group}",
            "area": "mechanics",
            "group": group,
            "title": title_for_group(group),
            "severity_score": round(score, 1),
            "severity": severity,
            "confidence": confidence,
            "evidence_count": len(items),
            "clean_training_examples": clean_count,
            "partial_examples": partial_count,
            "avg_source_priority": avg_priority,
            "top_events": top_events,
        })

    return sorted(issues, key=lambda x: (-safe_float(x.get("severity_score")), safe_str(x.get("issue_id"))))


def summarize(issues: list[dict[str, Any]], mech_payload: dict[str, Any]) -> dict[str, Any]:
    groups = Counter(i.get("group") for i in issues)
    severity = Counter(i.get("severity") for i in issues)
    summary = mech_payload.get("summary", {})

    return {
        "version": VERSION,
        "issues_total": len(issues),
        "group_counts": dict(groups),
        "severity_counts": dict(severity),
        "source_events_total": summary.get("events_total"),
        "source_actionable_count": summary.get("actionable_count"),
        "source_clean_training_examples": summary.get("clean_training_examples"),
        "main_issue": issues[0] if issues else {},
    }


def rows_for_csv(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i in issues:
        out.append({
            "issue_id": i.get("issue_id"),
            "area": i.get("area"),
            "group": i.get("group"),
            "title": i.get("title"),
            "severity_score": i.get("severity_score"),
            "severity": i.get("severity"),
            "confidence": i.get("confidence"),
            "evidence_count": i.get("evidence_count"),
            "clean_training_examples": i.get("clean_training_examples"),
            "partial_examples": i.get("partial_examples"),
            "top_events": i.get("top_events"),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    mech_json = data_root / "layers" / args.match_id / f"canonical_mechanics_events_{args.player}_v0_1.json"

    print("=== Mechanics Problem Analyzer v0.1 ===")
    print(f"Mechanics layer: {mech_json} exists={mech_json.exists()}")

    mech_payload = load_json(mech_json)
    issues = build_issues(mech_payload)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "canonical_mechanics_events": str(mech_json),
        },
        "summary": summarize(issues, mech_payload),
        "issues": issues,
    }

    out_dir = data_root / "analysis" / args.match_id
    json_path = out_dir / f"mechanics_problem_{args.player}_v0_1.json"
    csv_path = out_dir / f"mechanics_problem_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows_for_csv(issues))

    print("")
    print("=== MECHANICS PROBLEM ANALYZER v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
