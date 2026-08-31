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


def default_report_path(match_id: str, player: str) -> Path:
    return (
        PROJECT_ROOT
        / "data"
        / "ai"
        / match_id
        / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru_repaired_v0_1.json"
    )


def collect_claim_basis(report: Dict[str, Any]) -> Dict[str, Any]:
    basis: Dict[str, Any] = {
        "schema_version": report.get("schema_version"),
        "expected_rounds": report.get("expected_rounds"),
        "rounds_coverage": report.get("rounds_coverage"),
        "round_claims": [],
        "current_match_summary": report.get("match_summary"),
        "current_top_priorities": report.get("top_priorities"),
        "uncertainties": report.get("uncertainties"),
    }

    for rr in report.get("round_reviews", []) or []:
        if not isinstance(rr, dict):
            continue

        compact_round = {
            "round_num": rr.get("round_num"),
            "round_result": rr.get("round_result"),
            "main_takeaway": rr.get("main_takeaway"),
            "claims": [],
        }

        for claim in rr.get("claims", []) or []:
            if not isinstance(claim, dict):
                continue

            compact_round["claims"].append({
                "claim_id": claim.get("claim_id"),
                "claim_type": claim.get("claim_type"),
                "claim_strength": claim.get("claim_strength"),
                "claim_text": claim.get("claim_text"),
                "limitations": claim.get("limitations"),
                "alternative_explanations": claim.get("alternative_explanations"),
                "actionability": claim.get("actionability"),
            })

        basis["round_claims"].append(compact_round)

    return basis


def build_system_prompt() -> str:
    return """
Ты surface-level report repair model для CS2 demo coach.

Ты НЕ переписываешь claims.
Ты НЕ меняешь round_reviews.
Ты НЕ меняешь evidence_refs.
Ты НЕ добавляешь новые факты.

Твоя задача — исправить только верхний user-facing текст:
- match_summary;
- top_priorities[*].why_it_matters;
- top_priorities[*].training_focus;
- при необходимости top_priorities[*].title.

Главная проблема: верхний текст не должен быть сильнее, чем claims.
Запрещено делать глобальные обобщения без evidence:
- "большинство раундов";
- "часто";
- "регулярно";
- "систематически";
- "невыгодные дуэли";
- "отсутствие размена";
если это не прямо поддержано набором claims.

Но это НЕ hotword-запрет: оценивай смысл. Если формулировка доказана claims — можно оставить. Если нет — смягчи.

Правильный стиль:
- "в выбранных review-раундах";
- "в нескольких разобранных эпизодах";
- "повторяющийся сигнал в review-наборе";
- "по доступным evidence";
- "видно несколько эпизодов";
- "нужно проверить на следующих демках".

Верни только JSON patch.

Схема:
{
  "schema_version": "ai_surface_report_repair_patch_v0_1",
  "patches": [
    {
      "patch_id": "sr001",
      "target_path": "match_summary",
      "old_text": "...",
      "new_text": "...",
      "reason": "..."
    },
    {
      "patch_id": "sr002",
      "target_path": "top_priorities[1].why_it_matters",
      "old_text": "...",
      "new_text": "...",
      "reason": "..."
    }
  ]
}
""".strip()


