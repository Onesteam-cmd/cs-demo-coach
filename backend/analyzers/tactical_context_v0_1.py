from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ANALYZER_VERSION = "tactical_context_v0_1"
TICK_RATE_ASSUMED = 64.0


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Optional[Path]) -> Any:
    if not path or not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = {}
            for key in fieldnames:
                value = row.get(key)
                if isinstance(value, (dict, list)):
                    flat[key] = json.dumps(value, ensure_ascii=False)
                else:
                    flat[key] = value
            writer.writerow(flat)


def version_key(path: Path) -> Tuple[Tuple[int, ...], float, str]:
    nums = tuple(int(x) for x in re.findall(r"_v(\d+)|_(\d+)", path.name)[0] if x) if re.findall(r"_v(\d+)|_(\d+)", path.name) else (-1,)
    # More robust fallback: collect all numbers after v/underscore in filename.
    all_nums = re.findall(r"(?:_v|_)(\d+)", path.name)
    if all_nums:
        nums = tuple(int(x) for x in all_nums)
    return nums, path.stat().st_mtime, path.name


def latest_file(directory: Path, pattern: str) -> Optional[Path]:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    if not files:
        return None
    return max(files, key=version_key)


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def pick(d: Any, keys: Iterable[str], default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for key in keys:
        value = d.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def first_by_round(items: List[Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_int(pick(item, ["round_num", "round", "round_number"]))
        if rn is not None and rn not in out:
            out[rn] = item
    return out


def group_by_round(items: List[Any]) -> Dict[int, List[Dict[str, Any]]]:
    out: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        rn = safe_int(pick(item, ["round_num", "round", "round_number"]))
        if rn is not None:
            out[rn].append(item)
    return out


def compact(value: Any, limit_list: int = 8, limit_dict_keys: int = 60) -> Any:
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


def confidence_rank(value: str) -> int:
    return {"none": 0, "unknown": 0, "low": 1, "medium": 2, "high": 3}.get(str(value or "").lower(), 0)


def permission(status: str, strength: str, reason: str, limitations: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "status": status,
        "max_claim_strength": strength,
        "reason": reason,
        "limitations": limitations or [],
    }


def focus_tick_from_round(row: Dict[str, Any]) -> Optional[int]:
    for key in [
        "player_death_tick",
        "player_first_damage_taken_tick",
        "player_first_damage_dealt_tick",
        "plant_tick",
        "end_tick",
    ]:
        value = safe_int(row.get(key))
        if value is not None:
            return value
    return None


def infer_round_phase(row: Dict[str, Any], focus_tick: Optional[int]) -> Dict[str, Any]:
    freeze_end = safe_int(row.get("freeze_end_tick"))
    plant_tick = safe_int(row.get("plant_tick"))
    has_plant = bool(row.get("has_plant"))

    elapsed_sec = None
    if focus_tick is not None and freeze_end is not None:
        elapsed_sec = round(max(0, focus_tick - freeze_end) / TICK_RATE_ASSUMED, 3)

    if has_plant and plant_tick is not None and focus_tick is not None and focus_tick >= plant_tick:
        phase = "postplant"
    elif elapsed_sec is None:
        phase = "unknown"
    elif elapsed_sec < 20:
        phase = "early_round"
    elif elapsed_sec < 55:
        phase = "mid_round"
    else:
        phase = "late_round"

    return {
        "phase": phase,
        "focus_tick": focus_tick,
        "elapsed_after_freeze_sec_assumed": elapsed_sec,
        "plant_tick": plant_tick,
        "has_plant": has_plant,
        "player_death_phase_source": row.get("player_death_phase"),
        "limitations": [
            "phase is inferred from ticks and plant/death timing only",
            "does not know actual team comms or called strat",
        ],
    }


def alive_state_before_focus(row: Dict[str, Any], focus_tick: Optional[int]) -> Dict[str, Any]:
    alive = {"t": 5, "ct": 5}
    events = as_list(row.get("round_kill_events"))

    for ev in sorted([x for x in events if isinstance(x, dict)], key=lambda x: safe_int(x.get("tick")) or 0):
        tick = safe_int(ev.get("tick"))
        if focus_tick is not None and tick is not None and tick >= focus_tick:
            continue
        victim_side = str(ev.get("victim_side") or "").lower()
        if victim_side in alive and alive[victim_side] > 0:
            alive[victim_side] -= 1

    player_side = str(row.get("player_side") or "").lower()
    enemy_side = "ct" if player_side == "t" else "t" if player_side == "ct" else "unknown"

    own_alive = alive.get(player_side) if player_side in alive else None
    enemy_alive = alive.get(enemy_side) if enemy_side in alive else None
    alive_delta = None
    if own_alive is not None and enemy_alive is not None:
        alive_delta = own_alive - enemy_alive

    return {
        "t_alive_before_focus": alive["t"],
        "ct_alive_before_focus": alive["ct"],
        "player_side": player_side or "unknown",
        "enemy_side": enemy_side,
        "own_alive_before_focus": own_alive,
        "enemy_alive_before_focus": enemy_alive,
        "alive_delta_before_focus": alive_delta,
        "limitations": [
            "alive state is reconstructed from kill events before focus tick",
            "does not include exact spatial support or line-of-sight support",
        ],
    }


def infer_pressure(row: Dict[str, Any], phase: Dict[str, Any], alive: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    score = 0

    delta = alive.get("alive_delta_before_focus")
    own_alive = alive.get("own_alive_before_focus")
    player_side = alive.get("player_side")

    if own_alive is not None and own_alive <= 1:
        score += 3
        reasons.append("player team had one alive before focus")
    elif delta is not None and delta <= -3:
        score += 3
        reasons.append(f"large alive disadvantage before focus: {delta}")
    elif delta is not None and delta <= -2:
        score += 2
        reasons.append(f"alive disadvantage before focus: {delta}")
    elif delta is not None and delta <= -1:
        score += 1
        reasons.append(f"slight alive disadvantage before focus: {delta}")

    if phase.get("phase") in {"late_round", "postplant"}:
        score += 1
        reasons.append(f"phase pressure: {phase.get('phase')}")

    if player_side == "ct" and intent.get("plan_family") == "execute" and str(intent.get("confidence")) in {"medium", "high"}:
        score += 1
        reasons.append("enemy execute pressure inferred with medium/high confidence")

    if player_side == "t" and not row.get("has_plant") and phase.get("phase") == "late_round":
        score += 1
        reasons.append("T side late round without plant")

    if score >= 4:
        level = "critical"
    elif score >= 3:
        level = "high"
    elif score >= 1:
        level = "medium"
    else:
        level = "low"

    return {
        "pressure_level": level,
        "pressure_score_v0_1": score,
        "reasons": reasons,
        "limitations": [
            "pressure is heuristic, not a real coach verdict",
            "does not know economy, comms, exact spacing, or player intent",
        ],
    }


def active_weapon_context(mechanics_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    weapons = []
    for ev in mechanics_events:
        snapshot = ev.get("player_snapshot") if isinstance(ev, dict) else None
        weapon = snapshot.get("active_weapon") if isinstance(snapshot, dict) else None
        if weapon and weapon not in weapons:
            weapons.append(str(weapon))
    return {
        "active_weapons_near_mechanics_events": weapons,
        "c4_observed_near_mechanics_event": any("c4" in w.lower() or "explosive" in w.lower() for w in weapons),
    }


def likely_enemy_zones(info_summary: Dict[str, Any], intent: Dict[str, Any]) -> List[Dict[str, Any]]:
    zones: List[Dict[str, Any]] = []

    def add(area: Any, source: str, confidence: Any, tick: Any = None, enemy: Any = None, freshness: Any = None) -> None:
        if area in (None, "", [], {}):
            return
        item = {
            "area": str(area),
            "source": source,
            "confidence": str(confidence or "unknown"),
        }
        if tick is not None:
            item["tick"] = tick
        if enemy:
            item["enemy"] = enemy
        if freshness:
            item["freshness"] = freshness
        signature = (item["area"], item.get("enemy"), item["source"])
        existing = {(x["area"], x.get("enemy"), x["source"]) for x in zones}
        if signature not in existing:
            zones.append(item)

    add(intent.get("primary_area"), "enemy_intent.primary_area", intent.get("confidence"))
    add(intent.get("bombsite"), "enemy_intent.bombsite", intent.get("confidence"))

    death_samples = as_list(info_summary.get("death_snapshots_sample"))
    samples = death_samples or as_list(info_summary.get("focus_snapshots_sample"))
    for snap in samples[:3]:
        if not isinstance(snap, dict):
            continue
        last = snap.get("opponent_last_known")
        if isinstance(last, dict):
            add(
                last.get("area"),
                f"info_state.{last.get('source') or 'last_known'}",
                last.get("confidence"),
                tick=last.get("last_tick"),
                enemy=last.get("enemy"),
                freshness=last.get("freshness"),
            )
        for known in as_list(snap.get("known_enemies_before_event"))[:5]:
            if isinstance(known, dict):
                add(
                    known.get("area"),
                    f"info_state.{known.get('source') or 'known_enemy'}",
                    known.get("confidence"),
                    tick=known.get("last_tick"),
                    enemy=known.get("enemy"),
                    freshness=known.get("freshness"),
                )

    return zones[:12]


def trade_support_assessment(trade_rows: List[Dict[str, Any]], focus_tick: Optional[int]) -> Dict[str, Any]:
    player_events = [r for r in trade_rows if str(r.get("player_focus") or "") not in {"", "none"}]
    death_events = [r for r in player_events if r.get("player_role") == "victim"]
    kill_traded_events = [r for r in player_events if r.get("player_focus") == "player_kill_traded_by_enemy"]

    focus_death = None
    if death_events:
        if focus_tick is not None:
            focus_death = min(death_events, key=lambda x: abs((safe_int(x.get("kill_tick")) or 0) - focus_tick))
        else:
            focus_death = death_events[-1]

    status = "unknown"
    confidence = "low"
    reasons = []

    if focus_death:
        pf = str(focus_death.get("player_focus") or "")
        if pf == "player_death_traded_by_team":
            status = "team_trade_confirmed_after_death"
            confidence = "high"
            reasons.append("trade layer marks player death as traded by team")
        elif pf == "player_death_untraded":
            status = "death_untraded"
            confidence = "medium"
            reasons.append("trade layer marks player death as untraded")
        else:
            status = pf or "player_death_context"
            confidence = "low"
            reasons.append(f"trade layer player_focus={pf}")

    if kill_traded_events:
        reasons.append(f"player kills traded by enemy before/near death: {len(kill_traded_events)}")

    return {
        "trade_support_status": status,
        "trade_support_confidence": confidence,
        "player_focus_events": compact(player_events, limit_list=6, limit_dict_keys=30),
        "reasons": reasons,
        "limitations": [
            "trade layer proves timing of trades, not whether a teammate had a realistic angle",
            "untraded death is not automatically a spacing mistake without spatial support evidence",
        ],
    }


def safe_fallback_assessment(row: Dict[str, Any], info_summary: Dict[str, Any], alive: Dict[str, Any], pressure: Dict[str, Any], trade: Dict[str, Any]) -> Dict[str, Any]:
    death_tick = safe_int(row.get("player_death_tick"))
    if death_tick is None:
        return {
            "safe_fallback_confidence": "unknown",
            "safe_fallback_claim_allowed": False,
            "reasons": ["no player death focus event"],
            "blockers": ["no death event to assess fallback against"],
            "limitations": ["fallback cannot be inferred without focus death/contact context"],
        }

    reasons: List[str] = []
    blockers: List[str] = []
    score = 0

    interpretations = []
    for snap in as_list(info_summary.get("death_snapshots_sample")):
        if isinstance(snap, dict) and isinstance(snap.get("interpretation_v0_2"), dict):
            interpretations.append(snap["interpretation_v0_2"])

    if any(x.get("could_have_rotated_or_repositioned") is True for x in interpretations):
        score += 1
        reasons.append("info_state says rotate/reposition may have been available")
    else:
        blockers.append("info_state does not support rotate/reposition as available")

    if pressure.get("pressure_level") in {"critical", "high"}:
        blockers.append(f"high pressure context: {pressure.get('pressure_level')}")
    elif pressure.get("pressure_level") in {"low", "medium"}:
        score += 1
        reasons.append(f"pressure was not critical/high: {pressure.get('pressure_level')}")

    if alive.get("own_alive_before_focus") is not None and alive.get("own_alive_before_focus") <= 1:
        blockers.append("player was last/near-last alive before focus")

    if trade.get("trade_support_status") == "team_trade_confirmed_after_death":
        score += 1
        reasons.append("team trade existed after death, suggesting some support was nearby/timed")
    elif trade.get("trade_support_status") == "death_untraded":
        blockers.append("death was untraded; spatial support not proven")

    if score >= 3 and not any("last/near-last" in b for b in blockers):
        confidence = "medium"
    elif score >= 1:
        confidence = "low"
    else:
        confidence = "unknown"

    allowed = confidence == "medium"

    return {
        "safe_fallback_confidence": confidence,
        "safe_fallback_claim_allowed": allowed,
        "reasons": reasons,
        "blockers": blockers,
        "limitations": [
            "safe fallback requires map geometry, visibility, and teammate angle evidence; v0.1 only gives a weak proxy",
            "do not convert this into 'bad duel choice' unless claim permission explicitly allows it",
        ],
    }


def infer_player_task(row: Dict[str, Any], phase: Dict[str, Any], intent: Dict[str, Any], weapon_ctx: Dict[str, Any]) -> Dict[str, Any]:
    side = str(row.get("player_side") or "unknown").lower()
    phase_name = phase.get("phase")
    task = "unknown_task"
    confidence = "low"
    reasons: List[str] = []

    if side == "ct":
        if phase_name == "postplant":
            task = "ct_retake_or_save_context"
            confidence = "medium"
            reasons.append("CT side after plant")
        elif intent.get("plan_family") == "execute" and intent.get("bombsite"):
            task = "ct_defend_or_rotate_against_execute"
            confidence = "medium"
            reasons.append("CT side facing inferred execute pressure")
        else:
            task = "ct_hold_or_info_gathering_context"
            confidence = "low"
            reasons.append("CT preplant/nonplant context without exact role")
    elif side == "t":
        if phase_name == "postplant":
            task = "t_postplant_hold_context"
            confidence = "medium"
            reasons.append("T side after plant")
        elif weapon_ctx.get("c4_observed_near_mechanics_event"):
            task = "t_bomb_carrier_entry_or_plant_attempt_context"
            confidence = "medium"
            reasons.append("C4 observed as active weapon near mechanics event")
        elif phase_name == "late_round":
            task = "t_late_round_site_entry_or_contact_context"
            confidence = "low"
            reasons.append("T side late round without exact called strat")
        else:
            task = "t_default_or_pack_contact_context"
            confidence = "low"
            reasons.append("T side preplant/nonplant context without exact role")

    return {
        "player_task_hypothesis": task,
        "confidence": confidence,
        "reasons": reasons,
        "limitations": [
            "task is inferred from side, phase, plant state, C4/mechanics evidence, and enemy intent",
            "does not know actual role assignment or voice comms",
        ],
    }


def build_claim_permissions(ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    mech_flags = Counter()
    for ev in as_list(ctx.get("mechanics_events_sample")):
        for flag in as_list(ev.get("deep_flags") if isinstance(ev, dict) else []):
            mech_flags[str(flag)] += 1

    info_counts = ctx.get("info_state", {}).get("death_info_context_counts") or {}
    trade = ctx.get("trade_support") or {}
    fallback = ctx.get("safe_fallback") or {}
    pressure = ctx.get("pressure") or {}
    weapon_ctx = ctx.get("active_weapon_context") or {}
    postplant = ctx.get("postplant_context") or {}
    intent = ctx.get("enemy_intent") or {}

    perms: Dict[str, Dict[str, Any]] = {}

    if mech_flags.get("movement_risk_at_contact") or mech_flags.get("large_crosshair_offset") or mech_flags.get("moderate_crosshair_offset") or mech_flags.get("no_shot_response_near_event"):
        perms["mechanical_issue"] = permission(
            "allowed",
            "supported",
            "mechanics_deep has movement/crosshair/no-shot flags",
            ["visibility/raycast still limited; keep claim scoped to mechanics evidence"],
        )
    else:
        perms["mechanical_issue"] = permission(
            "limited_or_blocked",
            "limited",
            "no strong mechanics flags found for this round",
            ["may still mention mechanics only as weak context if other evidence supports it"],
        )

    stale_missing = sum(int(info_counts.get(k, 0) or 0) for k in ["stale", "expired", "no_prior_info"])
    fresh_recent = sum(int(info_counts.get(k, 0) or 0) for k in ["fresh", "recent"])
    if stale_missing > 0:
        perms["info_mistake"] = permission(
            "allowed_limited",
            "limited",
            "death info context contains stale/expired/no_prior_info",
            ["info_state is reconstructable demo info, not proof of what player heard/knew"],
        )
    elif fresh_recent > 0:
        perms["info_mistake"] = permission(
            "blocked",
            "unsupported_avoided",
            "death info context was fresh/recent, so do not call it missing-info mistake",
            ["can discuss decision under known pressure instead"],
        )
    else:
        perms["info_mistake"] = permission(
            "blocked",
            "unsupported_avoided",
            "no death info snapshot supports an info mistake",
            ["avoid claiming player should have known something"],
        )

    if fallback.get("safe_fallback_claim_allowed") is True:
        perms["bad_duel_choice"] = permission(
            "allowed_limited",
            "limited",
            "safe_fallback proxy has medium confidence",
            ["must still avoid categorical wording; exact safe fallback is not proven by raycast/map geometry"],
        )
    else:
        perms["bad_duel_choice"] = permission(
            "blocked",
            "unsupported_avoided",
            "safe fallback is not sufficiently supported",
            ["do not write 'bad duel choice', 'unfavorable duel', or 'free death' as a fact"],
        )

    if trade.get("trade_support_status") in {"death_untraded", "team_trade_confirmed_after_death"} or "player_kill_traded_by_enemy" in json.dumps(trade, ensure_ascii=False):
        perms["spacing_issue"] = permission(
            "allowed_limited",
            "limited",
            "trade layer has player-focused trade/spacing timing evidence",
            ["trade timing does not prove teammate had a realistic angle"],
        )
    else:
        perms["spacing_issue"] = permission(
            "limited_or_blocked",
            "limited",
            "no strong player-focused trade evidence",
            ["do not infer spacing from round loss alone"],
        )

    plant_label = str(postplant.get("plant_phase_label") or "")
    if plant_label and plant_label not in {"neutral", ""}:
        perms["postplant_issue"] = permission(
            "allowed_limited",
            "limited",
            f"postplant layer label={plant_label}",
            ["plant phase analyzer is a coarse layer; keep wording limited"],
        )
    else:
        perms["postplant_issue"] = permission(
            "blocked",
            "unsupported_avoided",
            "postplant layer is neutral or absent",
            ["do not create a postplant mistake from unrelated evidence"],
        )

    if weapon_ctx.get("c4_observed_near_mechanics_event"):
        perms["c4_safety_issue"] = permission(
            "allowed_limited",
            "limited",
            "C4 was observed as active weapon near a mechanics/contact event",
            ["do not generalize to grenades unless grenade evidence is explicit"],
        )
    else:
        perms["c4_safety_issue"] = permission(
            "blocked",
            "unsupported_avoided",
            "C4 not observed in tactical/mechanics context",
            ["avoid C4 safety claims without active C4 evidence"],
        )

    if intent.get("likely_enemy_plan"):
        max_strength = "hypothesis" if intent.get("confidence") in {"low", "medium"} else "limited"
        perms["enemy_intent_claim"] = permission(
            "allowed_as_hypothesis",
            max_strength,
            "enemy intent layer has likely_enemy_plan",
            ["enemy intent is always inferred from observable events, not enemy thoughts"],
        )
    else:
        perms["enemy_intent_claim"] = permission(
            "blocked",
            "unsupported_avoided",
            "enemy intent layer has no likely plan",
            ["avoid inventing enemy plan"],
        )

    perms["tactical_task_claim"] = permission(
        "allowed_as_hypothesis",
        "hypothesis",
        "player task is inferred from tactical_context_v0_1",
        ["do not state inferred task as called role or team plan"],
    )

    if pressure.get("pressure_level") in {"critical", "high"}:
        perms["decision_error_strength_cap"] = permission(
            "cap_to_limited_or_hypothesis",
            "limited",
            f"pressure level is {pressure.get('pressure_level')}",
            ["high pressure reduces confidence that a clean alternative existed"],
        )
    else:
        perms["decision_error_strength_cap"] = permission(
            "normal_cap",
            "limited",
            f"pressure level is {pressure.get('pressure_level')}",
            ["decision claims still require explicit evidence"],
        )

    return perms


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player

    analysis_dir = root / "data" / "analysis" / match_id
    layers_dir = root / "data" / "layers" / match_id

    round_timeline_path = latest_file(layers_dir, f"canonical_round_timeline_{player}_v*.json")
    decision_context_path = analysis_dir / "decision_context_current.json"
    enemy_intent_path = analysis_dir / "enemy_intent_current.json"
    mechanics_path = analysis_dir / "mechanics_deep_current.json"
    trade_path = latest_file(layers_dir, f"canonical_trade_layer_{player}_v*.json")
    postplant_path = latest_file(analysis_dir, f"postplant_retake_{player}_v*.json")

    missing = [
        str(p) for p in [round_timeline_path, decision_context_path, enemy_intent_path, mechanics_path, trade_path]
        if p is None or not Path(p).exists()
    ]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + "; ".join(missing))

    round_timeline = load_json(round_timeline_path) or {}
    decision_context = load_json(decision_context_path) or {}
    enemy_intent = load_json(enemy_intent_path) or {}
    mechanics = load_json(mechanics_path) or {}
    trade_layer = load_json(trade_path) or {}
    postplant = load_json(postplant_path) or {}

    timeline_by_round = first_by_round(as_list(round_timeline.get("rows")))
    decision_by_round = first_by_round(as_list(decision_context.get("decision_rounds")))
    intent_by_round = first_by_round(as_list(enemy_intent.get("round_intents")))
    mechanics_by_round = group_by_round(as_list(mechanics.get("deep_events")))
    trade_by_round = group_by_round(as_list(trade_layer.get("rows")))
    postplant_by_round = first_by_round(as_list(postplant.get("rows")))

    review_rounds: List[int] = []
    for item in as_list((decision_context.get("summary") or {}).get("top_review_rounds")):
        rn = safe_int(pick(item, ["round_num", "round"])) if isinstance(item, dict) else safe_int(item)
        if rn is not None and rn not in review_rounds:
            review_rounds.append(rn)
    if not review_rounds:
        review_rounds = sorted(decision_by_round.keys())[:12]

    rows: List[Dict[str, Any]] = []
    permission_rows: List[Dict[str, Any]] = []

    for rn in sorted(timeline_by_round.keys()):
        row = timeline_by_round[rn]
        decision = decision_by_round.get(rn, {})
        intent = intent_by_round.get(rn, {})
        mechanics_events = mechanics_by_round.get(rn, [])
        trade_rows = trade_by_round.get(rn, [])
        postplant_row = postplant_by_round.get(rn, {})

        focus_tick = focus_tick_from_round(row)
        phase = infer_round_phase(row, focus_tick)
        alive = alive_state_before_focus(row, focus_tick)
        pressure = infer_pressure(row, phase, alive, intent)
        weapon_ctx = active_weapon_context(mechanics_events)
        zones = likely_enemy_zones(decision.get("info_state") or {}, intent)
        trade = trade_support_assessment(trade_rows, focus_tick)
        fallback = safe_fallback_assessment(row, decision.get("info_state") or {}, alive, pressure, trade)
        task = infer_player_task(row, phase, intent, weapon_ctx)

        ctx = {
            "round_num": rn,
            "is_review_round": rn in review_rounds,
            "round_result": row.get("player_round_result"),
            "player_side": row.get("player_side"),
            "round_phase": phase,
            "player_task": task,
            "pressure": pressure,
            "alive_state_before_focus": alive,
            "enemy_intent": {
                "likely_enemy_plan": intent.get("likely_enemy_plan"),
                "plan_family": intent.get("plan_family"),
                "confidence": intent.get("confidence"),
                "primary_area": intent.get("primary_area"),
                "bombsite": intent.get("bombsite"),
                "plant_phase": intent.get("plant_phase"),
                "quality_flags": intent.get("quality_flags", []),
            },
            "likely_enemy_zones": zones,
            "info_state": {
                "death_info_context_counts": (decision.get("info_state") or {}).get("death_info_context_counts"),
                "all_info_context_counts": (decision.get("info_state") or {}).get("all_info_context_counts"),
                "death_snapshots_sample": compact((decision.get("info_state") or {}).get("death_snapshots_sample", []), limit_list=2, limit_dict_keys=40),
            },
            "active_weapon_context": weapon_ctx,
            "trade_support": trade,
            "safe_fallback": fallback,
            "postplant_context": {
                "plant_phase_label": postplant_row.get("plant_phase_label"),
                "plant_phase_score": postplant_row.get("plant_phase_score"),
                "categories": postplant_row.get("categories", []),
                "reasons": postplant_row.get("reasons", []),
            },
            "mechanics_events_sample": compact(mechanics_events, limit_list=4, limit_dict_keys=50),
            "source_decision_label": decision.get("decision_label"),
            "source_decision_confidence": decision.get("decision_confidence"),
            "limitations_v0_1": [
                "No raycast/visibility proof.",
                "No voice comms or player intention data.",
                "Safe fallback is only a weak proxy; do not use it as fact unless permission allows it.",
                "Player task is a hypothesis, not assigned team role.",
            ],
        }
        ctx["claim_permissions"] = build_claim_permissions(ctx)
        rows.append(ctx)

        permission_rows.append({
            "round_num": rn,
            "is_review_round": rn in review_rounds,
            "round_result": row.get("player_round_result"),
            "player_side": row.get("player_side"),
            "round_phase": phase.get("phase"),
            "pressure_level": pressure.get("pressure_level"),
            "player_task_hypothesis": task.get("player_task_hypothesis"),
            "safe_fallback_confidence": fallback.get("safe_fallback_confidence"),
            "trade_support_status": trade.get("trade_support_status"),
            "bad_duel_choice": ctx["claim_permissions"]["bad_duel_choice"],
            "info_mistake": ctx["claim_permissions"]["info_mistake"],
            "mechanical_issue": ctx["claim_permissions"]["mechanical_issue"],
            "spacing_issue": ctx["claim_permissions"]["spacing_issue"],
            "postplant_issue": ctx["claim_permissions"]["postplant_issue"],
            "c4_safety_issue": ctx["claim_permissions"]["c4_safety_issue"],
        })

    summary = {
        "version": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "rounds_total": len(rows),
        "review_rounds_total": sum(1 for r in rows if r.get("is_review_round")),
        "phase_counts": dict(Counter((r.get("round_phase") or {}).get("phase") for r in rows)),
        "pressure_counts": dict(Counter((r.get("pressure") or {}).get("pressure_level") for r in rows)),
        "bad_duel_choice_permission_counts": dict(Counter(((r.get("claim_permissions") or {}).get("bad_duel_choice") or {}).get("status") for r in rows)),
        "info_mistake_permission_counts": dict(Counter(((r.get("claim_permissions") or {}).get("info_mistake") or {}).get("status") for r in rows)),
        "mechanical_issue_permission_counts": dict(Counter(((r.get("claim_permissions") or {}).get("mechanical_issue") or {}).get("status") for r in rows)),
        "known_limitations_v0_1": [
            "This layer is a conservative tactical scaffold, not a final coach verdict.",
            "bad_duel_choice should remain blocked unless safe_fallback proxy is at least medium and later judge agrees.",
            "No geometry/raycast/voice comms/economy model is used yet.",
        ],
    }

    tactical_payload = {
        "meta": {
            "version": ANALYZER_VERSION,
            "generated_at_utc": utc_now(),
            "match_id": match_id,
            "player": player,
            "purpose": "Round tactical context scaffold for claim permission and LLM grounding.",
        },
        "summary": summary,
        "round_contexts": rows,
        "source_files": {
            "round_timeline": rel(round_timeline_path, root),
            "decision_context": rel(decision_context_path, root),
            "enemy_intent": rel(enemy_intent_path, root),
            "mechanics_deep": rel(mechanics_path, root),
            "trade_layer": rel(trade_path, root),
            "postplant": rel(postplant_path, root),
        },
    }

    claim_payload = {
        "meta": {
            "version": "claim_permission_layer_v0_1",
            "generated_at_utc": utc_now(),
            "match_id": match_id,
            "player": player,
            "source_layer": ANALYZER_VERSION,
            "purpose": "Explicit allow/block/cap decisions for claim types before LLM report generation.",
        },
        "summary": {
            "rounds_total": len(permission_rows),
            "review_rounds_total": sum(1 for r in permission_rows if r.get("is_review_round")),
            "bad_duel_choice_permission_counts": summary["bad_duel_choice_permission_counts"],
            "info_mistake_permission_counts": summary["info_mistake_permission_counts"],
            "mechanical_issue_permission_counts": summary["mechanical_issue_permission_counts"],
        },
        "round_permissions": permission_rows,
        "source_files": {
            "tactical_context": f"data/analysis/{match_id}/tactical_context_{player}_v0_1.json",
        },
    }

    out_tactical = analysis_dir / f"tactical_context_{player}_v0_1.json"
    out_tactical_current = analysis_dir / "tactical_context_current.json"
    out_tactical_csv = analysis_dir / f"tactical_context_{player}_v0_1.csv"

    out_permissions = analysis_dir / f"claim_permissions_{player}_v0_1.json"
    out_permissions_current = analysis_dir / "claim_permissions_current.json"
    out_permissions_csv = analysis_dir / f"claim_permissions_{player}_v0_1.csv"

    write_json(out_tactical, tactical_payload)
    write_json(out_tactical_current, tactical_payload)
    write_json(out_permissions, claim_payload)
    write_json(out_permissions_current, claim_payload)

    tactical_fields = [
        "round_num", "is_review_round", "round_result", "player_side", "round_phase",
        "player_task", "pressure", "alive_state_before_focus", "safe_fallback",
        "trade_support", "likely_enemy_zones", "source_decision_label", "source_decision_confidence",
    ]
    write_csv(out_tactical_csv, rows, tactical_fields)

    permission_fields = [
        "round_num", "is_review_round", "round_result", "player_side", "round_phase", "pressure_level",
        "player_task_hypothesis", "safe_fallback_confidence", "trade_support_status",
        "bad_duel_choice", "info_mistake", "mechanical_issue", "spacing_issue", "postplant_issue", "c4_safety_issue",
    ]
    write_csv(out_permissions_csv, permission_rows, permission_fields)

    return {
        "status": "ok",
        "analyzer": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "rounds_total": len(rows),
        "review_rounds_total": summary["review_rounds_total"],
        "phase_counts": summary["phase_counts"],
        "pressure_counts": summary["pressure_counts"],
        "bad_duel_choice_permission_counts": summary["bad_duel_choice_permission_counts"],
        "created": {
            "tactical_context": rel(out_tactical, root),
            "tactical_context_current": rel(out_tactical_current, root),
            "tactical_context_csv": rel(out_tactical_csv, root),
            "claim_permissions": rel(out_permissions, root),
            "claim_permissions_current": rel(out_permissions_current, root),
            "claim_permissions_csv": rel(out_permissions_csv, root),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
