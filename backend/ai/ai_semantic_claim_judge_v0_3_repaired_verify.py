from __future__ import annotations

import argparse
import hashlib
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


ROUND_KEYS = {
    "round",
    "round_num",
    "round_number",
    "roundnum",
    "round_id",
}


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


def to_int_list(raw: str) -> List[int]:
    result: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            result.append(int(part))
    return result


def find_evidence_path(match_id: str) -> Path:
    candidates = [
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_rich_guarded_current.json",
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_current.json",
        PROJECT_ROOT / "data" / "ai" / match_id / "ai_coach_judge_input_compact_current.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No evidence input found. Checked:\n"
        + "\n".join(str(path) for path in candidates)
    )


def default_repaired_report_path(match_id: str, player: str) -> Path:
    repaired = (
        PROJECT_ROOT
        / "data"
        / "ai"
        / match_id
        / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru_repaired_v0_1.json"
    )

    if repaired.exists():
        return repaired

    return (
        PROJECT_ROOT
        / "data"
        / "ai"
        / match_id
        / f"ai_coach_judge_llm_report_{player}_v0_7_claims_ru.json"
    )


def optional_json(path: Path) -> Optional[Any]:
    if path.exists():
        return load_json(path)
    return None


def direct_round_num(obj: Dict[str, Any]) -> Optional[int]:
    for key, value in obj.items():
        key_l = str(key).lower()
        if key_l in ROUND_KEYS:
            try:
                num = int(value)
                if 1 <= num <= 100:
                    return num
            except Exception:
                return None
    return None


def compact_value(value: Any, depth: int = 0, max_depth: int = 3, max_list_items: int = 8) -> Any:
    if depth > max_depth:
        return "<truncated_depth>"

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        compacted = []
        for item in value[:max_list_items]:
            compacted.append(compact_value(item, depth + 1, max_depth, max_list_items))
        if len(value) > max_list_items:
            compacted.append(f"<truncated_list_items:{len(value) - max_list_items}>")
        return compacted

    if isinstance(value, dict):
        out: Dict[str, Any] = {}

        priority_keys = [
            "round",
            "round_num",
            "round_number",
            "tick",
            "event_tick",
            "player",
            "player_name",
            "attacker",
            "victim",
            "enemy",
            "opponent",
            "weapon",
            "active_weapon",
            "active_weapon_name",
            "speed",
            "speed_band",
            "yaw_error_abs",
            "first_shot_delay_ms",
            "shots_after_event",
            "claim_id",
            "claim_type",
            "claim_strength",
            "label",
            "decision_label",
            "plan",
            "confidence",
            "info_context",
            "age_sec",
            "limitations",
            "flags",
            "quality_flags",
            "evidence_refs",
            "evidence_summary",
            "source",
            "source_file",
        ]

        for key in priority_keys:
            if key in value:
                out[key] = compact_value(value[key], depth + 1, max_depth, max_list_items)

        # Keep a limited set of additional scalar fields.
        for key, child in value.items():
            if key in out:
                continue
            if isinstance(child, (str, int, float, bool)) or child is None:
                out[key] = child
            if len(out) >= 35:
                break

        return out

    return str(value)


