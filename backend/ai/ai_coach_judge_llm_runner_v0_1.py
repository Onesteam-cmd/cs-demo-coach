import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


RUNNER_VERSION = "ai_coach_judge_llm_runner_v0_1"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def compact(value: Any, limit_list: int = 12, limit_dict_keys: int = 60) -> Any:
    if isinstance(value, list):
        return [compact(x, limit_list, limit_dict_keys) for x in value[:limit_list]]
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= limit_dict_keys:
                out["_truncated_keys"] = len(value) - limit_dict_keys
                break
            out[k] = compact(v, limit_list, limit_dict_keys)
        return out
    return value


def getenv_clean(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def normalize_base_url(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return base_url + "/chat/completions"
    return base_url + "/v1/chat/completions"


def build_messages(ai_input: Dict[str, Any]) -> List[Dict[str, str]]:
    model_contract = ai_input.get("model_contract", {})
    match_context = ai_input.get("match_context", {})
    round_cards = ai_input.get("round_cards_for_model", [])
    final_instruction = ai_input.get("final_instruction", "")

    system_text = "\n".join([
        str(model_contract.get("role", "Ты Counter-Strike тренер-аналитик.")),
        "",
        "ОБЯЗАТЕЛЬНО:",
        *[f"- {x}" for x in model_contract.get("must_do", [])],
        "",
        "ЗАПРЕЩЕНО:",
        *[f"- {x}" for x in model_contract.get("must_not_do", [])],
        "",
        "Формат ответа:",
        json.dumps(model_contract.get("output_schema", {}), ensure_ascii=False, indent=2),
    ])

    user_payload = {
        "match_context": compact(match_context, limit_list=12, limit_dict_keys=70),
        "round_cards_for_model": compact(round_cards, limit_list=12, limit_dict_keys=90),
        "final_instruction": final_instruction,
    }

    user_text = (
        "Ниже evidence package для тренерского разбора. "
        "Сформируй итоговый coach report на русском языке, строго по evidence.\n\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2)
    )

    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


def extract_text_from_response(response_json: Dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]

    output = response_json.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        parts.append(c["text"])
            elif isinstance(content, str):
                parts.append(content)
        if parts:
            return "\n".join(parts)

    return json.dumps(response_json, ensure_ascii=False, indent=2)


def call_chat_completions(
    endpoint: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout_sec: int,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    request = urllib.request.Request(
        endpoint,
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status_code": response.status,
                "raw": raw,
                "json": json.loads(raw),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": e.code,
            "raw": raw,
            "json": None,
            "error": f"HTTPError: {e.code} {e.reason}",
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "raw": "",
            "json": None,
            "error": f"{type(e).__name__}: {e}",
        }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player
    mode = args.mode

    ai_dir = root / "data" / "ai" / match_id
    input_path = ai_dir / "ai_coach_judge_input_current.json"

    if not input_path.exists():
        raise FileNotFoundError(f"MISSING ai input: {input_path}")

    ai_input = load_json(input_path)

    if ai_input.get("meta", {}).get("version") != "ai_coach_judge_input_v0_1":
        raise ValueError(f"Expected ai_coach_judge_input_v0_1, got {ai_input.get('meta', {}).get('version')}")

    messages = build_messages(ai_input)

    base_url = getenv_clean("CS_DEMO_COACH_LLM_BASE_URL")
    api_key = getenv_clean("CS_DEMO_COACH_LLM_API_KEY")
    model = getenv_clean("CS_DEMO_COACH_LLM_MODEL")
    temperature_raw = getenv_clean("CS_DEMO_COACH_LLM_TEMPERATURE")
    max_tokens_raw = getenv_clean("CS_DEMO_COACH_LLM_MAX_TOKENS")
    timeout_raw = getenv_clean("CS_DEMO_COACH_LLM_TIMEOUT_SEC")

    temperature = float(temperature_raw) if temperature_raw else 0.2
    max_tokens = int(max_tokens_raw) if max_tokens_raw else 4500
    timeout_sec = int(timeout_raw) if timeout_raw else 120

    missing_env = []
    if not base_url:
        missing_env.append("CS_DEMO_COACH_LLM_BASE_URL")
    if not api_key:
        missing_env.append("CS_DEMO_COACH_LLM_API_KEY")
    if not model:
        missing_env.append("CS_DEMO_COACH_LLM_MODEL")

    endpoint = normalize_base_url(base_url) if base_url else ""

    request_preview = {
        "endpoint": endpoint or None,
        "model": model or None,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages_count": len(messages),
        "system_chars": len(messages[0]["content"]) if messages else 0,
        "user_chars": len(messages[1]["content"]) if len(messages) > 1 else 0,
        "round_cards_for_model": len(ai_input.get("round_cards_for_model", [])),
    }

    out_status = ai_dir / f"ai_coach_judge_llm_status_{player}_v0_1.json"
    out_status_current = ai_dir / "ai_coach_judge_llm_status_current.json"
    out_request_preview = ai_dir / f"ai_coach_judge_llm_request_preview_{player}_v0_1.json"
    out_prompt_preview = ai_dir / f"ai_coach_judge_llm_prompt_preview_{player}_v0_1.txt"

    prompt_text = "\n\n--- SYSTEM ---\n\n" + messages[0]["content"] + "\n\n--- USER ---\n\n" + messages[1]["content"]

    write_json(out_request_preview, {
        "meta": {
            "version": RUNNER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "mode": mode,
        },
        "request_preview": request_preview,
        "messages": messages,
    })
    write_text(out_prompt_preview, prompt_text)

    if mode == "check":
        status = {
            "status": "ok_ready_for_llm" if not missing_env else "config_missing",
            "runner": RUNNER_VERSION,
            "mode": mode,
            "match_id": match_id,
            "player": player,
            "missing_env": missing_env,
            "request_preview": request_preview,
            "next_step": (
                "Run with -Mode llm after setting required env vars."
                if missing_env else
                "Config looks complete. Run with -Mode llm to call the model."
            ),
            "created": {
                "status_json": rel(out_status, root),
                "status_current": rel(out_status_current, root),
                "request_preview": rel(out_request_preview, root),
                "prompt_preview": rel(out_prompt_preview, root),
            }
        }
        write_json(out_status, status)
        write_json(out_status_current, status)
        return status

    if mode != "llm":
        raise ValueError("mode must be either check or llm")

    if missing_env:
        status = {
            "status": "config_missing",
            "runner": RUNNER_VERSION,
            "mode": mode,
            "match_id": match_id,
            "player": player,
            "missing_env": missing_env,
            "request_preview": request_preview,
            "error": "Cannot call LLM without required env vars.",
            "created": {
                "status_json": rel(out_status, root),
                "status_current": rel(out_status_current, root),
                "request_preview": rel(out_request_preview, root),
                "prompt_preview": rel(out_prompt_preview, root),
            }
        }
        write_json(out_status, status)
        write_json(out_status_current, status)
        return status

    call_result = call_chat_completions(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_sec=timeout_sec,
    )

    out_result = ai_dir / f"ai_coach_judge_llm_result_{player}_v0_1.json"
    out_result_current = ai_dir / "ai_coach_judge_llm_result_current.json"
    out_text = ai_dir / f"ai_coach_judge_llm_report_{player}_v0_1.txt"

    text = ""
    if call_result["ok"] and call_result["json"] is not None:
        text = extract_text_from_response(call_result["json"])

    result_package = {
        "meta": {
            "version": RUNNER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "mode": mode,
            "source_input": rel(input_path, root),
        },
        "request_preview": request_preview,
        "call": {
            "ok": call_result["ok"],
            "status_code": call_result["status_code"],
            "error": call_result["error"],
        },
        "text": text,
        "raw_response": call_result["json"] if call_result["json"] is not None else call_result["raw"],
    }

    write_json(out_result, result_package)
    write_json(out_result_current, result_package)
    write_text(out_text, text if text else call_result.get("raw", ""))

    status = {
        "status": "ok" if call_result["ok"] else "llm_call_failed",
        "runner": RUNNER_VERSION,
        "mode": mode,
        "match_id": match_id,
        "player": player,
        "request_preview": request_preview,
        "call": result_package["call"],
        "text_chars": len(text),
        "created": {
            "status_json": rel(out_status, root),
            "status_current": rel(out_status_current, root),
            "request_preview": rel(out_request_preview, root),
            "prompt_preview": rel(out_prompt_preview, root),
            "result_json": rel(out_result, root),
            "result_current": rel(out_result_current, root),
            "report_txt": rel(out_text, root),
        }
    }

    write_json(out_status, status)
    write_json(out_status_current, status)

    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    parser.add_argument("--mode", choices=["check", "llm"], default="check")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("status") == "llm_call_failed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
