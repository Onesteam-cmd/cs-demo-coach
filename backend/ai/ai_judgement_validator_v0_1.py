from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


RISKY_VISIBILITY_PATTERNS = [
    r"\bточно видел\b",
    r"\bобязан был видеть\b",
    r"\bвидел соперника\b",
    r"\bего ослепило\b",
    r"\bбыл ослеплен\b",
    r"\bflash\b.*\bточно\b",
    r"\braycast\b",
]

RISKY_INTENT_PATTERNS = [
    r"\bвраги точно\b",
    r"\bсоперник точно\b",
    r"\bвраги знали\b",
    r"\bсоперник знал\b",
    r"\bспециально задумали\b",
    r"\bих план был\b",
]

RISKY_DECISION_PATTERNS = [
    r"\bневерный выбор дуэли\b",
    r"\bbad duel choice\b",
    r"\bумер бесплатно\b",
    r"\bбесплатно\b",
    r"\bумер первым\b",
    r"\bбез возможности\b",
    r"\bбез размена\b",
    r"\bне мог\b",
    r"\bобязан\b",
]

RISKY_MECHANICS_PATTERNS = [
    r"\bсистематически пренебрегает\b",
    r"\bполностью устранить\b",
    r"\bсделало точный выстрел невозможным\b",
    r"\bHUD\b",
    r"\bскорость движения по HUD\b",
]

ROUND_RE = re.compile(
    r'\{\s*"round_num"\s*:\s*(?P<round>\d+)\s*,(?P<body>.*?)(?=\n\s*\},\s*\{\s*"round_num"|\n\s*\]\s*,\s*"mechanics_review")',
    re.S,
)


