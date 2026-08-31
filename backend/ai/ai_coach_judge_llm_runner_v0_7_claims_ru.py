from __future__ import annotations

import argparse
import json
import os
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

DEFAULT_EXPECTED_ROUNDS = [2, 3, 4, 8, 9, 11, 14, 15, 16, 17, 19, 20]


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


def find_input_path(match_id: str, player: str) -> Path:
    candidates = [
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_rich_guarded_current.json",
        PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_input_rich_guarded_{player}_v0_6_ru.json",
        PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_input_rich_guarded_{player}_v0_5.json",
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_current.json",
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_compact_current.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No AI coach judge input found. Checked:\n"
        + "\n".join(str(path) for path in candidates)
    )


def collect_round_numbers(value: Any) -> List[int]:
    found: List[int] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, child in obj.items():
                key_l = str(key).lower()
                if key_l in {"round_num", "round_number", "round"}:
                    try:
                        num = int(child)
                        if 1 <= num <= 100:
                            found.append(num)
                    except Exception:
                        pass
                else:
                    walk(child)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(value)

    ordered_unique: List[int] = []
    for num in found:
        if num not in ordered_unique:
            ordered_unique.append(num)

    return ordered_unique


def infer_expected_rounds(input_payload: Any) -> List[int]:
    if isinstance(input_payload, dict):
        for key in [
            "expected_rounds",
            "top_rounds",
            "rounds_for_review",
            "review_rounds",
        ]:
            raw = input_payload.get(key)
            if isinstance(raw, list):
                nums = []
                for item in raw:
                    try:
                        nums.append(int(item))
                    except Exception:
                        pass
                if nums:
                    return nums

        for key in [
            "round_cards_for_model",
            "round_cards",
            "review_round_cards",
        ]:
            raw = input_payload.get(key)
            if isinstance(raw, list):
                nums = []
                for item in raw:
                    if isinstance(item, dict):
                        for rk in ["round_num", "round_number", "round"]:
                            if rk in item:
                                try:
                                    nums.append(int(item[rk]))
                                except Exception:
                                    pass
                                break
                if nums:
                    return nums

    found = collect_round_numbers(input_payload)
    review_like = [num for num in DEFAULT_EXPECTED_ROUNDS if num in found]

    if len(review_like) >= 6:
        return review_like

    return DEFAULT_EXPECTED_ROUNDS


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
        return None, "No JSON object boundaries found in model output."

    candidate = clean[first : last + 1]

    try:
        return json.loads(candidate), None
    except Exception as exc:
        return None, f"JSON parse failed after extraction: {exc}"