def collect_compact_round_objects(
    payload: Any,
    target_rounds: List[int],
    max_objects: int = 80,
) -> List[Any]:
    targets = set(target_rounds)
    found: List[Any] = []
    seen: set[str] = set()

    def add_obj(obj: Dict[str, Any]) -> None:
        compacted = compact_value(obj)
        dumped = json.dumps(compacted, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(dumped.encode("utf-8")).hexdigest()

        if digest in seen:
            return

        seen.add(digest)
        found.append(compacted)

    def walk(obj: Any) -> None:
        if len(found) >= max_objects:
            return

        if isinstance(obj, dict):
            rn = direct_round_num(obj)
            if rn in targets:
                add_obj(obj)
                return

            for child in obj.values():
                if isinstance(child, (dict, list)):
                    walk(child)
                    if len(found) >= max_objects:
                        return

        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    walk(item)
                    if len(found) >= max_objects:
                        return

    walk(payload)
    return found


def filter_report_rounds(report: Dict[str, Any], target_rounds: List[int]) -> Dict[str, Any]:
    return {
        "schema_version": report.get("schema_version"),
        "language": report.get("language"),
        "expected_rounds": report.get("expected_rounds"),
        "rounds_coverage": report.get("rounds_coverage"),
        "round_reviews": [
            rr for rr in report.get("round_reviews", [])
            if isinstance(rr, dict) and int(rr.get("round_num", -999)) in target_rounds
        ],
        "training_plan": report.get("training_plan"),
        "uncertainties": report.get("uncertainties"),
    }


def build_system_prompt() -> str:
    return """
Ты final targeted semantic verifier для repaired CS2 demo coach report.

Проверяешь только исправленный отчёт после repair-pass.
Твоя задача:
- подтвердить, что конкретные repair-проблемы устранены;
- не искать новые проблемы вне target rounds;
- не запрещать фразы;
- оценивать смысл и доказанность.

Особенно проверь:
1. ROUND 17 main_takeaway:
   - должен критиковать подтверждённую механику;
   - не должен утверждать "плохой выбор дуэли", "невыгодная дуэль" или аналогичный decision verdict как факт без safe fallback evidence.
2. ROUND 14 actionability:
   - должен быть контекстным;
   - не должен звучать как абсолютное правило "никогда" без учёта ограничений.

Верни только валидный JSON без Markdown.

Схема:
{
  "schema_version": "ai_semantic_claim_judge_result_v0_3_repaired_verify",
  "judge_model_role": "repaired_targeted_verifier",
  "language": "ru",
  "overall_status": "pass|warn|fail",
  "can_show_to_user_without_repair": true,
  "summary": "...",
  "target_rounds": [14,17],
  "resolved_previous_issues": [
    {
      "round_num": 17,
      "previous_issue": "...",
      "resolved": true,
      "assessment": "..."
    }
  ],
  "remaining_findings": [
    {
      "finding_id": "rv001",
      "severity": "warning|error",
      "round_num": 17,
      "target_type": "main_takeaway|claim|actionability|training_note",
      "claim_id": "r17_decision_01|null",
      "issue_type": "unsupported|overconfident|too_categorical|missing_limitation|evidence_mismatch",
      "problem": "...",
      "recommended_action": "keep|repair_again|send_to_full_quality"
    }
  ],
  "final_recommendation": {
    "use_repaired_report": true,
    "needs_more_repair": false,
    "notes": "..."
  }
}
""".strip()


def build_user_prompt(
    match_id: str,
    player: str,
    target_rounds: List[int],
    evidence_pack: Dict[str, Any],
    repaired_report_focus: Dict[str, Any],
    targeted_judge_v0_2: Optional[Any],
    repair_result: Optional[Any],
) -> str:
    return f"""
Матч: {match_id}
Игрок: {player}
Target rounds: {target_rounds}

PREVIOUS TARGETED JUDGE:
{json.dumps(targeted_judge_v0_2, ensure_ascii=False, separators=(",", ":"))}

REPAIR RESULT:
{json.dumps(repair_result, ensure_ascii=False, separators=(",", ":"))}

COMPACT TARGETED EVIDENCE:
{json.dumps(evidence_pack, ensure_ascii=False, separators=(",", ":"))}

REPAIRED REPORT FOCUS:
{json.dumps(repaired_report_focus, ensure_ascii=False, separators=(",", ":"))}

Проверь, устранены ли предыдущие проблемы.
Не требуй нового repair, если прошлые issue действительно сняты и новых критических проблем именно в target fields нет.
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
    parser.add_argument("--target-rounds", default="14,17")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    args = parser.parse_args()

    target_rounds = to_int_list(args.target_rounds)

    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)

    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")
    model = profiles_env.get("CS_DEMO_COACH_MODEL_SEMANTIC_JUDGE", "").strip()

    evidence_path = find_evidence_path(args.match_id)

    if args.report_path:
        report_path = Path(args.report_path)
        if not report_path.is_absolute():
            report_path = PROJECT_ROOT / report_path
    else:
        report_path = default_repaired_report_path(args.match_id, args.player)

    evidence_payload = load_json(evidence_path)
    repaired_report = load_json(report_path)

    targeted_judge_v0_2_path = (
        PROJECT_ROOT
        / "data"
        / "ai"
        / args.match_id
        / f"ai_semantic_claim_judge_{args.player}_v0_2_targeted_r2_8_14_17.json"
    )

    repair_result_path = (
        PROJECT_ROOT
        / "data"
        / "ai"
        / args.match_id
        / f"ai_claim_report_repair_result_{args.player}_v0_1.json"
    )

    targeted_judge_v0_2 = optional_json(targeted_judge_v0_2_path)
    repair_result = optional_json(repair_result_path)

    compact_objects = collect_compact_round_objects(evidence_payload, target_rounds)

    evidence_pack = {
        "target_rounds": target_rounds,
        "compact_objects_count": len(compact_objects),
        "compact_objects": compact_objects,
        "limitations": [
            "This is a compact targeted evidence pack.",
            "If safe fallback/voice comms/raycast/visibility are not present here, verifier must treat them as missing.",
        ],
    }

    repaired_report_focus = filter_report_rounds(repaired_report, target_rounds)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        match_id=args.match_id,
        player=args.player,
        target_rounds=target_rounds,
        evidence_pack=evidence_pack,
        repaired_report_focus=repaired_report_focus,
        targeted_judge_v0_2=targeted_judge_v0_2,
        repair_result=repair_result,
    )

    estimated_input_tokens_rough = int((len(system_prompt) + len(user_prompt)) / 3.7)

    output_dir = PROJECT_ROOT / "data" / "ai" / args.match_id
    suffix = "_".join(str(x) for x in target_rounds)

    evidence_pack_path = output_dir / f"ai_semantic_claim_judge_evidence_pack_{args.player}_v0_3_repaired_r{suffix}.json"
    judge_txt_path = output_dir / f"ai_semantic_claim_judge_{args.player}_v0_3_repaired_r{suffix}.txt"
    judge_json_path = output_dir / f"ai_semantic_claim_judge_{args.player}_v0_3_repaired_r{suffix}.json"
    judge_result_path = output_dir / f"ai_semantic_claim_judge_result_{args.player}_v0_3_repaired_r{suffix}.json"

    write_json(evidence_pack_path, evidence_pack)

    common = {
        "judge": "ai_semantic_claim_judge_v0_3_repaired_verify",
        "mode": args.mode,
        "match_id": args.match_id,
        "player": args.player,
        "target_rounds": target_rounds,
        "model": model,
        "evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
        "evidence_pack_path": str(evidence_pack_path.relative_to(PROJECT_ROOT)),
        "compact_objects_count": len(compact_objects),
        "report_path": str(report_path.relative_to(PROJECT_ROOT)),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "estimated_input_tokens_rough": estimated_input_tokens_rough,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
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
    if model != "gemini-2.5-flash":
        issues.append({"severity": "warning", "code": "unexpected_semantic_judge_model", "message": f"Expected gemini-2.5-flash, got {model}."})
    if estimated_input_tokens_rough + args.max_tokens > 245000:
        issues.append({
            "severity": "warning",
            "code": "near_tpm_limit",
            "message": f"Estimated tokens {estimated_input_tokens_rough + args.max_tokens} is close to 250K TPM.",
        })

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
        write_json(judge_result_path, result)
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
        write_json(judge_result_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    model_text = extract_message_text(str(call_result["raw"]))
    parsed_judge, parse_error = extract_json_from_text(model_text)

    judge_txt_path.write_text(model_text, encoding="utf-8")

    if parsed_judge is not None:
        write_json(judge_json_path, parsed_judge)

    result = {
        "status": "ok" if parsed_judge is not None else "warn",
        **common,
        "call": {
            "ok": True,
            "status_code": call_result.get("status_code"),
            "elapsed_sec": call_result.get("elapsed_sec"),
        },
        "text_chars": len(model_text),
        "json_parse": {
            "ok": parsed_judge is not None,
            "error": parse_error,
        },
        "created": {
            "judge_txt": str(judge_txt_path.relative_to(PROJECT_ROOT)),
            "judge_json": str(judge_json_path.relative_to(PROJECT_ROOT)) if parsed_judge is not None else None,
            "judge_result": str(judge_result_path.relative_to(PROJECT_ROOT)),
        },
    }

    write_json(judge_result_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if parsed_judge is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
