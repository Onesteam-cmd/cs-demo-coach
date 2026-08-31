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


TARGET_EXTRA_CHARS_SOFT = 85000
PER_ROUND_OBJECT_LIMIT = 28
PER_SOURCE_ROUND_LIMIT = 7


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


def maybe_round(obj: dict[str, Any]) -> int | None:
    for key in ("round_num", "round", "round_number", "roundNum"):
        if key in obj:
            try:
                return int(obj[key])
            except Exception:
                pass
    return None


def collect_review_rounds(compact: dict[str, Any]) -> list[int]:
    rounds = []
    cards = compact.get("round_cards_for_model", [])
    if isinstance(cards, list):
        for c in cards:
            if isinstance(c, dict) and "round_num" in c:
                try:
                    rounds.append(int(c["round_num"]))
                except Exception:
                    pass
    return sorted(set(rounds))


def short_value(v: Any, depth: int = 0) -> Any:
    if depth >= 5:
        return "..."
    if isinstance(v, dict):
        priority = [
            "round_num", "round", "tick", "event_tick", "focus_event_tick",
            "event_id", "event_type", "focus_event_kind", "type", "label",
            "decision_label", "decision_labels", "decision_confidence",
            "player", "player_name", "attacker", "victim", "opponent", "enemy",
            "combat_role", "combat_place", "place", "area", "site", "bombsite",
            "round_result", "side", "team",
            "speed", "speed_band", "velocity_X", "velocity_Y", "velocity_Z",
            "yaw", "pitch", "yaw_error_abs", "yaw_error_abs_deg_approx", "yaw_error_band",
            "shots_after_event", "shots_in_window", "first_shot_delay_ms", "first_shot_delay_ms_assumed",
            "root_cause", "deep_label", "deep_confidence", "deep_flags",
            "flags", "quality_flags", "reasoning_quality_flags",
            "opponent_info_context", "info_context", "info_age_sec", "opponent_last_known",
            "enemy_plan", "likely_enemy_plan", "plan", "plan_family", "confidence",
            "plant_phase", "primary_area",
            "trade", "spacing", "nearest_teammate", "teammate_distance", "teammates",
            "summary", "interpretation", "evidence", "evidence_reasons", "limitations", "notes",
            "questions_for_model", "coach_reasoning",
        ]
        out: dict[str, Any] = {}
        for k in priority:
            if k in v:
                out[k] = short_value(v[k], depth + 1)
        for k, val in v.items():
            if k not in out and len(out) < 32:
                out[k] = short_value(val, depth + 1)
        return out
    if isinstance(v, list):
        return [short_value(x, depth + 1) for x in v[:16]]
    if isinstance(v, str) and len(v) > 500:
        return v[:500] + "...[truncated]"
    return v


def object_score(obj: dict[str, Any], source_name: str) -> int:
    text = json.dumps(obj, ensure_ascii=False).lower()
    score = 0

    high_terms = [
        "death", "player_death", "kill", "damage", "combat", "mechanics",
        "decision", "trade", "spacing", "teammate", "shot", "yaw", "speed",
        "timing", "visibility", "flash", "intent", "plant", "bombsite",
        "round_result", "lost", "loss"
    ]

    for t in high_terms:
        if t in text:
            score += 2

    if "manual" in text:
        score += 1
    if "visibility_flash_context_missing_or_limited" in text:
        score += 4
    if "first_shot_delay" in text:
        score += 4
    if "bad_duel_choice" in text:
        score += 5
    if "death_order" in text or "player_died_first" in text:
        score += 5
    if "ai_coach_judge_input_current" in source_name:
        score += 3
    if "mechanics_deep" in source_name:
        score += 3
    if "decision_context" in source_name:
        score += 3

    return score


def collect_round_objects(data: Any, source: str, wanted_rounds: set[int], trail: str = "root") -> list[dict[str, Any]]:
    found = []
    if isinstance(data, dict):
        rnd = maybe_round(data)
        if rnd in wanted_rounds:
            compact_obj = short_value(data)
            found.append({
                "source": source,
                "trail": trail,
                "round_num": rnd,
                "score": object_score(data, source),
                "keys": list(data.keys())[:60],
                "object": compact_obj,
            })
        for k, v in data.items():
            found.extend(collect_round_objects(v, source, wanted_rounds, f"{trail}.{k}"))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            found.extend(collect_round_objects(v, source, wanted_rounds, f"{trail}[{i}]"))
    return found


