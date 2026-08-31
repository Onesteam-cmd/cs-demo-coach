import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


COMPACTOR_VERSION = "ai_coach_judge_input_compactor_v0_2"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def keep_dict(d: Any, keys: List[str]) -> Dict[str, Any]:
    if not isinstance(d, dict):
        return {}
    return {k: d.get(k) for k in keys if d.get(k) not in (None, "", [], {})}


def compact_event(event: Any) -> Dict[str, Any]:
    if not isinstance(event, dict):
        return {}

    player_snapshot = event.get("player_snapshot") or {}
    aim_context = event.get("aim_context") or {}
    shot_context = event.get("shot_context") or {}
    combat_context = event.get("combat_context") or {}

    return {
        "event_id": event.get("event_id"),
        "round_num": event.get("round_num"),
        "tick": event.get("tick"),
        "root_cause": event.get("root_cause"),
        "deep_label": event.get("deep_label"),
        "deep_confidence": event.get("deep_confidence"),
        "deep_flags": as_list(event.get("deep_flags"))[:8],
        "speed_band": player_snapshot.get("speed_band"),
        "speed": player_snapshot.get("speed"),
        "yaw_error_band": aim_context.get("yaw_error_band"),
        "yaw_error_abs_deg_approx": aim_context.get("yaw_error_abs_deg_approx"),
        "shots_after_event": shot_context.get("shots_after_event"),
        "first_shot_delay_ms_assumed": shot_context.get("first_shot_delay_ms_assumed"),
        "combat_role": combat_context.get("role"),
        "opponent": combat_context.get("opponent"),
        "combat_place": combat_context.get("place"),
    }


def compact_death_snapshot(snapshot: Any) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}

    last = snapshot.get("opponent_last_known") or {}
    interp = snapshot.get("interpretation_v0_2") or snapshot.get("interpretation_v0_1") or {}

    return {
        "round_num": snapshot.get("round_num"),
        "tick": snapshot.get("tick"),
        "focus_event_kind": snapshot.get("focus_event_kind"),
        "opponent": snapshot.get("opponent"),
        "opponent_info_context": snapshot.get("opponent_info_context"),
        "opponent_last_known": {
            "age_sec": last.get("age_sec"),
            "freshness": last.get("freshness"),
            "source": last.get("source"),
            "confidence": last.get("confidence"),
            "area": last.get("area"),
        } if last else None,
        "interpretation": {
            "info_was_actionable": interp.get("info_was_actionable"),
            "info_was_stale_or_absent": interp.get("info_was_stale_or_absent"),
            "could_have_rotated_or_repositioned": interp.get("could_have_rotated_or_repositioned"),
        },
    }


