import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ANALYZER_VERSION = "decision_context_v0_1"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Optional[Path]) -> Any:
    if not path or not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def version_key(path: Path) -> Tuple[Tuple[int, ...], float, str]:
    name = path.name
    m = re.search(r"_v(\d+)(?:_(\d+))?", name)
    if m:
        version = tuple(int(x) for x in m.groups() if x is not None)
    else:
        version = (-1,)
    return version, path.stat().st_mtime, name


def latest_file(directory: Path, pattern: str) -> Optional[Path]:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    if not files:
        return None
    return max(files, key=version_key)


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def compact(value: Any, limit_list: int = 24, limit_dict_keys: int = 80) -> Any:
    if isinstance(value, list):
        return [compact(x, limit_list, limit_dict_keys) for x in value[:limit_list]]
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= limit_dict_keys:
                out["_truncated_keys"] = len(value) - limit_dict_keys
                break
            out[k] = compact(v, limit_list, limit_dict_keys)
        return out
    return value


def safe_round(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def pick(d: Any, keys: List[str], default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return default


def group_by_round(items: List[Any]) -> Dict[int, List[Dict[str, Any]]]:
    out: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_round(pick(item, ["round_num", "round", "round_number"]))
        if rn is not None:
            out[rn].append(item)
    return out


def first_by_round(items: List[Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_round(pick(item, ["round_num", "round", "round_number"]))
        if rn is not None and rn not in out:
            out[rn] = item
    return out


def count_values(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    c = Counter()
    for item in items:
        value = item.get(key)
        if isinstance(value, list):
            for x in value:
                c[str(x)] += 1
        elif value not in (None, "", [], {}):
            c[str(value)] += 1
    return dict(c)


def flatten_flags(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    c = Counter()
    for item in items:
        flags = item.get(key)
        if isinstance(flags, list):
            for flag in flags:
                c[str(flag)] += 1
    return dict(c)


def infer_decision_label(
    round_card: Dict[str, Any],
    intent: Dict[str, Any],
    info_snapshots: List[Dict[str, Any]],
    mechanics_events: List[Dict[str, Any]],
) -> Tuple[str, List[str], str]:
    reasons: List[str] = []
    confidence_score = 0

    round_result = pick(round_card, ["result", "round_result"], "")
    likely_plan = intent.get("likely_enemy_plan") if isinstance(intent, dict) else None
    plan_family = intent.get("plan_family") if isinstance(intent, dict) else None
    intent_conf = intent.get("confidence") if isinstance(intent, dict) else None

    if intent:
        confidence_score += 1
        if intent_conf in ("medium", "high"):
            confidence_score += 1
            reasons.append(f"enemy intent available: {likely_plan}/{intent_conf}")

    death_snaps = [
        s for s in info_snapshots
        if s.get("focus_event_kind") == "player_death"
    ]

    stale_or_missing_deaths = [
        s for s in death_snaps
        if s.get("opponent_info_context") in ("stale", "expired", "no_prior_info")
    ]

    actionable_info_deaths = [
        s for s in death_snaps
        if s.get("opponent_info_context") in ("fresh", "recent")
    ]

    if death_snaps:
        confidence_score += 1
        reasons.append(f"death info snapshots={len(death_snaps)}")

    if stale_or_missing_deaths:
        reasons.append(f"death with stale/missing prior info={len(stale_or_missing_deaths)}")

    if actionable_info_deaths:
        reasons.append(f"death with actionable prior info={len(actionable_info_deaths)}")

    mech_flags = []
    mech_labels = []
    for e in mechanics_events:
        mech_labels.append(e.get("deep_label"))
        mech_flags.extend(as_list(e.get("deep_flags")))

    mech_flag_counter = Counter(str(x) for x in mech_flags if x)
    mech_label_counter = Counter(str(x) for x in mech_labels if x)

    if mechanics_events:
        confidence_score += 1
        reasons.append(f"mechanics deep events={len(mechanics_events)}")

    if mech_flag_counter.get("movement_risk_at_contact", 0) >= 1:
        reasons.append("movement risk near mechanics event")

    if mech_flag_counter.get("large_crosshair_offset", 0) >= 1 or mech_flag_counter.get("moderate_crosshair_offset", 0) >= 1:
        reasons.append("crosshair offset evidence exists")

    if mech_flag_counter.get("no_shot_response_near_event", 0) >= 1:
        reasons.append("no-shot response evidence exists")

    if mech_flag_counter.get("visibility_flash_context_missing_or_limited", 0) >= 1:
        reasons.append("visibility/flash context limited")

    # Label priority
    if stale_or_missing_deaths and likely_plan:
        label = "decision_under_stale_or_missing_info"
    elif actionable_info_deaths and plan_family in ("execute", "contact", "default"):
        label = "decision_against_known_or_inferable_pressure"
    elif mech_flag_counter.get("movement_risk_at_contact", 0) >= 2:
        label = "mechanics_movement_decision_overlap"
    elif mech_flag_counter.get("no_shot_response_near_event", 0) >= 1:
        label = "reaction_timing_or_no_response_context"
    elif mech_flag_counter.get("large_crosshair_offset", 0) >= 1 or mech_flag_counter.get("moderate_crosshair_offset", 0) >= 1:
        label = "aim_alignment_context"
    elif plan_family in ("execute", "contact") and round_result == "loss":
        label = "enemy_plan_context_for_lost_round"
    elif likely_plan:
        label = "round_context_available"
    else:
        label = "limited_decision_context"

    if confidence_score >= 4:
        confidence = "high"
    elif confidence_score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return label, reasons, confidence


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    package_dir = root / "data" / "package" / match_id
    analysis_dir = root / "data" / "analysis" / match_id
    layers_dir = root / "data" / "layers" / match_id

    coach_input_path = package_dir / "coach_input_package_current.json"
    info_state_path = layers_dir / "canonical_info_state_current.json"
    enemy_intent_path = analysis_dir / "enemy_intent_current.json"
    mechanics_deep_path = analysis_dir / "mechanics_deep_current.json"

    trade_spacing_path = latest_file(analysis_dir, f"trade_spacing_{player}_v*.json")
    round_impact_path = latest_file(analysis_dir, f"round_impact_{player}_v*.json")
    plant_phase_path = latest_file(analysis_dir, f"postplant_retake_{player}_v*.json")

    warnings: List[str] = []

    coach_input = load_json(coach_input_path)
    info_state = load_json(info_state_path)
    enemy_intent = load_json(enemy_intent_path)
    mechanics_deep = load_json(mechanics_deep_path)
    trade_spacing = load_json(trade_spacing_path)
    round_impact = load_json(round_impact_path)
    plant_phase = load_json(plant_phase_path)

    required = {
        "coach_input_package_current": coach_input,
        "canonical_info_state_current": info_state,
        "enemy_intent_current": enemy_intent,
        "mechanics_deep_current": mechanics_deep,
    }

    for name, obj in required.items():
        if obj is None:
            raise FileNotFoundError(f"MISSING required source: {name}")

    optional = {
        "trade_spacing": trade_spacing,
        "round_impact": round_impact,
        "plant_phase": plant_phase,
    }

    for name, obj in optional.items():
        if obj is None:
            warnings.append(f"optional source missing: {name}")

    round_cards = as_list(pick(coach_input.get("review", {}), ["round_cards"], []))
    top_cases = as_list(pick(coach_input.get("review", {}), ["top_cases"], []))
    focus_snapshots = as_list(info_state.get("focus_snapshots", []))
    round_intents = as_list(enemy_intent.get("round_intents", []))
    deep_events = as_list(mechanics_deep.get("deep_events", []))

    round_cards_by_round = first_by_round(round_cards)
    top_cases_by_round = first_by_round(top_cases)
    info_by_round = group_by_round(focus_snapshots)
    intent_by_round = first_by_round(round_intents)
    mechanics_by_round = group_by_round(deep_events)

    all_rounds = sorted(set(
        list(round_cards_by_round.keys())
        + list(top_cases_by_round.keys())
        + list(info_by_round.keys())
        + list(intent_by_round.keys())
        + list(mechanics_by_round.keys())
    ))

    decision_rounds: List[Dict[str, Any]] = []

    for rn in all_rounds:
        round_card = round_cards_by_round.get(rn, {})
        top_case = top_cases_by_round.get(rn, {})
        info_items = info_by_round.get(rn, [])
        intent = intent_by_round.get(rn, {})
        mech_items = mechanics_by_round.get(rn, [])

        label, reasons, confidence = infer_decision_label(round_card, intent, info_items, mech_items)

        death_info_context_counts = count_values(
            [x for x in info_items if x.get("focus_event_kind") == "player_death"],
            "opponent_info_context"
        )

        all_info_context_counts = count_values(info_items, "opponent_info_context")
        mechanics_label_counts = count_values(mech_items, "deep_label")
        mechanics_confidence_counts = count_values(mech_items, "deep_confidence")
        mechanics_flag_counts = flatten_flags(mech_items, "deep_flags")

        coaching_questions = []

        if death_info_context_counts:
            coaching_questions.append("Была ли у игрока актуальная prior-инфа по противнику перед смертью?")

        if intent:
            coaching_questions.append("Совпадало ли решение игрока с вероятным планом врага в этом раунде?")

        if mechanics_flag_counts.get("movement_risk_at_contact"):
            coaching_questions.append("Игрок стрелял/принимал контакт в движении или без стабилизации?")

        if mechanics_flag_counts.get("no_shot_response_near_event"):
            coaching_questions.append("Почему не было выстрела/ответа рядом с событием: тайминг, граната, reload, позиция?")

        if mechanics_flag_counts.get("large_crosshair_offset") or mechanics_flag_counts.get("moderate_crosshair_offset"):
            coaching_questions.append("Была ли проблема в pre-aim/crosshair placement до контакта?")

        if mechanics_flag_counts.get("visibility_flash_context_missing_or_limited"):
            coaching_questions.append("Нельзя ли объяснить эпизод visibility/flash ограничениями данных? Не делать жёсткий вывод без проверки.")

        review_weight = 0
        if confidence == "high":
            review_weight += 3
        elif confidence == "medium":
            review_weight += 2
        else:
            review_weight += 1

        if pick(round_card, ["result", "round_result"], "") == "loss":
            review_weight += 2

        if label in (
            "decision_under_stale_or_missing_info",
            "decision_against_known_or_inferable_pressure",
            "mechanics_movement_decision_overlap",
            "reaction_timing_or_no_response_context",
        ):
            review_weight += 3

        if mech_items:
            review_weight += 1

        if intent and intent.get("confidence") in ("medium", "high"):
            review_weight += 1

        decision_rounds.append({
            "round_num": rn,
            "decision_label": label,
            "decision_confidence": confidence,
            "review_weight": review_weight,
            "round_result": pick(round_card, ["result", "round_result"], pick(top_case, ["result", "round_result"], "")),
            "round_card_label": pick(round_card, ["label", "case_label"], pick(top_case, ["label", "case_label"], "")),
            "enemy_intent": {
                "likely_enemy_plan": intent.get("likely_enemy_plan"),
                "plan_family": intent.get("plan_family"),
                "confidence": intent.get("confidence"),
                "primary_area": intent.get("primary_area"),
                "bombsite": intent.get("bombsite"),
                "plant_phase": intent.get("plant_phase"),
                "quality_flags": intent.get("reasoning_quality_flags", []),
                "evidence": intent.get("evidence", []),
            } if intent else None,
            "info_state": {
                "focus_snapshots_count": len(info_items),
                "death_info_context_counts": death_info_context_counts,
                "all_info_context_counts": all_info_context_counts,
                "death_snapshots_sample": compact(
                    [x for x in info_items if x.get("focus_event_kind") == "player_death"],
                    limit_list=4,
                    limit_dict_keys=60,
                ),
            },
            "mechanics_deep": {
                "events_count": len(mech_items),
                "deep_label_counts": mechanics_label_counts,
                "deep_confidence_counts": mechanics_confidence_counts,
                "deep_flag_counts": mechanics_flag_counts,
                "top_events_sample": compact(mech_items, limit_list=5, limit_dict_keys=70),
            },
            "coach_reasoning": {
                "reasons": reasons,
                "coaching_questions": coaching_questions,
                "model_instruction": (
                    "Use this as a grounded decision context. Explain only what evidence supports. "
                    "Do not invent comms, exact visibility, or enemy intentions beyond confidence/evidence."
                ),
            },
            "source_round_card": compact(round_card, limit_list=10, limit_dict_keys=70),
        })

    decision_label_counts = Counter(x["decision_label"] for x in decision_rounds)
    decision_confidence_counts = Counter(x["decision_confidence"] for x in decision_rounds)

    top_review_rounds = sorted(
        decision_rounds,
        key=lambda x: (x["review_weight"], 1 if x["round_result"] == "loss" else 0),
        reverse=True
    )[:12]

    summary = {
        "version": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "rounds_total": len(decision_rounds),
        "decision_label_counts": dict(decision_label_counts),
        "decision_confidence_counts": dict(decision_confidence_counts),
        "top_review_rounds": [
            {
                "round_num": x["round_num"],
                "decision_label": x["decision_label"],
                "decision_confidence": x["decision_confidence"],
                "review_weight": x["review_weight"],
                "round_result": x["round_result"],
                "enemy_plan": (x.get("enemy_intent") or {}).get("likely_enemy_plan"),
                "death_info_context_counts": x.get("info_state", {}).get("death_info_context_counts"),
                "mechanics_label_counts": x.get("mechanics_deep", {}).get("deep_label_counts"),
                "reasons": x.get("coach_reasoning", {}).get("reasons"),
            }
            for x in top_review_rounds
        ],
        "source_versions": {
            "coach_input_package": pick(coach_input.get("meta", {}), ["version"]),
            "info_state": pick(info_state.get("summary", {}), ["version"]),
            "enemy_intent": pick(enemy_intent.get("summary", {}), ["version"]),
            "mechanics_deep": pick(mechanics_deep.get("summary", {}), ["version"]),
        },
        "warnings": warnings,
        "known_limitations_v0_1": [
            "This layer connects existing evidence; it does not add new visibility/raycast data.",
            "Enemy intent remains hypothesis-based.",
            "Info state estimates reconstructable prior info, not actual voice comms.",
            "Mechanics deep uses approximate yaw/position context and limited flash/visibility context.",
        ],
    }

    package = {
        "meta": {
            "version": ANALYZER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "purpose": "round-level decision context bridge for future AI coach judge",
        },
        "summary": summary,
        "decision_rounds": decision_rounds,
        "source_files": {
            "coach_input_package": rel(coach_input_path, root),
            "info_state": rel(info_state_path, root),
            "enemy_intent": rel(enemy_intent_path, root),
            "mechanics_deep": rel(mechanics_deep_path, root),
            "trade_spacing": rel(trade_spacing_path, root),
            "round_impact": rel(round_impact_path, root),
            "plant_phase": rel(plant_phase_path, root),
        },
    }

    out_json = analysis_dir / f"decision_context_{player}_v0_1.json"
    out_current = analysis_dir / "decision_context_current.json"
    out_csv = analysis_dir / f"decision_context_{player}_v0_1.csv"

    write_json(out_json, package)
    write_json(out_current, package)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "round_num",
            "decision_label",
            "decision_confidence",
            "review_weight",
            "round_result",
            "round_card_label",
            "enemy_plan",
            "enemy_plan_family",
            "enemy_plan_confidence",
            "death_info_context_counts",
            "all_info_context_counts",
            "mechanics_label_counts",
            "mechanics_confidence_counts",
            "mechanics_flag_counts",
            "reasons",
            "coaching_questions",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for x in decision_rounds:
            intent = x.get("enemy_intent") or {}
            info = x.get("info_state") or {}
            mech = x.get("mechanics_deep") or {}
            reasoning = x.get("coach_reasoning") or {}

            writer.writerow({
                "round_num": x.get("round_num"),
                "decision_label": x.get("decision_label"),
                "decision_confidence": x.get("decision_confidence"),
                "review_weight": x.get("review_weight"),
                "round_result": x.get("round_result"),
                "round_card_label": x.get("round_card_label"),
                "enemy_plan": intent.get("likely_enemy_plan"),
                "enemy_plan_family": intent.get("plan_family"),
                "enemy_plan_confidence": intent.get("confidence"),
                "death_info_context_counts": json.dumps(info.get("death_info_context_counts", {}), ensure_ascii=False),
                "all_info_context_counts": json.dumps(info.get("all_info_context_counts", {}), ensure_ascii=False),
                "mechanics_label_counts": json.dumps(mech.get("deep_label_counts", {}), ensure_ascii=False),
                "mechanics_confidence_counts": json.dumps(mech.get("deep_confidence_counts", {}), ensure_ascii=False),
                "mechanics_flag_counts": json.dumps(mech.get("deep_flag_counts", {}), ensure_ascii=False),
                "reasons": " | ".join(reasoning.get("reasons", [])),
                "coaching_questions": " | ".join(reasoning.get("coaching_questions", [])),
            })

    return {
        "status": "ok",
        "analyzer": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "summary": summary,
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "csv": rel(out_csv, root),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
