from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_V07_CLAIM_TYPES = {
    "mechanics",
    "decision",
    "info_state",
    "enemy_intent",
    "trade_spacing",
    "round_impact",
    "training",
}

# v0.8 permission keys are NOT valid v0.7 claim_type values.
# They must stay inside claim.permission_gate.permission_key.
PERMISSION_KEY_TO_V07_CLAIM_TYPE = {
    "bad_duel_choice": "decision",
    "info_mistake": "info_state",
    "mechanical_issue": "mechanics",
    "spacing_issue": "trade_spacing",
    "postplant_issue": "round_impact",
    "c4_safety_issue": "decision",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def backup(path: Path, tag: str) -> Optional[Path]:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(path.name + f".bak_{tag}_{stamp}")
    shutil.copy2(path, dst)
    return dst


def normalize_report(report: Any) -> Dict[str, Any]:
    patches: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    report_root = report
    if isinstance(report, dict) and isinstance(report.get("report"), dict):
        report_root = report["report"]

    if not isinstance(report_root, dict):
        return {
            "status": "failed",
            "reason": "report_root_not_object",
            "patches": patches,
            "issues": [{"severity": "error", "code": "report_root_not_object"}],
            "report": report,
        }

    round_reviews = report_root.get("round_reviews")
    if not isinstance(round_reviews, list):
        return {
            "status": "failed",
            "reason": "round_reviews_not_list",
            "patches": patches,
            "issues": [{"severity": "error", "code": "round_reviews_not_list"}],
            "report": report,
        }

    for rr_idx, rr in enumerate(round_reviews):
        if not isinstance(rr, dict):
            continue
        round_num = rr.get("round_num")
        claims = rr.get("claims")
        if not isinstance(claims, list):
            continue

        for claim_idx, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue

            claim_type = claim.get("claim_type")
            path = f"round_reviews[{rr_idx}].claims[{claim_idx}].claim_type"

            if claim_type in ALLOWED_V07_CLAIM_TYPES:
                continue

            mapped = PERMISSION_KEY_TO_V07_CLAIM_TYPE.get(str(claim_type))
            if mapped:
                claim["claim_type_original_v0_8"] = claim_type
                claim["claim_type"] = mapped
                patches.append({
                    "round_num": round_num,
                    "path": path,
                    "old": claim_type,
                    "new": mapped,
                    "reason": "v0.8 permission key was emitted as claim_type; normalized to v0.7-compatible claim_type",
                })
                continue

            issues.append({
                "severity": "error",
                "code": "unmapped_invalid_claim_type",
                "message": f"Invalid claim_type cannot be mapped safely: {claim_type}",
                "path": path,
                "round_num": round_num,
            })

    meta = report_root.setdefault("v0_8_compatibility_meta", {})
    if isinstance(meta, dict):
        meta["normalized_claim_types_for_v0_7_contract"] = True
        meta["normalizer"] = "normalize_claim_types_v0_8_to_v0_7.py"
        meta["normalized_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        meta["patches_total"] = len(patches)
        meta["allowed_v0_7_claim_types"] = sorted(ALLOWED_V07_CLAIM_TYPES)

    status = "ok" if not issues else "failed"
    return {
        "status": status,
        "patches": patches,
        "issues": issues,
        "report": report,
    }


def default_report_path(match_id: str, player: str) -> Path:
    return PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_v0_8_claims_ru.json"


def default_compat_path(match_id: str, player: str) -> Path:
    return PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.json"


def default_txt_path(match_id: str, player: str, version: str) -> Path:
    return PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_{version}.txt"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--report-path", default="")
    parser.add_argument("--write-compat-v07", action="store_true")
    parser.add_argument("--update-txt", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report_path) if args.report_path else default_report_path(args.match_id, args.player)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path

    result: Dict[str, Any] = {
        "status": "running",
        "normalizer": "normalize_claim_types_v0_8_to_v0_7",
        "match_id": args.match_id,
        "player": args.player,
        "report_path": rel(report_path),
    }

    if not report_path.exists():
        result.update({
            "status": "failed",
            "reason": "report_file_missing",
            "issues_total": 1,
            "issues": [{"severity": "error", "code": "report_file_missing", "path": rel(report_path)}],
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    report = load_json(report_path)
    normalized = normalize_report(report)
    patched_report = normalized["report"]

    backups: Dict[str, Optional[str]] = {}
    backups["source_json"] = rel(backup(report_path, "claim_type_compat") or Path("")) if report_path.exists() else None
    write_json(report_path, patched_report)

    written: Dict[str, str] = {"source_json": rel(report_path)}

    if args.write_compat_v07:
        compat = default_compat_path(args.match_id, args.player)
        backups["compat_json"] = rel(backup(compat, "claim_type_compat") or Path("")) if compat.exists() else None
        write_json(compat, patched_report)
        written["compat_json"] = rel(compat)

    if args.update_txt:
        text_payload = json.dumps(patched_report, ensure_ascii=False, indent=2)
        src_txt = default_txt_path(args.match_id, args.player, "v0_8_claims_ru")
        backups["source_txt"] = rel(backup(src_txt, "claim_type_compat") or Path("")) if src_txt.exists() else None
        src_txt.write_text(text_payload, encoding="utf-8")
        written["source_txt"] = rel(src_txt)

        if args.write_compat_v07:
            compat_txt = default_txt_path(args.match_id, args.player, "v0_7_claims_ru")
            backups["compat_txt"] = rel(backup(compat_txt, "claim_type_compat") or Path("")) if compat_txt.exists() else None
            compat_txt.write_text(text_payload, encoding="utf-8")
            written["compat_txt"] = rel(compat_txt)

    issues = normalized["issues"]
    patches = normalized["patches"]
    status = "ok" if not issues else "failed"

    result.update({
        "status": status,
        "patches_total": len(patches),
        "patches": patches,
        "issues_total": len(issues),
        "issues": issues,
        "written": written,
        "backups": backups,
    })

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
