from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "coach_action_plan_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compact_rounds(rounds: list[dict[str, Any]], limit: int = 8) -> list[int]:
    out = []
    seen = set()

    for r in rounds or []:
        rn = safe_int(r.get("round_num"))
        if rn is None or rn in seen:
            continue
        seen.add(rn)
        out.append(rn)
        if len(out) >= limit:
            break

    return out


def action_type_for_cluster(cluster_id: str, area: str) -> str:
    if cluster_id.startswith("mechanics."):
        return "mechanics_drill"
    if "trade_spacing" in cluster_id:
        return "demo_review_and_decision_rule"
    if "low_impact" in cluster_id:
        return "round_plan"
    if "postplant" in cluster_id or area == "plant_phase":
        return "scenario_review"
    if cluster_id.startswith("utility."):
        return "utility_protocol"
    return "general_review"


def estimated_time_for_cluster(cluster_id: str, tier: str) -> int:
    if tier == "primary":
        return 25
    if tier == "secondary":
        return 15
    if "utility" in cluster_id:
        return 12
    return 10


def build_action_blocks(priority: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []

    for cluster in priority.get("clusters", []):
        cluster_id = safe_str(cluster.get("cluster_id"))
        tier = safe_str(cluster.get("priority_tier"))
        area = safe_str(cluster.get("area"))

        if tier not in {"primary", "secondary", "supporting"}:
            continue

        focus = cluster.get("training_focus") or []
        top_rounds = compact_rounds(cluster.get("top_rounds") or [])

        block = {
            "action_id": f"action.{cluster_id}",
            "source_cluster_id": cluster_id,
            "priority_rank": safe_int(cluster.get("rank")),
            "priority_tier": tier,
            "area": area,
            "title": safe_str(cluster.get("title")),
            "action_type": action_type_for_cluster(cluster_id, area),
            "estimated_minutes": estimated_time_for_cluster(cluster_id, tier),
            "priority_score": safe_float(cluster.get("priority_score")),
            "confidence": safe_str(cluster.get("confidence")),
            "evidence_count": safe_int(cluster.get("evidence_count"), 0),
            "why": safe_str(cluster.get("why_it_matters")),
            "focus": focus,
            "review_rounds": top_rounds,
            "done_condition": done_condition(cluster_id, area),
        }

        blocks.append(block)

    return sorted(blocks, key=lambda b: (safe_int(b.get("priority_rank"), 999), -safe_float(b.get("priority_score"))))


def done_condition(cluster_id: str, area: str) -> str:
    if cluster_id == "mechanics.first_shot_control":
        return "В следующей демке меньше чистых first-shot ошибок: меньше недоводов/перефликов и меньше первого bullet до доводки."
    if cluster_id == "macro.trade_spacing_and_survival":
        return "В следующих демках меньше смертей без размена и меньше ситуаций kill → мгновенный enemy trade."
    if cluster_id == "round_impact.low_impact_losses":
        return "В проигранных gun rounds чаще есть measurable value: damage, utility, info, space или trade."
    if cluster_id == "plant_phase.postplant_retake":
        return "В plant-rounds меньше одиночных смертей после plant и больше impact после установки/на retake."
    if cluster_id == "utility.timing_and_position":
        return "Меньше partial/bad utility из-за позднего timing, gap или неправильной позиции."
    return "Проблема реже повторяется в следующей демке."


def build_round_review_queue(priority: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[int, str]] = set()

    for cluster in priority.get("clusters", []):
        cluster_id = safe_str(cluster.get("cluster_id"))
        for r in cluster.get("top_rounds") or []:
            rn = safe_int(r.get("round_num"))
            if rn is None:
                continue

            key = (rn, cluster_id)
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "round_num": rn,
                "source_cluster_id": cluster_id,
                "area": safe_str(cluster.get("area")),
                "priority_rank": safe_int(cluster.get("rank")),
                "priority_tier": safe_str(cluster.get("priority_tier")),
                "cluster_title": safe_str(cluster.get("title")),
                "round_score": safe_int(r.get("score"), 0),
                "round_label": safe_str(r.get("label")),
                "round_result": safe_str(r.get("round_result")),
                "kd_damage": safe_str(r.get("kd_damage")),
                "auto_reasons": r.get("reasons") or [],
                "review_status": "todo",
                "real_issue": "",
                "root_cause": "",
                "manual_note": "",
            })

    return sorted(rows, key=lambda r: (
        safe_int(r.get("priority_rank"), 999),
        -safe_int(r.get("round_score"), 0),
        safe_int(r.get("round_num"), 9999)
    ))


