from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_int, safe_float, safe_str, write_csv, write_json, print_json


VERSION = "evidence_priority_engine_v0_1"


def load_json_optional(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Could not read JSON {path}: {e}")
        return {}


def score_to_severity(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def confidence_from_sources(evidence_count: int, source_count: int, manual_confirmed: bool = False) -> str:
    if manual_confirmed and evidence_count >= 3:
        return "high"
    if source_count >= 2 and evidence_count >= 5:
        return "high"
    if evidence_count >= 3:
        return "medium"
    return "low"


def top_rounds_from_problem_rows(rows: list[dict[str, Any]], score_key: str, limit: int = 8) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda r: (-(safe_int(r.get(score_key), 0) or 0), safe_int(r.get("round_num"), 9999) or 9999),
    )

    out = []
    for r in ordered[:limit]:
        out.append({
            "round_num": safe_int(r.get("round_num")),
            "score": safe_int(r.get(score_key), 0),
            "label": safe_str(r.get("round_label") or r.get("category") or r.get("plant_phase_label")),
            "round_result": safe_str(r.get("round_result")),
            "kd_damage": f"{safe_int(r.get('player_kills'), 0)}/{safe_int(r.get('player_deaths'), 0)}/{safe_float(r.get('player_damage'))}",
            "reasons": r.get("problem_reasons") or r.get("reasons") or [],
        })
    return out


def mechanics_issues(manual_summary: dict[str, Any], coach_verdict: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    text = json.dumps([manual_summary, coach_verdict], ensure_ascii=False).lower()

    manual = manual_summary.get("summary", manual_summary)
    actionable = safe_int(manual.get("actionable_yes_or_partial_keep"), 0) or 0
    clean = safe_int(manual.get("clean_training_examples"), 0) or 0

    if "large_first_shot_error" in text or "качество первого выстрела" in text:
        evidence_count = max(actionable, clean, 5)
        score = min(100, 45 + clean * 4 + actionable * 2)

        issues.append({
            "problem_id": "mechanics.first_shot_accuracy",
            "area": "mechanics",
            "title": "Качество первого выстрела / недовод или перефлик",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": confidence_from_sources(evidence_count, 2, manual_confirmed=True),
            "evidence_count": evidence_count,
            "source_count": 2,
            "top_rounds": [],
            "why_it_matters": "Первый выстрел часто решает дуэль. Если первый bullet уходит до точной доводки, игрок проигрывает даже нормальные позиции.",
            "training_focus": [
                "pre-aim на уровне головы",
                "микродоводка до первого bullet",
                "не стрелять до стабилизации crosshair",
                "отдельно смотреть моменты с недоводом и перефликом",
            ],
        })

    if "moving_first" in text:
        evidence_count = 4
        score = 38
        issues.append({
            "problem_id": "mechanics.moving_first_shot",
            "area": "mechanics",
            "title": "Первый выстрел в движении / нестабильный counter-strafe",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": "medium",
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": [],
            "why_it_matters": "Даже правильный aim теряет value, если первый bullet сделан до остановки.",
            "training_focus": [
                "counter-strafe перед первым bullet",
                "короткие peek-stop-shoot упражнения",
                "проверка скорости в момент первого выстрела",
            ],
        })

    return issues


def trade_spacing_issues(trade_spacing: dict[str, Any]) -> list[dict[str, Any]]:
    if not trade_spacing:
        return []

    rows = trade_spacing.get("rows", [])
    summary = trade_spacing.get("summary", {})

    problem_rows = [r for r in rows if bool(r.get("is_problem"))]
    untraded_deaths = [r for r in problem_rows if safe_str(r.get("category")) in {"death_untraded", "preplant_death_untraded", "postplant_death_untraded", "opening_death_untraded"}]
    kill_traded = [r for r in problem_rows if safe_str(r.get("category")) in {"kill_traded_by_enemy", "opening_kill_traded"}]

    issues: list[dict[str, Any]] = []

    if untraded_deaths:
        evidence_count = len(untraded_deaths)
        high_count = sum(1 for r in untraded_deaths if safe_str(r.get("severity")) == "high")
        score = min(100, 35 + evidence_count * 4 + high_count * 7)

        issues.append({
            "problem_id": "macro.trade_spacing.untraded_deaths",
            "area": "macro",
            "title": "Смерти без быстрого размена",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": confidence_from_sources(evidence_count, 1),
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": top_rounds_from_problem_rows(untraded_deaths, "priority_score"),
            "why_it_matters": "Если смерть не разменивается, команда теряет игрока без компенсации. Это часто хуже, чем сама механическая ошибка в дуэли.",
            "training_focus": [
                "перед контактом понимать, кто тебя трейдит",
                "не принимать одиночные дуэли без refrag-условия",
                "если играешь первым номером — создавать понятный timing для тиммейта",
            ],
        })

    if kill_traded:
        evidence_count = len(kill_traded)
        score = min(100, 30 + evidence_count * 5)

        issues.append({
            "problem_id": "macro.trade_spacing.kill_then_traded",
            "area": "macro",
            "title": "После kill тебя быстро разменивают",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": confidence_from_sources(evidence_count, 1),
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": top_rounds_from_problem_rows(kill_traded, "priority_score"),
            "why_it_matters": "Kill сам по себе не всегда хороший, если после него игрок бесплатно отдаёт refrag и не меняет структуру раунда.",
            "training_focus": [
                "после kill сразу менять позицию",
                "не оставаться на открытой линии",
                "играть от укрытия и задержки второго контакта",
            ],
        })

    return issues


def round_impact_issues(round_impact: dict[str, Any]) -> list[dict[str, Any]]:
    if not round_impact:
        return []

    rows = round_impact.get("rows", [])
    summary = round_impact.get("summary", {})
    category_counts = summary.get("problem_category_counts", {})

    issues: list[dict[str, Any]] = []

    low_impact_rows = [
        r for r in rows
        if "low_impact_loss" in (r.get("problem_categories") or [])
    ]

    if low_impact_rows:
        evidence_count = len(low_impact_rows)
        score = min(100, 30 + evidence_count * 8)

        issues.append({
            "problem_id": "round_impact.low_impact_losses",
            "area": "macro",
            "title": "Проигранные раунды с низким личным impact",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": confidence_from_sources(evidence_count, 1),
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": top_rounds_from_problem_rows(low_impact_rows, "problem_score"),
            "why_it_matters": "В таких раундах игрок не дал kill, damage, space или заметную utility-value до проигрыша.",
            "training_focus": [
                "найти стабильный early-round plan",
                "каждый gun round давать измеримый value: damage, utility, info или space",
                "не выпадать из раунда без impact",
            ],
        })

    major_rows = [
        r for r in rows
        if safe_str(r.get("round_label")) == "major_problem_loss"
    ]

    if major_rows:
        evidence_count = len(major_rows)
        score = min(100, 45 + evidence_count * 8)

        issues.append({
            "problem_id": "round_impact.major_problem_losses",
            "area": "macro",
            "title": "Крупные проблемные проигранные раунды",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": confidence_from_sources(evidence_count, 1),
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": top_rounds_from_problem_rows(major_rows, "problem_score"),
            "why_it_matters": "Это раунды, где совпало несколько негативных факторов: смерть, отсутствие impact, плохой размен или plant-phase проблема.",
            "training_focus": [
                "просмотреть эти раунды первыми",
                "отделить aim-проблему от macro-проблемы",
                "искать повторяемое решение, а не единичный missplay",
            ],
        })

    return issues


def postplant_issues(postplant: dict[str, Any]) -> list[dict[str, Any]]:
    if not postplant:
        return []

    rows = postplant.get("rows", [])
    problem_rows = [
        r for r in rows
        if safe_int(r.get("plant_phase_score"), 0) > 0 and safe_str(r.get("plant_phase_label")) != "positive_plant_phase"
    ]

    if not problem_rows:
        return []

    evidence_count = len(problem_rows)
    major_count = sum(1 for r in problem_rows if safe_str(r.get("plant_phase_label")) == "major_plant_phase_problem")
    score = min(100, 25 + evidence_count * 6 + major_count * 10)

    return [{
        "problem_id": "plant_phase.postplant_retake_impact",
        "area": "plant_phase",
        "title": "Post-plant / retake impact",
        "severity_score": score,
        "severity": score_to_severity(score),
        "confidence": confidence_from_sources(evidence_count, 1),
        "evidence_count": evidence_count,
        "source_count": 1,
        "top_rounds": top_rounds_from_problem_rows(problem_rows, "plant_phase_score"),
        "why_it_matters": "После plant раунд часто решается не чистым aim, а позицией, utility, временем, trade и правильным входом/удержанием.",
        "training_focus": [
            "после plant играть от времени и crossfire",
            "на retake заходить не одиночно, а под trade/utility",
            "отдельно разбирать смерти после plant",
        ],
    }]


def utility_issues(utility_map_summary: dict[str, Any], old_utility: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    summary = utility_map_summary.get("summary", utility_map_summary)
    good = safe_int(summary.get("good"), 0) or 0
    partial = safe_int(summary.get("partial"), 0) or 0
    bad = safe_int(summary.get("bad"), 0) or 0
    checked = safe_int(summary.get("checked"), 0) or safe_int(summary.get("rows_total"), 0) or (good + partial + bad)

    if checked > 0 and (partial + bad) > 0:
        evidence_count = partial + bad
        score = min(100, 25 + partial * 6 + bad * 10)

        issues.append({
            "problem_id": "utility.timing_position",
            "area": "utility",
            "title": "Utility тайминг / позиция броска",
            "severity_score": score,
            "severity": score_to_severity(score),
            "confidence": confidence_from_sources(evidence_count, 1, manual_confirmed=True),
            "evidence_count": evidence_count,
            "source_count": 1,
            "top_rounds": [],
            "why_it_matters": "Граната может быть правильной по идее, но поздней, с gap или без value. Тогда команда не получает полного эффекта.",
            "training_focus": [
                "заготовить стабильные utility-сценарии",
                "проверять timing, а не только место приземления",
                "отдельно собрать lineups/gap слой позже",
            ],
        })

    text = json.dumps(old_utility, ensure_ascii=False).lower()
    if "нет flash assists" in text:
        issues.append({
            "problem_id": "utility.flash_value",
            "area": "utility",
            "title": "Низкая командная value от flash",
            "severity_score": 32,
            "severity": "low",
            "confidence": "low",
            "evidence_count": 1,
            "source_count": 1,
            "top_rounds": [],
            "why_it_matters": "Flash без ассистов не всегда плохая, но это сигнал, что blind/value слой надо проверять отдельно.",
            "training_focus": [
                "не считать flash только по количеству",
                "позже добавить blind-duration / teammate-peek слой",
            ],
        })

    return issues


def merge_duplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    for issue in issues:
        pid = issue.get("problem_id")
        if not pid:
            continue

        if pid not in by_id:
            by_id[pid] = issue
            continue

        old = by_id[pid]
        old["severity_score"] = max(safe_float(old.get("severity_score")), safe_float(issue.get("severity_score")))
        old["evidence_count"] = safe_int(old.get("evidence_count"), 0) + safe_int(issue.get("evidence_count"), 0)
        old["source_count"] = safe_int(old.get("source_count"), 0) + safe_int(issue.get("source_count"), 0)
        old["top_rounds"] = (old.get("top_rounds") or []) + (issue.get("top_rounds") or [])
        old["severity"] = score_to_severity(safe_float(old.get("severity_score")))

    return list(by_id.values())


def rank_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    area_weight = {
        "mechanics": 1.10,
        "macro": 1.00,
        "plant_phase": 0.95,
        "utility": 0.85,
    }

    confidence_weight = {
        "high": 1.15,
        "medium": 1.0,
        "low": 0.75,
    }

    for issue in issues:
        base = safe_float(issue.get("severity_score"))
        aw = area_weight.get(safe_str(issue.get("area")), 1.0)
        cw = confidence_weight.get(safe_str(issue.get("confidence")), 1.0)
        issue["priority_score"] = round(base * aw * cw, 1)

    return sorted(issues, key=lambda x: (-safe_float(x.get("priority_score")), safe_str(x.get("area")), safe_str(x.get("problem_id"))))


def summarize(issues: list[dict[str, Any]]) -> dict[str, Any]:
    area_counts = Counter(i.get("area") for i in issues)
    severity_counts = Counter(i.get("severity") for i in issues)

    top = []
    for i in issues[:5]:
        top.append({
            "problem_id": i.get("problem_id"),
            "area": i.get("area"),
            "title": i.get("title"),
            "priority_score": i.get("priority_score"),
            "severity": i.get("severity"),
            "confidence": i.get("confidence"),
            "evidence_count": i.get("evidence_count"),
        })

    return {
        "version": VERSION,
        "issues_total": len(issues),
        "area_counts": dict(area_counts),
        "severity_counts": dict(severity_counts),
        "top_issues": top,
    }


def issue_rows_for_csv(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for rank, issue in enumerate(issues, start=1):
        out.append({
            "rank": rank,
            "problem_id": issue.get("problem_id"),
            "area": issue.get("area"),
            "title": issue.get("title"),
            "priority_score": issue.get("priority_score"),
            "severity_score": issue.get("severity_score"),
            "severity": issue.get("severity"),
            "confidence": issue.get("confidence"),
            "evidence_count": issue.get("evidence_count"),
            "source_count": issue.get("source_count"),
            "why_it_matters": issue.get("why_it_matters"),
            "training_focus": issue.get("training_focus"),
            "top_rounds": issue.get("top_rounds"),
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

    reports = data_root / "reports" / args.match_id
    reviews = data_root / "reviews" / args.match_id
    analysis = data_root / "analysis" / args.match_id

    paths = {
        "coach_verdict": reports / f"coach_verdict_{args.player}_v0_2.json",
        "manual_mechanics_summary": reviews / f"manual_review_summary_{args.player}_v0_1.json",
        "utility_map_summary": reports / "utility_map_summary_v0_1.json",
        "utility_analyzer": reports / "utility_analyzer_v0_2.json",
        "trade_spacing": analysis / f"trade_spacing_{args.player}_v0_1.json",
        "round_impact": analysis / f"round_impact_{args.player}_v0_1.json",
        "postplant_retake": analysis / f"postplant_retake_{args.player}_v0_1.json",
    }

    print("=== Evidence Priority Engine v0.1 ===")
    for name, path in paths.items():
        print(f"{name}: {path} exists={path.exists()}")

    payloads = {name: load_json_optional(path) for name, path in paths.items()}

    issues: list[dict[str, Any]] = []
    issues.extend(mechanics_issues(payloads["manual_mechanics_summary"], payloads["coach_verdict"]))
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
    json_path = out_dir / f"evidence_priority_{args.player}_v0_1.json"
    csv_path = out_dir / f"evidence_priority_{args.player}_v0_1.csv"

    write_json(json_path, out_payload)
    write_csv(csv_path, issue_rows_for_csv(issues))

    print("")
    print("=== EVIDENCE PRIORITY ENGINE v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
