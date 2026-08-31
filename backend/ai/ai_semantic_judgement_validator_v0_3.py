from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def load_json(path: Path) -> Any:
    return json.loads(read_text(path))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}

    if path.exists():
        for raw in read_text(path).splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

    for k, v in os.environ.items():
        if k.startswith("CS_DEMO_COACH_LLM_"):
            env[k] = v

    return env


def endpoint_from_base(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""
    msg = choices[0].get("message", {})
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content)


def call_once(endpoint: str, api_key: str, payload: dict[str, Any], timeout_sec: int):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw), None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, None, raw
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


def call_with_retries(endpoint: str, api_key: str, payload: dict[str, Any], timeout_sec: int, retries: int):
    attempts = []
    last_status = 0
    last_response = None
    last_error = None

    for attempt in range(1, retries + 2):
        status_code, response, error = call_once(endpoint, api_key, payload, timeout_sec)

        attempts.append({
            "attempt": attempt,
            "status_code": status_code,
            "ok": response is not None and 200 <= status_code < 300,
            "retryable": status_code in RETRYABLE_STATUS_CODES,
            "error_preview": str(error)[:500] if error else None,
        })

        last_status = status_code
        last_response = response
        last_error = error

        if response is not None and 200 <= status_code < 300:
            return status_code, response, error, attempts

        if status_code not in RETRYABLE_STATUS_CODES:
            return status_code, response, error, attempts

        if attempt <= retries:
            time.sleep(min(3 * attempt, 12))

    return last_status, last_response, last_error, attempts


def load_optional_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return load_json(path)
    except Exception:
        return None