def build_session_plan(action_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    session = []

    primary = [b for b in action_blocks if b.get("priority_tier") == "primary"]
    secondary = [b for b in action_blocks if b.get("priority_tier") == "secondary"]
    supporting = [b for b in action_blocks if b.get("priority_tier") == "supporting"]

    order = primary[:1] + secondary[:2] + supporting[:1]

    for idx, block in enumerate(order, start=1):
        session.append({
            "step": idx,
            "minutes": block.get("estimated_minutes"),
            "title": block.get("title"),
            "area": block.get("area"),
            "action_type": block.get("action_type"),
            "focus": (block.get("focus") or [])[:4],
            "review_rounds": block.get("review_rounds") or [],
            "done_condition": block.get("done_condition"),
        })

    return session


def build_summary(priority: dict[str, Any], action_blocks: list[dict[str, Any]], round_queue: list[dict[str, Any]]) -> dict[str, Any]:
    top = action_blocks[0] if action_blocks else {}

    return {
        "version": VERSION,
        "actions_total": len(action_blocks),
        "round_review_items_total": len(round_queue),
        "session_steps_total": min(4, len(action_blocks)),
        "primary_action": {
            "title": top.get("title"),
            "area": top.get("area"),
            "priority_score": top.get("priority_score"),
            "confidence": top.get("confidence"),
        } if top else {},
        "top_actions": [
            {
                "rank": a.get("priority_rank"),
                "title": a.get("title"),
                "area": a.get("area"),
                "tier": a.get("priority_tier"),
                "action_type": a.get("action_type"),
                "minutes": a.get("estimated_minutes"),
                "review_rounds": a.get("review_rounds"),
            }
            for a in action_blocks[:5]
        ],
    }


def csv_action_rows(action_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []

    for a in action_blocks:
        rows.append({
            "priority_rank": a.get("priority_rank"),
            "priority_tier": a.get("priority_tier"),
            "area": a.get("area"),
            "title": a.get("title"),
            "action_type": a.get("action_type"),
            "estimated_minutes": a.get("estimated_minutes"),
            "priority_score": a.get("priority_score"),
            "confidence": a.get("confidence"),
            "evidence_count": a.get("evidence_count"),
            "focus": a.get("focus"),
            "review_rounds": a.get("review_rounds"),
            "done_condition": a.get("done_condition"),
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

    priority_json = data_root / "verdict" / args.match_id / f"coach_priority_{args.player}_v0_2.json"

    print("=== Coach Action Plan v0.1 ===")
    print(f"Coach priority: {priority_json} exists={priority_json.exists()}")

    priority = load_json(priority_json)

    action_blocks = build_action_blocks(priority)
    round_queue = build_round_review_queue(priority)
    session_plan = build_session_plan(action_blocks)

    payload = {
        "version": VERSION,
        "match_id": args.match_id,
        "player": args.player,
        "inputs": {
            "coach_priority": str(priority_json),
        },
        "summary": build_summary(priority, action_blocks, round_queue),
        "session_plan": session_plan,
        "action_blocks": action_blocks,
        "round_review_queue": round_queue,
    }

    verdict_dir = data_root / "verdict" / args.match_id
    review_dir = data_root / "reviews" / args.match_id

    json_path = verdict_dir / f"coach_action_plan_{args.player}_v0_1.json"
    csv_path = verdict_dir / f"coach_action_plan_{args.player}_v0_1.csv"
    review_csv_path = review_dir / f"coach_round_review_queue_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, csv_action_rows(action_blocks))
    write_csv(review_csv_path, round_queue)

    print("")
    print("=== COACH ACTION PLAN v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"Round review queue: {review_csv_path}")
    print("")
    print_json(payload["summary"])


if __name__ == "__main__":
    main()
