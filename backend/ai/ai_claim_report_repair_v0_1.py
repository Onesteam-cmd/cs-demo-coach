from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

BASE_ENV_PATH = CONFIG_DIR / "llm.env"
PROFILES_ENV_PATH = CONFIG_DIR / "llm_profiles.env"


def parse_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}

    if not path.exists():
        return result

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")

    return result


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def endpoint_from_base_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def extract_json_from_text(text: str) -> Tuple[Optional[Any], Optional[str]]:
    clean = text.strip()

    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

    try:
        return json.loads(clean), None
    except Exception:
        pass

    first = clean.find("{")
    last = clean.rfind("}")

    if first == -1 or last == -1 or last <= first:
        return None, "No JSON object boundaries found."

    candidate = clean[first:last + 1]

    try:
        return json.loads(candidate), None
    except Exception as exc:
        return None, f"JSON parse failed after extraction: {exc}"


def find_report_path(match_id: str, player: str) -> Path:
    return (
        PROJECT_ROOT
        / "data"
        / "ai"
        / match_id
        / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.json"
    )


def find_targeted_judge_path(match_id: str, player: str, target_rounds_suffix: str = "2_8_14_17") -> Path:
    return (
        PROJECT_ROOT
        / "data"
        / "ai"
        / match_id
        / f"ai_semantic_claim_judge_{player}_v0_2_targeted_r{target_rounds_suffix}.json"
    )


def get_round_review(report: Dict[str, Any], round_num: int) -> Optional[Dict[str, Any]]:
    for rr in report.get("round_reviews", []):
        if isinstance(rr, dict) and int(rr.get("round_num", -999)) == round_num:
            return rr
    return None


def get_claim(round_review: Dict[str, Any], claim_id: str) -> Optional[Dict[str, Any]]:
    for claim in round_review.get("claims", []):
        if isinstance(claim, dict) and claim.get("claim_id") == claim_id:
            return claim
    return None


def affected_rounds_from_judge(judge: Dict[str, Any]) -> List[int]:
    rounds: List[int] = []

    repair = judge.get("repair_recommendation")
    if isinstance(repair, dict):
        for x in repair.get("target_rounds", []):
            try:
                num = int(x)
                if num not in rounds:
                    rounds.append(num)
            except Exception:
                pass

    for finding in judge.get("findings", []):
        if isinstance(finding, dict):
            try:
                num = int(finding.get("round_num"))
                if num not in rounds:
                    rounds.append(num)
            except Exception:
                pass

    return rounds


def focused_report_for_repair(report: Dict[str, Any], judge: Dict[str, Any]) -> Dict[str, Any]:
    rounds = affected_rounds_from_judge(judge)

    return {
        "schema_version": report.get("schema_version"),
        "language": report.get("language"),
        "affected_rounds": rounds,
        "round_reviews": [
            rr for rr in report.get("round_reviews", [])
            if isinstance(rr, dict) and int(rr.get("round_num", -999)) in rounds
        ],
        "note": "Only these fields may be patched. Do not rewrite the full report.",
    }


def build_system_prompt() -> str:
    return """
Ты claim report repair model для CS2 demo coach.

Твоя задача — НЕ переписывать отчёт.
Твоя задача — предложить минимальные patch-изменения только для полей, которые semantic judge отметил как problematic.

Правила:
- Не добавляй новые факты.
- Не меняй evidence_refs.
- Не меняй claim_id.
- Не меняй claim_type без прямой необходимости.
- Не меняй claim_strength без прямой инструкции judge.
- Не переписывай все claims.
- Не меняй раунды, которые judge не отметил.
- Исправляй только смысловую чрезмерную уверенность/категоричность.
- Для раунда 17 main_takeaway должен критиковать подтверждённую механику, но НЕ утверждать "плохой выбор дуэли" как факт.
- Для раунда 14 actionability должен быть менее категоричным и учитывать ограничения контекста.

Верни только валидный JSON без Markdown.

Схема:
{
  "schema_version": "ai_claim_report_repair_patch_v0_1",
  "repair_model_role": "targeted_patch_repair",
  "language": "ru",
  "patches": [
    {
      "patch_id": "rp001",
      "round_num": 17,
      "target_type": "main_takeaway|claim_field|training_note",
      "claim_id": null,
      "field": "main_takeaway|actionability|claim_text|limitations|alternative_explanations|training_note",
      "old_text": "...",
      "new_text": "...",
      "reason": "..."
    }
  ],
  "unchanged_policy": "All fields not listed in patches must remain unchanged."
}
""".strip()


