from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def text(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    s = str(value).strip()
    return s if s else fallback


def bullet_lines(items: Any, indent: str = "- ") -> list[str]:
    out = []
    for item in as_list(items):
        if isinstance(item, dict):
            out.append(f"{indent}{json.dumps(item, ensure_ascii=False)}")
        else:
            out.append(f"{indent}{text(item)}")
    if not out:
        out.append(f"{indent}—")
    return out


def numbered_priorities(items: Any) -> list[str]:
    out = []
    priorities = as_list(items)
    if not priorities:
        return ["—"]

    for i, item in enumerate(priorities, 1):
        if isinstance(item, dict):
            priority = text(item.get("priority"))
            strength = text(item.get("claim_strength"))
            fix = text(item.get("practical_fix"))
            basis = item.get("evidence_basis", [])

            out.append(f"{i}. **{priority}**")
            out.append(f"   - Уверенность вывода: `{strength}`")
            out.append(f"   - Практическая правка: {fix}")
            out.append("   - Основание:")
            for b in as_list(basis):
                out.append(f"     - {text(b)}")
        else:
            out.append(f"{i}. {text(item)}")
    return out


def render_round_review(r: dict[str, Any]) -> list[str]:
    rn = text(r.get("round_num"))
    result = text(r.get("round_result"))
    strength = text(r.get("claim_strength"))
    takeaway = text(r.get("main_takeaway"))

    lines = []
    lines.append(f"## Раунд {rn} — {result}")
    lines.append("")
    lines.append(f"**Главный вывод:** {takeaway}")
    lines.append("")
    lines.append(f"**Уверенность вывода:** `{strength}`")
    lines.append("")

    lines.append("**Что подтверждается evidence:**")
    lines.extend(bullet_lines(r.get("what_evidence_supports")))
    lines.append("")

    lines.append("**Что evidence НЕ подтверждает / где нужны ограничения:**")
    lines.extend(bullet_lines(r.get("what_evidence_does_not_support")))
    lines.append("")

    mechanics = r.get("mechanics", {}) if isinstance(r.get("mechanics"), dict) else {}
    decision = r.get("decision", {}) if isinstance(r.get("decision"), dict) else {}
    info_state = r.get("info_state", {}) if isinstance(r.get("info_state"), dict) else {}
    enemy_intent = r.get("enemy_intent", {}) if isinstance(r.get("enemy_intent"), dict) else {}

    lines.append("### Механика")
    lines.append("Подтверждено:")
    lines.extend(bullet_lines(mechanics.get("supported")))
    lines.append("Ограничено / спорно:")
    lines.extend(bullet_lines(mechanics.get("limited_or_uncertain")))
    lines.append("")

    lines.append("### Решение")
    lines.append("Подтверждено:")
    lines.extend(bullet_lines(decision.get("supported")))
    lines.append("Ограничено / спорно:")
    lines.extend(bullet_lines(decision.get("limited_or_uncertain")))
    lines.append("")

    lines.append("### Информация")
    lines.append("Подтверждено:")
    lines.extend(bullet_lines(info_state.get("supported")))
    lines.append("Ограничено / спорно:")
    lines.extend(bullet_lines(info_state.get("limited_or_uncertain")))
    lines.append("")

    lines.append("### Гипотеза по плану соперника")
    lines.append(f"- Гипотеза: {text(enemy_intent.get('hypothesis'))}")
    lines.append(f"- Confidence: `{text(enemy_intent.get('confidence'))}`")
    lines.append(f"- Ограничение: {text(enemy_intent.get('caveat'))}")
    lines.append("")

    lines.append("### Тренерская заметка")
    lines.append(text(r.get("training_note")))
    lines.append("")

    return lines


def render_training_plan(plan: dict[str, Any]) -> list[str]:
    lines = []
    lines.append("# План тренировки")
    lines.append("")

    lines.append("## Правила")
    lines.extend(bullet_lines(plan.get("rules") if isinstance(plan, dict) else []))
    lines.append("")

    lines.append("## Упражнения")
    lines.extend(bullet_lines(plan.get("exercises") if isinstance(plan, dict) else []))
    lines.append("")

    lines.append("## Вопросы для review после игры")
    lines.extend(bullet_lines(plan.get("review_questions") if isinstance(plan, dict) else []))
    lines.append("")

    return lines


def render_report(report: dict[str, Any], verdict: dict[str, Any] | None, match_id: str, player: str) -> str:
    lines: list[str] = []

    lines.append(f"# CS Demo Coach Report — {player}")
    lines.append("")
    lines.append(f"- Матч: `{match_id}`")
    lines.append(f"- Версия отчёта: `{text(report.get('schema_version'))}`")

    if verdict:
        lines.append(f"- Production semantic judge: `{text(verdict.get('overall_status'))}`")
        score = verdict.get("score", {})
        if isinstance(score, dict):
            lines.append(
                "- Judge score: "
                f"grounding `{text(score.get('grounding'))}`, "
                f"usefulness `{text(score.get('usefulness'))}`, "
                f"uncertainty `{text(score.get('uncertainty_handling'))}`, "
                f"production `{text(score.get('production_readiness'))}`"
            )

    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("# Краткий вывод")
    lines.append("")
    lines.append(text(report.get("match_summary")))
    lines.append("")

    qc = report.get("quality_control", {}) if isinstance(report.get("quality_control"), dict) else {}

    lines.append("# Контроль качества и ограничения")
    lines.append("")
    lines.append("## Главные ограничения анализа")
    lines.extend(bullet_lines(qc.get("major_limitations")))
    lines.append("")

    lines.append("## Какие неподдержанные утверждения отчёт избегает")
    lines.extend(bullet_lines(qc.get("unsupported_claims_avoided")))
    lines.append("")

    gaps = qc.get("evidence_conflicts_or_gaps")
    if gaps:
        lines.append("## Пробелы / конфликты evidence")
        lines.extend(bullet_lines(gaps))
        lines.append("")

    lines.append("# Главные приоритеты")
    lines.append("")
    lines.extend(numbered_priorities(report.get("top_priorities")))
    lines.append("")

    lines.append("# Разбор раундов")
    lines.append("")

    for r in as_list(report.get("round_reviews")):
        if isinstance(r, dict):
            lines.extend(render_round_review(r))

    plan = report.get("training_plan", {})
    if isinstance(plan, dict):
        lines.extend(render_training_plan(plan))

    lines.append("# Общие uncertainty / ограничения")
    lines.append("")
    lines.extend(bullet_lines(report.get("uncertainties")))
    lines.append("")

    if verdict:
        lines.append("# Вердикт production semantic judge")
        lines.append("")
        lines.append(f"**Статус:** `{text(verdict.get('overall_status'))}`")
        lines.append("")
        lines.append(text(verdict.get("summary")))
        lines.append("")

        final = verdict.get("final_acceptance", {})
        if isinstance(final, dict):
            lines.append("## Приёмка")
            lines.append(f"- Можно использовать для human review: `{text(final.get('can_use_report_for_human_review'))}`")
            lines.append(f"- Можно показывать как final product output: `{text(final.get('can_use_report_as_final_product_output'))}`")
            lines.append(f"- Причина: {text(final.get('reason'))}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--match-id", default="example_match")
    p.add_argument("--player", default="Player")
    p.add_argument("--report-version", default="v0_5")
    args = p.parse_args()

    match_id = args.match_id
    player = args.player
    report_version = args.report_version

    report_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_{report_version}.json")
    verdict_path = Path(f"data/validation/{match_id}/ai_semantic_judgement_verdict_{player}_{report_version}_production_semantic_v0_3.json")

    if not report_path.exists():
        raise FileNotFoundError(f"Missing report: {report_path}")

    report = read_json(report_path)
    verdict = read_json(verdict_path) if verdict_path.exists() else None

    rendered = render_report(report, verdict, match_id, player)

    out_md = Path(f"data/reports/{match_id}/coach_report_{player}_{report_version}_rendered_v0_1.md")
    out_txt = Path(f"data/reports/{match_id}/coach_report_{player}_{report_version}_rendered_v0_1.txt")

    write_text(out_md, rendered)
    write_text(out_txt, rendered)

    print(json.dumps({
        "status": "ok",
        "renderer": "coach_report_renderer_v0_1",
        "created": {
            "markdown": str(out_md),
            "text": str(out_txt)
        },
        "chars": len(rendered),
        "lines": len(rendered.splitlines()),
        "semantic_verdict_attached": verdict is not None
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