def build_system_prompt() -> str:
    return """
Ты тренер-аналитик CS2 demo и строгий claim-based report generator.

Твоя задача: на основе предоставленного grounded evidence сделать русский тренерский отчёт v0.7_claims_ru.

Ключевой принцип:
- Не пиши просто красивые выводы.
- Каждый важный вывод должен быть оформлен как claim.
- Claim должен иметь силу, evidence_refs, limitations, alternative_explanations и actionability.
- Если evidence неполное, claim_strength должен быть limited или hypothesis.
- Если вывод нельзя подтвердить, не усиливай его. Отрази ограничение.
- Не придумывай visibility/raycast/flash/trade/intent факты, если их нет в evidence.
- Enemy intent — только вероятностная гипотеза по observable events.
- Info state — только reconstructable prior info, а не доказательство, что игрок точно слышал/знал.
- Mechanics deep — supporting evidence, но не абсолютная истина, потому что visibility/raycast ограничены.
- Не делай жёстких verdict без доказательства альтернативы, безопасного отхода, видимости и trade context.
- Не используй manual review notes как production input, если они случайно есть в данных.
- Весь user-facing текст должен быть на русском.
- Верни только валидный JSON без Markdown.

Структура ответа обязательна:
{
  "schema_version": "ai_coach_judge_report_v0_7_claims_ru",
  "model_role": "core_claim_generator",
  "language": "ru",
  "expected_rounds": [..],
  "rounds_coverage": {
    "expected_count": 12,
    "actual_count": 12,
    "missing_rounds": [],
    "extra_rounds": []
  },
  "match_summary": "...",
  "top_priorities": [
    {
      "priority_id": "p01",
      "title": "...",
      "why_it_matters": "...",
      "supporting_rounds": [2, 8],
      "claims_refs": ["r2_decision_01"],
      "training_focus": "..."
    }
  ],
  "round_reviews": [
    {
      "round_num": 17,
      "round_result": "win|loss|unknown",
      "main_takeaway": "...",
      "claims": [
        {
          "claim_id": "r17_decision_01",
          "claim_type": "mechanics|decision|info_state|enemy_intent|trade_spacing|round_impact|training",
          "claim_text": "...",
          "claim_strength": "supported|limited|hypothesis|unsupported_avoided",
          "evidence_refs": ["..."],
          "evidence_summary": ["..."],
          "limitations": ["..."],
          "alternative_explanations": ["..."],
          "actionability": "...",
          "should_show_to_user": true
        }
      ],
      "training_note": "..."
    }
  ],
  "training_plan": {
    "short_term": [],
    "medium_term": [],
    "review_method": "..."
  },
  "uncertainties": [
    {
      "topic": "...",
      "why_uncertain": "...",
      "what_evidence_is_missing": "..."
    }
  ]
}
""".strip()


