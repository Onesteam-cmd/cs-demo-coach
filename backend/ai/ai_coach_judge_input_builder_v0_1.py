import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


BUILDER_VERSION = "ai_coach_judge_input_builder_v0_1"


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def compact(value: Any, limit_list: int = 12, limit_dict_keys: int = 60) -> Any:
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


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def safe_round(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def pick(d: Any, keys: List[str], default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] not in (None, "", [], {}):
            return d[key]
    return default


def group_by_round(items: List[Any]) -> Dict[int, List[Dict[str, Any]]]:
    out: Dict[int, List[Dict[str, Any]]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_round(pick(item, ["round_num", "round", "round_number"]))
        if rn is None:
            continue
        out.setdefault(rn, []).append(item)
    return out


def one_by_round(items: List[Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_round(pick(item, ["round_num", "round", "round_number"]))
        if rn is None:
            continue
        if rn not in out:
            out[rn] = item
    return out


def make_round_prompt_card(decision_round: Dict[str, Any], round_card: Dict[str, Any]) -> Dict[str, Any]:
    rn = decision_round.get("round_num")

    enemy_intent = decision_round.get("enemy_intent") or {}
    info_state = decision_round.get("info_state") or {}
    mechanics = decision_round.get("mechanics_deep") or {}
    reasoning = decision_round.get("coach_reasoning") or {}

    return {
        "round_num": rn,
        "round_result": decision_round.get("round_result"),
        "decision_label": decision_round.get("decision_label"),
        "decision_confidence": decision_round.get("decision_confidence"),
        "review_weight": decision_round.get("review_weight"),
        "round_card_label": decision_round.get("round_card_label"),
        "enemy_intent": {
            "likely_enemy_plan": enemy_intent.get("likely_enemy_plan"),
            "plan_family": enemy_intent.get("plan_family"),
            "confidence": enemy_intent.get("confidence"),
            "primary_area": enemy_intent.get("primary_area"),
            "bombsite": enemy_intent.get("bombsite"),
            "plant_phase": enemy_intent.get("plant_phase"),
            "quality_flags": enemy_intent.get("quality_flags", []),
            "evidence": enemy_intent.get("evidence", []),
        },
        "info_state": {
            "focus_snapshots_count": info_state.get("focus_snapshots_count"),
            "death_info_context_counts": info_state.get("death_info_context_counts"),
            "all_info_context_counts": info_state.get("all_info_context_counts"),
            "death_snapshots_sample": compact(info_state.get("death_snapshots_sample", []), limit_list=3, limit_dict_keys=40),
        },
        "mechanics_deep": {
            "events_count": mechanics.get("events_count"),
            "deep_label_counts": mechanics.get("deep_label_counts"),
            "deep_confidence_counts": mechanics.get("deep_confidence_counts"),
            "deep_flag_counts": mechanics.get("deep_flag_counts"),
            "top_events_sample": compact(mechanics.get("top_events_sample", []), limit_list=4, limit_dict_keys=45),
        },
        "coach_reasoning": {
            "evidence_reasons": reasoning.get("reasons", []),
            "questions_for_model": reasoning.get("coaching_questions", []),
        },
        "round_card_evidence": compact(round_card, limit_list=8, limit_dict_keys=50),
        "required_model_behavior_for_this_round": [
            "объяснить только то, что подтверждено evidence",
            "отделить macro/decision от mechanics",
            "не утверждать точную видимость, если visibility/raycast отсутствует",
            "не утверждать реальные коллы команды или мысли врагов",
            "если evidence противоречивый или слабый — явно сказать об этом",
        ],
    }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    package_dir = root / "data" / "package" / match_id
    analysis_dir = root / "data" / "analysis" / match_id
    ai_dir = root / "data" / "ai" / match_id

    coach_input_path = package_dir / "coach_input_package_current.json"
    decision_context_path = analysis_dir / "decision_context_current.json"

    coach_input = load_json(coach_input_path)
    decision_context = load_json(decision_context_path)

    if coach_input is None:
        raise FileNotFoundError(f"MISSING coach_input_package_current: {coach_input_path}")

    if decision_context is None:
        raise FileNotFoundError(f"MISSING decision_context_current: {decision_context_path}")

    if pick(coach_input.get("meta", {}), ["version"]) != "v0_6":
        raise ValueError(f"coach_input_package_current must be v0_6 before AI judge input; got {pick(coach_input.get('meta', {}), ['version'])}")

    if pick(decision_context.get("summary", {}), ["version"]) != "decision_context_v0_1":
        raise ValueError("decision_context_current must be decision_context_v0_1")

    overview = coach_input.get("overview", {})
    priorities = as_list(coach_input.get("coach_priorities", []))
    review = coach_input.get("review", {})
    round_cards = as_list(review.get("round_cards", []))
    round_cards_by_round = one_by_round(round_cards)

    decision_rounds = as_list(decision_context.get("decision_rounds", []))
    top_rounds_raw = as_list(pick(decision_context.get("summary", {}), ["top_review_rounds"], []))

    top_round_nums = []
    for item in top_rounds_raw:
        rn = safe_round(pick(item, ["round_num"]))
        if rn is not None and rn not in top_round_nums:
            top_round_nums.append(rn)

    if not top_round_nums:
        sorted_rounds = sorted(
            [x for x in decision_rounds if isinstance(x, dict)],
            key=lambda x: x.get("review_weight") or 0,
            reverse=True
        )
        top_round_nums = [safe_round(x.get("round_num")) for x in sorted_rounds[:12]]
        top_round_nums = [x for x in top_round_nums if x is not None]

    decision_by_round = one_by_round(decision_rounds)

    prompt_round_cards = []
    for rn in top_round_nums[:12]:
        decision_round = decision_by_round.get(rn)
        if not decision_round:
            continue
        prompt_round_cards.append(
            make_round_prompt_card(decision_round, round_cards_by_round.get(rn, {}))
        )

    model_contract = {
        "language": "ru",
        "role": "Ты строгий Counter-Strike тренер-аналитик. Ты объясняешь решения, механику, инфу, тайминги и macro без фантазий.",
        "must_do": [
            "использовать только evidence из карточек",
            "отделять факты от гипотез",
            "отдельно оценивать mechanics, decision, info_state, enemy_intent и round impact",
            "явно писать, когда confidence medium/low",
            "давать практичные советы игроку Player",
            "выделять 3–5 главных паттернов, а не перечислять всё подряд"
        ],
        "must_not_do": [
            "не выдумывать voice comms, реальные мысли врагов или точную видимость",
            "не говорить, что игрок точно видел врага, если нет visibility/raycast",
            "не считать enemy_intent абсолютной истиной",
            "не обвинять aim, если evidence указывает на timing/info/position",
            "не делать вывод только по одному числу без контекста"
        ],
        "output_schema": {
            "match_summary": "короткий диагноз матча",
            "top_priorities": "3–5 главных приоритетов",
            "round_reviews": "разбор выбранных раундов",
            "mechanics_review": "aim/reaction/movement выводы",
            "macro_review": "spacing/info/intent/decision выводы",
            "training_plan": "практические упражнения и правила на следующую игру",
            "uncertainties": "что нельзя утверждать из-за ограничений данных"
        }
    }

    ai_input = {
        "meta": {
            "version": "ai_coach_judge_input_v0_1",
            "builder": BUILDER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "source_contract": "coach_input_package_current_v0_6",
            "purpose": "compact grounded input for future AI coach judge",
        },
        "source_files": {
            "coach_input_package_current": rel(coach_input_path, root),
            "decision_context_current": rel(decision_context_path, root),
        },
        "model_contract": model_contract,
        "match_context": {
            "primary_diagnosis": compact(overview.get("primary_diagnosis"), limit_list=8, limit_dict_keys=40),
            "main_priority": compact(overview.get("main_priority"), limit_list=8, limit_dict_keys=40),
            "review_rounds": overview.get("review_rounds"),
            "coach_priorities": compact(priorities, limit_list=8, limit_dict_keys=45),
            "decision_context_summary": compact(decision_context.get("summary"), limit_list=12, limit_dict_keys=50),
        },
        "round_cards_for_model": prompt_round_cards,
        "final_instruction": (
            "Сформируй тренерский разбор матча для игрока Player на русском языке. "
            "Опирайся только на evidence. Если данные неполные — прямо укажи ограничение. "
            "Главная цель: практические выводы, которые игрок сможет применить в следующей игре."
        )
    }

    out_json = ai_dir / f"ai_coach_judge_input_{player}_v0_1.json"
    out_current = ai_dir / "ai_coach_judge_input_current.json"
    out_jsonl = ai_dir / f"ai_coach_judge_round_cards_{player}_v0_1.jsonl"
    out_txt = ai_dir / f"ai_coach_judge_prompt_preview_{player}_v0_1.txt"

    write_json(out_json, ai_input)
    write_json(out_current, ai_input)

    with out_jsonl.open("w", encoding="utf-8", newline="\n") as f:
        for card in prompt_round_cards:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    prompt_preview = []
    prompt_preview.append("SYSTEM / ROLE:")
    prompt_preview.append(model_contract["role"])
    prompt_preview.append("")
    prompt_preview.append("MUST DO:")
    for item in model_contract["must_do"]:
        prompt_preview.append(f"- {item}")
    prompt_preview.append("")
    prompt_preview.append("MUST NOT DO:")
    for item in model_contract["must_not_do"]:
        prompt_preview.append(f"- {item}")
    prompt_preview.append("")
    prompt_preview.append("MATCH CONTEXT:")
    prompt_preview.append(json.dumps(ai_input["match_context"], ensure_ascii=False, indent=2))
    prompt_preview.append("")
    prompt_preview.append("ROUND CARDS:")
    prompt_preview.append(json.dumps(prompt_round_cards, ensure_ascii=False, indent=2))
    prompt_preview.append("")
    prompt_preview.append("FINAL INSTRUCTION:")
    prompt_preview.append(ai_input["final_instruction"])

    write_text(out_txt, "\n".join(prompt_preview))

    index_path = ai_dir / f"ai_coach_judge_input_index_{player}_v0_1.csv"
    with index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "version", "value": "ai_coach_judge_input_v0_1"})
        writer.writerow({"key": "round_cards_for_model", "value": str(len(prompt_round_cards))})
        writer.writerow({"key": "json", "value": rel(out_json, root)})
        writer.writerow({"key": "current", "value": rel(out_current, root)})
        writer.writerow({"key": "jsonl", "value": rel(out_jsonl, root)})
        writer.writerow({"key": "prompt_preview", "value": rel(out_txt, root)})

    return {
        "status": "ok",
        "builder": BUILDER_VERSION,
        "match_id": match_id,
        "player": player,
        "version": "ai_coach_judge_input_v0_1",
        "round_cards_for_model": len(prompt_round_cards),
        "top_rounds": [x.get("round_num") for x in prompt_round_cards],
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "jsonl": rel(out_jsonl, root),
            "prompt_preview": rel(out_txt, root),
            "index": rel(index_path, root),
        }
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
