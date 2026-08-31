from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SAFE_FIELD_HINTS = [
    "unsupported_claims_avoided",
    "what_evidence_does_not_support",
    "limited_or_uncertain",
    "major_limitations",
    "evidence_conflicts_or_gaps",
    "uncertainties",
    "caveat",
]

ASSERTIVE_FIELD_HINTS = [
    "match_summary",
    "main_takeaway",
    "priority",
    "practical_fix",
    "evidence_basis",
    "what_evidence_supports",
    "supported",
    "training_note",
    "rules",
    "exercises",
    "review_questions",
]


RISK_PATTERNS = {
    "visibility_overclaim": [
        r"\bdefinitely saw\b",
        r"\bdefinitely failed to see\b",
        r"\bточно видел\b",
        r"\bточно не видел\b",
        r"\bобязан был видеть\b",
        r"\bplayer saw\b",
        r"\bplayer failed to see\b",
    ],
    "flash_overclaim": [
        r"\bwas blinded\b",
        r"\bwas not blinded\b",
        r"\bего ослепило\b",
        r"\bне был ослепл[её]н\b",
    ],
    "enemy_intent_overclaim": [
        r"\benemy definitely\b",
        r"\benemies definitely\b",
        r"\bthe enemy knew\b",
        r"\bвраги точно\b",
        r"\bсоперник точно\b",
        r"\bвраги знали\b",
        r"\bсоперник знал\b",
    ],
    "died_first_overclaim": [
        r"\bdied first\b",
        r"\bумер первым\b",
    ],
    "bad_duel_choice_overclaim": [
        r"\bbad duel choice\b",
        r"\bневерный выбор дуэли\b",
    ],
    "trade_overclaim": [
        r"\bfree death\b",
        r"\bdied for free\b",
        r"\buntraded\b",
        r"\bno trade\b",
        r"\bбез размена\b",
        r"\bумер бесплатно\b",
    ],
    "hud_speed_wording": [
        r"\bHUD\b",
        r"\bскорость движения по HUD\b",
    ],
}