def build_user_prompt(
    match_id: str,
    player: str,
    expected_rounds: List[int],
    evidence_text: str,
) -> str:
    expected_count = len(expected_rounds)

    return f"""
Матч: {match_id}
Игрок: {player}
Ожидаемые review rounds: {expected_rounds}
Ожидаемое количество round_reviews: {expected_count}

Сделай claim-based русский отчёт.

Жёсткие требования к coverage:
- round_reviews должен содержать каждый round из expected_rounds.
- Нельзя пропускать раунды из expected_rounds.
- Нельзя добавлять лишние раунды в round_reviews.
- rounds_coverage должен честно отражать expected/actual/missing/extra.

Жёсткие требования к claims:
- В каждом round_review должен быть непустой claims.
- Каждый claim должен быть самостоятельным проверяемым утверждением.
- claim_strength:
  - supported = evidence прямо поддерживает вывод;
  - limited = evidence указывает на проблему/паттерн, но есть важные ограничения;
  - hypothesis = вероятная интерпретация, но не факт;
  - unsupported_avoided = потенциальный вывод, который НЕ надо показывать как факт.
- Для supported claims evidence_refs не должен быть пустым.
- limitations должен быть списком даже если ограничений мало.
- alternative_explanations должен быть списком.
- actionability должен объяснять, что игроку делать практически.

Требование к качеству:
- Лучше честный limited claim, чем уверенный overclaim.
- Не делай вывод сильнее, чем позволяет evidence.
- Не переписывай evidence своими фантазиями.

EVIDENCE JSON:
{evidence_text}
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    args = parser.parse_args()

    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)

    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")
    model = profiles_env.get("CS_DEMO_COACH_MODEL_CORE", "").strip() or base_env.get("CS_DEMO_COACH_LLM_MODEL", "")

    input_path = find_input_path(args.match_id, args.player)
    input_payload = load_json(input_path)
    expected_rounds = infer_expected_rounds(input_payload)

    evidence_text = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(args.match_id, args.player, expected_rounds, evidence_text)

    estimated_input_tokens_rough = int((len(system_prompt) + len(user_prompt)) / 3.7)

    output_dir = PROJECT_ROOT / "data" / "ai" / args.match_id
    report_txt_path = output_dir / f"ai_coach_judge_llm_report_{args.player}_v0_7_claims_ru.txt"
    report_json_path = output_dir / f"ai_coach_judge_llm_report_{args.player}_v0_7_claims_ru.json"
    result_json_path = output_dir / f"ai_coach_judge_llm_result_{args.player}_v0_7_claims_ru.json"

    common = {
        "runner": "ai_coach_judge_llm_runner_v0_7_claims_ru",
        "mode": args.mode,
        "match_id": args.match_id,
        "player": args.player,
        "model": model,
        "input_path": str(input_path.relative_to(PROJECT_ROOT)),
        "input_chars": len(evidence_text),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "estimated_input_tokens_rough": estimated_input_tokens_rough,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "expected_rounds": expected_rounds,
        "output_paths": {
            "report_txt": str(report_txt_path.relative_to(PROJECT_ROOT)),
            "report_json": str(report_json_path.relative_to(PROJECT_ROOT)),
            "result_json": str(result_json_path.relative_to(PROJECT_ROOT)),
        },
    }

    check_issues: List[Dict[str, str]] = []

    if not BASE_ENV_PATH.exists():
        check_issues.append({"severity": "error", "code": "missing_llm_env", "message": "config/llm.env not found."})
    if not PROFILES_ENV_PATH.exists():
        check_issues.append({"severity": "error", "code": "missing_profiles_env", "message": "config/llm_profiles.env not found."})
    if not base_url:
        check_issues.append({"severity": "error", "code": "missing_base_url", "message": "CS_DEMO_COACH_LLM_BASE_URL missing."})
    if not api_key:
        check_issues.append({"severity": "error", "code": "missing_api_key", "message": "CS_DEMO_COACH_LLM_API_KEY missing."})
    if model != "gemini-3.5-flash":
        check_issues.append({"severity": "warning", "code": "unexpected_core_model", "message": f"Expected gemini-3.5-flash, got {model}."})
    if estimated_input_tokens_rough + args.max_tokens > 245000:
        check_issues.append({
            "severity": "warning",
            "code": "near_tpm_limit",
            "message": f"Estimated tokens {estimated_input_tokens_rough + args.max_tokens} is close to 250K TPM.",
        })

    error_count = sum(1 for issue in check_issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in check_issues if issue["severity"] == "warning")

    if args.mode == "check":
        status = "fail" if error_count else ("warn" if warning_count else "ok_ready_for_llm")
        print(json.dumps({
            "status": status,
            **common,
            "issues_total": len(check_issues),
            "issues_by_severity": {
                "error": error_count,
                "warning": warning_count,
                "info": sum(1 for issue in check_issues if issue["severity"] == "info"),
            },
            "issues": check_issues,
        }, ensure_ascii=False, indent=2))
        return 1 if error_count else 0

    if error_count:
        print(json.dumps({
            "status": "fail",
            **common,
            "issues": check_issues,
        }, ensure_ascii=False, indent=2))
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
        write_json(result_json_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    model_text = extract_message_text(str(call_result["raw"]))

    parsed_report, parse_error = extract_json_from_text(model_text)

    report_txt_path.parent.mkdir(parents=True, exist_ok=True)
    report_txt_path.write_text(model_text, encoding="utf-8")

    if parsed_report is not None:
        write_json(report_json_path, parsed_report)

    result = {
        "status": "ok" if parsed_report is not None else "warn",
        **common,
        "call": {
            "ok": True,
            "status_code": call_result.get("status_code"),
            "elapsed_sec": call_result.get("elapsed_sec"),
        },
        "text_chars": len(model_text),
        "json_parse": {
            "ok": parsed_report is not None,
            "error": parse_error,
        },
        "created": {
            "report_txt": str(report_txt_path.relative_to(PROJECT_ROOT)),
            "report_json": str(report_json_path.relative_to(PROJECT_ROOT)) if parsed_report is not None else None,
            "result_json": str(result_json_path.relative_to(PROJECT_ROOT)),
        },
    }

    write_json(result_json_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if parsed_report is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