def compact_round_card(card: Any) -> Dict[str, Any]:
    if not isinstance(card, dict):
        return {}

    enemy = card.get("enemy_intent") or {}
    info = card.get("info_state") or {}
    mechanics = card.get("mechanics_deep") or {}
    reasoning = card.get("coach_reasoning") or {}

    top_events = as_list(mechanics.get("top_events_sample"))[:3]
    death_snaps = as_list(info.get("death_snapshots_sample"))[:2]

    return {
        "round_num": card.get("round_num"),
        "round_result": card.get("round_result"),
        "decision_label": card.get("decision_label"),
        "decision_confidence": card.get("decision_confidence"),
        "review_weight": card.get("review_weight"),
        "round_card_label": card.get("round_card_label"),

        "enemy_intent": {
            "likely_enemy_plan": enemy.get("likely_enemy_plan"),
            "plan_family": enemy.get("plan_family"),
            "confidence": enemy.get("confidence"),
            "primary_area": enemy.get("primary_area"),
            "bombsite": enemy.get("bombsite"),
            "plant_phase": enemy.get("plant_phase"),
            "quality_flags": as_list(enemy.get("quality_flags"))[:5],
            "evidence": as_list(enemy.get("evidence"))[:5],
        },

        "info_state": {
            "focus_snapshots_count": info.get("focus_snapshots_count"),
            "death_info_context_counts": info.get("death_info_context_counts"),
            "all_info_context_counts": info.get("all_info_context_counts"),
            "death_snapshots_sample": [compact_death_snapshot(x) for x in death_snaps],
        },

        "mechanics_deep": {
            "events_count": mechanics.get("events_count"),
            "deep_label_counts": mechanics.get("deep_label_counts"),
            "deep_confidence_counts": mechanics.get("deep_confidence_counts"),
            "deep_flag_counts": mechanics.get("deep_flag_counts"),
            "top_events_sample": [compact_event(x) for x in top_events],
        },

        "coach_reasoning": {
            "evidence_reasons": as_list(reasoning.get("evidence_reasons"))[:6],
            "questions_for_model": as_list(reasoning.get("questions_for_model"))[:5],
        },
    }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    ai_dir = root / "data" / "ai" / match_id
    source_path = ai_dir / "ai_coach_judge_input_current.json"

    if not source_path.exists():
        raise FileNotFoundError(f"MISSING source input: {source_path}")

    source = load_json(source_path)

    if source.get("meta", {}).get("version") != "ai_coach_judge_input_v0_1":
        raise ValueError(f"Expected ai_coach_judge_input_v0_1, got {source.get('meta', {}).get('version')}")

    match_context = source.get("match_context") or {}
    decision_summary = (match_context.get("decision_context_summary") or {})

    round_cards = as_list(source.get("round_cards_for_model"))
    compact_cards = [compact_round_card(x) for x in round_cards]

    compact_input = {
        "meta": {
            "version": "ai_coach_judge_input_v0_2_compact",
            "builder": COMPACTOR_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "source_input": rel(source_path, root),
            "purpose": "compact grounded input for first real LLM coach judge call",
        },
        "model_contract": source.get("model_contract"),
        "match_context": {
            "primary_diagnosis": match_context.get("primary_diagnosis"),
            "main_priority": keep_dict(match_context.get("main_priority"), [
                "title", "area", "tier", "score", "confidence", "action"
            ]),
            "coach_priorities": [
                keep_dict(x, ["rank", "title", "area", "tier", "score", "confidence", "action"])
                for x in as_list(match_context.get("coach_priorities"))[:6]
            ],
            "decision_context_summary": {
                "rounds_total": decision_summary.get("rounds_total"),
                "decision_label_counts": decision_summary.get("decision_label_counts"),
                "decision_confidence_counts": decision_summary.get("decision_confidence_counts"),
                "source_versions": decision_summary.get("source_versions"),
                "known_limitations_v0_1": decision_summary.get("known_limitations_v0_1"),
            },
        },
        "round_cards_for_model": compact_cards,
        "final_instruction": source.get("final_instruction"),
        "data_limitations": [
            "enemy_intent is a hypothesis from observable demo events, not actual enemy comms",
            "info_state is reconstructable prior info, not guaranteed voice/team communication",
            "mechanics_deep lacks full raycast/visibility and reliable flash/blind context",
            "yaw error is approximate and must be treated as supporting evidence",
        ],
    }

    out_json = ai_dir / f"ai_coach_judge_input_{player}_v0_2_compact.json"
    out_current = ai_dir / "ai_coach_judge_input_compact_current.json"
    out_txt = ai_dir / f"ai_coach_judge_prompt_preview_{player}_v0_2_compact.txt"

    write_json(out_json, compact_input)
    write_json(out_current, compact_input)

    prompt_preview = "\n\n".join([
        "SYSTEM:",
        json.dumps(compact_input["model_contract"], ensure_ascii=False, indent=2),
        "USER PAYLOAD:",
        json.dumps({
            "match_context": compact_input["match_context"],
            "round_cards_for_model": compact_input["round_cards_for_model"],
            "data_limitations": compact_input["data_limitations"],
            "final_instruction": compact_input["final_instruction"],
        }, ensure_ascii=False, indent=2)
    ])

    write_text(out_txt, prompt_preview)

    old_chars = len(json.dumps(source, ensure_ascii=False))
    new_chars = len(json.dumps(compact_input, ensure_ascii=False))

    result = {
        "status": "ok",
        "builder": COMPACTOR_VERSION,
        "match_id": match_id,
        "player": player,
        "version": "ai_coach_judge_input_v0_2_compact",
        "round_cards_for_model": len(compact_cards),
        "char_budget": {
            "old_json_chars": old_chars,
            "new_json_chars": new_chars,
            "reduction_ratio": round(new_chars / max(old_chars, 1), 4),
            "saved_chars": old_chars - new_chars,
        },
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "prompt_preview": rel(out_txt, root),
        }
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
