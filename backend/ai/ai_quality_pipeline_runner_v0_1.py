from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "ai_quality_pipeline_manifest_v0_1"
ACCEPTED_REPORT_VERSION = "v0_7_claims_ru_final_v0_1"
ACCEPTED_REPORT_SCHEMA = "ai_coach_judge_report_v0_7_claims_ru"


@dataclass
class PsStep:
    name: str
    candidates: List[str]
    required: bool = True
    timeout_sec: int = 1800


PIPELINE_STEPS: List[PsStep] = [
    PsStep(
        name="llm_profiles_check",
        candidates=["scripts/check_llm_profiles_v0_1.ps1"],
        timeout_sec=120,
    ),
    PsStep(
        name="core_claim_report_generate",
        candidates=[
            "scripts/run_ai_coach_judge_llm_v0_7_claims_ru_retry.ps1",
            "scripts/run_ai_coach_judge_llm_v0_7_claims_ru.ps1",
        ],
        timeout_sec=2400,
    ),
    PsStep(
        name="claim_contract_validate",
        candidates=["scripts/validate_claim_report_contract_v0_1.ps1"],
        timeout_sec=300,
    ),
    PsStep(
        name="cheap_semantic_claim_judge",
        candidates=["scripts/run_ai_semantic_claim_judge_v0_1.ps1"],
        timeout_sec=900,
    ),
    PsStep(
        name="targeted_semantic_claim_judge",
        candidates=[
            "scripts/run_ai_semantic_claim_judge_v0_2_targeted_retry.ps1",
            "scripts/run_ai_semantic_claim_judge_v0_2_targeted.ps1",
        ],
        timeout_sec=1200,
    ),
    PsStep(
        name="claim_report_repair",
        candidates=[
            "scripts/run_ai_claim_report_repair_v0_1_retry.ps1",
            "scripts/run_ai_claim_report_repair_v0_1.ps1",
        ],
        timeout_sec=1200,
    ),
    PsStep(
        name="repaired_report_verify",
        candidates=[
            "scripts/run_ai_semantic_claim_judge_v0_3_repaired_verify_retry.ps1",
            "scripts/run_ai_semantic_claim_judge_v0_3_repaired_verify.ps1",
        ],
        timeout_sec=1200,
    ),
    PsStep(
        name="surface_report_repair",
        candidates=[
            "scripts/run_ai_surface_report_repair_v0_1_retry.ps1",
            "scripts/run_ai_surface_report_repair_v0_1.ps1",
        ],
        timeout_sec=1200,
    ),
    PsStep(
        name="claim_report_render",
        candidates=["scripts/render_claim_report_v0_2.ps1"],
        timeout_sec=300,
    ),
    PsStep(
        name="accept_claim_report",
        candidates=["scripts/accept_ai_coach_judge_report_v0_1.ps1"],
        timeout_sec=300,
    ),
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def choose_powershell() -> str:
    return shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"


def choose_existing(root: Path, candidates: List[str]) -> Optional[Path]:
    for rel in candidates:
        path = root / rel
        if path.exists():
            return path
    return None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def preflight(root: Path, match_id: str, player: str) -> Dict[str, Any]:
    script_checks = []

    missing_required = []
    for step in PIPELINE_STEPS:
        found = choose_existing(root, step.candidates)
        item = {
            "step": step.name,
            "found": str(found.relative_to(root)) if found else None,
            "candidates": step.candidates,
            "required": step.required,
        }
        script_checks.append(item)
        if step.required and found is None:
            missing_required.append(item)

    expected_existing_inputs = [
        f"data/package/{match_id}/coach_input_package_current.json",
        f"data/ai/{match_id}/ai_coach_judge_input_current.json",
        f"data/ai/{match_id}/ai_coach_judge_dry_run_current.json",
    ]

    input_checks = []
    missing_inputs = []
    for rel in expected_existing_inputs:
        exists = (root / rel).exists()
        item = {"path": rel, "exists": exists}
        input_checks.append(item)
        if not exists:
            missing_inputs.append(item)

    status = "preflight_ok"
    if missing_required:
        status = "preflight_error_missing_scripts"
    elif missing_inputs:
        status = "preflight_warn_missing_inputs"

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "preflight",
        "status": status,
        "project_root": str(root),
        "match_id": match_id,
        "player": player,
        "script_checks": script_checks,
        "missing_required_scripts": missing_required,
        "input_checks": input_checks,
        "missing_inputs": missing_inputs,
        "ready_to_run_quality_pipeline": len(missing_required) == 0 and len(missing_inputs) == 0,
        "note": "Preflight does not call LLM providers and does not spend Gemini quota.",
    }


