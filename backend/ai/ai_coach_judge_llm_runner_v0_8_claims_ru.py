from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

BASE_ENV_PATH = CONFIG_DIR / "llm.env"
PROFILES_ENV_PATH = CONFIG_DIR / "llm_profiles.env"

RUNNER_VERSION = "ai_coach_judge_llm_runner_v0_8_claims_ru"
INPUT_VERSION = "ai_coach_judge_input_v0_8"
REPORT_SCHEMA_VERSION = "ai_coach_judge_report_v0_7_claims_ru"
DEFAULT_EXPECTED_ROUNDS = [2, 3, 4, 8, 9, 11, 14, 15, 16, 17, 19, 20]

REQUIRED_PERMISSION_TYPES = [
    "bad_duel_choice",
    "info_mistake",
    "mechanical_issue",
    "spacing_issue",
    "postplant_issue",
    "c4_safety_issue",
]


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


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def find_input_path(match_id: str, player: str) -> Path:
    candidates = [
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_v0_8_current.json",
        PROJECT_ROOT / "data" / "ai" / match_id / f"ai_coach_judge_input_{player}_v0_8.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No v0.8 AI coach judge input found. Build it first with scripts/build_ai_coach_judge_input_v0_8.ps1. Checked:\n"
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
        raw = input_payload.get("expected_rounds")
        if isinstance(raw, list):
            nums = []
            for item in raw:
                try:
                    nums.append(int(item))
                except Exception:
                    pass
            if nums:
                return nums

        raw_cards = input_payload.get("round_cards_for_model")
        if isinstance(raw_cards, list):
            nums = []
            for item in raw_cards:
                if isinstance(item, dict):
                    try:
                        nums.append(int(item.get("round_num")))
                    except Exception:
                        pass
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


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def compact(value: Any, limit_list: int = 16, limit_dict_keys: int = 60, depth: int = 5) -> Any:
    if depth <= 0:
        if isinstance(value, dict):
            return {"_truncated_depth": True, "keys": list(value.keys())[:8]}
        if isinstance(value, list):
            return {"_truncated_depth": True, "items_count": len(value)}
        return value

    if isinstance(value, list):
        out = [compact(x, limit_list, limit_dict_keys, depth - 1) for x in value[:limit_list]]
        if len(value) > limit_list:
            out.append({"_truncated_items": len(value) - limit_list})
        return out

    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= limit_dict_keys:
                out["_truncated_keys"] = len(value) - limit_dict_keys
                break
            out[str(k)] = compact(v, limit_list, limit_dict_keys, depth - 1)
        return out

    return value


def extract_permission_table(input_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    cards = input_payload.get("round_cards_for_model")
    if not isinstance(cards, list):
        return rows

    for card in cards:
        if not isinstance(card, dict):
            continue
        try:
            rn = int(card.get("round_num"))
        except Exception:
            continue

        tactical = card.get("tactical_context_v0_8") if isinstance(card.get("tactical_context_v0_8"), dict) else {}
        permissions = card.get("claim_permissions_v0_8") if isinstance(card.get("claim_permissions_v0_8"), dict) else {}
        summary = card.get("claim_permission_summary_v0_8") if isinstance(card.get("claim_permission_summary_v0_8"), dict) else {}

        row: Dict[str, Any] = {
            "round_num": rn,
            "phase": (tactical.get("round_phase") or {}).get("phase") if isinstance(tactical.get("round_phase"), dict) else None,
            "pressure": (tactical.get("pressure") or {}).get("pressure_level") if isinstance(tactical.get("pressure"), dict) else None,
            "player_task_hypothesis": (tactical.get("player_task") or {}).get("player_task_hypothesis") if isinstance(tactical.get("player_task"), dict) else None,
            "safe_fallback_confidence": (tactical.get("safe_fallback") or {}).get("safe_fallback_confidence") if isinstance(tactical.get("safe_fallback"), dict) else None,
            "trade_support_status": (tactical.get("trade_support") or {}).get("trade_support_status") if isinstance(tactical.get("trade_support"), dict) else None,
            "allowed_claim_types": summary.get("allowed_claim_types", []),
            "restricted_claim_types": summary.get("restricted_claim_types", []),
            "blocked_or_weak_claim_types": summary.get("blocked_or_weak_claim_types", []),
            "permissions": {},
        }

        for key in REQUIRED_PERMISSION_TYPES:
            raw = permissions.get(key)
            if isinstance(raw, dict):
                row["permissions"][key] = {
                    "status": raw.get("status"),
                    "max_claim_strength": raw.get("max_claim_strength"),
                    "reason": raw.get("reason"),
                }
            else:
                row["permissions"][key] = {
                    "status": "missing",
                    "max_claim_strength": "unsupported_avoided",
                    "reason": "missing permission entry",
                }

        rows.append(row)

    return rows


def summarize_permissions(permission_table: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {k: {} for k in REQUIRED_PERMISSION_TYPES}
    for row in permission_table:
        permissions = row.get("permissions") if isinstance(row.get("permissions"), dict) else {}
        for key in REQUIRED_PERMISSION_TYPES:
            status = str((permissions.get(key) or {}).get("status") or "missing")
            counts[key][status] = counts[key].get(status, 0) + 1
    return counts


def build_system_prompt() -> str:
    return f"""
Ты тренер-аналитик CS2 demo и строгий claim-based report generator.

Твоя задача: на основе grounded evidence сделать русский тренерский отчёт, используя v0.8 tactical context и claim permission layer.

ВАЖНО О ВЕРСИЯХ:
- source input version: {INPUT_VERSION}
- report schema version оставь совместимой: {REPORT_SCHEMA_VERSION}
- Это v0.8 по входным данным и правилам, но JSON schema отчёта совместима с v0.7 validators/renderer.

Главный принцип v0.8:
- Не пытайся быть "настоящим тренером" через догадки.
- Используй tactical_context_v0_8 только как evidence/proxy layer.
- Используй claim_permissions_v0_8 как binding contract.
- Если permission запрещает вывод, не формулируй его как user-facing факт.
- Если permission ограничивает max_claim_strength, не повышай силу claim выше лимита.

Обязательные правила permission layer:
- Перед каждым claim выбери permission_key:
  bad_duel_choice | info_mistake | mechanical_issue | spacing_issue | postplant_issue | c4_safety_issue | not_applicable
- ВАЖНО: claim_type и permission_key — разные поля.
- claim_type должен быть только одной из v0.7-категорий:
  mechanics | decision | info_state | enemy_intent | trade_spacing | round_impact | training
- Нельзя писать permission_key в claim_type. Например, postplant_issue, c4_safety_issue, mechanical_issue, spacing_issue, info_mistake, bad_duel_choice — НЕвалидные claim_type; они допустимы только в permission_gate.permission_key.
- В каждый claim добавь extra field permission_gate:
  {{
    "permission_key": "...",
    "permission_status": "allowed|allowed_limited|limited_or_blocked|blocked|missing|not_applicable",
    "max_claim_strength": "supported|limited|hypothesis|unsupported_avoided|not_applicable",
    "obeyed": true,
    "reason": "кратко почему claim допустим или почему вывод не усилен"
  }}
- Если permission_status=blocked, claim_strength должен быть unsupported_avoided, should_show_to_user=false, либо вообще не создавай такой claim.
- Если max_claim_strength=limited, claim_strength не может быть supported.
- Если max_claim_strength=hypothesis, claim_strength может быть только hypothesis или unsupported_avoided.
- bad_duel_choice запрещён, если permission не allowed. Нельзя писать как факт: плохой выбор дуэли, невыгодная дуэль, бесплатная смерть, можно было просто отойти, если safe fallback не доказан.
- spacing/trade можно формулировать limited, если evidence не доказывает реальную возможность размена.
- enemy_intent всегда гипотеза по observable events, а не знание намерений врагов.
- tactical task всегда гипотеза, а не доказанная роль игрока.

Ключевые ограничения evidence:
- Нет полноценного raycast/visibility proof.
- Нет voice comms.
- Info state — reconstructable prior info, а не гарантия, что игрок реально услышал/понял.
- Mechanics deep — supporting evidence, не абсолютный verdict.
- Safe fallback confidence — proxy, не доказательство безопасного отхода.
- Trade support confidence — proxy, не доказательство, что тиммейт реально мог разменять.

User-facing язык:
- Только русский.
- Без категоричных "точно", "обязан", "бесплатно умер", если это не доказано.
- Лучше честный limited claim, чем уверенный overclaim.

Верни только валидный JSON без Markdown.

Структура ответа обязательна:
{{
  "schema_version": "{REPORT_SCHEMA_VERSION}",
  "source_input_version": "{INPUT_VERSION}",
  "model_role": "core_claim_generator_v0_8_tactical_permissions",
  "language": "ru",
  "expected_rounds": [..],
  "rounds_coverage": {{
    "expected_count": 12,
    "actual_count": 12,
    "missing_rounds": [],
    "extra_rounds": []
  }},
  "tactical_context_usage": {{
    "used": true,
    "limitations": ["..."]
  }},
  "claim_permission_usage": {{
    "used": true,
    "rule": "blocked permissions are not shown as factual claims"
  }},
  "match_summary": "...",
  "top_priorities": [
    {{
      "priority_id": "p01",
      "title": "...",
      "why_it_matters": "...",
      "supporting_rounds": [2, 8],
      "claims_refs": ["r2_decision_01"],
      "training_focus": "..."
    }}
  ],
  "round_reviews": [
    {{
      "round_num": 17,
      "round_result": "win|loss|unknown",
      "main_takeaway": "...",
      "claims": [
        {{
          "claim_id": "r17_mechanics_01",
          "claim_type": "mechanics|decision|info_state|enemy_intent|trade_spacing|round_impact|training",
          "claim_text": "...",
          "claim_strength": "supported|limited|hypothesis|unsupported_avoided",
          "evidence_refs": ["..."],
          "evidence_summary": ["..."],
          "limitations": ["..."],
          "alternative_explanations": ["..."],
          "actionability": "...",
          "should_show_to_user": true,
          "permission_gate": {{
            "permission_key": "mechanical_issue",
            "permission_status": "allowed",
            "max_claim_strength": "supported",
            "obeyed": true,
            "reason": "..."
          }}
        }}
      ],
      "training_note": "..."
    }}
  ],
  "training_plan": {{
    "short_term": [],
    "medium_term": [],
    "review_method": "..."
  }},
  "uncertainties": [
    {{
      "topic": "...",
      "why_uncertain": "...",
      "what_evidence_is_missing": "..."
    }}
  ]
}}
""".strip()


def build_user_prompt(
    match_id: str,
    player: str,
    expected_rounds: List[int],
    permission_table: List[Dict[str, Any]],
    evidence_text: str,
) -> str:
    expected_count = len(expected_rounds)
    permission_text = json.dumps(permission_table, ensure_ascii=False, indent=2)

    return f"""
Матч: {match_id}
Игрок: {player}
Ожидаемые review rounds: {expected_rounds}
Ожидаемое количество round_reviews: {expected_count}

Сделай claim-based русский отчёт на основе v0.8 input.

СНАЧАЛА ПРОЧИТАЙ ЭТУ PERMISSION TABLE. Это краткий binding contract по раундам:
{permission_text}

Жёсткие требования к coverage:
- round_reviews должен содержать каждый round из expected_rounds.
- Нельзя пропускать раунды из expected_rounds.
- Нельзя добавлять лишние раунды в round_reviews.
- rounds_coverage должен честно отражать expected/actual/missing/extra.

Жёсткие требования к claims:
- В каждом round_review должен быть непустой claims.
- Каждый claim должен быть самостоятельным проверяемым утверждением.
- Каждый claim должен иметь permission_gate.
- claim_type должен быть только: mechanics, decision, info_state, enemy_intent, trade_spacing, round_impact, training.
- permission_gate должен ссылаться на реальный permission_key, если claim относится к одному из контролируемых типов.
- Не смешивай claim_type с permission_key. postplant_issue/c4_safety_issue/etc. должны быть только в permission_gate.permission_key.
- claim_strength:
  - supported = evidence прямо поддерживает вывод и permission разрешает supported;
  - limited = evidence указывает на проблему/паттерн, но есть важные ограничения или permission cap;
  - hypothesis = вероятная интерпретация, но не факт;
  - unsupported_avoided = потенциальный вывод, который НЕ надо показывать как факт.
- Для supported claims evidence_refs не должен быть пустым.
- limitations должен быть списком даже если ограничений мало.
- alternative_explanations должен быть списком.
- actionability должен объяснять, что игроку делать практически.

Требование к качеству:
- Не делай вывод сильнее, чем позволяет evidence и claim_permissions_v0_8.
- Если tactical_context_v0_8 говорит safe_fallback low/unknown, не делай bad_duel_choice как факт.
- Если claim permission blocked, либо не создавай claim, либо создай unsupported_avoided с should_show_to_user=false.
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


def maybe_backup(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(path.name + f".bak_v0_8_{stamp}")
    shutil.copy2(path, backup)
    return rel(backup)


def write_compat_v07_outputs(report_txt_path: Path, report_json_path: Path, match_id: str, player: str) -> Dict[str, Any]:
    output_dir = PROJECT_ROOT / "data" / "ai" / match_id
    compat_txt = output_dir / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.txt"
    compat_json = output_dir / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.json"

    backups = {
        "txt": maybe_backup(compat_txt),
        "json": maybe_backup(compat_json),
    }

    if report_txt_path.exists():
        shutil.copy2(report_txt_path, compat_txt)
    if report_json_path.exists():
        shutil.copy2(report_json_path, compat_json)

    return {
        "compat_report_txt": rel(compat_txt),
        "compat_report_json": rel(compat_json),
        "backups": backups,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    parser.add_argument("--max-tokens", type=int, default=18000)
    parser.add_argument("--temperature", type=float, default=0.12)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--write-compat-v07", action="store_true")
    args = parser.parse_args()

    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)

    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")
    model = profiles_env.get("CS_DEMO_COACH_MODEL_CORE", "").strip() or base_env.get("CS_DEMO_COACH_LLM_MODEL", "")

    input_path = find_input_path(args.match_id, args.player)
    input_payload = load_json(input_path)
    expected_rounds = infer_expected_rounds(input_payload)

    meta = input_payload.get("meta") if isinstance(input_payload, dict) else {}
    input_version = (meta or {}).get("version") if isinstance(meta, dict) else None

    permission_table = extract_permission_table(input_payload if isinstance(input_payload, dict) else {})
    permission_counts = summarize_permissions(permission_table)

    evidence_text = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(args.match_id, args.player, expected_rounds, permission_table, evidence_text)

    estimated_input_tokens_rough = int((len(system_prompt) + len(user_prompt)) / 3.7)

    output_dir = PROJECT_ROOT / "data" / "ai" / args.match_id
    report_txt_path = output_dir / f"ai_coach_judge_llm_report_{args.player}_v0_8_claims_ru.txt"
    report_json_path = output_dir / f"ai_coach_judge_llm_report_{args.player}_v0_8_claims_ru.json"
    result_json_path = output_dir / f"ai_coach_judge_llm_result_{args.player}_v0_8_claims_ru.json"

    common = {
        "runner": RUNNER_VERSION,
        "mode": args.mode,
        "match_id": args.match_id,
        "player": args.player,
        "model": model,
        "input_path": rel(input_path),
        "input_version": input_version,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "input_chars": len(evidence_text),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "estimated_input_tokens_rough": estimated_input_tokens_rough,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "expected_rounds": expected_rounds,
        "permission_counts": permission_counts,
        "output_paths": {
            "report_txt": rel(report_txt_path),
            "report_json": rel(report_json_path),
            "result_json": rel(result_json_path),
        },
        "write_compat_v07": bool(args.write_compat_v07),
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
    if input_version != INPUT_VERSION:
        check_issues.append({"severity": "error", "code": "wrong_input_version", "message": f"Expected {INPUT_VERSION}, got {input_version}."})
    if len(permission_table) != len(expected_rounds):
        check_issues.append({"severity": "error", "code": "permission_table_round_count_mismatch", "message": f"Expected {len(expected_rounds)} permission rows, got {len(permission_table)}."})
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
        print(json.dumps({"status": "fail", **common, "issues": check_issues}, ensure_ascii=False, indent=2))
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
        if isinstance(parsed_report, dict):
            parsed_report.setdefault("schema_version", REPORT_SCHEMA_VERSION)
            parsed_report.setdefault("source_input_version", INPUT_VERSION)
            parsed_report.setdefault("model_role", "core_claim_generator_v0_8_tactical_permissions")
        write_json(report_json_path, parsed_report)

    compat_outputs = None
    if parsed_report is not None and args.write_compat_v07:
        compat_outputs = write_compat_v07_outputs(report_txt_path, report_json_path, args.match_id, args.player)

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
            "report_txt": rel(report_txt_path),
            "report_json": rel(report_json_path) if parsed_report is not None else None,
            "result_json": rel(result_json_path),
            "compat_outputs": compat_outputs,
        },
    }

    write_json(result_json_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if parsed_report is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
