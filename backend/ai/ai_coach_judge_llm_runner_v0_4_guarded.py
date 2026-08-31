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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read_text(path))


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


def walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def has_key_deep(obj: Any, keys: list[str]) -> bool:
    for d in walk(obj):
        if isinstance(d, dict):
            for k in keys:
                if k in d:
                    return True
    return False


def round_limitations(card: dict[str, Any]) -> list[str]:
    limitations: list[str] = []

    mechanics = card.get("mechanics_deep", {})
    info = card.get("info_state", {})

    if isinstance(mechanics, dict):
        events_count = mechanics.get("events_count", 0)
        if isinstance(events_count, int) and events_count <= 1:
            limitations.append("mechanics_deep_has_only_one_or_zero_events_do_not_generalize_whole_round")

        top_sample = mechanics.get("top_events_sample")
        if isinstance(top_sample, list) and len(top_sample) <= 1:
            limitations.append("only_one_top_mechanics_event_sample")

        flags = mechanics.get("deep_flag_counts", {})
        if isinstance(flags, dict) and flags.get("visibility_flash_context_missing_or_limited", 0) > 0:
            limitations.append("visibility_flash_context_limited_no_hard_visibility_or_reaction_verdict")

    if isinstance(info, dict):
        focus_count = info.get("focus_snapshots_count", 0)
        if isinstance(focus_count, int) and focus_count >= 5:
            mechanics_events = mechanics.get("events_count", 0) if isinstance(mechanics, dict) else 0
            if isinstance(mechanics_events, int) and mechanics_events <= 1:
                limitations.append("many_info_snapshots_but_few_mechanics_events_round_may_be_multiphase")

        if info.get("death_info_context_counts") and not has_key_deep(card, ["death_order", "player_died_first", "entry_death", "first_death"]):
            limitations.append("death_snapshot_without_death_order_do_not_claim_died_first")

    if not has_key_deep(card, ["nearest_teammate", "teammate_distance", "trade_possible", "trade_available", "spacing"]):
        limitations.append("no_explicit_teammate_spacing_do_not_claim_no_trade_or_free_death")

    if not has_key_deep(card, ["escape_available", "safe_fallback", "retreat_path", "duel_forced", "fallback_option"]):
        limitations.append("no_escape_or_fallback_evidence_do_not_claim_bad_duel_choice")

    if not has_key_deep(card, ["visibility_confirmed", "raycast", "seen_by_player", "line_of_sight"]):
        limitations.append("no_raycast_visibility_do_not_claim_player_saw_or_should_have_seen_enemy")

    return list(dict.fromkeys(limitations))


def guardrails_for_limitations(limitations: list[str]) -> list[str]:
    rules: list[str] = []

    if any("visibility" in x or "raycast" in x for x in limitations):
        rules.append("Use 'visibility/reaction evidence is limited' when discussing first-shot delay, no-shot response, shoulder peeks, smoke, flash, or timing.")
    if any("death_order" in x for x in limitations):
        rules.append("Do not write 'died first' unless explicit death order is present.")
    if any("teammate_spacing" in x for x in limitations):
        rules.append("Do not write 'no trade', 'free death', or 'bad spacing' as fact; phrase as 'trade/spacing cannot be confirmed from current evidence'.")
    if any("fallback" in x for x in limitations):
        rules.append("Do not write 'bad duel choice' unless escape/fallback evidence exists.")
    if any("multiphase" in x or "one_top" in x or "one_or_zero" in x for x in limitations):
        rules.append("Do not generalize one mechanics event into a whole-round verdict; say the card may omit other contacts.")
    return rules


def build_guarded_input(compact: dict[str, Any]) -> dict[str, Any]:
    guarded = {
        "version": "ai_coach_judge_input_v0_3_guarded",
        "source_version": compact.get("version") or compact.get("input_version"),
        "match_id": compact.get("match_id"),
        "player": compact.get("player"),
        "global_guardrails": [
            "All claims must be grounded in supplied evidence.",
            "enemy_intent is a hypothesis, never a fact.",
            "info_state is reconstructable prior info, not real voice comms or player awareness.",
            "mechanics_deep has limited visibility/flash context; do not make hard visibility verdicts.",
            "Do not mention HUD speed; use parsed movement/speed evidence only.",
            "Do not claim died first, no trade, free death, or bad duel choice without explicit support.",
            "When evidence is incomplete, write limited/uncertain instead of inventing context."
        ],
        "round_cards_for_model": [],
        "original_compact_keys": list(compact.keys())
    }

    cards = compact.get("round_cards_for_model", [])
    if not isinstance(cards, list):
        cards = []

    for card in cards:
        if not isinstance(card, dict):
            continue
        limitations = round_limitations(card)
        guarded_card = dict(card)
        guarded_card["evidence_limitations"] = limitations
        guarded_card["claim_guardrails"] = guardrails_for_limitations(limitations)
        guarded["round_cards_for_model"].append(guarded_card)

    guarded["round_cards_total"] = len(guarded["round_cards_for_model"])
    return guarded