def run_ps_step(
    root: Path,
    step: PsStep,
    match_id: str,
    player: str,
    quality_profile: str,
    logs_dir: Path,
) -> Dict[str, Any]:
    script_path = choose_existing(root, step.candidates)
    if script_path is None:
        return {
            "step": step.name,
            "status": "missing_script",
            "required": step.required,
            "candidates": step.candidates,
        }

    ps = choose_powershell()
    log_base = logs_dir / f"{len(list(logs_dir.glob('*.stdout.txt'))) + 1:02d}_{step.name}"

    command = f"""
$ErrorActionPreference = 'Stop'
$scriptPath = {ps_literal(str(script_path))}
$cmd = Get-Command -LiteralPath $scriptPath

$params = @{{}}

if ($cmd.Parameters.ContainsKey('MatchId')) {{
    $params['MatchId'] = {ps_literal(match_id)}
}}

if ($cmd.Parameters.ContainsKey('Player')) {{
    $params['Player'] = {ps_literal(player)}
}}

if ($cmd.Parameters.ContainsKey('PlayerName')) {{
    $params['PlayerName'] = {ps_literal(player)}
}}

if ($cmd.Parameters.ContainsKey('QualityProfile')) {{
    $params['QualityProfile'] = {ps_literal(quality_profile)}
}}

& $scriptPath @params

if ($LASTEXITCODE -is [int] -and $LASTEXITCODE -ne 0) {{
    exit $LASTEXITCODE
}}

exit 0
""".strip()

    started = time.time()
    try:
        result = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=str(root),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=step.timeout_sec,
        )
        elapsed = round(time.time() - started, 3)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        (log_base.with_suffix(".stdout.txt")).write_text(stdout, encoding="utf-8", errors="replace")
        (log_base.with_suffix(".stderr.txt")).write_text(stderr, encoding="utf-8", errors="replace")
        return {
            "step": step.name,
            "status": "timeout",
            "script": str(script_path.relative_to(root)),
            "timeout_sec": step.timeout_sec,
        }

    (log_base.with_suffix(".stdout.txt")).write_text(result.stdout or "", encoding="utf-8", errors="replace")
    (log_base.with_suffix(".stderr.txt")).write_text(result.stderr or "", encoding="utf-8", errors="replace")

    return {
        "step": step.name,
        "status": "ok" if result.returncode == 0 else "failed",
        "script": str(script_path.relative_to(root)),
        "returncode": result.returncode,
        "elapsed_sec": elapsed,
        "stdout_log": str(log_base.with_suffix(".stdout.txt").relative_to(root)),
        "stderr_log": str(log_base.with_suffix(".stderr.txt").relative_to(root)),
    }


def apply_local_final_surface_patch(root: Path, match_id: str, player: str) -> Dict[str, Any]:
    ai_dir = root / "data" / "ai" / match_id

    src = ai_dir / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru_repaired_v0_2.json"
    dst = ai_dir / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru_final_v0_1.json"

    if not src.exists():
        if dst.exists():
            return {
                "step": "local_final_surface_patch",
                "status": "ok_existing_final",
                "final_json": str(dst.relative_to(root)),
            }

        return {
            "step": "local_final_surface_patch",
            "status": "missing_source",
            "expected_source": str(src.relative_to(root)),
            "expected_final": str(dst.relative_to(root)),
        }

    data = read_json(src)
    patches = []

    priorities = data.get("top_priorities")
    if isinstance(priorities, list):
        for idx, item in enumerate(priorities):
            if not isinstance(item, dict):
                continue

            old_title = item.get("title")
            if old_title == "Безопасность при обращении с C4 и гранатами":
                item["title"] = "Безопасность при обращении с C4"
                patches.append({
                    "path": f"top_priorities[{idx}].title",
                    "old": old_title,
                    "new": item["title"],
                })

    data.setdefault("quality_pipeline_meta", {})
    if isinstance(data["quality_pipeline_meta"], dict):
        data["quality_pipeline_meta"]["finalized_by"] = "ai_quality_pipeline_runner_v0_1"
        data["quality_pipeline_meta"]["finalized_at"] = now_iso()
        data["quality_pipeline_meta"]["local_surface_patches"] = patches

    write_json(dst, data)

    return {
        "step": "local_final_surface_patch",
        "status": "ok",
        "source_json": str(src.relative_to(root)),
        "final_json": str(dst.relative_to(root)),
        "patches_total": len(patches),
        "patches": patches,
    }