def build_user_prompt(report_focus: Dict[str, Any], judge: Dict[str, Any]) -> str:
    return f"""
Semantic judge findings:
{json.dumps(judge, ensure_ascii=False, separators=(",", ":"))}

Focused original report:
{json.dumps(report_focus, ensure_ascii=False, separators=(",", ":"))}

Сделай только минимальные patches.

Ожидаемые исправления:
1. ROUND 17 main_takeaway:
   - убрать unsupported verdict про "невыгодную дуэль";
   - оставить подтверждённые механические проблемы: ошибка наводки, стрельба в движении, контроль Galil;
   - не утверждать плохой выбор дуэли без safe fallback evidence.

2. ROUND 14 claim r14_decision_01 actionability:
   - убрать категоричное "Никогда";
   - заменить на контекстный совет: избегать C4 в руках в нерасчищенной зоне, заранее уточнять/получать колл безопасности, готовить оружие перед зачисткой;
   - не добавлять новых фактов.
""".strip()


def make_openai_compatible_call(
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    timeout_sec: int,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_object",
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    started = time.time()

    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": int(exc.code),
            "elapsed_sec": round(time.time() - started, 3),
            "raw": raw,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "elapsed_sec": round(time.time() - started, 3),
            "error": str(exc),
            "raw": "",
        }

    return {
        "ok": 200 <= status_code < 300,
        "status_code": status_code,
        "elapsed_sec": round(time.time() - started, 3),
        "raw": raw,
    }


def extract_message_text(api_raw: str) -> str:
    parsed = json.loads(api_raw)
    choices = parsed.get("choices")

    if not choices:
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)

    return str(content)


