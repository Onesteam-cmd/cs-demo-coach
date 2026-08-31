from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.canonical_io_v0_1 import safe_float, safe_int, safe_str, write_csv, write_json, print_json


VERSION = "coach_brief_builder_v0_1"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def first(items: list[Any], default: Any = None) -> Any:
    return items[0] if items else default


def top_items(items: list[Any], limit: int) -> list[Any]:
    return items[:limit] if isinstance(items, list) else []


def compact_round_list(rounds: list[dict[str, Any]], limit: int = 8) -> list[int]:
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


def collect_rounds_from_priorities(priorities: list[dict[str, Any]], top_cases: list[dict[str, Any]]) -> list[int]:
    seen = set()
    out = []

    for p in priorities[:4]:
        for r in p.get("top_rounds") or []:
            rn = safe_int(r.get("round_num"))
            if rn is not None and rn not in seen:
                seen.add(rn)
                out.append(rn)

    for c in top_cases[:10]:
        rn = safe_int(c.get("round_num"))
        if rn is not None and rn not in seen:
            seen.add(rn)
            out.append(rn)

    return out[:12]


def summarize_main_diagnosis(package: dict[str, Any]) -> dict[str, Any]:
    priorities = package.get("coach", {}).get("priorities", [])
    top = first(priorities, {}) or {}

    return {
        "primary_title": top.get("title", "Недостаточно данных"),
        "primary_area": top.get("area", ""),
        "primary_score": top.get("priority_score"),
        "primary_confidence": top.get("confidence"),
        "primary_why": top.get("why_it_matters", ""),
        "short_diagnosis": build_short_diagnosis(package),
    }


def build_short_diagnosis(package: dict[str, Any]) -> str:
    priorities = package.get("coach", {}).get("priorities", [])
    loss_patterns = package.get("coach", {}).get("loss_patterns", [])
    phase = package.get("coach", {}).get("phase_profile", {})
    area = package.get("coach", {}).get("area_profile", {})
    advantage = package.get("coach", {}).get("advantage_profile", {})

    top_priority = first(priorities, {}) or {}
    top_loss = first(loss_patterns, {}) or {}
    main_phase = safe_str(phase.get("main_problem_phase"))
    top_area = first(area.get("top_problem_areas", []), {}) or {}

    parts = []

    if top_priority:
        parts.append(f"главный приоритет — {safe_str(top_priority.get('title'))}")

    if top_loss:
        parts.append(f"частый паттерн проигранных раундов — {safe_str(top_loss.get('title'))}")

    if main_phase:
        parts.append(f"проблемная фаза — {main_phase}")

    if top_area and safe_str(top_area.get("area")):
        parts.append(f"проблемная зона — {safe_str(top_area.get('area'))}")

    neg_swings = safe_int(advantage.get("tag_counts", {}).get("death_from_even"), 0) if isinstance(advantage.get("tag_counts"), dict) else 0
    if neg_swings:
        parts.append("есть смерти, которые ломают равный state")

    if not parts:
        return "Сигналов пока недостаточно: нужен ручной review top rounds."

    return "; ".join(parts) + "."


def build_sections(package: dict[str, Any]) -> dict[str, Any]:
    coach = package.get("coach", {})
    summaries = package.get("summaries", {})

    priorities = top_items(coach.get("priorities", []), 5)
    action_blocks = top_items(coach.get("action_blocks", []), 5)
    session_plan = top_items(coach.get("session_plan", []), 4)
    top_cases = top_items(package.get("rounds", {}).get("top_cases", []), 12)

    loss_patterns = top_items(coach.get("loss_patterns", []), 6)
    utility_value = top_items(coach.get("utility_value", []), 6)
    combat_profile = coach.get("combat_profile", {})
    phase_profile = coach.get("phase_profile", {})
    advantage_profile = coach.get("advantage_profile", {})
    area_profile = coach.get("area_profile", {})

    return {
        "priorities": [
            {
                "rank": p.get("rank"),
                "area": p.get("area"),
                "title": p.get("title"),
                "tier": p.get("priority_tier"),
                "score": p.get("priority_score"),
                "confidence": p.get("confidence"),
                "evidence_count": p.get("evidence_count"),
                "training_focus": p.get("training_focus"),
                "review_rounds": compact_round_list(p.get("top_rounds") or []),
            }
            for p in priorities
        ],
        "loss_patterns": loss_patterns,
        "phase_profile": {
            "main_problem_phase": phase_profile.get("main_problem_phase"),
            "problem_rounds_total": phase_profile.get("problem_rounds_total"),
            "phase_problem_scores": phase_profile.get("phase_problem_scores", []),
            "top_problem_rounds": phase_profile.get("top_problem_rounds", []),
        },
        "area_profile": {
            "top_problem_areas": area_profile.get("top_problem_areas", []),
            "top_value_areas": area_profile.get("top_value_areas", []),
        },
        "advantage_profile": {
            "swing_label_counts": advantage_profile.get("swing_label_counts", {}),
            "tag_counts": advantage_profile.get("tag_counts", {}),
            "top_negative_swings": advantage_profile.get("top_negative_swings", []),
            "top_positive_swings": advantage_profile.get("top_positive_swings", []),
        },
        "utility_value": utility_value,
        "combat_profile": {
            "top_weapons": combat_profile.get("top_weapons", []),
            "top_combat_rounds": combat_profile.get("top_combat_rounds", []),
            "combat_label_counts": combat_profile.get("combat_label_counts", {}),
        },
        "review_rounds": collect_rounds_from_priorities(priorities, top_cases),
        "top_cases": top_cases,
        "session_plan": session_plan,
        "action_blocks": action_blocks,
        "health": package.get("health", {}),
        "summaries": {
            "round_cases": summaries.get("round_cases", {}),
            "coach_priority": summaries.get("coach_priority", {}),
            "loss_patterns": summaries.get("loss_patterns", {}),
            "phase_profile": summaries.get("phase_profile", {}),
            "area_profile": summaries.get("area_profile", {}),
            "advantage_profile": summaries.get("advantage_profile", {}),
            "combat_profile": summaries.get("combat_profile", {}),
            "utility_value": summaries.get("utility_value", {}),
        },
    }


