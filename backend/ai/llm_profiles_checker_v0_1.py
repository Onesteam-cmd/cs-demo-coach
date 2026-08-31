from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

BASE_ENV_PATH = CONFIG_DIR / "llm.env"
PROFILES_ENV_PATH = CONFIG_DIR / "llm_profiles.env"


MODEL_LIMITS = {
    "gemini-3.5-flash": {
        "rpm": 5,
        "tpm": 250_000,
        "rpd": 20,
        "role_fit": "core_reasoning",
        "enabled_by_quota": True,
    },
    "gemini-3.1-flash-lite": {
        "rpm": 15,
        "tpm": 250_000,
        "rpd": 500,
        "role_fit": "cheap_judge_high_volume",
        "enabled_by_quota": True,
    },
    "gemini-2.5-flash": {
        "rpm": 5,
        "tpm": 250_000,
        "rpd": 20,
        "role_fit": "semantic_judge_ru_editor_repair",
        "enabled_by_quota": True,
    },
    "gemini-3.1-pro": {
        "rpm": 0,
        "tpm": 0,
        "rpd": 0,
        "role_fit": "arbiter_disabled",
        "enabled_by_quota": False,
    },
}


ROLE_REQUIREMENTS = {
    "core": {
        "env_key": "CS_DEMO_COACH_MODEL_CORE",
        "required": True,
        "expected": "gemini-3.5-flash",
    },
    "cheap_judge": {
        "env_key": "CS_DEMO_COACH_MODEL_CHEAP_JUDGE",
        "required": True,
        "expected": "gemini-3.1-flash-lite",
    },
    "semantic_judge": {
        "env_key": "CS_DEMO_COACH_MODEL_SEMANTIC_JUDGE",
        "required": True,
        "expected": "gemini-2.5-flash",
    },
    "ru_editor": {
        "env_key": "CS_DEMO_COACH_MODEL_RU_EDITOR",
        "required": True,
        "expected": "gemini-2.5-flash",
    },
    "repair": {
        "env_key": "CS_DEMO_COACH_MODEL_REPAIR",
        "required": True,
        "expected": "gemini-2.5-flash",
    },
    "arbiter": {
        "env_key": "CS_DEMO_COACH_MODEL_ARBITER",
        "required": False,
        "expected": "",
    },
}


QUALITY_PROFILES = {
    "cheap": {
        "description": "Core report + local structural validation + cheap model judge.",
        "roles": ["core", "cheap_judge"],
        "semantic_judge_policy": "disabled_by_default",
        "repair_policy": "disabled_by_default",
    },
    "balanced": {
        "description": "Core report + structural validation + cheap judge; semantic judge only on warn/fail.",
        "roles": ["core", "cheap_judge", "semantic_judge", "repair"],
        "semantic_judge_policy": "only_if_cheap_judge_warn_or_fail",
        "repair_policy": "only_if_semantic_judge_warn_or_fail",
    },
    "full_quality": {
        "description": "Core report + structural validation + cheap judge + semantic judge; repair if needed.",
        "roles": ["core", "cheap_judge", "semantic_judge", "repair"],
        "semantic_judge_policy": "always",
        "repair_policy": "only_if_judge_warn_or_fail",
    },
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
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        result[key] = value

    return result


def mask_secret(value: Optional[str]) -> Dict[str, object]:
    if not value:
        return {
            "present": False,
            "preview": None,
        }

    return {
        "present": True,
        "preview": f"{value[:4]}...{value[-4:]}" if len(value) >= 8 else "***",
    }


def main() -> int:
    base_env = parse_env_file(BASE_ENV_PATH)
    profiles_env = parse_env_file(PROFILES_ENV_PATH)

    issues: List[Dict[str, str]] = []

    base_url = base_env.get("CS_DEMO_COACH_LLM_BASE_URL", "")
    api_key = base_env.get("CS_DEMO_COACH_LLM_API_KEY", "")

    if not BASE_ENV_PATH.exists():
        issues.append({
            "severity": "error",
            "code": "missing_base_env",
            "message": "config/llm.env not found. Existing LLM runners need this file.",
        })

    if not PROFILES_ENV_PATH.exists():
        issues.append({
            "severity": "error",
            "code": "missing_profiles_env",
            "message": "config/llm_profiles.env not found.",
        })

    if not base_url:
        issues.append({
            "severity": "error",
            "code": "missing_base_url",
            "message": "CS_DEMO_COACH_LLM_BASE_URL is missing in config/llm.env.",
        })

    if not api_key:
        issues.append({
            "severity": "error",
            "code": "missing_api_key",
            "message": "CS_DEMO_COACH_LLM_API_KEY is missing in config/llm.env.",
        })

    roles: Dict[str, Dict[str, object]] = {}

    for role_name, req in ROLE_REQUIREMENTS.items():
        env_key = str(req["env_key"])
        model = profiles_env.get(env_key, "").strip()
        expected = str(req["expected"])
        required = bool(req["required"])

        limits = MODEL_LIMITS.get(model) if model else None
        enabled_by_quota = bool(limits.get("enabled_by_quota")) if limits else False

        role_status = "ok"

        if required and not model:
            role_status = "error"
            issues.append({
                "severity": "error",
                "code": f"missing_role_{role_name}",
                "message": f"{env_key} is required but empty.",
            })
        elif model and model not in MODEL_LIMITS:
            role_status = "warning"
            issues.append({
                "severity": "warning",
                "code": f"unknown_model_{role_name}",
                "message": f"{env_key} uses unknown model: {model}",
            })
        elif model and not enabled_by_quota:
            role_status = "disabled"
            issues.append({
                "severity": "warning" if required else "info",
                "code": f"quota_disabled_{role_name}",
                "message": f"{env_key} uses model with zero quota: {model}",
            })
        elif expected and model != expected:
            role_status = "warning"
            issues.append({
                "severity": "warning",
                "code": f"unexpected_model_{role_name}",
                "message": f"{env_key} expected {expected}, got {model}",
            })

        roles[role_name] = {
            "env_key": env_key,
            "model": model,
            "required": required,
            "expected": expected,
            "status": role_status,
            "limits": limits,
        }

    default_profile = profiles_env.get("CS_DEMO_COACH_DEFAULT_QUALITY_PROFILE", "balanced").strip() or "balanced"

    if default_profile not in QUALITY_PROFILES:
        issues.append({
            "severity": "error",
            "code": "invalid_default_quality_profile",
            "message": f"Unknown CS_DEMO_COACH_DEFAULT_QUALITY_PROFILE: {default_profile}",
        })

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")

    if error_count:
        status = "fail"
    elif warning_count:
        status = "warn"
    else:
        status = "ok"

    output = {
        "status": status,
        "checker": "llm_profiles_checker_v0_1",
        "project_root": str(PROJECT_ROOT),
        "config_files": {
            "base_env": {
                "path": str(BASE_ENV_PATH),
                "exists": BASE_ENV_PATH.exists(),
                "base_url_present": bool(base_url),
                "api_key": mask_secret(api_key),
            },
            "profiles_env": {
                "path": str(PROFILES_ENV_PATH),
                "exists": PROFILES_ENV_PATH.exists(),
            },
        },
        "default_quality_profile": default_profile,
        "quality_profiles": QUALITY_PROFILES,
        "roles": roles,
        "issues_total": len(issues),
        "issues_by_severity": {
            "error": error_count,
            "warning": warning_count,
            "info": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "issues": issues,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