def load_json_soft(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def find_patterns(text: str, patterns: list[str]) -> list[str]:
    found = []
    for pat in patterns:
        if re.search(pat, text, re.I | re.U):
            found.append(pat)
    return found


def extract_round_blocks(report_text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in ROUND_RE.finditer(report_text):
        try:
            rnd = int(m.group("round"))
            out[rnd] = m.group(0)
        except Exception:
            pass
    return out


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def get_round_card(compact: Any, round_num: int) -> dict[str, Any] | None:
    if not isinstance(compact, dict):
        return None
    cards = compact.get("round_cards_for_model")
    if isinstance(cards, list):
        for card in cards:
            if isinstance(card, dict) and int(card.get("round_num", -1)) == round_num:
                return card
    for d in walk(compact):
        if isinstance(d, dict):
            try:
                if int(d.get("round_num", -999999)) == round_num and "coach_reasoning" in d:
                    return d
            except Exception:
                pass
    return None


def has_explicit_support(card: dict[str, Any] | None, support_keys: list[str]) -> bool:
    if not isinstance(card, dict):
        return False
    for d in walk(card):
        if not isinstance(d, dict):
            continue
        for key in support_keys:
            if key in d:
                return True
    return False


def round_card_limitations(card: dict[str, Any] | None) -> list[str]:
    if not isinstance(card, dict):
        return ["round_card_missing"]

    limitations = []
    md = card.get("mechanics_deep", {})
    info = card.get("info_state", {})

    if isinstance(md, dict):
        if md.get("events_count", 0) <= 1:
            limitations.append("mechanics_deep_has_only_one_or_zero_events")
        flags = md.get("deep_flag_counts", {})
        if isinstance(flags, dict) and flags.get("visibility_flash_context_missing_or_limited", 0) > 0:
            limitations.append("visibility_flash_context_limited")
        if isinstance(md.get("top_events_sample"), list) and len(md.get("top_events_sample", [])) <= 1:
            limitations.append("only_one_top_mechanics_event_sample")

    if isinstance(info, dict):
        if info.get("focus_snapshots_count", 0) >= 5 and isinstance(md, dict) and md.get("events_count", 0) <= 1:
            limitations.append("many_info_snapshots_but_few_mechanics_events")
        if info.get("death_info_context_counts") and not has_explicit_support(card, ["player_died_first", "death_order", "entry_death"]):
            limitations.append("death_snapshot_without_death_order_context")

    return limitations


def add_issue(issues: list[dict[str, Any]], severity: str, code: str, message: str, **extra):
    item = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    item.update(extra)
    issues.append(item)


def validate_report(args) -> dict[str, Any]:
    report_path = Path(args.report)
    compact_path = Path(args.compact_input)
    manual_path = Path(args.manual_notes)
    out_json = Path(args.out_json)
    out_txt = Path(args.out_txt)

    report_text = read_text(report_path)
    compact, compact_err = load_json_soft(compact_path)
    manual, manual_err = load_json_soft(manual_path)

    issues: list[dict[str, Any]] = []

    parsed_report, report_json_err = load_json_soft(report_path)
    if report_json_err:
        add_issue(
            issues,
            "error",
            "report_json_invalid_or_truncated",
            "LLM report is not valid JSON or was truncated. It must not be accepted as a final machine-readable report.",
            error=report_json_err,
        )

    if compact_err:
        add_issue(issues, "error", "compact_input_unreadable", "Compact input could not be parsed.", error=compact_err)

    if manual_err:
        add_issue(issues, "warning", "manual_notes_unreadable", "Manual calibration notes could not be parsed.", error=manual_err)

    global_checks = [
        ("visibility_overclaim", RISKY_VISIBILITY_PATTERNS, "Report may overclaim visibility/flash/raycast."),
        ("enemy_intent_overclaim", RISKY_INTENT_PATTERNS, "Report may overclaim enemy intent/knowledge."),
        ("decision_overclaim", RISKY_DECISION_PATTERNS, "Report contains strong decision verdicts that require explicit support."),
        ("mechanics_overclaim", RISKY_MECHANICS_PATTERNS, "Report contains strong mechanics/HUD wording that may be unsupported."),
    ]

    for code, pats, msg in global_checks:
        found = find_patterns(report_text, pats)
        if found:
            add_issue(issues, "warning", code, msg, patterns=found)

    round_blocks = extract_round_blocks(report_text)

    for rnd, block in sorted(round_blocks.items()):
        card = get_round_card(compact, rnd)
        limitations = round_card_limitations(card)

        risky_decisions = find_patterns(block, RISKY_DECISION_PATTERNS)
        if risky_decisions and limitations:
            add_issue(
                issues,
                "warning",
                "round_verdict_with_limited_context",
                f"Round {rnd}: strong verdict appears while evidence card has limitations.",
                round_num=rnd,
                patterns=risky_decisions,
                evidence_limitations=limitations,
            )

        if re.search(r"\bумер первым\b", block, re.I | re.U):
            if not has_explicit_support(card, ["player_died_first", "death_order", "entry_death", "first_death"]):
                add_issue(
                    issues,
                    "warning",
                    "died_first_unsupported",
                    f"Round {rnd}: 'died first' claim is present but no explicit death-order support exists in compact card.",
                    round_num=rnd,
                )

        if re.search(r"\bбез размена\b|\bразмен", block, re.I | re.U):
            if not has_explicit_support(card, ["trade_available", "trade_possible", "nearest_teammate", "teammate_distance", "spacing"]):
                add_issue(
                    issues,
                    "warning",
                    "trade_claim_unsupported",
                    f"Round {rnd}: trade/spacing claim appears but no explicit teammate spacing/trade support exists in compact card.",
                    round_num=rnd,
                )

        if re.search(r"\bbad duel choice\b|\bневерный выбор дуэли\b", block, re.I | re.U):
            if not has_explicit_support(card, ["escape_available", "safe_fallback", "duel_forced", "angle_escape", "retreat_path"]):
                add_issue(
                    issues,
                    "warning",
                    "bad_duel_choice_unsupported",
                    f"Round {rnd}: bad duel choice verdict appears without explicit fallback/escape evidence.",
                    round_num=rnd,
                )

        if re.search(r"\bпервый выстрел.*?\d+[.,]?\d*\s*мс|\bfirst_shot_delay", block, re.I | re.U):
            if "visibility_flash_context_limited" in limitations:
                add_issue(
                    issues,
                    "info",
                    "reaction_delay_needs_visibility_caveat",
                    f"Round {rnd}: reaction/first-shot delay is mentioned while visibility/flash context is limited.",
                    round_num=rnd,
                )

    if isinstance(manual, dict):
        manual_rounds = manual.get("rounds", {})
        for rnd_str, note in manual_rounds.items():
            try:
                rnd = int(rnd_str)
            except Exception:
                continue

            block = round_blocks.get(rnd, "")
            corrections = note.get("corrections", {}) if isinstance(note, dict) else {}

            if corrections.get("player_died_first") is False and re.search(r"\bумер первым\b", block, re.I | re.U):
                add_issue(
                    issues,
                    "error",
                    "manual_contradiction_died_first",
                    f"Round {rnd}: report says player died first, but manual review says player did not die first.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )

            if corrections.get("third_duel_was_forced_or_reasonable") is True and re.search(r"\bbad duel choice\b|\bневерный выбор дуэли\b", block, re.I | re.U):
                add_issue(
                    issues,
                    "error",
                    "manual_contradiction_bad_duel_choice",
                    f"Round {rnd}: report says bad duel choice, but manual review says the duel was forced or reasonable from the position.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )

            if corrections.get("first_contact_was_won") is True and re.search(r"\bсделало точный выстрел невозможным\b", block, re.I | re.U):
                add_issue(
                    issues,
                    "warning",
                    "manual_correction_first_contact_won",
                    f"Round {rnd}: report overstates movement impact; manual review says first contact was won despite counter-strafe issue.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )

            if corrections.get("contact1_visual_contact") is False and re.search(r"Контакт 1", block, re.I | re.U):
                add_issue(
                    issues,
                    "info",
                    "manual_context_contact1_not_visual",
                    f"Round {rnd}: manual review says contact 1 was not visual; report should avoid treating it as a normal visual duel.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )

    severity_rank = {"error": 3, "warning": 2, "info": 1}
    max_sev = max([severity_rank.get(i["severity"], 0) for i in issues], default=0)
    status = "pass"
    if max_sev >= 3:
        status = "fail"
    elif max_sev >= 2:
        status = "warn"

    summary = {
        "status": status,
        "validator": "ai_judgement_validator_v0_1",
        "report": str(report_path),
        "compact_input": str(compact_path),
        "manual_notes": str(manual_path),
        "issues_total": len(issues),
        "issues_by_severity": {
            "error": sum(1 for i in issues if i["severity"] == "error"),
            "warning": sum(1 for i in issues if i["severity"] == "warning"),
            "info": sum(1 for i in issues if i["severity"] == "info"),
        },
        "issues": issues,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    lines.append(f"AI Judgement Validator v0.1")
    lines.append(f"Status: {status}")
    lines.append(f"Issues total: {len(issues)}")
    lines.append(f"By severity: {summary['issues_by_severity']}")
    lines.append("")
    for idx, issue in enumerate(issues, 1):
        lines.append(f"{idx}. [{issue['severity'].upper()}] {issue['code']}")
        lines.append(f"   {issue['message']}")
        if "round_num" in issue:
            lines.append(f"   round: {issue['round_num']}")
        if "patterns" in issue:
            lines.append(f"   patterns: {issue['patterns']}")
        if "evidence_limitations" in issue:
            lines.append(f"   evidence_limitations: {issue['evidence_limitations']}")
        lines.append("")

    out_txt.write_text("\n".join(lines), encoding="utf-8")

    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report", required=True)
    p.add_argument("--compact-input", required=True)
    p.add_argument("--manual-notes", required=True)
    p.add_argument("--out-json", required=True)
    p.add_argument("--out-txt", required=True)
    args = p.parse_args()

    summary = validate_report(args)
    print(json.dumps({
        "status": summary["status"],
        "validator": summary["validator"],
        "issues_total": summary["issues_total"],
        "issues_by_severity": summary["issues_by_severity"],
        "created": {
            "json": args.out_json,
            "txt": args.out_txt
        }
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
