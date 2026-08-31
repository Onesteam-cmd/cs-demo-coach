from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "coach_priority_engine_v0_2"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def severity(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def confidence_rank(value: str) -> int:
    return {
        "low": 1,
        "medium": 2,
        "high": 3,
    }.get(value, 1)


def best_confidence(values: list[str]) -> str:
    if not values:
        return "low"
    ordered = sorted(values, key=confidence_rank, reverse=True)
    return ordered[0]


def find_issue(issues: list[dict[str, Any]], problem_id: str) -> dict[str, Any] | None:
    for issue in issues:
        if safe_str(issue.get("problem_id")) == problem_id:
            return issue
    return None


def top_rounds_unique(issues: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    seen = set()
    out = []

    for issue in issues:
        for r in issue.get("top_rounds") or []:
            rn = safe_int(r.get("round_num"))
            if rn is None or rn in seen:
                continue
            seen.add(rn)
            out.append(r)
            if len(out) >= limit:
                return out

    return out


def merge_training_focus(issues: list[dict[str, Any]]) -> list[str]:
    seen = set()
    out = []

    for issue in issues:
        for item in issue.get("training_focus") or []:
            key = safe_str(item).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)

    return out[:8]


def cluster_score(issues: list[dict[str, Any]], base_bonus: float = 0.0) -> float:
    if not issues:
        return 0.0

    best = max(safe_float(i.get("priority_score")) for i in issues)
    evidence = sum(safe_int(i.get("evidence_count"), 0) or 0 for i in issues)
    source_count = sum(safe_int(i.get("source_count"), 0) or 0 for i in issues)

    score = best + base_bonus
    score += min(12, evidence * 0.8)
    score += min(8, source_count * 1.5)

    return round(clamp(score), 1)


def make_cluster(
    cluster_id: str,
    area: str,
    title: str,
    issues: list[dict[str, Any]],
    why: str,
    training_focus_override: list[str] | None = None,
    base_bonus: float = 0.0,
) -> dict[str, Any] | None:
    issues = [i for i in issues if i]
    if not issues:
        return None

    score = cluster_score(issues, base_bonus=base_bonus)
    evidence_count = sum(safe_int(i.get("evidence_count"), 0) or 0 for i in issues)
    source_problem_ids = [safe_str(i.get("problem_id")) for i in issues if safe_str(i.get("problem_id"))]

    return {
        "cluster_id": cluster_id,
        "area": area,
        "title": title,
        "priority_score": score,
        "severity": severity(score),
        "confidence": best_confidence([safe_str(i.get("confidence")) for i in issues]),
        "evidence_count": evidence_count,
        "source_problem_ids": source_problem_ids,
        "top_rounds": top_rounds_unique(issues),
        "why_it_matters": why,
        "training_focus": training_focus_override if training_focus_override is not None else merge_training_focus(issues),
    }


def build_clusters(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    issues = evidence.get("issues", [])

    mechanics_first = find_issue(issues, "mechanics.first_shot_accuracy")
    mechanics_moving = find_issue(issues, "mechanics.moving_first_shot")

    trade_untraded = find_issue(issues, "macro.trade_spacing.untraded_deaths")
    trade_kill_then = find_issue(issues, "macro.trade_spacing.kill_then_traded")
    major_losses = find_issue(issues, "round_impact.major_problem_losses")
    low_impact = find_issue(issues, "round_impact.low_impact_losses")
    plant_phase = find_issue(issues, "plant_phase.postplant_retake_impact")
    utility_timing = find_issue(issues, "utility.timing_position")
    utility_flash = find_issue(issues, "utility.flash_value")

    clusters: list[dict[str, Any]] = []

    c = make_cluster(
        cluster_id="mechanics.first_shot_control",
        area="mechanics",
        title="Первый выстрел: точность, доводка, стабильность",
        issues=[x for x in [mechanics_first, mechanics_moving] if x],
        why="Это самый подтверждённый слой: mechanics уже прошла ручную калибровку, и главный повторяемый паттерн связан с качеством первого bullet.",
        training_focus_override=[
            "pre-aim на уровне головы до контакта",
            "доводка crosshair перед первым bullet",
            "не стрелять во время недовода/перефлика",
            "отдельно проверять counter-strafe, если первый bullet сделан в движении",
        ],
        base_bonus=6.0,
    )
    if c:
        clusters.append(c)

    c = make_cluster(
        cluster_id="macro.trade_spacing_and_survival",
        area="macro",
        title="Размены, дистанция от тиммейтов и жизнь после kill",
        issues=[x for x in [trade_untraded, trade_kill_then, major_losses] if x],
        why="Несколько анализаторов указывают на один macro-контекст: игрок часто умирает без быстрого размена или получает kill, но затем быстро отдаёт refrag.",
        training_focus_override=[
            "перед контактом понимать, кто тебя трейдит",
            "не принимать одиночный fight без refrag-условия",
            "после kill сразу менять позицию или уходить за укрытие",
            "играть не только на kill, а на сохранение advantage после kill",
        ],
        base_bonus=2.0,
    )
    if c:
        clusters.append(c)

    c = make_cluster(
        cluster_id="round_impact.low_impact_losses",
        area="macro",
        title="Низкий impact в проигранных раундах",
        issues=[x for x in [low_impact] if x],
        why="Отдельный класс раундов, где игрок не дал достаточно measurable value до проигрыша: kill, damage, space, utility или информацию.",
        training_focus_override=[
            "заранее иметь early-round plan на gun rounds",
            "давать измеримый value даже без kill: damage, flash, molly, info, space",
            "после смерти проверять: команда получила что-то взамен или нет",
        ],
    )
    if c:
        clusters.append(c)

    c = make_cluster(
        cluster_id="plant_phase.postplant_retake",
        area="plant_phase",
        title="Post-plant / retake решения",
        issues=[x for x in [plant_phase] if x],
        why="Plant-phase раунды требуют отдельной логики: время, позиция, crossfire, utility и trade важнее обычной дуэли.",
        training_focus_override=[
            "на retake заходить под trade/utility, а не одиночно",
            "после plant играть от времени и crossfire",
            "отдельно разбирать смерти после plant",
        ],
    )
    if c:
        clusters.append(c)

    c = make_cluster(
        cluster_id="utility.timing_and_position",
        area="utility",
        title="Utility: тайминг, позиция, partial value",
        issues=[x for x in [utility_timing, utility_flash] if x],
        why="Utility слой показывает не полный провал, а partial-value: гранаты часто полезны по идее, но теряют силу из-за тайминга, позиции или отсутствия командной follow-up value.",
        training_focus_override=[
            "заготовить стабильные utility-сценарии",
            "проверять timing броска, а не только место приземления",
            "позже добавить lineups/gap/blind-duration слой",
        ],
    )
    if c:
        clusters.append(c)

    clusters = sorted(clusters, key=lambda x: (-safe_float(x.get("priority_score")), safe_str(x.get("cluster_id"))))

    for i, c in enumerate(clusters, start=1):
        c["rank"] = i
        if i == 1:
            c["priority_tier"] = "primary"
        elif i <= 3:
            c["priority_tier"] = "secondary"
        else:
            c["priority_tier"] = "supporting"

    return clusters


def build_training_blocks(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = []

    for c in clusters:
        if c.get("priority_tier") == "supporting":
            continue

        blocks.append({
            "block_id": f"training.{c.get('cluster_id')}",
            "source_cluster_id": c.get("cluster_id"),
            "title": c.get("title"),
            "priority_tier": c.get("priority_tier"),
            "goal": c.get("why_it_matters"),
            "focus": c.get("training_focus"),
            "review_rounds": [r.get("round_num") for r in (c.get("top_rounds") or []) if r.get("round_num") is not None],
        })

    return blocks


def summarize(clusters: list[dict[str, Any]], training_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    area_counts = Counter(c.get("area") for c in clusters)
    tier_counts = Counter(c.get("priority_tier") for c in clusters)

    return {
        "version": VERSION,
        "clusters_total": len(clusters),
        "training_blocks_total": len(training_blocks),
        "area_counts": dict(area_counts),
        "tier_counts": dict(tier_counts),
        "top_clusters": [
            {
                "rank": c.get("rank"),
                "cluster_id": c.get("cluster_id"),
                "title": c.get("title"),
                "area": c.get("area"),
                "priority_tier": c.get("priority_tier"),
                "priority_score": c.get("priority_score"),
                "severity": c.get("severity"),
                "confidence": c.get("confidence"),
                "evidence_count": c.get("evidence_count"),
            }
            for c in clusters[:5]
        ],
    }


def rows_for_csv(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for c in clusters:
        rows.append({
            "rank": c.get("rank"),
            "cluster_id": c.get("cluster_id"),
            "area": c.get("area"),
            "title": c.get("title"),
            "priority_tier": c.get("priority_tier"),
            "priority_score": c.get("priority_score"),
            "severity": c.get("severity"),
            "confidence": c.get("confidence"),
            "evidence_count": c.get("evidence_count"),
            "source_problem_ids": c.get("source_problem_ids"),
            "top_rounds": c.get("top_rounds"),
            "why_it_matters": c.get("why_it_matters"),
            "training_focus": c.get("training_focus"),
        })

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--player", required=True)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    root = Path.cwd()
    data_root = root / args.data_dir

    evidence_json = data_root / "verdict" / args.match_id / f"evidence_priority_{args.player}_v0_1.json"

    print("=== Coach Priority Engine v0.2 ===")
    print(f"Evidence priority: {evidence_json} exists={evidence_json.exists()}")

    evidence = load_json(evidence_json)

    clusters = build_clusters(evidence)
    training_blocks = build_training_blocks(clusters)
    summary = summarize(clusters, training_blocks)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "evidence_priority": str(evidence_json),
        },
        "summary": summary,
        "clusters": clusters,
        "training_blocks": training_blocks,
    }

    out_dir = data_root / "verdict" / args.match_id
    json_path = out_dir / f"coach_priority_{args.player}_v0_2.json"
    csv_path = out_dir / f"coach_priority_{args.player}_v0_2.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows_for_csv(clusters))

    print("")
    print("=== COACH PRIORITY ENGINE v0.2 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json(summary)


if __name__ == "__main__":
    main()
