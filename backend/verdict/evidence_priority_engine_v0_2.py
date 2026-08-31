from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json
from backend.verdict.evidence_priority_engine_v0_1 import (
    trade_spacing_issues,
    round_impact_issues,
    postplant_issues,
    utility_issues,
    merge_duplicate_issues,
    rank_issues,
    summarize,
    issue_rows_for_csv,
)


VERSION = "evidence_priority_engine_v0_2"


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Could not read JSON {path}: {e}")
        return {}


def confidence_from_mechanics_issue(issue: dict[str, Any]) -> str:
    conf = safe_str(issue.get("confidence"))
    if conf:
        return conf

    clean = safe_int(issue.get("clean_training_examples"), 0) or 0
    evidence = safe_int(issue.get("evidence_count"), 0) or 0

    if clean >= 3:
        return "high"
    if evidence >= 3:
        return "medium"
    return "low"


def map_mechanics_problem_id(group: str) -> str:
    group = safe_str(group)

    if group == "first_shot_accuracy":
        return "mechanics.first_shot_accuracy"
    if group == "movement_shooting":
        return "mechanics.moving_first_shot"
    if group == "no_response":
        return "mechanics.no_response"
    if group == "duel_decision":
        return "mechanics.duel_decision"
    if group == "visibility_noise":
        return "mechanics.visibility_noise"

    return f"mechanics.{group or 'unknown'}"


def mechanics_training_focus(group: str) -> list[str]:
    group = safe_str(group)

    if group == "first_shot_accuracy":
        return [
            "pre-aim на уровне головы",
            "доводка crosshair перед первым bullet",
            "не стрелять во время недовода/перефлика",
            "разбирать top mechanics examples по round/tick",
        ]

    if group == "movement_shooting":
        return [
            "counter-strafe перед первым bullet",
            "peek-stop-shoot",
            "проверять скорость в момент первого выстрела",
        ]

    if group == "no_response":
        return [
            "разобрать, почему не было ответа на контакт",
            "отделить flash/grenade/reload ситуации от настоящей реакции",
            "проверить ready-state перед углом",
        ]

    if group == "duel_decision":
        return [
            "не переигрывать угол без условия",
            "проверять overpeek после первого контакта",
            "сравнивать риск дуэли с value для раунда",
        ]

    return [
        "проверить top examples вручную",
        "отделить настоящую ошибку от шума",
    ]


def mechanics_why(group: str) -> str:
    group = safe_str(group)

    if group == "first_shot_accuracy":
        return "Это подтверждённый manual-review mechanics-паттерн: первый bullet часто уходит до точной доводки, из-за чего даже нормальные позиции теряют value."

    if group == "movement_shooting":
        return "Если первый bullet сделан во время движения, качество aim фактически теряет значение: выстрел становится нестабильным."

    if group == "no_response":
        return "No-response моменты показывают ситуации, где игрок не успевает или не может ответить на реальный контакт."

    if group == "duel_decision":
        return "Некоторые смерти могут быть не aim-проблемой, а плохим выбором дуэли, overpeek или неправильным timing."

    return "Mechanics-сигнал требует проверки по top examples."


def mechanics_top_rounds(issue: dict[str, Any]) -> list[dict[str, Any]]:
    out = []

    for ev in issue.get("top_events") or []:
        rn = safe_int(ev.get("round_num"))
        if rn is None:
            continue

        out.append({
            "round_num": rn,
            "score": safe_float(ev.get("priority_score")),
            "label": safe_str(ev.get("root_cause")),
            "round_result": "",
            "kd_damage": "",
            "reasons": [
                f"event={safe_str(ev.get('event_id'))}",
                f"tick={safe_int(ev.get('tick'))}",
                f"root={safe_str(ev.get('root_cause'))}",
            ],
        })

    return out[:8]


def mechanics_issues_from_layer(mechanics_problem: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []

    for issue in mechanics_problem.get("issues", []):
        group = safe_str(issue.get("group"))
        if group == "visibility_noise":
            continue

        severity_score = safe_float(issue.get("severity_score"))
        evidence_count = safe_int(issue.get("evidence_count"), 0) or 0

        if evidence_count <= 0:
            continue

        issues.append({
            "problem_id": map_mechanics_problem_id(group),
            "area": "mechanics",
            "title": safe_str(issue.get("title")),
            "severity_score": severity_score,
            "severity": safe_str(issue.get("severity")),
            "confidence": confidence_from_mechanics_issue(issue),
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": mechanics_top_rounds(issue),
            "why_it_matters": mechanics_why(group),
            "training_focus": mechanics_training_focus(group),
        })

    return issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    reports = data_root / "reports" / args.match_id
    analysis = data_root / "analysis" / args.match_id

    paths = {
        "mechanics_problem": analysis / f"mechanics_problem_{args.player}_v0_1.json",
        "utility_map_summary": reports / "utility_map_summary_v0_1.json",
        "utility_analyzer": reports / "utility_analyzer_v0_2.json",
        "trade_spacing": analysis / f"trade_spacing_{args.player}_v0_1.json",
        "round_impact": analysis / f"round_impact_{args.player}_v0_1.json",
        "postplant_retake": analysis / f"postplant_retake_{args.player}_v0_1.json",
    }

    print("=== Evidence Priority Engine v0.2 ===")
    for name, path in paths.items():
        print(f"{name}: {path} exists={path.exists()}")

    payloads = {name: load_json_optional(path) for name, path in paths.items()}

    issues: list[dict[str, Any]] = []
    issues.extend(mechanics_issues_from_layer(payloads["mechanics_problem"]))
    issues.extend(trade_spacing_issues(payloads["trade_spacing"]))
    issues.extend(round_impact_issues(payloads["round_impact"]))
    issues.extend(postplant_issues(payloads["postplant_retake"]))
    issues.extend(utility_issues(payloads["utility_map_summary"], payloads["utility_analyzer"]))

    issues = merge_duplicate_issues(issues)
    issues = rank_issues(issues)
    summary = summarize(issues)

    out_payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {k: str(v) for k, v in paths.items()},
        "summary": summary,
        "issues": issues,
    }

    out_dir = data_root / "verdict" / args.match_id
    json_path = out_dir / f"evidence_priority_{args.player}_v0_2.json"
    csv_path = out_dir / f"evidence_priority_{args.player}_v0_2.csv"

    write_json(json_path, out_payload)
    write_csv(csv_path, issue_rows_for_csv(issues))

    print("")
    print("=== EVIDENCE PRIORITY ENGINE v0.2 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
