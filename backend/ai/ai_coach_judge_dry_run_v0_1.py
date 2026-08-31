import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


RUNNER_VERSION = "ai_coach_judge_dry_run_v0_1"


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


def pick(d: Any, keys: List[str], default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for key in keys:
        if key in d and d[key] not in (None, "", [], {}):
            return d[key]
    return default


def flatten_dict_counts(value: Any) -> Dict[str, int]:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                pass
        return out
    return {}


def summarize_round(card: Dict[str, Any]) -> Dict[str, Any]:
    rn = card.get("round_num")
    decision_label = card.get("decision_label")
    decision_confidence = card.get("decision_confidence")
    result = card.get("round_result")

    enemy = card.get("enemy_intent") or {}
    info = card.get("info_state") or {}
    mechanics = card.get("mechanics_deep") or {}
    reasoning = card.get("coach_reasoning") or {}

    enemy_plan = enemy.get("likely_enemy_plan")
    enemy_conf = enemy.get("confidence")
    enemy_area = enemy.get("primary_area")
    bombsite = enemy.get("bombsite")
    plant_phase = enemy.get("plant_phase")

    death_counts = flatten_dict_counts(info.get("death_info_context_counts"))
    mech_labels = flatten_dict_counts(mechanics.get("deep_label_counts"))
    mech_flags = flatten_dict_counts(mechanics.get("deep_flag_counts"))

    main_causes = []

    if death_counts:
        if any(k in death_counts for k in ["stale", "expired", "no_prior_info"]):
            main_causes.append("инфа по противнику была устаревшей или отсутствовала перед смертью")
        if any(k in death_counts for k in ["fresh", "recent"]):
            main_causes.append("перед частью смертей была свежая или недавняя prior-инфа")

    if enemy_plan:
        main_causes.append(f"вероятный план врага: {enemy_plan}")

    if mech_flags.get("movement_risk_at_contact", 0) > 0:
        main_causes.append("есть риск принятия контакта в движении")

    if mech_flags.get("no_shot_response_near_event", 0) > 0:
        main_causes.append("есть эпизод без выстрела/ответа рядом с событием")

    if mech_flags.get("large_crosshair_offset", 0) > 0 or mech_flags.get("moderate_crosshair_offset", 0) > 0:
        main_causes.append("есть evidence по смещению прицела относительно цели")

    if not main_causes:
        main_causes.append("контекст есть, но сильная причина не выделена")

    recommended_focus = []

    if "decision_under_stale_or_missing_info" == decision_label:
        recommended_focus.append("не играть так, будто старая инфа всё ещё актуальна")
        recommended_focus.append("перед повторным контактом обновлять инфу или играть безопаснее")

    if "decision_against_known_or_inferable_pressure" == decision_label:
        recommended_focus.append("учиться распознавать давление врага и не принимать одиночный fight против вероятного execute/contact")
        recommended_focus.append("сверять свою позицию с планом команды и возможностью размена")

    if mech_flags.get("movement_risk_at_contact", 0) > 0:
        recommended_focus.append("стабилизироваться перед первым выстрелом: counter-strafe / stop-shoot")

    if mech_flags.get("no_shot_response_near_event", 0) > 0:
        recommended_focus.append("разобрать тайминг реакции: почему не было выстрела — граната, reload, позиция или поздняя готовность")

    if mech_flags.get("large_crosshair_offset", 0) > 0 or mech_flags.get("moderate_crosshair_offset", 0) > 0:
        recommended_focus.append("проверить pre-aim и crosshair placement в этом типе позиции")

    if not recommended_focus:
        recommended_focus.append("использовать раунд как контекстный review, не как отдельный механический verdict")

    uncertainty = [
        "нет полноценного raycast/visibility check",
        "flash/blind context ограничен",
        "enemy_intent — гипотеза по событиям, а не реальные мысли/коллы врага"
    ]

    return {
        "round_num": rn,
        "result": result,
        "decision_label": decision_label,
        "decision_confidence": decision_confidence,
        "enemy_plan": enemy_plan,
        "enemy_confidence": enemy_conf,
        "enemy_area": enemy_area,
        "bombsite": bombsite,
        "plant_phase": plant_phase,
        "main_causes": main_causes[:5],
        "recommended_focus": recommended_focus[:5],
        "evidence_reasons": as_list(reasoning.get("evidence_reasons"))[:8],
        "model_questions": as_list(reasoning.get("questions_for_model"))[:8],
        "uncertainty": uncertainty,
    }


def build_text_report(report: Dict[str, Any]) -> str:
    lines = []

    lines.append("AI COACH JUDGE DRY-RUN v0.1")
    lines.append("")
    lines.append(f"Матч: {report['meta']['match_id']}")
    lines.append(f"Игрок: {report['meta']['player']}")
    lines.append("")
    lines.append("Важно: это dry-run без внешней ИИ-модели. Он проверяет структуру будущего coach report и опирается только на evidence.")
    lines.append("")

    lines.append("1. Короткий диагноз")
    lines.append(report["coach_review"]["match_summary"])
    lines.append("")

    lines.append("2. Главные приоритеты")
    for i, item in enumerate(report["coach_review"]["top_priorities"], start=1):
        lines.append(f"{i}) {item}")
    lines.append("")

    lines.append("3. Раунды для review")
    for r in report["coach_review"]["round_reviews"]:
        lines.append(f"Раунд {r['round_num']} — {r['decision_label']} / confidence={r['decision_confidence']}")
        lines.append(f"- План врага: {r.get('enemy_plan')} ({r.get('enemy_confidence')})")
        lines.append(f"- Главные причины: {'; '.join(r.get('main_causes', []))}")
        lines.append(f"- Фокус: {'; '.join(r.get('recommended_focus', []))}")
        lines.append("")

    lines.append("4. Mechanics review")
    for item in report["coach_review"]["mechanics_review"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("5. Macro / decision review")
    for item in report["coach_review"]["macro_review"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("6. План тренировки")
    for item in report["coach_review"]["training_plan"]:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("7. Ограничения данных")
    for item in report["coach_review"]["uncertainties"]:
        lines.append(f"- {item}")

    return "\n".join(lines)


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    ai_dir = root / "data" / "ai" / match_id
    input_path = ai_dir / "ai_coach_judge_input_current.json"

    if not input_path.exists():
        raise FileNotFoundError(f"MISSING ai_coach_judge_input_current: {input_path}")

    ai_input = load_json(input_path)

    if ai_input.get("meta", {}).get("version") != "ai_coach_judge_input_v0_1":
        raise ValueError(f"Expected ai_coach_judge_input_v0_1, got {ai_input.get('meta', {}).get('version')}")

    match_context = ai_input.get("match_context", {})
    round_cards = as_list(ai_input.get("round_cards_for_model", []))

    round_reviews = [summarize_round(card) for card in round_cards]

    decision_labels = Counter(r.get("decision_label") for r in round_reviews if r.get("decision_label"))
    enemy_plans = Counter(r.get("enemy_plan") for r in round_reviews if r.get("enemy_plan"))

    priorities = []
    main_priority = pick(match_context.get("main_priority", {}), ["title"])
    if main_priority:
        priorities.append(main_priority)

    for label, count in decision_labels.most_common(4):
        priorities.append(f"{label}: {count} раунд(ов) среди выбранных review-карточек")

    if not priorities:
        priorities.append("нет устойчивого приоритета без внешней модели")

    mechanics_review = []

    movement_count = 0
    no_response_count = 0
    offset_count = 0

    for card in round_cards:
        mech = (card.get("mechanics_deep") or {}).get("deep_flag_counts") or {}
        movement_count += int(mech.get("movement_risk_at_contact", 0) or 0)
        no_response_count += int(mech.get("no_shot_response_near_event", 0) or 0)
        offset_count += int(mech.get("large_crosshair_offset", 0) or 0)
        offset_count += int(mech.get("moderate_crosshair_offset", 0) or 0)

    if movement_count:
        mechanics_review.append(f"Movement/counter-strafe контекст повторяется: {movement_count} flag(s) movement_risk_at_contact.")
    if no_response_count:
        mechanics_review.append(f"Есть no-response эпизоды: {no_response_count} flag(s), нужно отдельно смотреть гранату/reload/timing.")
    if offset_count:
        mechanics_review.append(f"Есть crosshair offset evidence: {offset_count} flag(s), но без raycast это не абсолютный verdict.")
    if not mechanics_review:
        mechanics_review.append("Механика в выбранных карточках не дала сильного повторяющегося флага.")

    macro_review = []
    if enemy_plans:
        plan_text = ", ".join([f"{k}: {v}" for k, v in enemy_plans.most_common(5)])
        macro_review.append(f"Вероятные планы врага в review-раундах: {plan_text}.")
    if decision_labels:
        label_text = ", ".join([f"{k}: {v}" for k, v in decision_labels.most_common(5)])
        macro_review.append(f"Decision labels в review-раундах: {label_text}.")
    macro_review.append("Главное правило для интерпретации: enemy_intent — гипотеза, info_state — reconstructable prior info, не реальные comms.")

    training_plan = [
        "Перед каждым агрессивным контактом проговаривать: кто меня трейдит и куда я ухожу после kill.",
        "После kill не оставаться на той же линии без причины: reposition / cover / teammate trade.",
        "Отдельно потренировать stop-shoot: короткие серии с контролем скорости перед первым выстрелом.",
        "Разобрать review-раунды из ai_coach_judge_input_current: смотреть не только kill/death, а 5–10 секунд до события.",
        "В следующих матчах отслеживать смерти по stale/expired/no_prior_info: не играть по старой инфе как по свежей."
    ]

    uncertainties = [
        "Dry-run не заменяет настоящую LLM-модель; это структурный черновик.",
        "Нет полноценного raycast/visibility check.",
        "Flash/blind context отсутствует или ограничен.",
        "Enemy intent — вероятностная классификация по событиям, а не реальные планы/коллы врага.",
        "Yaw error и mechanics_deep — supporting evidence, не абсолютная истина."
    ]

    primary_diag = match_context.get("primary_diagnosis", {})
    short_diag = pick(primary_diag, ["short_diagnosis", "primary_why", "primary_title"], "")

    if short_diag:
        match_summary = f"Главный вывод: {short_diag}"
    else:
        match_summary = "Главный вывод: основной review должен идти через связку decision context + mechanics context."

    report = {
        "meta": {
            "version": RUNNER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "source_input": rel(input_path, root),
            "type": "dry_run_no_external_llm",
        },
        "coach_review": {
            "match_summary": match_summary,
            "top_priorities": priorities[:6],
            "round_reviews": round_reviews,
            "mechanics_review": mechanics_review,
            "macro_review": macro_review,
            "training_plan": training_plan,
            "uncertainties": uncertainties,
        },
        "debug_summary": {
            "round_cards_used": len(round_cards),
            "decision_label_counts": dict(decision_labels),
            "enemy_plan_counts": dict(enemy_plans),
            "mechanics_flags_total": {
                "movement_risk_at_contact": movement_count,
                "no_shot_response_near_event": no_response_count,
                "crosshair_offset": offset_count,
            },
        },
    }

    out_json = ai_dir / f"ai_coach_judge_dry_run_{player}_v0_1.json"
    out_current = ai_dir / "ai_coach_judge_dry_run_current.json"
    out_txt = ai_dir / f"ai_coach_judge_dry_run_{player}_v0_1.txt"
    out_index = ai_dir / f"ai_coach_judge_dry_run_index_{player}_v0_1.csv"

    write_json(out_json, report)
    write_json(out_current, report)
    write_text(out_txt, build_text_report(report))

    with out_index.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["key", "value"])
        writer.writeheader()
        writer.writerow({"key": "status", "value": "ok"})
        writer.writerow({"key": "match_id", "value": match_id})
        writer.writerow({"key": "player", "value": player})
        writer.writerow({"key": "version", "value": RUNNER_VERSION})
        writer.writerow({"key": "round_cards_used", "value": str(len(round_cards))})
        writer.writerow({"key": "json", "value": rel(out_json, root)})
        writer.writerow({"key": "current", "value": rel(out_current, root)})
        writer.writerow({"key": "txt", "value": rel(out_txt, root)})

    return {
        "status": "ok",
        "runner": RUNNER_VERSION,
        "match_id": match_id,
        "player": player,
        "round_cards_used": len(round_cards),
        "debug_summary": report["debug_summary"],
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "txt": rel(out_txt, root),
            "index": rel(out_index, root),
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