def dedupe_objects(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = json.dumps(item.get("object"), ensure_ascii=False, sort_keys=True)[:2000]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def has_key_deep(obj: Any, keys: list[str]) -> bool:
    for d in walk(obj):
        if isinstance(d, dict):
            for k in keys:
                if k in d:
                    return True
    return False


def round_limitations(card: dict[str, Any]) -> list[str]:
    limitations = []
    mechanics = card.get("mechanics_deep", {})
    info = card.get("info_state", {})

    if isinstance(mechanics, dict):
        events_count = mechanics.get("events_count", 0)
        if isinstance(events_count, int) and events_count <= 1:
            limitations.append("compact_mechanics_has_only_one_or_zero_events_do_not_generalize_whole_round")
        top_sample = mechanics.get("top_events_sample")
        if isinstance(top_sample, list) and len(top_sample) <= 1:
            limitations.append("compact_has_only_one_top_mechanics_event_sample")
        flags = mechanics.get("deep_flag_counts", {})
        if isinstance(flags, dict) and flags.get("visibility_flash_context_missing_or_limited", 0) > 0:
            limitations.append("visibility_flash_context_limited_no_hard_visibility_or_reaction_verdict")

    if isinstance(info, dict):
        focus_count = info.get("focus_snapshots_count", 0)
        mechanics_events = mechanics.get("events_count", 0) if isinstance(mechanics, dict) else 0
        if isinstance(focus_count, int) and focus_count >= 5 and isinstance(mechanics_events, int) and mechanics_events <= 1:
            limitations.append("many_info_snapshots_but_few_compact_mechanics_events_round_may_be_multiphase")
        if info.get("death_info_context_counts") and not has_key_deep(card, ["death_order", "player_died_first", "entry_death", "first_death"]):
            limitations.append("death_snapshot_without_death_order_do_not_claim_died_first")

    if not has_key_deep(card, ["nearest_teammate", "teammate_distance", "trade_possible", "trade_available", "spacing"]):
        limitations.append("no_explicit_teammate_spacing_do_not_claim_no_trade_or_free_death_as_fact")

    if not has_key_deep(card, ["escape_available", "safe_fallback", "retreat_path", "duel_forced", "fallback_option"]):
        limitations.append("no_escape_or_fallback_evidence_do_not_claim_bad_duel_choice_as_fact")

    if not has_key_deep(card, ["visibility_confirmed", "raycast", "seen_by_player", "line_of_sight"]):
        limitations.append("no_raycast_visibility_do_not_claim_player_saw_or_should_have_seen_enemy")

    return list(dict.fromkeys(limitations))


def guardrails_for_limitations(limitations: list[str]) -> list[str]:
    rules = []
    if any("visibility" in x or "raycast" in x for x in limitations):
        rules.append("Use visibility/reaction caveats for first-shot delay, no-shot response, shoulder peeks, smoke, flash, or timing.")
    if any("death_order" in x for x in limitations):
        rules.append("Do not write died first unless explicit death order is present.")
    if any("teammate_spacing" in x for x in limitations):
        rules.append("Do not write no trade/free death/bad spacing as fact unless expanded evidence explicitly supports it.")
    if any("fallback" in x for x in limitations):
        rules.append("Do not write bad duel choice unless expanded evidence proves rational fallback/escape existed.")
    if any("multiphase" in x or "one_top" in x or "one_or_zero" in x for x in limitations):
        rules.append("Do not generalize one compact mechanics event into a whole-round verdict; inspect expanded_round_evidence.")
    return rules


def build_rich_guarded_input(match_id: str, player: str) -> dict[str, Any]:
    compact_path = Path(f"data/ai/{match_id}/ai_coach_judge_input_compact_current.json")
    compact = load_json(compact_path)

    review_rounds = collect_review_rounds(compact)
    wanted = set(review_rounds)

    sources = [
        f"data/ai/{match_id}/ai_coach_judge_input_current.json",
        f"data/analysis/{match_id}/mechanics_deep_current.json",
        f"data/analysis/{match_id}/decision_context_current.json",
        f"data/layers/{match_id}/canonical_info_state_current.json",
        f"data/analysis/{match_id}/enemy_intent_current.json",
        f"data/package/{match_id}/coach_input_package_current.json",
    ]

    all_items_by_round: dict[int, list[dict[str, Any]]] = {r: [] for r in review_rounds}
    source_stats = {}

    for rel in sources:
        path = Path(rel)
        if not path.exists():
            source_stats[rel] = {"exists": False, "objects": 0}
            continue
        data = load_json(path)
        items = collect_round_objects(data, rel, wanted)
        source_stats[rel] = {"exists": True, "objects": len(items)}
        for item in items:
            all_items_by_round.setdefault(item["round_num"], []).append(item)

    guarded_cards = []
    cards = compact.get("round_cards_for_model", [])
    if not isinstance(cards, list):
        cards = []

    total_extra_chars = 0

    for card in cards:
        if not isinstance(card, dict):
            continue
        rnd = int(card.get("round_num", -1))
        limitations = round_limitations(card)

        candidates = dedupe_objects(all_items_by_round.get(rnd, []))
        candidates.sort(key=lambda x: (-int(x.get("score", 0)), x.get("source", ""), x.get("trail", "")))

        selected = []
        per_source_count: dict[str, int] = {}
        for item in candidates:
            src = item.get("source", "")
            if per_source_count.get(src, 0) >= PER_SOURCE_ROUND_LIMIT:
                continue
            if len(selected) >= PER_ROUND_OBJECT_LIMIT:
                break

            item_chars = len(json.dumps(item, ensure_ascii=False))
            if total_extra_chars + item_chars > TARGET_EXTRA_CHARS_SOFT and rnd not in {14, 17}:
                continue

            selected.append(item)
            per_source_count[src] = per_source_count.get(src, 0) + 1
            total_extra_chars += item_chars

        guarded = dict(card)
        guarded["evidence_limitations"] = limitations
        guarded["claim_guardrails"] = guardrails_for_limitations(limitations)
        guarded["expanded_round_evidence"] = {
            "purpose": "Additional focused evidence to avoid overgeneralizing compact samples.",
            "objects_total_available": len(candidates),
            "objects_selected": len(selected),
            "selection_note": "Objects are scored and truncated. They may still be partial; use caveats when chronology/trade/visibility is not explicit.",
            "objects": selected,
        }
        guarded_cards.append(guarded)

    rich = {
        "version": "ai_coach_judge_input_v0_6_ru_rich_guarded",
        "match_id": match_id,
        "player": player,
        "source_compact_input": str(compact_path),
        "review_rounds": review_rounds,
        "global_guardrails": [
            "All claims must be grounded in supplied evidence.",
            "Prefer useful coaching, but mark claim_strength as limited when evidence is partial.",
            "enemy_intent is a hypothesis, never a fact.",
            "info_state is reconstructable prior info, not proof of voice comms or player awareness.",
            "mechanics_deep has limited visibility/flash context; do not make hard visibility verdicts.",
            "Do not mention HUD speed. Use parsed demo speed only.",
            "Do not claim died first unless explicit death_order/player_died_first evidence exists.",
            "Do not claim no trade/free death/bad spacing unless teammate spacing/trade evidence exists.",
            "Do not claim bad duel choice unless evidence shows a rational fallback/escape existed.",
            "If compact evidence and expanded evidence conflict, report the conflict and lower claim_strength.",
            "If a round appears multiphase, do not summarize it from a single death/contact event.",
        ],
        "source_stats": source_stats,
        "round_cards_for_model": guarded_cards,
        "round_cards_total": len(guarded_cards),
    }

    return rich


def build_messages(rich_input: dict[str, Any]) -> list[dict[str, str]]:
    system = """
Ты AI coach judge для CS2 demo analyzer.

Твоя задача: дать качественный тренерский разбор игрока по evidence. Нужен не сухой пересказ, а полезный coach report. Но каждое утверждение должно быть grounded. ВАЖНО: весь пользовательский текст в JSON должен быть на русском языке. Не пиши английские формулировки в match_summary, priorities, round_reviews, training_plan, uncertainties, notes, limitations. Английскими могут оставаться только технические enum-значения supported/limited и schema_version.

ЖЁСТКИЕ ПРАВИЛА:
1. Ответ должен быть ТОЛЬКО валидным JSON. Без markdown, без ```json, без текста до/после. Весь человекочитаемый текст — строго на русском языке.
2. Не используй абсолютные формулировки про намерения врагов. enemy_intent = гипотеза.
3. Не утверждай, что игрок точно видел/не видел врага, если нет raycast/visibility evidence.
4. Не утверждай, что игрок был/не был ослеплён, если flash/blind context limited.
5. Не пиши "умер первым", если нет explicit death_order/player_died_first evidence.
6. Не пиши "без размена", "умер бесплатно", "bad spacing", если нет teammate spacing/trade evidence.
7. Не пиши "bad duel choice", если нет evidence, что был рациональный отход/fallback/escape.
8. Не пиши "скорость по HUD". Скорость берётся из parsed demo data.
9. Если compact-card показывает один mechanics event, проверь expanded_round_evidence и не обобщай один event на весь раунд.
10. Если expanded evidence всё равно неполный, давай тренерский вывод как limited, а не supported.
11. Нельзя выдумывать kill chronology, видимость, флеши, размены, тиммейтов и намерения врагов.

Схема ответа:
{
  "schema_version": "ai_coach_judge_report_v0_6_ru_rich_guarded",
  "match_summary": "...",
  "quality_control": {
    "json_validity_intent": "valid_json_only",
    "major_limitations": [],
    "unsupported_claims_avoided": [],
    "evidence_conflicts_or_gaps": []
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

    user = json.dumps(rich_input, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_openai_compatible(endpoint: str, api_key: str, payload: dict[str, Any], timeout_sec: int):
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

    rich = build_rich_guarded_input(match_id, player)
    messages = build_messages(rich)

    rich_path = Path(f"data/ai/{match_id}/ai_coach_judge_input_rich_guarded_{player}_v0_6_ru.json")
    rich_current = Path(f"data/ai/{match_id}/ai_coach_judge_input_rich_guarded_current.json")
    preview_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_request_preview_{player}_v0_6_ru.json")
    prompt_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_prompt_preview_{player}_v0_6_ru.txt")

    write_json(rich_path, rich)
    write_json(rich_current, rich)

    env_path = Path("config/llm.env")
    env = load_env_file(env_path)

    required = ["CS_DEMO_COACH_LLM_BASE_URL", "CS_DEMO_COACH_LLM_API_KEY", "CS_DEMO_COACH_LLM_MODEL"]
    missing = [k for k in required if not env.get(k)]

    max_tokens = int(env.get("CS_DEMO_COACH_LLM_MAX_TOKENS", "16000") or "16000")
    if max_tokens < 14000:
        max_tokens = 16000

    timeout_sec = int(env.get("CS_DEMO_COACH_LLM_TIMEOUT_SEC", "1800") or "1800")
    temperature = float(env.get("CS_DEMO_COACH_LLM_TEMPERATURE", "0.2") or "0.2")
    endpoint = endpoint_from_base(env.get("CS_DEMO_COACH_LLM_BASE_URL", "")) if not missing else None

    preview = {
        "input_kind": "rich_guarded",
        "input_version": rich["version"],
        "input_path": str(rich_current),
        "local_env_file": str(env_path),
        "endpoint": endpoint,
        "model": env.get("CS_DEMO_COACH_LLM_MODEL"),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_sec": timeout_sec,
        "messages_count": len(messages),
        "system_chars": len(messages[0]["content"]),
        "user_chars": len(messages[1]["content"]),
        "estimated_input_tokens_rough": round((len(messages[0]["content"]) + len(messages[1]["content"])) / 3.7),
        "round_cards_for_model": len(rich.get("round_cards_for_model", [])),
        "review_rounds": rich.get("review_rounds", []),
        "source_stats": rich.get("source_stats", {}),
    }

    write_json(preview_path, preview)
    prompt_path.write_text(messages[0]["content"] + "\n\n=== USER JSON ===\n\n" + messages[1]["content"], encoding="utf-8")

    if args.mode == "build-input":
        print(json.dumps({
            "status": "ok",
            "mode": args.mode,
            "created": {
                "rich_input": str(rich_path),
                "rich_current": str(rich_current),
                "request_preview": str(preview_path),
                "prompt_preview": str(prompt_path),
            },
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

    if args.mode == "check":
        print(json.dumps({
            "status": "ok_ready_for_llm",
            "runner": "ai_coach_judge_llm_runner_v0_6_ru",
            "request_preview": preview,
            "created": {
                "rich_input": str(rich_path),
                "rich_current": str(rich_current),
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

    result_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_result_{player}_v0_6_ru.json")
    report_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_v0_6_ru.json")
    report_txt_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_v0_6_ru.txt")
    status_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_status_{player}_v0_6_ru.json")

    call_ok = response is not None and 200 <= status_code < 300
    text = ""
    json_parse_ok = False
    json_parse_error = None

    if call_ok and response is not None:
        write_json(result_path, response)
        text = extract_text(response)
        report_txt_path.write_text(text, encoding="utf-8")
        clean = strip_code_fences(text)
        try:
            parsed = json.loads(clean)
            json_parse_ok = True
            write_json(report_path, parsed)
        except Exception as e:
            json_parse_error = f"{type(e).__name__}: {e}"
            report_path.write_text(clean, encoding="utf-8")
    else:
        result_path.write_text(error or "unknown error", encoding="utf-8")

    status = {
        "status": "ok" if call_ok else "error",
        "runner": "ai_coach_judge_llm_runner_v0_6_ru",
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
            "rich_input": str(rich_path),
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