def final_contract_check(root: Path, match_id: str, player: str) -> Dict[str, Any]:
    accepted_json = root / "data" / "ai" / match_id / "ai_coach_judge_report_accepted_current.json"
    accepted_md = root / "data" / "reports" / match_id / "coach_report_accepted_current.md"
    accepted_txt = root / "data" / "reports" / match_id / "coach_report_accepted_current.txt"
    manifest_path = root / "data" / "ai" / match_id / "ai_coach_judge_acceptance_manifest_current.json"

    required_files = [accepted_json, accepted_md, accepted_txt, manifest_path]
    missing = [str(p.relative_to(root)) for p in required_files if not p.exists()]

    if missing:
        return {
            "step": "final_contract_check",
            "status": "failed",
            "reason": "missing_accepted_outputs",
            "missing": missing,
        }

    report = read_json(accepted_json)
    manifest = read_json(manifest_path)

    issues = []

    if manifest.get("status") != "accepted":
        issues.append({
            "path": "manifest.status",
            "expected": "accepted",
            "actual": manifest.get("status"),
        })

    if manifest.get("accepted_report_version") != ACCEPTED_REPORT_VERSION:
        issues.append({
            "path": "manifest.accepted_report_version",
            "expected": ACCEPTED_REPORT_VERSION,
            "actual": manifest.get("accepted_report_version"),
        })

    if report.get("schema_version") != ACCEPTED_REPORT_SCHEMA:
        issues.append({
            "path": "accepted_report.schema_version",
            "expected": ACCEPTED_REPORT_SCHEMA,
            "actual": report.get("schema_version"),
        })

    if report.get("language") != "ru":
        issues.append({
            "path": "accepted_report.language",
            "expected": "ru",
            "actual": report.get("language"),
        })

    round_reviews = report.get("round_reviews")
    if not isinstance(round_reviews, list) or len(round_reviews) != 12:
        issues.append({
            "path": "accepted_report.round_reviews",
            "expected_count": 12,
            "actual_count": len(round_reviews) if isinstance(round_reviews, list) else None,
        })

    checks = manifest.get("acceptance_checks")
    if not isinstance(checks, dict):
        issues.append({
            "path": "manifest.acceptance_checks",
            "expected": "object",
            "actual": type(checks).__name__,
        })
        checks = {}

    if checks.get("contract_status") != "ok":
        issues.append({
            "path": "manifest.acceptance_checks.contract_status",
            "expected": "ok",
            "actual": checks.get("contract_status"),
        })

    if checks.get("semantic_verifier_status") != "pass":
        issues.append({
            "path": "manifest.acceptance_checks.semantic_verifier_status",
            "expected": "pass",
            "actual": checks.get("semantic_verifier_status"),
        })

    if checks.get("needs_more_repair") is not False:
        issues.append({
            "path": "manifest.acceptance_checks.needs_more_repair",
            "expected": False,
            "actual": checks.get("needs_more_repair"),
        })

    return {
        "step": "final_contract_check",
        "status": "ok" if not issues else "failed",
        "issues_total": len(issues),
        "issues": issues,
        "accepted_json": str(accepted_json.relative_to(root)),
        "accepted_markdown": str(accepted_md.relative_to(root)),
        "accepted_text": str(accepted_txt.relative_to(root)),
        "acceptance_manifest": str(manifest_path.relative_to(root)),
        "accepted_report_version": manifest.get("accepted_report_version"),
        "accepted_report_round_reviews": len(round_reviews) if isinstance(round_reviews, list) else None,
        "accepted_report_semantic_status": checks.get("semantic_verifier_status"),
        "final_contract": (
            "ok_v0_7_with_ai_judge_input_dry_run_and_accepted_claims_ru_report"
            if not issues else
            "failed_v0_7_quality_pipeline_contract"
        ),
    }


