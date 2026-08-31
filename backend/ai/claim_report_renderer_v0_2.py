from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def render_list(items: Any, indent: str = "- ") -> List[str]:
    lines: List[str] = []

    for item in as_list(items):
        if isinstance(item, str):
            lines.append(f"{indent}{item}")
        elif isinstance(item, dict):
            compact = []
            for key, value in item.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    compact.append(f"{key}: {value}")
                elif isinstance(value, list):
                    compact.append(f"{key}: {', '.join(str(x) for x in value)}")
            lines.append(f"{indent}{'; '.join(compact)}")
        else:
            lines.append(f"{indent}{item}")

    if not lines:
        lines.append(f"{indent}—")

    return lines


def render_priority(priority: Any, idx: int) -> List[str]:
    lines: List[str] = []

    if not isinstance(priority, dict):
        return [f"{idx}. {priority}"]

    title = priority.get("title") or priority.get("priority") or f"Приоритет {idx}"
    lines.append(f"{idx}. **{title}**")

    if priority.get("why_it_matters"):
        lines.append(f"   - Почему важно: {priority.get('why_it_matters')}")

    if priority.get("supporting_rounds"):
        lines.append(f"   - Раунды: {', '.join(str(x) for x in priority.get('supporting_rounds', []))}")

    if priority.get("claims_refs"):
        lines.append(f"   - Claims: {', '.join(str(x) for x in priority.get('claims_refs', []))}")

    if priority.get("training_focus"):
        lines.append(f"   - Фокус тренировки: {priority.get('training_focus')}")

    return lines