def build_messages(guarded_input: dict[str, Any]) -> list[dict[str, str]]:
    system = """
Ты AI coach judge для CS2 demo analyzer.

Твоя задача: дать тренерский разбор ТОЛЬКО по evidence. Если evidence недостаточно, нужно прямо написать "ограничено текущими данными", а не додумывать.

ЖЁСТКИЕ ПРАВИЛА:
1. Ответ должен быть ТОЛЬКО валидным JSON. Без markdown, без ```json, без текста до/после.
2. Не используй абсолютные формулировки про намерения врагов. enemy_intent = гипотеза.
3. Не утверждай, что игрок точно видел/не видел врага, если нет raycast/visibility evidence.
4. Не утверждай, что игрок был ослеплён или не был ослеплён, если flash/blind context limited.
5. Не пиши "умер первым", если нет explicit death_order/player_died_first evidence.
6. Не пиши "без размена", "умер бесплатно", "bad spacing", если нет teammate spacing/trade evidence.
7. Не пиши "bad duel choice", если нет evidence, что был рациональный отход/fallback/escape.
8. Не пиши "скорость по HUD". Скорость берётся из parsed demo data.
9. Если mechanics event один, не обобщай его на весь раунд.
10. Для каждого спорного вывода указывай claim_strength: supported / limited / unsupported_avoided.

Схема ответа:
{
  "schema_version": "ai_coach_judge_report_v0_4_guarded",
  "match_summary": "...",
  "quality_control": {
    "json_validity_intent": "valid_json_only",
    "major_limitations": [],
    "unsupported_claims_avoided": []
  },
  "top_priorities": [
    {
      "priority": "...",
      "claim_strength": "supported|limited",
      "evidence_basis": [],
      "practical_fix": "..."
    }
  ],
  "round_reviews": [
    {
      "round_num": 0,
      "round_result": "...",
      "main_takeaway": "...",
      "claim_strength": "supported|limited",
      "what_evidence_supports": [],
      "what_evidence_does_not_support": [],
      "mechanics": {
        "supported": [],
        "limited_or_uncertain": []
      },
      "decision": {
        "supported": [],
        "limited_or_uncertain": []
      },
      "info_state": {
        "supported": [],
        "limited_or_uncertain": []
      },
      "enemy_intent": {
        "hypothesis": "...",
        "confidence": "...",
        "caveat": "..."
      },
      "training_note": "..."
    }
  ],
  "training_plan": {
    "rules": [],
    "exercises": [],
    "review_questions": []
  },
  "uncertainties": []
}
""".strip()

    user = json.dumps(guarded_input, ensure_ascii=False, indent=2)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]


def call_openai_compatible(endpoint: str, api_key: str, payload: dict[str, Any], timeout_sec: int) -> tuple[int, dict[str, Any] | None, str | None]:
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


def strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--match-id", default="example_match")
    p.add_argument("--player", default="Player")
    p.add_argument("--mode", choices=["build-input", "check", "llm"], default="check")
    args = p.parse_args()

    match_id = args.match_id
    player = args.player

    compact_path = Path(f"data/ai/{match_id}/ai_coach_judge_input_compact_current.json")
    env_path = Path("config/llm.env")

    guarded_path = Path(f"data/ai/{match_id}/ai_coach_judge_input_guarded_{player}_v0_3.json")
    guarded_current = Path(f"data/ai/{match_id}/ai_coach_judge_input_guarded_current.json")

    if not compact_path.exists():
        print(json.dumps({"status": "error", "error": f"missing compact input: {compact_path}"}, ensure_ascii=False, indent=2))
        sys.exit(1)

    compact = load_json(compact_path)
    guarded = build_guarded_input(compact)
    write_json(guarded_path, guarded)
    write_json(guarded_current, guarded)

    env = load_env_file(env_path)
    required = [
        "CS_DEMO_COACH_LLM_BASE_URL",
        "CS_DEMO_COACH_LLM_API_KEY",
        "CS_DEMO_COACH_LLM_MODEL",
    ]
    missing = [k for k in required if not env.get(k)]

    max_tokens = int(env.get("CS_DEMO_COACH_LLM_MAX_TOKENS", "12000") or "12000")
    if max_tokens < 10000:
        max_tokens = 12000

    timeout_sec = int(env.get("CS_DEMO_COACH_LLM_TIMEOUT_SEC", "1800") or "1800")
    temperature = float(env.get("CS_DEMO_COACH_LLM_TEMPERATURE", "0.15") or "0.15")

    endpoint = endpoint_from_base(env.get("CS_DEMO_COACH_LLM_BASE_URL", "")) if not missing else None
    messages = build_messages(guarded)

    preview = {
        "input_kind": "guarded",
        "input_version": guarded["version"],
        "input_path": str(guarded_current),
        "local_env_file": str(env_path),
        "endpoint": endpoint,
        "model": env.get("CS_DEMO_COACH_LLM_MODEL"),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_sec": timeout_sec,
        "messages_count": len(messages),
        "system_chars": len(messages[0]["content"]),
        "user_chars": len(messages[1]["content"]),
        "round_cards_for_model": len(guarded.get("round_cards_for_model", [])),
    }

    preview_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_request_preview_{player}_v0_4.json")
    prompt_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_prompt_preview_{player}_v0_4.txt")
    write_json(preview_path, preview)
    prompt_path.write_text(messages[0]["content"] + "\n\n=== USER JSON ===\n\n" + messages[1]["content"], encoding="utf-8")

    if args.mode == "build-input":
        print(json.dumps({
            "status": "ok",
            "mode": args.mode,
            "created": {
                "guarded_input": str(guarded_path),
                "guarded_current": str(guarded_current),
                "request_preview": str(preview_path),
                "prompt_preview": str(prompt_path),
            },
            "request_preview": preview
        }, ensure_ascii=False, indent=2))
        return

    if missing:
        print(json.dumps({
            "status": "config_missing",
            "missing_env": missing,
            "request_preview": preview
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    if args.mode == "check":
        print(json.dumps({
            "status": "ok_ready_for_llm",
            "runner": "ai_coach_judge_llm_runner_v0_4_guarded",
            "request_preview": preview,
            "created": {
                "guarded_input": str(guarded_path),
                "guarded_current": str(guarded_current),
                "request_preview": str(preview_path),
                "prompt_preview": str(prompt_path),
            }
        }, ensure_ascii=False, indent=2))
        return

    payload = {
        "model": env["CS_DEMO_COACH_LLM_MODEL"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    started = time.time()
    status_code, response, error = call_openai_compatible(endpoint, env["CS_DEMO_COACH_LLM_API_KEY"], payload, timeout_sec)
    elapsed_sec = round(time.time() - started, 3)

    result_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_result_{player}_v0_4.json")
    report_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_v0_4.json")
    report_txt_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_v0_4.txt")
    status_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_status_{player}_v0_4.json")

    call_ok = response is not None and 200 <= status_code < 300

    text = ""
    json_parse_ok = False
    json_parse_error = None
    parsed_report = None

    if call_ok and response is not None:
        write_json(result_path, response)
        text = extract_text(response)
        clean = strip_code_fences(text)
        report_txt_path.write_text(text, encoding="utf-8")
        try:
            parsed_report = json.loads(clean)
            json_parse_ok = True
            write_json(report_path, parsed_report)
        except Exception as e:
            json_parse_error = f"{type(e).__name__}: {e}"
            report_path.write_text(clean, encoding="utf-8")
    else:
        result_path.write_text(error or "unknown error", encoding="utf-8")

    status = {
        "status": "ok" if call_ok else "error",
        "runner": "ai_coach_judge_llm_runner_v0_4_guarded",
        "mode": args.mode,
        "match_id": match_id,
        "player": player,
        "elapsed_sec": elapsed_sec,
        "request_preview": preview,
        "call": {
            "ok": call_ok,
            "status_code": status_code,
            "error": error,
        },
        "text_chars": len(text),
        "json_parse": {
            "ok": json_parse_ok,
            "error": json_parse_error,
        },
        "created": {
            "status_json": str(status_path),
            "guarded_input": str(guarded_path),
            "request_preview": str(preview_path),
            "prompt_preview": str(prompt_path),
            "result_json": str(result_path),
            "report_json": str(report_path),
            "report_txt": str(report_txt_path),
        }
    }

    write_json(status_path, status)
    write_json(Path(f"data/ai/{match_id}/ai_coach_judge_llm_status_current.json"), status)

    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