NEGATION_HINTS = [
    "does not prove",
    "does not support",
    "not prove",
    "not supported",
    "unsupported",
    "avoided claiming",
    "avoid claiming",
    "lack of",
    "due to lack",
    "limited",
    "cannot confirm",
    "cannot be confirmed",
    "нельзя доказать",
    "не доказывает",
    "не подтверждает",
    "избежал",
    "избегать",
    "нет данных",
    "ограничено",
    "нельзя утверждать",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def load_json_soft(path: Path):
    try:
        return json.loads(read_text(path)), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def path_is_safe(path: str) -> bool:
    p = path.lower()
    return any(h in p for h in SAFE_FIELD_HINTS)


def path_is_assertive(path: str) -> bool:
    p = path.lower()
    return any(h in p for h in ASSERTIVE_FIELD_HINTS)


def text_is_negated_or_caveated(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in NEGATION_HINTS)


def walk_strings(obj: Any, path: str = "root"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


def extract_round_num_from_path(path: str, report: Any) -> int | None:
    m = re.search(r"round_reviews\[(\d+)\]", path)
    if not m:
        return None
    idx = int(m.group(1))
    try:
        return int(report["round_reviews"][idx].get("round_num"))
    except Exception:
        return None


def add_issue(issues: list[dict[str, Any]], severity: str, code: str, message: str, **extra):
    item = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    item.update(extra)
    issues.append(item)


def find_risky_assertions(report: dict[str, Any]) -> list[dict[str, Any]]:
    issues = []

    for path, text in walk_strings(report):
        safe = path_is_safe(path)
        assertive = path_is_assertive(path)
        negated = text_is_negated_or_caveated(text)

        for code, patterns in RISK_PATTERNS.items():
            matched = []
            for pat in patterns:
                if re.search(pat, text, re.I | re.U):
                    matched.append(pat)

            if not matched:
                continue

            if safe or negated:
                continue

            if code == "hud_speed_wording":
                add_issue(
                    issues,
                    "warning",
                    code,
                    "Report mentions HUD speed outside a safe/negative context. Use parsed demo speed wording only.",
                    path=path,
                    text=text,
                    patterns=matched,
                    round_num=extract_round_num_from_path(path, report),
                )
                continue

            if assertive:
                add_issue(
                    issues,
                    "warning",
                    code,
                    "Risky claim appears in an assertive field without an explicit caveat/negation.",
                    path=path,
                    text=text,
                    patterns=matched,
                    round_num=extract_round_num_from_path(path, report),
                )

    return issues


def validate_schema(report: Any, issues: list[dict[str, Any]]) -> None:
    if not isinstance(report, dict):
        add_issue(issues, "error", "report_not_object", "Report JSON root must be an object.")
        return

    required = [
        "schema_version",
        "match_summary",
        "quality_control",
        "top_priorities",
        "round_reviews",
        "training_plan",
        "uncertainties",
    ]

    for key in required:
        if key not in report:
            add_issue(issues, "error", "missing_required_key", f"Missing required report key: {key}", key=key)

    if report.get("schema_version") not in {
        "ai_coach_judge_report_v0_4_guarded",
        "ai_coach_judge_report_v0_5_rich_guarded",
    }:
        add_issue(
            issues,
            "warning",
            "unexpected_schema_version",
            "Unexpected schema version.",
            schema_version=report.get("schema_version"),
        )

    rounds = report.get("round_reviews")
    if not isinstance(rounds, list) or not rounds:
        add_issue(issues, "error", "round_reviews_missing_or_empty", "round_reviews must be a non-empty list.")
        return

    for idx, r in enumerate(rounds):
        if not isinstance(r, dict):
            add_issue(issues, "error", "round_review_not_object", f"Round review #{idx} is not an object.")
            continue

        for key in [
            "round_num",
            "round_result",
            "main_takeaway",
            "claim_strength",
            "what_evidence_supports",
            "what_evidence_does_not_support",
            "mechanics",
            "decision",
            "info_state",
            "enemy_intent",
            "training_note",
        ]:
            if key not in r:
                add_issue(
                    issues,
                    "warning",
                    "round_review_missing_key",
                    f"Round review is missing key: {key}",
                    round_num=r.get("round_num"),
                    key=key,
                )

        if r.get("claim_strength") not in {"supported", "limited"}:
            add_issue(
                issues,
                "warning",
                "unexpected_claim_strength",
                "claim_strength should be supported or limited.",
                round_num=r.get("round_num"),
                claim_strength=r.get("claim_strength"),
            )


def validate_quality_control(report: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    qc = report.get("quality_control")
    if not isinstance(qc, dict):
        add_issue(issues, "error", "quality_control_missing", "quality_control must be present as an object.")
        return

    avoided = qc.get("unsupported_claims_avoided")
    if not isinstance(avoided, list) or not avoided:
        add_issue(
            issues,
            "warning",
            "unsupported_claims_avoided_missing",
            "quality_control.unsupported_claims_avoided should list avoided unsupported claims.",
        )

    limitations = qc.get("major_limitations")
    if not isinstance(limitations, list) or not limitations:
        add_issue(
            issues,
            "warning",
            "major_limitations_missing",
            "quality_control.major_limitations should list key limitations.",
        )


def validate_manual_contradictions(report: dict[str, Any], manual: Any, issues: list[dict[str, Any]]) -> None:
    if not isinstance(manual, dict):
        return

    manual_rounds = manual.get("rounds", {})
    if not isinstance(manual_rounds, dict):
        return

    round_map = {}
    for r in report.get("round_reviews", []):
        if isinstance(r, dict) and "round_num" in r:
            try:
                round_map[int(r["round_num"])] = r
            except Exception:
                pass

    for rnd_str, note in manual_rounds.items():
        try:
            rnd = int(rnd_str)
        except Exception:
            continue

        if not isinstance(note, dict):
            continue

        corrections = note.get("corrections", {})
        if not isinstance(corrections, dict):
            continue

        r = round_map.get(rnd)
        if not isinstance(r, dict):
            continue

        r_text = json.dumps(r, ensure_ascii=False).lower()
        support_text = json.dumps({
            "main_takeaway": r.get("main_takeaway"),
            "what_evidence_supports": r.get("what_evidence_supports"),
            "mechanics_supported": r.get("mechanics", {}).get("supported") if isinstance(r.get("mechanics"), dict) else None,
            "decision_supported": r.get("decision", {}).get("supported") if isinstance(r.get("decision"), dict) else None,
            "training_note": r.get("training_note"),
        }, ensure_ascii=False).lower()

        unsupported_text = json.dumps({
            "what_evidence_does_not_support": r.get("what_evidence_does_not_support"),
            "mechanics_uncertain": r.get("mechanics", {}).get("limited_or_uncertain") if isinstance(r.get("mechanics"), dict) else None,
            "decision_uncertain": r.get("decision", {}).get("limited_or_uncertain") if isinstance(r.get("decision"), dict) else None,
        }, ensure_ascii=False).lower()

        if corrections.get("player_died_first") is False:
            if re.search(r"\bdied first\b|умер первым", support_text, re.I | re.U):
                add_issue(
                    issues,
                    "error",
                    "manual_contradiction_died_first",
                    "Report assertively says player died first, but manual review says player did not die first.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )

        if corrections.get("third_duel_was_forced_or_reasonable") is True:
            if re.search(r"\bbad duel choice\b|неверный выбор дуэли", support_text, re.I | re.U):
                add_issue(
                    issues,
                    "error",
                    "manual_contradiction_bad_duel_choice",
                    "Report assertively says bad duel choice, but manual review says the duel was forced/reasonable.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )

        if corrections.get("bad_duel_choice_unsupported") is True:
            if re.search(r"\bbad duel choice\b|неверный выбор дуэли", support_text, re.I | re.U) and not re.search(
                r"does not support|does not prove|not supported|unsupported|не подтверждает|не доказывает",
                unsupported_text,
                re.I | re.U,
            ):
                add_issue(
                    issues,
                    "error",
                    "manual_contradiction_unsupported_bad_duel_choice",
                    "Report supports bad duel choice despite manual note that this is unsupported.",
                    round_num=rnd,
                    manual_summary=note.get("manual_summary"),
                )


def validate_report(args) -> dict[str, Any]:
    report_path = Path(args.report)
    manual_path = Path(args.manual_notes)

    issues: list[dict[str, Any]] = []

    report, report_err = load_json_soft(report_path)
    if report_err:
        add_issue(
            issues,
            "error",
            "report_json_invalid_or_truncated",
            "LLM report is not valid JSON or was truncated.",
            error=report_err,
        )
        report = None

    manual, manual_err = load_json_soft(manual_path)
    if manual_err:
        add_issue(issues, "warning", "manual_notes_unreadable", "Manual notes could not be read.", error=manual_err)
        manual = None

    if isinstance(report, dict):
        validate_schema(report, issues)
        validate_quality_control(report, issues)
        issues.extend(find_risky_assertions(report))
        validate_manual_contradictions(report, manual, issues)

    severity_rank = {"error": 3, "warning": 2, "info": 1}
    max_sev = max([severity_rank.get(i["severity"], 0) for i in issues], default=0)

    status = "pass"
    if max_sev >= 3:
        status = "fail"
    elif max_sev >= 2:
        status = "warn"

    summary = {
        "status": status,
        "validator": "ai_judgement_validator_v0_2",
        "report": str(report_path),
        "manual_notes": str(manual_path),
        "issues_total": len(issues),
        "issues_by_severity": {
            "error": sum(1 for i in issues if i["severity"] == "error"),
            "warning": sum(1 for i in issues if i["severity"] == "warning"),
            "info": sum(1 for i in issues if i["severity"] == "info"),
        },
        "issues": issues,
    }

    out_json = Path(args.out_json)
    out_txt = Path(args.out_txt)
    write_json(out_json, summary)

    lines = []
    lines.append("AI Judgement Validator v0.2")
    lines.append(f"Status: {status}")
    lines.append(f"Issues total: {len(issues)}")
    lines.append(f"By severity: {summary['issues_by_severity']}")
    lines.append("")
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. [{issue['severity'].upper()}] {issue['code']}")
        lines.append(f"   {issue['message']}")
        if "round_num" in issue and issue["round_num"] is not None:
            lines.append(f"   round: {issue['round_num']}")
        if "path" in issue:
            lines.append(f"   path: {issue['path']}")
        if "text" in issue:
            text = str(issue["text"]).replace("\n", " ")
            if len(text) > 360:
                text = text[:360] + "...[truncated]"
            lines.append(f"   text: {text}")
        lines.append("")

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines), encoding="utf-8")

    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report", required=True)
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
            "txt": args.out_txt,
        }
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