def render_claim(claim: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    claim_id = claim.get("claim_id", "claim")
    claim_type = claim.get("claim_type", "unknown")
    strength = claim.get("claim_strength", "unknown")
    show = claim.get("should_show_to_user", True)

    lines.append(f"#### Claim `{claim_id}`")
    lines.append("")
    lines.append(f"- Тип: `{claim_type}`")
    lines.append(f"- Сила: `{strength}`")
    lines.append(f"- Показывать пользователю: `{show}`")
    lines.append("")
    lines.append(f"**Вывод:** {claim.get('claim_text', '—')}")
    lines.append("")

    lines.append("**Evidence:**")
    lines.extend(render_list(claim.get("evidence_summary")))
    lines.append("")

    refs = claim.get("evidence_refs")
    if refs:
        lines.append("**Evidence refs:**")
        lines.extend(render_list(refs))
        lines.append("")

    lines.append("**Ограничения:**")
    lines.extend(render_list(claim.get("limitations")))
    lines.append("")

    lines.append("**Альтернативные объяснения:**")
    lines.extend(render_list(claim.get("alternative_explanations")))
    lines.append("")

    lines.append(f"**Практическое действие:** {claim.get('actionability', '—')}")
    lines.append("")

    return lines


def render_training_plan(training_plan: Any) -> List[str]:
    lines: List[str] = []

    if not isinstance(training_plan, dict):
        return render_list(training_plan)

    for key, value in training_plan.items():
        title = str(key).replace("_", " ").strip().capitalize()
        lines.append(f"### {title}")

        if isinstance(value, list):
            lines.extend(render_list(value))
        elif isinstance(value, dict):
            for k, v in value.items():
                lines.append(f"- **{k}:** {v}")
        else:
            lines.append(f"- {value}")

        lines.append("")

    return lines


def render_uncertainties(uncertainties: Any) -> List[str]:
    lines: List[str] = []

    for idx, item in enumerate(as_list(uncertainties), start=1):
        if isinstance(item, dict):
            topic = item.get("topic", f"Неопределённость {idx}")
            why = item.get("why_uncertain", "")
            missing = item.get("what_evidence_is_missing", "")
            lines.append(f"{idx}. **{topic}**")
            if why:
                lines.append(f"   - Почему неопределённо: {why}")
            if missing:
                lines.append(f"   - Чего не хватает: {missing}")
        else:
            lines.append(f"{idx}. {item}")

    if not lines:
        lines.append("—")

    return lines


def render_markdown(
    report: Dict[str, Any],
    match_id: str,
    player: str,
    source_report_path: Path,
    repair_result: Optional[Dict[str, Any]],
    final_verdict: Optional[Dict[str, Any]],
) -> str:
    lines: List[str] = []

    lines.append(f"# CS Demo Coach Report — {player}")
    lines.append("")
    lines.append(f"- Матч: `{match_id}`")
    lines.append(f"- Игрок: `{player}`")
    lines.append(f"- Schema: `{report.get('schema_version', 'unknown')}`")
    lines.append(f"- Язык: `{report.get('language', 'unknown')}`")
    lines.append(f"- Source: `{source_report_path.relative_to(PROJECT_ROOT)}`")
    lines.append(f"- Rendered at: `{datetime.now().isoformat(timespec='seconds')}`")
    lines.append("")

    if final_verdict:
        final_rec = final_verdict.get("final_recommendation", {})
        lines.append("## QA verdict")
        lines.append("")
        lines.append(f"- Semantic verifier: `{final_verdict.get('overall_status', 'unknown')}`")
        lines.append(f"- Можно показывать без repair: `{final_verdict.get('can_show_to_user_without_repair', 'unknown')}`")
        lines.append(f"- Осталось findings: `{len(final_verdict.get('remaining_findings', []) or [])}`")
        lines.append(f"- Использовать repaired report: `{final_rec.get('use_repaired_report', 'unknown')}`")
        lines.append(f"- Нужен ещё repair: `{final_rec.get('needs_more_repair', 'unknown')}`")
        if final_rec.get("notes"):
            lines.append(f"- Notes: {final_rec.get('notes')}")
        lines.append("")

    if repair_result:
        lines.append("## Repair summary")
        lines.append("")
        lines.append(f"- Repair status: `{repair_result.get('status', 'unknown')}`")
        lines.append(f"- Patches total: `{repair_result.get('patches_total', 0)}`")
        lines.append(f"- Applied: `{repair_result.get('applied_count', 0)}`")
        lines.append(f"- Skipped: `{repair_result.get('skipped_count', 0)}`")
        lines.append("")

    lines.append("## Краткий вывод по матчу")
    lines.append("")
    lines.append(str(report.get("match_summary", "—")))
    lines.append("")

    lines.append("## Главные приоритеты")
    lines.append("")

    priorities = as_list(report.get("top_priorities"))
    if priorities:
        for idx, priority in enumerate(priorities, start=1):
            lines.extend(render_priority(priority, idx))
            lines.append("")
    else:
        lines.append("—")
        lines.append("")

    lines.append("## Разбор раундов")
    lines.append("")

    round_reviews = report.get("round_reviews", [])
    if not isinstance(round_reviews, list):
        round_reviews = []

    for rr in round_reviews:
        if not isinstance(rr, dict):
            continue

        round_num = rr.get("round_num", "?")
        round_result = rr.get("round_result", "unknown")

        lines.append(f"## Раунд {round_num}")
        lines.append("")
        lines.append(f"- Результат: `{round_result}`")
        lines.append(f"- Главный вывод: {rr.get('main_takeaway', '—')}")
        lines.append("")

        claims = rr.get("claims", [])
        if isinstance(claims, list) and claims:
            for claim in claims:
                if isinstance(claim, dict):
                    lines.extend(render_claim(claim))
        else:
            lines.append("Claims: —")
            lines.append("")

        lines.append(f"**Training note:** {rr.get('training_note', '—')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## План тренировки")
    lines.append("")
    lines.extend(render_training_plan(report.get("training_plan")))
    lines.append("")

    lines.append("## Неопределённости и ограничения")
    lines.append("")
    lines.extend(render_uncertainties(report.get("uncertainties")))
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def markdown_to_text(markdown: str) -> str:
    text = markdown
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("---", "-" * 60)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--report-path", default="")
    parser.add_argument("--repair-result-path", default="")
    parser.add_argument("--final-verdict-path", default="")
    args = parser.parse_args()

    if args.report_path:
        report_path = Path(args.report_path)
        if not report_path.is_absolute():
            report_path = PROJECT_ROOT / report_path
    else:
        report_path = (
            PROJECT_ROOT
            / "data"
            / "ai"
            / args.match_id
            / f"ai_coach_judge_llm_report_{args.player}_v0_7_claims_ru_repaired_v0_1.json"
        )

    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    if args.repair_result_path:
        repair_result_path = Path(args.repair_result_path)
        if not repair_result_path.is_absolute():
            repair_result_path = PROJECT_ROOT / repair_result_path
    else:
        repair_result_path = (
            PROJECT_ROOT
            / "data"
            / "ai"
            / args.match_id
            / f"ai_claim_report_repair_result_{args.player}_v0_1.json"
        )

    if args.final_verdict_path:
        final_verdict_path = Path(args.final_verdict_path)
        if not final_verdict_path.is_absolute():
            final_verdict_path = PROJECT_ROOT / final_verdict_path
    else:
        final_verdict_path = (
            PROJECT_ROOT
            / "data"
            / "ai"
            / args.match_id
            / f"ai_semantic_claim_judge_{args.player}_v0_3_repaired_r14_17.json"
        )

    report = load_json(report_path)
    repair_result = load_json(repair_result_path) if repair_result_path.exists() else None
    final_verdict = load_json(final_verdict_path) if final_verdict_path.exists() else None

    output_dir = PROJECT_ROOT / "data" / "reports" / args.match_id
    md_path = output_dir / f"coach_report_{args.player}_v0_7_claims_ru_repaired_v0_1.md"
    txt_path = output_dir / f"coach_report_{args.player}_v0_7_claims_ru_repaired_v0_1.txt"

    markdown = render_markdown(
        report=report,
        match_id=args.match_id,
        player=args.player,
        source_report_path=report_path,
        repair_result=repair_result,
        final_verdict=final_verdict,
    )

    text = markdown_to_text(markdown)

    write_text(md_path, markdown)
    write_text(txt_path, text)

    result = {
        "status": "ok",
        "renderer": "claim_report_renderer_v0_2",
        "match_id": args.match_id,
        "player": args.player,
        "source_report": str(report_path.relative_to(PROJECT_ROOT)),
        "repair_result_attached": repair_result is not None,
        "final_verdict_attached": final_verdict is not None,
        "round_reviews": len(report.get("round_reviews", []) or []),
        "top_priorities": len(report.get("top_priorities", []) or []),
        "created": {
            "markdown": str(md_path.relative_to(PROJECT_ROOT)),
            "text": str(txt_path.relative_to(PROJECT_ROOT)),
        },
        "chars": {
            "markdown": len(markdown),
            "text": len(text),
        },
        "lines": {
            "markdown": markdown.count("\n"),
            "text": text.count("\n"),
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