def build_user_prompt(claim_basis: Dict[str, Any]) -> str:
    return f"""
Исправь только surface-level верх отчёта.

Особое внимание:
1. match_summary:
   - не должен утверждать "большинство раундов", если это не строго доказано;
   - не должен говорить "невыгодные дуэли" как общий verdict;
   - лучше писать "в выбранных review-раундах видны..." и "по нескольким эпизодам".

2. top_priorities:
   - не используй "часто/регулярно/систематически", если это не поддержано claim coverage;
   - не превращай stale-info в обвинение в агрессии без evidence;
   - C4 priority должен быть привязан к конкретному сигналу/раунду, а не глобальному паттерну.

CLAIM BASIS:
{json.dumps(claim_basis, ensure_ascii=False, separators=(",", ":"))}
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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
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


def get_target_value(report: Dict[str, Any], target_path: str) -> Optional[str]:
    if target_path == "match_summary":
        value = report.get("match_summary")
        return value if isinstance(value, str) else None

    m = re.fullmatch(r"top_priorities\[(\d+)\]\.(title|why_it_matters|training_focus)", target_path)
    if m:
        idx = int(m.group(1))
        field = m.group(2)
        top = report.get("top_priorities")
        if isinstance(top, list) and 0 <= idx < len(top) and isinstance(top[idx], dict):
            value = top[idx].get(field)
            return value if isinstance(value, str) else None

    return None


def set_target_value(report: Dict[str, Any], target_path: str, new_text: str) -> bool:
    if target_path == "match_summary":
        report["match_summary"] = new_text
        return True

    m = re.fullmatch(r"top_priorities\[(\d+)\]\.(title|why_it_matters|training_focus)", target_path)
    if m:
        idx = int(m.group(1))
        field = m.group(2)
        top = report.get("top_priorities")
        if isinstance(top, list) and 0 <= idx < len(top) and isinstance(top[idx], dict):
            top[idx][field] = new_text
            return True

    return False


def apply_patches(report: Dict[str, Any], patch_payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    repaired = deepcopy(report)
    apply_log: List[Dict[str, Any]] = []

    patches = patch_payload.get("patches", [])
    if not isinstance(patches, list):
        raise ValueError("patches must be a list")

    for patch in patches:
        if not isinstance(patch, dict):
            apply_log.append({"status": "skipped", "reason": "patch_not_object"})
            continue

        target_path = patch.get("target_path")
        old_text = patch.get("old_text")
        new_text = patch.get("new_text")

        if not isinstance(target_path, str):
            apply_log.append({"status": "skipped", "reason": "target_path_invalid", "patch": patch})
            continue

        current = get_target_value(repaired, target_path)

        if current is None:
            apply_log.append({"status": "skipped", "reason": "target_not_found", "target_path": target_path})
            continue

        if isinstance(old_text, str) and current.strip() != old_text.strip():
            apply_log.append({
                "status": "skipped",
                "reason": "old_text_mismatch",
                "target_path": target_path,
                "current": current,
                "old_text": old_text,
            })
            continue

        if not isinstance(new_text, str) or len(new_text.strip()) < 20:
            apply_log.append({"status": "skipped", "reason": "new_text_invalid", "target_path": target_path})
            continue

        set_target_value(repaired, target_path, new_text.strip())

        apply_log.append({
            "status": "applied",
            "patch_id": patch.get("patch_id"),
            "target_path": target_path,
            "old_value": current,
            "new_value": new_text.strip(),
            "reason": patch.get("reason"),
        })

    return repaired, apply_log


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--report-path", default="")
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    args = parser.parse_args()

    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)

    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")
    model = profiles_env.get("CS_DEMO_COACH_MODEL_REPAIR", "").strip()

    if args.report_path:
        report_path = Path(args.report_path)
        if not report_path.is_absolute():
            report_path = PROJECT_ROOT / report_path
    else:
        report_path = default_report_path(args.match_id, args.player)

    report = load_json(report_path)
    claim_basis = collect_claim_basis(report)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(claim_basis)

    estimated_input_tokens_rough = int((len(system_prompt) + len(user_prompt)) / 3.7)

    output_dir = PROJECT_ROOT / "data" / "ai" / args.match_id

    patch_txt_path = output_dir / f"ai_surface_report_repair_patch_{args.player}_v0_1.txt"
    patch_json_path = output_dir / f"ai_surface_report_repair_patch_{args.player}_v0_1.json"
    repaired_report_path = output_dir / f"ai_coach_judge_llm_report_{args.player}_v0_7_claims_ru_repaired_v0_2.json"
    result_path = output_dir / f"ai_surface_report_repair_result_{args.player}_v0_1.json"

    common = {
        "repair": "ai_surface_report_repair_v0_1",
        "mode": args.mode,
        "match_id": args.match_id,
        "player": args.player,
        "model": model,
        "report_path": str(report_path.relative_to(PROJECT_ROOT)),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "estimated_input_tokens_rough": estimated_input_tokens_rough,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "output_paths": {
            "patch_txt": str(patch_txt_path.relative_to(PROJECT_ROOT)),
            "patch_json": str(patch_json_path.relative_to(PROJECT_ROOT)),
            "repaired_report": str(repaired_report_path.relative_to(PROJECT_ROOT)),
            "result": str(result_path.relative_to(PROJECT_ROOT)),
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
        result = {"status": "fail", **common, "issues": issues}
        write_json(result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    call_result = make_openai_compatible_call(
        endpoint=endpoint_from_base_url(base_url),
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
        write_json(result_path, result)
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
            "json_parse": {"ok": False, "error": parse_error},
        }
        write_json(result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    repaired, apply_log = apply_patches(report, patch_payload)
    write_json(repaired_report_path, repaired)

    applied_count = sum(1 for x in apply_log if x.get("status") == "applied")
    skipped_count = sum(1 for x in apply_log if x.get("status") != "applied")

    result = {
        "status": "ok" if applied_count > 0 and skipped_count == 0 else "warn",
        **common,
        "call": {
            "ok": True,
            "status_code": call_result.get("status_code"),
            "elapsed_sec": call_result.get("elapsed_sec"),
        },
        "text_chars": len(model_text),
        "json_parse": {"ok": True, "error": None},
        "patches_total": len(patch_payload.get("patches", []) or []),
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "apply_log": apply_log,
        "created": {
            "patch_txt": str(patch_txt_path.relative_to(PROJECT_ROOT)),
            "patch_json": str(patch_json_path.relative_to(PROJECT_ROOT)),
            "repaired_report": str(repaired_report_path.relative_to(PROJECT_ROOT)),
            "result": str(result_path.relative_to(PROJECT_ROOT)),
        },
    }

    write_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if applied_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
