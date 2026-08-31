from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
BASE_ENV_PATH = CONFIG_DIR / "llm.env"
PROFILES_ENV_PATH = CONFIG_DIR / "llm_profiles.env"

JUDGE_SCHEMA_VERSION = "ai_semantic_claim_judge_result_v0_8"
INPUT_VERSION = "ai_coach_judge_input_v0_8"
REPORT_VERSION = "v0_8_claims_ru"


def parse_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
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


def find_evidence_path(match_id: str) -> Path:
    candidates = [
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_v0_8_current.json",
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_current.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No v0.8 evidence input found. Checked:\n" + "\n".join(str(p) for p in candidates))


def find_report_path(match_id: str, player: str, prefer_compat_v07: bool) -> Path:
    candidates = []
    if not prefer_compat_v07:
        candidates.append(PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_v0_8_claims_ru.json")
    candidates.append(PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No claim report found. Checked:\n" + "\n".join(str(p) for p in candidates))


def compact_permission_summary(evidence_payload: Dict[str, Any]) -> Dict[str, Any]:
    cards = evidence_payload.get("round_cards_for_model") or []
    result: Dict[str, Any] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        rn = card.get("round_num")
        if rn is None:
            continue
        tc = card.get("tactical_context") or {}
        perms = card.get("claim_permissions") or {}
        result[str(rn)] = {
            "round_num": rn,
            "phase": tc.get("phase"),
            "player_task": tc.get("player_task"),
            "pressure": tc.get("pressure"),
            "safe_fallback_confidence": tc.get("safe_fallback_confidence"),
            "trade_support_confidence": tc.get("trade_support_confidence"),
            "claim_permissions": perms,
        }
    return result


def build_system_prompt() -> str:
    return """
Ты tactical semantic claim judge для CS2 demo coach v0.8.

Твоя задача — проверить claim-based отчёт против grounded evidence и v0.8 tactical/permission layer.
Ты НЕ генерируешь новый отчёт. Ты только находишь смысловые проблемы и указываешь, нужен ли repair.

Ключевые правила v0.8:
- claim_permissions являются hard guidance для отчёта.
- Если claim permission status = blocked, отчёт не должен делать этот вывод как claim, main_takeaway, top_priority или training focus.
- Если status = allowed_limited / limited_or_blocked, вывод не должен звучать как факт высокого confidence.
- bad_duel_choice требует evidence о safe fallback / рациональной альтернативе / возможности не принимать дуэль.
- spacing_issue требует осторожности: отсутствие быстрого размена не равно доказательство, что размен был реально возможен.
- postplant_issue и c4_safety_issue допустимы только если permission layer разрешает хотя бы limited claim.
- enemy_intent — гипотеза по observable events, не факт о намерениях врага.
- info_state — reconstructable prior info, не доказательство, что игрок точно слышал/знал.
- mechanics_deep — supporting evidence без raycast/visibility absolutism.

Проверяй CS-смысл, а не отдельные слова. Но если формулировка фактически утверждает запрещённый смысл, это finding.

Верни только валидный JSON без Markdown.

Схема ответа:
{
  "schema_version": "ai_semantic_claim_judge_result_v0_8",
  "judge_model_role": "cheap_tactical_claim_judge",
  "language": "ru",
  "overall_status": "pass|warn|fail",
  "can_continue_to_targeted_judge": true,
  "can_show_to_user_without_repair": false,
  "summary": "...",
  "rounds_checked": [2,3],
  "findings": [
    {
      "finding_id": "v8f001",
      "severity": "warning|error",
      "round_num": 17,
      "target_type": "main_takeaway|claim|top_priority|training_plan|surface_summary|permission_gate",
      "claim_id": "r17_decision_01|null",
      "issue_type": "blocked_permission_used|overconfident|unsupported|evidence_mismatch|missing_limitation|permission_mismatch|too_vague|good",
      "problem": "...",
      "evidence_assessment": "...",
      "permission_assessment": "...",
      "recommended_action": "keep|downgrade_strength|add_limitation|rewrite_takeaway|rewrite_surface|hide_from_user|send_to_repair"
    }
  ],
  "accepted_claims_sample": [
    {
      "round_num": 2,
      "claim_id": "r2_mechanics_01",
      "why_accepted": "..."
    }
  ],
  "repair_recommendation": {
    "needed": true,
    "scope": "none|specific_claims|specific_rounds|surface_only|full_report",
    "target_rounds": [17],
    "target_claim_ids": ["r17_decision_01"],
    "notes": "..."
  }
}
""".strip()


def build_user_prompt(match_id: str, player: str, evidence_payload: Dict[str, Any], report_payload: Dict[str, Any]) -> str:
    permission_summary = compact_permission_summary(evidence_payload)
    permission_text = json.dumps(permission_summary, ensure_ascii=False, separators=(",", ":"))
    evidence_text = json.dumps(evidence_payload, ensure_ascii=False, separators=(",", ":"))
    report_text = json.dumps(report_payload, ensure_ascii=False, separators=(",", ":"))

    return f"""
Матч: {match_id}
Игрок: {player}

Проверь v0.8 claim report против tactical context, claim permissions и evidence.

Сначала используй PERMISSION SUMMARY как карту разрешённых/заблокированных выводов. Потом проверяй полный EVIDENCE JSON и REPORT JSON.

Особое внимание:
- нет ли blocked permission claims;
- не протащил ли отчёт заблокированный смысл через main_takeaway/top_priority/training_plan;
- не звучат ли limited permissions как supported/high-confidence выводы;
- не вернулся ли старый overclaim по round 17: bad duel choice / плохой выбор дуэли / невыгодная дуэль как факт;
- не переутверждаются ли info_state/enemy_intent/spacing/postplant выводы.

PERMISSION SUMMARY JSON:
{permission_text}

FULL EVIDENCE JSON:
{evidence_text}

REPORT JSON:
{report_text}
""".strip()


def make_openai_compatible_call(endpoint: str, api_key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float, timeout_sec: int) -> Dict[str, Any]:
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
    request = urllib.request.Request(endpoint, data=data, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": int(exc.code), "elapsed_sec": round(time.time() - started, 3), "raw": raw}
    except Exception as exc:
        return {"ok": False, "status_code": None, "elapsed_sec": round(time.time() - started, 3), "error": str(exc), "raw": ""}
    return {"ok": 200 <= status_code < 300, "status_code": status_code, "elapsed_sec": round(time.time() - started, 3), "raw": raw}


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--prefer-compat-v07", action="store_true")
    args = parser.parse_args()

    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)
    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")
    model = profiles_env.get("CS_DEMO_COACH_MODEL_CHEAP_JUDGE", "").strip()

    evidence_path = find_evidence_path(args.match_id)
    report_path = find_report_path(args.match_id, args.player, args.prefer_compat_v07)
    evidence_payload = load_json(evidence_path)
    report_payload = load_json(report_path)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(args.match_id, args.player, evidence_payload, report_payload)
    estimated_input_tokens_rough = int((len(system_prompt) + len(user_prompt)) / 3.7)

    output_dir = PROJECT_ROOT / "data" / "ai" / args.match_id
    judge_txt_path = output_dir / f"ai_semantic_claim_judge_{args.player}_v0_8_cheap.txt"
    judge_json_path = output_dir / f"ai_semantic_claim_judge_{args.player}_v0_8_cheap.json"
    judge_result_path = output_dir / f"ai_semantic_claim_judge_result_{args.player}_v0_8_cheap.json"

    permission_summary = compact_permission_summary(evidence_payload)
    common = {
        "judge": "ai_semantic_claim_judge_v0_8",
        "mode": args.mode,
        "match_id": args.match_id,
        "player": args.player,
        "report_version": REPORT_VERSION,
        "model": model,
        "evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
        "report_path": str(report_path.relative_to(PROJECT_ROOT)),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "estimated_input_tokens_rough": estimated_input_tokens_rough,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "permission_rounds_total": len(permission_summary),
        "output_paths": {
            "judge_txt": str(judge_txt_path.relative_to(PROJECT_ROOT)),
            "judge_json": str(judge_json_path.relative_to(PROJECT_ROOT)),
            "judge_result": str(judge_result_path.relative_to(PROJECT_ROOT)),
        },
    }

    issues: List[Dict[str, str]] = []
    if not base_url:
        issues.append({"severity": "error", "code": "missing_base_url", "message": "CS_DEMO_COACH_LLM_BASE_URL missing."})
    if not api_key:
        issues.append({"severity": "error", "code": "missing_api_key", "message": "CS_DEMO_COACH_LLM_API_KEY missing."})
    if model != "gemini-3.1-flash-lite":
        issues.append({"severity": "warning", "code": "unexpected_cheap_judge_model", "message": f"Expected gemini-3.1-flash-lite, got {model}."})
    if evidence_payload.get("input_version") != INPUT_VERSION:
        issues.append({"severity": "warning", "code": "unexpected_input_version", "message": f"Expected {INPUT_VERSION}, got {evidence_payload.get('input_version')}."})
    if len(permission_summary) < 1:
        issues.append({"severity": "error", "code": "missing_permission_summary", "message": "No tactical permission summary could be extracted from v0.8 input."})
    if estimated_input_tokens_rough + args.max_tokens > 245000:
        issues.append({"severity": "warning", "code": "near_tpm_limit", "message": f"Estimated tokens {estimated_input_tokens_rough + args.max_tokens} is close to 250K TPM."})

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")

    if args.mode == "check":
        status = "fail" if error_count else ("warn" if warning_count else "ok_ready_for_llm")
        print(json.dumps({"status": status, **common, "issues_total": len(issues), "issues_by_severity": {"error": error_count, "warning": warning_count, "info": sum(1 for issue in issues if issue["severity"] == "info")}, "issues": issues}, ensure_ascii=False, indent=2))
        return 1 if error_count else 0

    if error_count:
        result = {"status": "fail", **common, "issues": issues}
        write_json(judge_result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    endpoint = endpoint_from_base_url(base_url)
    call_result = make_openai_compatible_call(endpoint, api_key, model, system_prompt, user_prompt, args.max_tokens, args.temperature, args.timeout_sec)

    if not call_result.get("ok"):
        result = {"status": "fail", **common, "call": {"ok": False, "status_code": call_result.get("status_code"), "elapsed_sec": call_result.get("elapsed_sec"), "error": call_result.get("error"), "raw_preview": str(call_result.get("raw", ""))[:2000]}}
        write_json(judge_result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    model_text = extract_message_text(str(call_result["raw"]))
    parsed_judge, parse_error = extract_json_from_text(model_text)
    judge_txt_path.write_text(model_text, encoding="utf-8")
    if parsed_judge is not None:
        write_json(judge_json_path, parsed_judge)

    result = {"status": "ok" if parsed_judge is not None else "warn", **common, "call": {"ok": True, "status_code": call_result.get("status_code"), "elapsed_sec": call_result.get("elapsed_sec")}, "text_chars": len(model_text), "json_parse": {"ok": parsed_judge is not None, "error": parse_error}, "created": {"judge_txt": str(judge_txt_path.relative_to(PROJECT_ROOT)), "judge_json": str(judge_json_path.relative_to(PROJECT_ROOT)) if parsed_judge is not None else None, "judge_result": str(judge_result_path.relative_to(PROJECT_ROOT))}}
    write_json(judge_result_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if parsed_judge is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