def apply_patches(original_report: Dict[str, Any], patch_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    repaired = deepcopy(original_report)
    apply_log: List[Dict[str, Any]] = []

    patches = patch_payload.get("patches", [])
    if not isinstance(patches, list):
        raise ValueError("patches must be a list")

    allowed_fields = {
        "main_takeaway",
        "training_note",
        "actionability",
        "claim_text",
        "limitations",
        "alternative_explanations",
    }

    for patch in patches:
        if not isinstance(patch, dict):
            apply_log.append({
                "status": "skipped",
                "reason": "patch_not_object",
                "patch": patch,
            })
            continue

        round_num = int(patch.get("round_num"))
        target_type = patch.get("target_type")
        claim_id = patch.get("claim_id")
        field = patch.get("field")
        old_text = patch.get("old_text")
        new_text = patch.get("new_text")

        if field not in allowed_fields:
            apply_log.append({
                "status": "skipped",
                "reason": "field_not_allowed",
                "patch": patch,
            })
            continue

        rr = get_round_review(repaired, round_num)
        if rr is None:
            apply_log.append({
                "status": "skipped",
                "reason": "round_not_found",
                "patch": patch,
            })
            continue

        target_obj: Optional[Dict[str, Any]]

        if target_type == "main_takeaway":
            target_obj = rr
            field = "main_takeaway"
        elif target_type == "training_note":
            target_obj = rr
            field = "training_note"
        elif target_type == "claim_field":
            if not claim_id:
                apply_log.append({
                    "status": "skipped",
                    "reason": "claim_id_required",
                    "patch": patch,
                })
                continue

            target_obj = get_claim(rr, str(claim_id))
            if target_obj is None:
                apply_log.append({
                    "status": "skipped",
                    "reason": "claim_not_found",
                    "patch": patch,
                })
                continue
        else:
            apply_log.append({
                "status": "skipped",
                "reason": "target_type_not_allowed",
                "patch": patch,
            })
            continue

        current_value = target_obj.get(field)

        if isinstance(current_value, str):
            if isinstance(old_text, str) and current_value.strip() != old_text.strip():
                apply_log.append({
                    "status": "skipped",
                    "reason": "old_text_mismatch",
                    "round_num": round_num,
                    "claim_id": claim_id,
                    "field": field,
                    "current_value": current_value,
                    "old_text": old_text,
                })
                continue

            if not isinstance(new_text, str) or len(new_text.strip()) < 10:
                apply_log.append({
                    "status": "skipped",
                    "reason": "new_text_invalid",
                    "patch": patch,
                })
                continue

            target_obj[field] = new_text.strip()

        elif isinstance(current_value, list):
            if not isinstance(new_text, list):
                apply_log.append({
                    "status": "skipped",
                    "reason": "new_text_for_list_must_be_list",
                    "patch": patch,
                })
                continue

            target_obj[field] = new_text

        else:
            apply_log.append({
                "status": "skipped",
                "reason": "unsupported_current_field_type",
                "patch": patch,
            })
            continue

        apply_log.append({
            "status": "applied",
            "patch_id": patch.get("patch_id"),
            "round_num": round_num,
            "target_type": target_type,
            "claim_id": claim_id,
            "field": field,
            "old_value": current_value,
            "new_value": target_obj.get(field),
        })

    return repaired, apply_log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    parser.add_argument("--max-tokens", type=int, default=5000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    args = parser.parse_args()

    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)

    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")
    model = profiles_env.get("CS_DEMO_COACH_MODEL_REPAIR", "").strip()

    report_path = find_report_path(args.match_id, args.player)
    judge_path = find_targeted_judge_path(args.match_id, args.player)

    report = load_json(report_path)
    judge = load_json(judge_path)
    report_focus = focused_report_for_repair(report, judge)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(report_focus, judge)

    estimated_input_tokens_rough = int((len(system_prompt) + len(user_prompt)) / 3.7)

    output_dir = PROJECT_ROOT / "data" / "ai" / args.match_id

    patch_txt_path = output_dir / f"ai_claim_report_repair_patch_{args.player}_v0_1.txt"
    patch_json_path = output_dir / f"ai_claim_report_repair_patch_{args.player}_v0_1.json"
    repaired_report_path = output_dir / f"ai_coach_judge_llm_report_{args.player}_v0_7_claims_ru_repaired_v0_1.json"
    repair_result_path = output_dir / f"ai_claim_report_repair_result_{args.player}_v0_1.json"

    common = {
        "repair": "ai_claim_report_repair_v0_1",
        "mode": args.mode,
        "match_id": args.match_id,
        "player": args.player,
        "model": model,
        "report_path": str(report_path.relative_to(PROJECT_ROOT)),
        "judge_path": str(judge_path.relative_to(PROJECT_ROOT)),
        "affected_rounds": report_focus.get("affected_rounds"),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "estimated_input_tokens_rough": estimated_input_tokens_rough,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "output_paths": {
            "patch_txt": str(patch_txt_path.relative_to(PROJECT_ROOT)),
            "patch_json": str(patch_json_path.relative_to(PROJECT_ROOT)),
            "repaired_report": str(repaired_report_path.relative_to(PROJECT_ROOT)),
            "repair_result": str(repair_result_path.relative_to(PROJECT_ROOT)),
        },
    }

    issues: List[Dict[str, str]] = []

    if not base_url:
        issues.append({"severity": "error", "code": "missing_base_url", "message": "CS_DEMO_COACH_LLM_BASE_URL missing."})
    if not api_key:
        issues.append({"severity": "error", "code": "missing_api_key", "message": "CS_DEMO_COACH_LLM_API_KEY missing."})
    if model != "gemini-2.5-flash":
        issues.append({"severity": "warning", "code": "unexpected_repair_model", "message": f"Expected gemini-2.5-flash, got {model}."})

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")

    if args.mode == "check":
        status = "fail" if error_count else ("warn" if warning_count else "ok_ready_for_llm")
        print(json.dumps({
            "status": status,
            **common,
            "issues_total": len(issues),
            "issues_by_severity": {
                "error": error_count,
                "warning": warning_count,
                "info": sum(1 for issue in issues if issue["severity"] == "info"),
            },
            "issues": issues,
        }, ensure_ascii=False, indent=2))
        return 1 if error_count else 0

    if error_count:
        result = {
            "status": "fail",
            **common,
            "issues": issues,
        }
        write_json(repair_result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    endpoint = endpoint_from_base_url(base_url)

    call_result = make_openai_compatible_call(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        timeout_sec=args.timeout_sec,
    )

    if not call_result.get("ok"):
        result = {
            "status": "fail",
            **common,
            "call": {
                "ok": False,
                "status_code": call_result.get("status_code"),
                "elapsed_sec": call_result.get("elapsed_sec"),
                "error": call_result.get("error"),
                "raw_preview": str(call_result.get("raw", ""))[:2000],
            },
        }
        write_json(repair_result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    model_text = extract_message_text(str(call_result["raw"]))
    patch_payload, parse_error = extract_json_from_text(model_text)

    patch_txt_path.write_text(model_text, encoding="utf-8")

    if patch_payload is not None:
        write_json(patch_json_path, patch_payload)

    if patch_payload is None:
        result = {
            "status": "warn",
            **common,
            "call": {
                "ok": True,
                "status_code": call_result.get("status_code"),
                "elapsed_sec": call_result.get("elapsed_sec"),
            },
            "json_parse": {
                "ok": False,
                "error": parse_error,
            },
        }
        write_json(repair_result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    repaired_report, apply_log = apply_patches(report, patch_payload)
    write_json(repaired_report_path, repaired_report)

    applied_count = sum(1 for item in apply_log if item.get("status") == "applied")
    skipped_count = sum(1 for item in apply_log if item.get("status") != "applied")

    result = {
        "status": "ok" if applied_count > 0 and skipped_count == 0 else "warn",
        **common,
        "call": {
            "ok": True,
            "status_code": call_result.get("status_code"),
            "elapsed_sec": call_result.get("elapsed_sec"),
        },
        "text_chars": len(model_text),
        "json_parse": {
            "ok": True,
            "error": None,
        },
        "patches_total": len(patch_payload.get("patches", [])) if isinstance(patch_payload.get("patches"), list) else None,
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "apply_log": apply_log,
        "created": {
            "patch_txt": str(patch_txt_path.relative_to(PROJECT_ROOT)),
            "patch_json": str(patch_json_path.relative_to(PROJECT_ROOT)),
            "repaired_report": str(repaired_report_path.relative_to(PROJECT_ROOT)),
            "repair_result": str(repair_result_path.relative_to(PROJECT_ROOT)),
        },
    }

    write_json(repair_result_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if applied_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