def build_final_notes(sections: dict[str, Any]) -> list[str]:
    notes = []

    priorities = sections.get("priorities", [])
    if priorities:
        p = priorities[0]
        notes.append(f"Первым тренировать: {safe_str(p.get('title'))}.")

    loss_patterns = sections.get("loss_patterns", [])
    if loss_patterns:
        lp = loss_patterns[0]
        notes.append(f"Главный loss pattern: {safe_str(lp.get('title'))}; раунды: {', '.join(str(x) for x in lp.get('rounds', [])[:6])}.")

    main_phase = sections.get("phase_profile", {}).get("main_problem_phase")
    if main_phase:
        notes.append(f"По timing чаще всего проблемы подсвечены в фазе: {main_phase}.")

    top_area = first(sections.get("area_profile", {}).get("top_problem_areas", []), {}) or {}
    if top_area:
        notes.append(f"По зонам first review: {safe_str(top_area.get('area'))}.")

    adv_tags = sections.get("advantage_profile", {}).get("tag_counts", {})
    if isinstance(adv_tags, dict) and adv_tags:
        negative_keys = [
            "death_from_even",
            "death_while_team_ahead",
            "opening_death_swing",
            "death_in_lost_round",
            "kill_not_converted_to_round",
        ]
        negative_tags = {
            k: safe_int(adv_tags.get(k), 0)
            for k in negative_keys
            if safe_int(adv_tags.get(k), 0) > 0
        }

        if negative_tags:
            top_tag = sorted(negative_tags.items(), key=lambda kv: (-safe_int(kv[1], 0), kv[0]))[0]
            notes.append(f"По round-state главный негативный swing-сигнал: {top_tag[0]} = {top_tag[1]}.")

    if not notes:
        notes.append("Нужен ручной review top cases, чтобы подтвердить главные причины.")

    return notes


def build_payload(package: dict[str, Any], match_id: str, player: str) -> dict[str, Any]:
    sections = build_sections(package)
    diagnosis = summarize_main_diagnosis(package)

    return {
        "version": VERSION,
        "match_id": match_id,
        "player": player,
        "source_package_version": package.get("version"),
        "diagnosis": diagnosis,
        "sections": sections,
        "final_notes": build_final_notes(sections),
    }


def rows_for_csv(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    for p in payload.get("sections", {}).get("priorities", []):
        rows.append({
            "section": "priority",
            "rank": p.get("rank"),
            "title": p.get("title"),
            "area": p.get("area"),
            "score": p.get("score"),
            "detail": p.get("training_focus"),
            "rounds": p.get("review_rounds"),
        })

    for i, note in enumerate(payload.get("final_notes", []), start=1):
        rows.append({
            "section": "final_note",
            "rank": i,
            "title": note,
            "area": "",
            "score": "",
            "detail": "",
            "rounds": "",
        })

    for c in payload.get("sections", {}).get("top_cases", [])[:10]:
        rows.append({
            "section": "round_case",
            "rank": "",
            "title": c.get("case_label"),
            "area": "",
            "score": c.get("case_priority_score"),
            "detail": c.get("case_reasons"),
            "rounds": c.get("round_num"),
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

    package_json = data_root / "package" / args.match_id / f"match_package_{args.player}_v0_7.json"

    print("=== Coach Brief Builder v0.1 ===")
    print(f"Match package: {package_json} exists={package_json.exists()}")

    package = load_json(package_json)
    payload = build_payload(package, args.match_id, args.player)

    out_dir = data_root / "verdict" / args.match_id
    json_path = out_dir / f"coach_brief_{args.player}_v0_1.json"
    csv_path = out_dir / f"coach_brief_{args.player}_v0_1.csv"

    write_json(json_path, payload)
    write_csv(csv_path, rows_for_csv(payload))

    print("")
    print("=== COACH BRIEF v0.1 COMPLETE ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("")
    print_json({
        "diagnosis": payload.get("diagnosis"),
        "final_notes": payload.get("final_notes"),
        "review_rounds": payload.get("sections", {}).get("review_rounds"),
    })


if __name__ == "__main__":
    main()