def run_pipeline(args: argparse.Namespace) -> Dict[str, Any]:
    root = Path(args.project_root).resolve() if args.project_root else Path.cwd().resolve()
    match_id = args.match_id
    player = args.player

    ai_dir = root / "data" / "ai" / match_id
    logs_dir = ai_dir / "quality_pipeline_logs_v0_1"
    ensure_dir(logs_dir)

    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "run",
        "status": "running",
        "project_root": str(root),
        "match_id": match_id,
        "player": player,
        "quality_profile": args.quality_profile,
        "started_at": now_iso(),
        "steps": [],
    }

    pre = preflight(root, match_id, player)
    manifest["preflight"] = pre

    if args.preflight_only:
        return pre

    if pre["missing_required_scripts"]:
        manifest["status"] = "failed_preflight_missing_scripts"
        write_json(ai_dir / f"ai_quality_pipeline_manifest_{player}_v0_1.json", manifest)
        write_json(ai_dir / "ai_quality_pipeline_manifest_current.json", manifest)
        return manifest

    for step in PIPELINE_STEPS:
        if args.skip_core_generation and step.name == "core_claim_report_generate":
            result = {
                "step": step.name,
                "status": "skipped_by_user",
                "reason": "SkipCoreGeneration",
            }
        elif args.skip_surface_repair and step.name == "surface_report_repair":
            result = {
                "step": step.name,
                "status": "skipped_by_user",
                "reason": "SkipSurfaceRepair",
            }
        else:
            result = run_ps_step(
                root=root,
                step=step,
                match_id=match_id,
                player=player,
                quality_profile=args.quality_profile,
                logs_dir=logs_dir,
            )

        manifest["steps"].append(result)
        write_json(ai_dir / f"ai_quality_pipeline_manifest_{player}_v0_1.json", manifest)
        write_json(ai_dir / "ai_quality_pipeline_manifest_current.json", manifest)

        if result.get("status") not in {"ok", "skipped_by_user"} and not args.keep_going:
            manifest["status"] = "failed"
            manifest["failed_step"] = result.get("step")
            manifest["finished_at"] = now_iso()
            write_json(ai_dir / f"ai_quality_pipeline_manifest_{player}_v0_1.json", manifest)
            write_json(ai_dir / "ai_quality_pipeline_manifest_current.json", manifest)
            return manifest

        if step.name == "surface_report_repair":
            local_patch = apply_local_final_surface_patch(root, match_id, player)
            manifest["steps"].append(local_patch)
            write_json(ai_dir / f"ai_quality_pipeline_manifest_{player}_v0_1.json", manifest)
            write_json(ai_dir / "ai_quality_pipeline_manifest_current.json", manifest)

            if local_patch.get("status") not in {"ok", "ok_existing_final"} and not args.keep_going:
                manifest["status"] = "failed"
                manifest["failed_step"] = "local_final_surface_patch"
                manifest["finished_at"] = now_iso()
                write_json(ai_dir / f"ai_quality_pipeline_manifest_{player}_v0_1.json", manifest)
                write_json(ai_dir / "ai_quality_pipeline_manifest_current.json", manifest)
                return manifest

    final_check = final_contract_check(root, match_id, player)
    manifest["steps"].append(final_check)

    manifest["status"] = "ok" if final_check.get("status") == "ok" else "failed_final_contract"
    manifest["finished_at"] = now_iso()
    manifest["final_contract"] = final_check.get("final_contract")

    write_json(ai_dir / f"ai_quality_pipeline_manifest_{player}_v0_1.json", manifest)
    write_json(ai_dir / "ai_quality_pipeline_manifest_current.json", manifest)

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default="")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--quality-profile", default="balanced")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-core-generation", action="store_true")
    parser.add_argument("--skip-surface-repair", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    result = run_pipeline(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    status = result.get("status")
    return 0 if status in {"ok", "preflight_ok", "preflight_warn_missing_inputs"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
