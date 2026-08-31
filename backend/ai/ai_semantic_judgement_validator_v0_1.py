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


def compact_rich_input_for_judge(rich: dict[str, Any]) -> dict[str, Any]:
    """
    Не режем смысл до ключевых слов. Просто убираем лишние служебные поля,
    оставляя round_cards, limitations, guardrails, expanded evidence.
    """
    return {
        "version": rich.get("version"),
        "match_id": rich.get("match_id"),
        "player": rich.get("player"),
        "review_rounds": rich.get("review_rounds"),
        "global_guardrails": rich.get("global_guardrails"),
        "round_cards_for_model": rich.get("round_cards_for_model"),
        "source_stats": rich.get("source_stats"),
    }


def build_semantic_judge_input(match_id: str, player: str, report_version: str) -> dict[str, Any]:
    report_path = Path(f"data/ai/{match_id}/ai_coach_judge_llm_report_{player}_{report_version}.json")
    rich_path = Path(f"data/ai/{match_id}/ai_coach_judge_input_rich_guarded_current.json")
    manual_path = Path(f"data/manual_review/{match_id}/manual_review_notes_{player}_v0_1.json")
    regex_v02_path = Path(f"data/validation/{match_id}/ai_judgement_validation_{player}_{report_version}_v0_2.json")

    report = load_json(report_path)
    rich = load_json(rich_path)
    manual = load_json(manual_path) if manual_path.exists() else None
    regex_v02 = load_json(regex_v02_path) if regex_v02_path.exists() else None

    return {
        "semantic_validator_version": "ai_semantic_judgement_validator_input_v0_1",
        "task": "Judge whether the coach report is semantically grounded in evidence and useful as a CS2 coaching report.",
        "match_id": match_id,
        "player": player,
        "report_version": report_version,
        "project_rules": [
            "Do not judge by keywords alone. Evaluate meaning and context.",
            "Regex validator warnings are only signals, not final verdicts.",
            "The coach report may mention risky terms safely when saying that evidence does NOT support such a claim.",
            "enemy_intent is a hypothesis, not truth.",
            "info_state is reconstructable prior information, not proof of what the player consciously knew.",
            "visibility/flash/raycast limitations must prevent hard visual awareness verdicts.",
            "Trade/spacing/death order claims require evidence or should be marked limited.",
            "A good report should remain practically useful, not become empty or over-cautious.",
            "Manual review notes are calibration evidence for this test demo only.",
        ],
        "judge_questions": [
            "Is the report JSON structurally usable?",
            "Does the report make unsupported claims?",
            "Does the report correctly avoid unsupported claims when it explicitly says evidence does not support them?",
            "Are manual calibration contradictions resolved compared with the earlier v0.2 report?",
            "Are remaining trade/spacing claims actually supported by report evidence, source evidence, or manual notes?",
            "Is the report useful enough for player improvement?",
            "What should be fixed in the generator, evidence layer, or report renderer next?"
        ],
        "coach_report_to_validate": report,
        "evidence_input_used_by_report": compact_rich_input_for_judge(rich),
        "manual_calibration_notes": manual,
        "regex_validator_v0_2_signals": regex_v02,
    }


def build_messages(judge_input: dict[str, Any]) -> list[dict[str, str]]:
    system = """
You are a semantic QA judge for a CS2 demo coaching report.

Evaluate the report by MEANING, not by keyword matching.

Important:
- A phrase like "does not prove bad duel choice" is SAFE and should not be flagged as a bad-duel-choice claim.
- A phrase like "lack of raycast evidence" is SAFE and should not be flagged as a visibility overclaim.
- Regex validator warnings are signals only. You must confirm or dismiss them semantically.
- Manual notes are calibration evidence for this specific test demo.
- Do not invent new gameplay facts. Judge only consistency, grounding, usefulness, and limitations.

Return ONLY valid JSON. No markdown.

Required output schema:
{
  "schema_version": "ai_semantic_judgement_validation_v0_1",
  "overall_status": "pass|warn|fail",
  "summary": "...",
  "score": {
    "grounding": 0,
    "usefulness": 0,
    "uncertainty_handling": 0,
    "schema_quality": 0
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
      "manual_calibration_conflicts": []
    }
  ],
  "generator_fix_recommendations": [],
  "evidence_layer_fix_recommendations": [],
  "final_acceptance": {
    "can_use_report_for_human_review": true,
    "can_use_report_as_final_product_output": false,
    "reason": "..."
  }
}
""".strip()

    user = json.dumps(judge_input, ensure_ascii=False, indent=2)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--match-id", default="example_match")
    p.add_argument("--player", default="Player")
    p.add_argument("--report-version", default="v0_5")
    p.add_argument("--mode", choices=["build-input", "check", "llm"], default="check")
    args = p.parse_args()

    match_id = args.match_id
    player = args.player
    report_version = args.report_version

    judge_input = build_semantic_judge_input(match_id, player, report_version)
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

    max_tokens = int(env.get("CS_DEMO_COACH_LLM_JUDGE_MAX_TOKENS", "10000") or "10000")
    timeout_sec = int(env.get("CS_DEMO_COACH_LLM_JUDGE_TIMEOUT_SEC", env.get("CS_DEMO_COACH_LLM_TIMEOUT_SEC", "1800")) or "1800")
    temperature = float(env.get("CS_DEMO_COACH_LLM_JUDGE_TEMPERATURE", "0.0") or "0.0")

    out_dir = Path(f"data/validation/{match_id}")

    input_path = out_dir / f"ai_semantic_judgement_input_{player}_{report_version}_v0_1.json"
    preview_path = out_dir / f"ai_semantic_judgement_request_preview_{player}_{report_version}_v0_1.json"
    prompt_path = out_dir / f"ai_semantic_judgement_prompt_preview_{player}_{report_version}_v0_1.txt"

    write_json(input_path, judge_input)
    prompt_path.write_text(messages[0]["content"] + "\n\n=== USER JSON ===\n\n" + messages[1]["content"], encoding="utf-8")

    preview = {
        "status": "preview",
        "validator": "ai_semantic_judgement_validator_v0_1",
        "mode": args.mode,
        "match_id": match_id,
        "player": player,
        "report_version": report_version,
        "endpoint": endpoint,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_sec": timeout_sec,
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
            "validator": "ai_semantic_judgement_validator_v0_1",
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
    status_code, response, error = call_openai_compatible(endpoint, api_key, payload, timeout_sec)
    elapsed_sec = round(time.time() - started, 3)

    result_path = out_dir / f"ai_semantic_judgement_result_{player}_{report_version}_v0_1.json"
    verdict_path = out_dir / f"ai_semantic_judgement_verdict_{player}_{report_version}_v0_1.json"
    verdict_txt_path = out_dir / f"ai_semantic_judgement_verdict_{player}_{report_version}_v0_1.txt"
    status_path = out_dir / f"ai_semantic_judgement_status_{player}_{report_version}_v0_1.json"

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
        "validator": "ai_semantic_judgement_validator_v0_1",
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