def keep_compact_object(obj: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return "..."

    if isinstance(obj, dict):
        priority = [
            "round_num", "tick", "event_tick", "focus_event_tick",
            "event_type", "focus_event_kind", "event_id",
            "player", "player_name", "attacker", "victim", "opponent", "enemy",
            "combat_role", "combat_place", "place", "area", "site", "bombsite",
            "round_result", "decision_label", "decision_labels", "decision_confidence",
            "speed", "speed_band", "yaw_error_band", "yaw_error_abs_deg_approx",
            "shots_after_event", "shots_in_window", "first_shot_delay_ms_assumed",
            "root_cause", "deep_label", "deep_confidence", "deep_flags",
            "opponent_info_context", "info_age_sec", "opponent_last_known",
            "likely_enemy_plan", "plan_family", "confidence", "evidence",
            "interpretation", "limitations", "summary", "notes",
            "trade", "spacing", "nearest_teammate", "teammate_distance",
            "quality_flags", "reasoning_quality_flags"
        ]
        out = {}
        for k in priority:
            if k in obj:
                out[k] = keep_compact_object(obj[k], depth + 1)
        for k, v in obj.items():
            if k not in out and len(out) < 24:
                out[k] = keep_compact_object(v, depth + 1)
        return out

    if isinstance(obj, list):
        return [keep_compact_object(x, depth + 1) for x in obj[:10]]

    if isinstance(obj, str) and len(obj) > 350:
        return obj[:350] + "...[truncated]"

    return obj


def object_score(item: dict[str, Any]) -> int:
    text = json.dumps(item, ensure_ascii=False).lower()
    score = 0
    for term in [
        "death", "kill", "damage", "trade", "spacing", "teammate",
        "bad_duel", "fallback", "escape", "visibility", "flash",
        "first_shot_delay", "speed", "yaw", "mechanics", "decision",
        "info_state", "enemy_intent", "plant", "bombsite"
    ]:
        if term in text:
            score += 2
    if "round 14" in text or '"round_num": 14' in text:
        score += 2
    if "round 17" in text or '"round_num": 17' in text:
        score += 2
    return score


def slim_evidence_for_production_judge(rich: dict[str, Any], per_round_objects: int = 8) -> dict[str, Any]:
    cards = rich.get("round_cards_for_model", [])
    slim_cards = []

    if not isinstance(cards, list):
        cards = []

    for card in cards:
        if not isinstance(card, dict):
            continue

        expanded = card.get("expanded_round_evidence", {})
        objects = expanded.get("objects", []) if isinstance(expanded, dict) else []
        if not isinstance(objects, list):
            objects = []

        sorted_objects = sorted(objects, key=object_score, reverse=True)
        selected_objects = []

        for item in sorted_objects[:per_round_objects]:
            if not isinstance(item, dict):
                continue
            selected_objects.append({
                "source": item.get("source"),
                "round_num": item.get("round_num"),
                "score": item.get("score"),
                "object": keep_compact_object(item.get("object")),
            })

        slim_card = {
            "round_num": card.get("round_num"),
            "round_result": card.get("round_result"),
            "decision_label": card.get("decision_label"),
            "decision_confidence": card.get("decision_confidence"),
            "review_weight": card.get("review_weight"),
            "round_card_label": card.get("round_card_label"),
            "enemy_intent": keep_compact_object(card.get("enemy_intent")),
            "info_state": keep_compact_object(card.get("info_state")),
            "mechanics_deep": keep_compact_object(card.get("mechanics_deep")),
            "coach_reasoning": keep_compact_object(card.get("coach_reasoning")),
            "evidence_limitations": card.get("evidence_limitations"),
            "claim_guardrails": card.get("claim_guardrails"),
            "expanded_round_evidence_summary": {
                "objects_total_available": expanded.get("objects_total_available") if isinstance(expanded, dict) else None,
                "objects_selected_for_judge": len(selected_objects),
                "objects": selected_objects,
            },
        }

        slim_cards.append(slim_card)

    return {
        "version": rich.get("version"),
        "match_id": rich.get("match_id"),
        "player": rich.get("player"),
        "review_rounds": rich.get("review_rounds"),
        "global_guardrails": rich.get("global_guardrails"),
        "source_stats": rich.get("source_stats"),
        "evidence_pack_note": (
            "This is a production semantic judge evidence pack. It is compacted structurally, "
            "not by keyword-only judgement. Use it to verify report claims against available evidence and limitations."
        ),
        "round_cards_for_model": slim_cards,
    }


def build_judge_input(match_id: str, player: str, report_version: str, per_round_objects: int) -> dict[str, Any]:
    report_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_{report_version}.json")
    rich_path = Path(f"data/ai/{match_id}/ai_coach_judge_input_rich_guarded_current.json")
    regex_v02_path = Path(f"data/validation/{match_id}/ai_judgement_validation_{player}_{report_version}_v0_2.json")

    report = load_json(report_path)
    rich = load_json(rich_path)
    regex_signals = load_optional_json(regex_v02_path)

    return {
        "semantic_validator_input_version": "ai_semantic_judgement_validator_input_v0_3_production_compact",
        "judge_mode": "production",
        "task": "Semantically validate whether a CS2 coaching report is grounded, useful, and safe to show.",
        "match_id": match_id,
        "player": player,
        "report_version": report_version,
        "project_rules": [
            "Evaluate by meaning, not keyword matching.",
            "Regex warnings are weak signals only.",
            "The report may safely mention risky terms when saying evidence does not support them.",
            "enemy_intent is a hypothesis, not truth.",
            "info_state is reconstructable prior demo info, not proof of actual player awareness or voice comms.",
            "No hard visibility, flash, or reaction verdicts without visibility/raycast/flash evidence.",
            "Trade, spacing, death order, and bad duel choice claims require explicit evidence.",
            "A good report must remain useful; do not reward empty over-cautious reports.",
            "Production mode must not rely on manual calibration notes.",
        ],
        "judge_questions": [
            "Is the report structurally usable JSON?",
            "Does it make unsupported claims?",
            "Does it properly downgrade uncertain claims to limited?",
            "Does it avoid treating enemy intent as fact?",
            "Does it avoid hard visibility/flash/reaction claims without evidence?",
            "Are trade/spacing/death-order claims sufficiently grounded?",
            "Is the coaching advice concrete and useful?",
            "Can this report be shown to a user as a product output?",
            "What should be fixed next in generator, evidence layer, or renderer?"
        ],
        "coach_report_to_validate": report,
        "evidence_input_used_by_report": slim_evidence_for_production_judge(rich, per_round_objects=per_round_objects),
        "regex_validator_v0_2_signals": regex_signals,
        "manual_calibration_notes": None,
        "production_note": "No manual demo review is available in production mode.",
    }


def build_messages(judge_input: dict[str, Any]) -> list[dict[str, str]]:
    system = """
You are a semantic QA judge for a CS2 demo coaching system.

Judge mode: production.

Evaluate by MEANING, not keyword matching.

Important:
- Regex warnings are weak signals only.
- "does not prove bad duel choice" is NOT a bad-duel-choice claim.
- "lack of raycast/visibility data" is NOT a visibility overclaim.
- Do not invent new gameplay facts.
- Judge consistency, grounding, uncertainty handling, and usefulness.
- A report can be useful with limited evidence if claim_strength and caveats are honest.
- In production mode, do not rely on manual calibration notes.

Return ONLY valid JSON. No markdown.

Required output schema:
{
  "schema_version": "ai_semantic_judgement_validation_v0_3",
  "judge_mode": "production",
  "overall_status": "pass|warn|fail",
  "summary": "...",
  "score": {
    "grounding": 0,
    "usefulness": 0,
    "uncertainty_handling": 0,
    "schema_quality": 0,
    "production_readiness": 0
  },
  "regex_warnings_assessment": [
    {
      "original_warning_code": "...",
      "semantic_status": "confirmed_issue|false_positive|unclear",
      "reason": "..."
    }
  ],
  "critical_issues": [],
  "warnings": [],
  "false_positives": [],
  "round_assessments": [
    {
      "round_num": 0,
      "status": "ok|warn|fail",
      "grounding_notes": [],
      "usefulness_notes": [],
      "unsupported_or_overconfident_claims": []
    }
  ],
  "generator_fix_recommendations": [],
  "evidence_layer_fix_recommendations": [],
  "renderer_fix_recommendations": [],
  "final_acceptance": {
    "can_use_report_for_human_review": true,
    "can_use_report_as_final_product_output": false,
    "reason": "..."
  }
}
""".strip()

    user = json.dumps(judge_input, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--match-id", default="example_match")
    p.add_argument("--player", default="Player")
    p.add_argument("--report-version", default="v0_5")
    p.add_argument("--mode", choices=["build-input", "check", "llm"], default="check")
    p.add_argument("--per-round-objects", type=int, default=8)
    p.add_argument("--retries", type=int, default=3)
    args = p.parse_args()

    match_id = args.match_id
    player = args.player
    report_version = args.report_version

    judge_input = build_judge_input(match_id, player, report_version, per_round_objects=args.per_round_objects)
    messages = build_messages(judge_input)

    env_path = Path("config/llm.env")
    env = load_env_file(env_path)

    base_url = env.get("CS_DEMO_COACH_LLM_JUDGE_BASE_URL") or env.get("CS_DEMO_COACH_LLM_BASE_URL")
    api_key = env.get("CS_DEMO_COACH_LLM_JUDGE_API_KEY") or env.get("CS_DEMO_COACH_LLM_API_KEY")
    model = env.get("CS_DEMO_COACH_LLM_JUDGE_MODEL") or env.get("CS_DEMO_COACH_LLM_MODEL")

    missing = []
    if not base_url:
        missing.append("CS_DEMO_COACH_LLM_JUDGE_BASE_URL or CS_DEMO_COACH_LLM_BASE_URL")
    if not api_key:
        missing.append("CS_DEMO_COACH_LLM_JUDGE_API_KEY or CS_DEMO_COACH_LLM_API_KEY")
    if not model:
        missing.append("CS_DEMO_COACH_LLM_JUDGE_MODEL or CS_DEMO_COACH_LLM_MODEL")

    endpoint = endpoint_from_base(base_url) if base_url else None

    max_tokens = int(env.get("CS_DEMO_COACH_LLM_JUDGE_MAX_TOKENS", "9000") or "9000")
    timeout_sec = int(env.get("CS_DEMO_COACH_LLM_JUDGE_TIMEOUT_SEC", env.get("CS_DEMO_COACH_LLM_TIMEOUT_SEC", "1800")) or "1800")
    temperature = float(env.get("CS_DEMO_COACH_LLM_JUDGE_TEMPERATURE", "0.0") or "0.0")

    out_dir = Path(f"data/validation/{match_id}")
    stem = f"{player}_{report_version}_production_semantic_v0_3"

    input_path = out_dir / f"ai_semantic_judgement_input_{stem}.json"
    preview_path = out_dir / f"ai_semantic_judgement_request_preview_{stem}.json"
    prompt_path = out_dir / f"ai_semantic_judgement_prompt_preview_{stem}.txt"

    write_json(input_path, judge_input)
    prompt_path.write_text(messages[0]["content"] + "\n\n=== USER JSON ===\n\n" + messages[1]["content"], encoding="utf-8")

    preview = {
        "status": "preview",
        "validator": "ai_semantic_judgement_validator_v0_3",
        "judge_mode": "production",
        "mode": args.mode,
        "match_id": match_id,
        "player": player,
        "report_version": report_version,
        "endpoint": endpoint,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_sec": timeout_sec,
        "retries": args.retries,
        "per_round_objects": args.per_round_objects,
        "messages_count": len(messages),
        "system_chars": len(messages[0]["content"]),
        "user_chars": len(messages[1]["content"]),
        "estimated_input_tokens_rough": round((len(messages[0]["content"]) + len(messages[1]["content"])) / 3.7),
        "created": {
            "judge_input": str(input_path),
            "request_preview": str(preview_path),
            "prompt_preview": str(prompt_path),
        }
    }

    write_json(preview_path, preview)

    if args.mode in {"build-input", "check"}:
        if missing:
            print(json.dumps({
                "status": "config_missing",
                "missing_env": missing,
                "request_preview": preview,
            }, ensure_ascii=False, indent=2))
            sys.exit(2)

        print(json.dumps({
            "status": "ok_ready_for_semantic_judge" if args.mode == "check" else "ok",
            "validator": "ai_semantic_judgement_validator_v0_3",
            "judge_mode": "production",
            "request_preview": preview,
        }, ensure_ascii=False, indent=2))
        return

    if missing:
        print(json.dumps({
            "status": "config_missing",
            "missing_env": missing,
            "request_preview": preview,
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    started = time.time()
    status_code, response, error, attempts = call_with_retries(endpoint, api_key, payload, timeout_sec, retries=args.retries)
    elapsed_sec = round(time.time() - started, 3)

    result_path = out_dir / f"ai_semantic_judgement_result_{stem}.json"
    verdict_path = out_dir / f"ai_semantic_judgement_verdict_{stem}.json"
    verdict_txt_path = out_dir / f"ai_semantic_judgement_verdict_{stem}.txt"
    status_path = out_dir / f"ai_semantic_judgement_status_{stem}.json"

    call_ok = response is not None and 200 <= status_code < 300
    text = ""
    json_parse_ok = False
    json_parse_error = None
    verdict = None

    if call_ok and response is not None:
        write_json(result_path, response)
        text = extract_text(response)
        verdict_txt_path.write_text(text, encoding="utf-8")
        clean = strip_code_fences(text)
        try:
            verdict = json.loads(clean)
            json_parse_ok = True
            write_json(verdict_path, verdict)
        except Exception as e:
            json_parse_error = f"{type(e).__name__}: {e}"
            verdict_path.write_text(clean, encoding="utf-8")
    else:
        result_path.write_text(error or "unknown error", encoding="utf-8")

    status = {
        "status": "ok" if call_ok else "error",
        "validator": "ai_semantic_judgement_validator_v0_3",
        "judge_mode": "production",
        "mode": args.mode,
        "match_id": match_id,
        "player": player,
        "report_version": report_version,
        "elapsed_sec": elapsed_sec,
        "request_preview": preview,
        "call": {
            "ok": call_ok,
            "status_code": status_code,
            "error": error,
            "attempts": attempts,
        },
        "text_chars": len(text),
        "json_parse": {
            "ok": json_parse_ok,
            "error": json_parse_error,
        },
        "semantic_status": verdict.get("overall_status") if isinstance(verdict, dict) else None,
        "created": {
            "status_json": str(status_path),
            "judge_input": str(input_path),
            "request_preview": str(preview_path),
            "prompt_preview": str(prompt_path),
            "result_json": str(result_path),
            "verdict_json": str(verdict_path),
            "verdict_txt": str(verdict_txt_path),
        }
    }

    write_json(status_path, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
