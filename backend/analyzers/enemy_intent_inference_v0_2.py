import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


ANALYZER_VERSION = "enemy_intent_inference_v0_2"
ASSUMED_TICK_RATE = 64.0


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def version_key(path: Path) -> Tuple[Tuple[int, ...], float, str]:
    name = path.name
    m = re.search(r"_v(\d+)(?:_(\d+))?", name)
    if m:
        version = tuple(int(x) for x in m.groups() if x is not None)
    else:
        version = (-1,)
    return version, path.stat().st_mtime, name


def latest_file(directory: Path, pattern: str) -> Optional[Path]:
    files = [p for p in directory.glob(pattern) if p.is_file()]
    if not files:
        return None
    return max(files, key=version_key)


def read_parquet_optional(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    return pd.read_parquet(path)


def read_csv_optional(path: Optional[Path]) -> Optional[pd.DataFrame]:
    if not path or not path.exists():
        return None
    return pd.read_csv(path)


def clean_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    s = str(value).strip()
    if s.lower() in ("nan", "none", "null", "<na>"):
        return ""
    return s


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return int(float(value))
    except Exception:
        return default


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def norm_name(value: Any) -> str:
    return clean_str(value).lower()


def norm_side(value: Any) -> str:
    s = clean_str(value).lower()
    s = s.replace("counterterrorist", "ct")
    s = s.replace("counter-terrorist", "ct")
    if s in ("ct", "counter_t", "counter-terrorists", "counterterrorists"):
        return "ct"
    if s in ("t", "tt", "terrorist", "terrorists"):
        return "t"
    return s if s in ("ct", "t") else ""


def enemy_side(player_side: str) -> str:
    if player_side == "ct":
        return "t"
    if player_side == "t":
        return "ct"
    return ""


def phase_from_progress(progress: Optional[float]) -> str:
    if progress is None:
        return "unknown"
    if progress < 0.33:
        return "early"
    if progress < 0.66:
        return "mid"
    return "late"


def find_col(columns: List[str], exact: List[str] = None, contains: List[str] = None) -> Optional[str]:
    exact = exact or []
    contains = contains or []
    lower_map = {str(c).lower(): str(c) for c in columns}

    for name in exact:
        key = name.lower()
        if key in lower_map:
            return lower_map[key]

    for needle in contains:
        n = needle.lower()
        for c in columns:
            if n in str(c).lower():
                return str(c)

    return None


def get(row: Dict[str, Any], col: Optional[str], default: Any = None) -> Any:
    if not col:
        return default
    return row.get(col, default)


def cols(df: Optional[pd.DataFrame]) -> List[str]:
    if df is None:
        return []
    return [str(c) for c in df.columns]


def detect_cols(df: Optional[pd.DataFrame], kind: str) -> Dict[str, Optional[str]]:
    c = cols(df)

    if kind == "rounds":
        return {
            "round": find_col(c, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "start_tick": find_col(c, ["start_tick", "round_start_tick", "freeze_end_tick"], ["start_tick", "round_start", "freeze_end"]),
            "freeze_end_tick": find_col(c, ["freeze_end_tick", "freezeEndTick"], ["freeze_end"]),
            "end_tick": find_col(c, ["end_tick", "round_end_tick"], ["end_tick", "round_end"]),
            "plant_tick": find_col(c, ["plant_tick", "bomb_plant_tick"], ["plant_tick", "plant"]),
            "has_plant": find_col(c, ["has_plant", "plant"], ["has_plant"]),
            "bombsite": find_col(c, ["bombsite", "site", "bomb_site"], ["bombsite", "site"]),
            "player_side": find_col(c, ["player_side"], ["player_side"]),
            "result": find_col(c, ["player_round_result", "round_result", "result"], ["result"]),
        }

    if kind in ("kills", "damages"):
        return {
            "round": find_col(c, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "tick": find_col(c, ["tick", "game_tick", "gameTick"], ["tick"]),
            "attacker": find_col(c, ["attacker_name", "attackerName", "attacker"], ["attacker"]),
            "victim": find_col(c, ["victim_name", "victimName", "victim"], ["victim"]),
            "attacker_side": find_col(c, ["attacker_side", "attackerSide", "attacker_team_side"], ["attacker_side", "attackerside"]),
            "victim_side": find_col(c, ["victim_side", "victimSide", "victim_team_side"], ["victim_side", "victimside"]),
            "weapon": find_col(c, ["weapon", "weapon_name", "weaponName"], ["weapon"]),
            "damage": find_col(c, ["damage", "dmg_health", "health_damage", "hp_damage"], ["damage", "dmg"]),
            "place": find_col(c, ["place", "area", "site"], ["place", "area", "site"]),
        }

    if kind == "utility":
        return {
            "round": find_col(c, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "tick": find_col(c, ["tick", "start_tick", "throw_tick", "game_tick", "gameTick"], ["tick"]),
            "event_kind": find_col(c, ["event_kind", "kind"], ["event_kind", "kind"]),
            "player": find_col(c, ["player", "player_name", "thrower", "thrower_name", "owner"], ["player", "thrower", "owner"]),
            "side": find_col(c, ["player_side", "side", "team_side"], ["side"]),
            "grenade_type": find_col(c, ["grenade_type", "utility_type", "type"], ["grenade", "utility", "type"]),
            "place": find_col(c, ["place", "area", "site"], ["place", "area", "site"]),
        }

    if kind == "bomb":
        return {
            "round": find_col(c, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "tick": find_col(c, ["tick", "game_tick", "gameTick"], ["tick"]),
            "player": find_col(c, ["player_name", "playerName", "player"], ["player"]),
            "side": find_col(c, ["player_side", "side", "team_side"], ["side"]),
            "event": find_col(c, ["event", "bomb_event", "bombEvent", "event_name"], ["event", "plant", "defuse", "bomb"]),
            "site": find_col(c, ["site", "bombsite", "bomb_site"], ["site"]),
            "place": find_col(c, ["place", "area"], ["place", "area"]),
        }

    return {}


def build_player_side_index(dfs: Dict[str, Optional[pd.DataFrame]]) -> Dict[Tuple[int, str], str]:
    out: Dict[Tuple[int, str], str] = {}

    for kind in ("kills", "damages"):
        df = dfs.get(kind)
        if df is None:
            continue

        dcols = detect_cols(df, kind)

        for _, row in df.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, dcols.get("round")))
            if rn is None:
                continue

            attacker = clean_str(get(d, dcols.get("attacker")))
            victim = clean_str(get(d, dcols.get("victim")))
            attacker_side = norm_side(get(d, dcols.get("attacker_side")))
            victim_side = norm_side(get(d, dcols.get("victim_side")))

            if attacker and attacker_side:
                out[(rn, norm_name(attacker))] = attacker_side
            if victim and victim_side:
                out[(rn, norm_name(victim))] = victim_side

    return out


def infer_actor_side(round_num: int, actor: str, explicit_side: Any, side_index: Dict[Tuple[int, str], str]) -> str:
    side = norm_side(explicit_side)
    if side:
        return side
    return side_index.get((round_num, norm_name(actor)), "")


def normalize_area(area: Any) -> str:
    s = clean_str(area)
    if not s:
        return "unknown_area"
    return s


def round_progress(tick: Optional[int], start_tick: Optional[int], end_tick: Optional[int]) -> Optional[float]:
    if tick is None or start_tick is None or end_tick is None:
        return None
    span = max(1, end_tick - start_tick)
    return max(0.0, min(1.0, (tick - start_tick) / span))


def top_counter(counter: Counter, limit: int = 5) -> List[Dict[str, Any]]:
    return [{"key": k, "count": v} for k, v in counter.most_common(limit)]


def dominant_area(events: List[Dict[str, Any]], min_count: int = 2) -> Optional[str]:
    c = Counter(e.get("area", "unknown_area") for e in events if e.get("area") and e.get("area") != "unknown_area")
    if not c:
        return None
    area, count = c.most_common(1)[0]
    if count >= min_count:
        return area
    return None


def unique_actors(events: List[Dict[str, Any]]) -> int:
    return len(set(norm_name(e.get("actor")) for e in events if norm_name(e.get("actor"))))


def area_count(events: List[Dict[str, Any]]) -> int:
    return len(set(e.get("area") for e in events if e.get("area") and e.get("area") != "unknown_area"))


def classify_round(ctx: Dict[str, Any]) -> Dict[str, Any]:
    events = ctx["events"]
    utility_events = [e for e in events if e["kind"] == "enemy_utility"]
    contact_events = [e for e in events if e["kind"] in ("enemy_contact", "team_contact", "player_contact")]
    enemy_contact_events = [e for e in events if e["kind"] == "enemy_contact"]
    objective_events = [e for e in events if e["kind"] == "objective"]

    start_tick = ctx.get("start_tick")
    end_tick = ctx.get("end_tick")
    plant_tick = ctx.get("plant_tick")
    has_plant = ctx.get("has_plant")
    bombsite = ctx.get("bombsite") or "unknown_site"

    first_contact_tick = min([e["tick"] for e in contact_events], default=None)
    first_utility_tick = min([e["tick"] for e in utility_events], default=None)

    plant_progress = round_progress(plant_tick, start_tick, end_tick) if plant_tick is not None else None
    first_contact_progress = round_progress(first_contact_tick, start_tick, end_tick) if first_contact_tick is not None else None

    preplant_events = [e for e in events if plant_tick is None or e["tick"] < plant_tick]
    postplant_events = [e for e in events if plant_tick is not None and e["tick"] >= plant_tick]

    preplant_utility = [e for e in utility_events if plant_tick is None or e["tick"] < plant_tick]
    preplant_contacts = [e for e in contact_events if plant_tick is None or e["tick"] < plant_tick]
    preplant_enemy_contacts = [e for e in enemy_contact_events if plant_tick is None or e["tick"] < plant_tick]

    early_cut = None
    late_cut = None
    if start_tick is not None and end_tick is not None:
        early_cut = start_tick + int((end_tick - start_tick) * 0.33)
        late_cut = start_tick + int((end_tick - start_tick) * 0.66)

    early_utility = [e for e in preplant_utility if early_cut is not None and e["tick"] <= early_cut]
    early_contacts = [e for e in preplant_contacts if early_cut is not None and e["tick"] <= early_cut]
    late_contacts = [e for e in preplant_contacts if late_cut is not None and e["tick"] >= late_cut]

    window_before_plant = []
    if plant_tick is not None:
        window_start = plant_tick - int(20 * ASSUMED_TICK_RATE)
        window_before_plant = [e for e in preplant_events if e["tick"] >= window_start]

    burst_utility_before_plant = [e for e in window_before_plant if e["kind"] == "enemy_utility"]
    contacts_before_plant_window = [e for e in window_before_plant if e["kind"] in ("enemy_contact", "team_contact", "player_contact")]
    enemy_contacts_before_plant_window = [e for e in window_before_plant if e["kind"] == "enemy_contact"]

    area_counter = Counter(e["area"] for e in preplant_events if e.get("area") and e["area"] != "unknown_area")
    utility_area_counter = Counter(e["area"] for e in preplant_utility if e.get("area") and e["area"] != "unknown_area")
    contact_area_counter = Counter(e["area"] for e in preplant_contacts if e.get("area") and e["area"] != "unknown_area")
    enemy_contact_area_counter = Counter(e["area"] for e in preplant_enemy_contacts if e.get("area") and e["area"] != "unknown_area")

    distinct_preplant_areas = len(area_counter)
    distinct_contact_areas = len(contact_area_counter)
    distinct_enemy_contact_areas = len(enemy_contact_area_counter)
    distinct_utility_areas = len(utility_area_counter)

    preplant_unique_enemy_actors = unique_actors([e for e in preplant_events if e.get("actor_side") == ctx.get("enemy_side")])
    window_unique_enemy_actors = unique_actors([e for e in window_before_plant if e.get("actor_side") == ctx.get("enemy_side")])

    dominant_contact_area = dominant_area(preplant_contacts)
    dominant_utility_area = dominant_area(preplant_utility)
    dominant_preplant_area = dominant_area(preplant_events)

    evidence = []
    quality_flags = []

    confidence = "low"
    likely_plan = "unknown_low_signal"
    plan_family = "unknown"

    if has_plant:
        primary_area = bombsite if bombsite and bombsite != "unknown_site" else (dominant_preplant_area or "unknown_area")
    else:
        primary_area = dominant_preplant_area or dominant_contact_area or dominant_utility_area or "unknown_area"

    if distinct_contact_areas >= 5 and distinct_utility_areas <= 1:
        quality_flags.append("contact_area_spread_may_be_noisy")

    if not ctx.get("enemy_side"):
        quality_flags.append("enemy_side_unknown")

    if has_plant:
        evidence.append(f"bomb planted/site={bombsite}")

        plant_phase = phase_from_progress(plant_progress)
        evidence.append(f"plant_phase={plant_phase}")

        if plant_progress is not None and plant_progress >= 0.62:
            likely_plan = "late_execute"
            plan_family = "execute"
            confidence = "medium"
            evidence.append("plant happened late in the round")

            if len(burst_utility_before_plant) >= 2:
                evidence.append(f"{len(burst_utility_before_plant)} utility events in 20s before plant")

        elif (
            plant_progress is not None
            and plant_progress <= 0.45
            and len(burst_utility_before_plant) >= 3
            and distinct_utility_areas >= 2
        ):
            likely_plan = "fast_or_mid_utility_execute"
            plan_family = "execute"
            confidence = "high" if len(burst_utility_before_plant) >= 5 else "medium"
            evidence.append(f"{len(burst_utility_before_plant)} utility events shortly before early/mid plant")
            evidence.append(f"utility came from {distinct_utility_areas} areas")

        elif (
            len(contacts_before_plant_window) >= 4
            and area_count(contacts_before_plant_window) >= 2
            and window_unique_enemy_actors >= 2
            and (len(burst_utility_before_plant) >= 2 or distinct_enemy_contact_areas >= 3)
        ):
            likely_plan = "split_or_layered_execute"
            plan_family = "execute"
            confidence = "medium"
            evidence.append(f"{len(contacts_before_plant_window)} contact events in 20s before plant")
            evidence.append(f"{window_unique_enemy_actors} enemy actors involved near plant timing")

        elif len(burst_utility_before_plant) >= 2:
            likely_plan = "site_execute_with_utility"
            plan_family = "execute"
            confidence = "medium"
            evidence.append(f"{len(burst_utility_before_plant)} utility events before plant")

        elif len(contacts_before_plant_window) >= 2 and len(burst_utility_before_plant) <= 1:
            likely_plan = "contact_into_site"
            plan_family = "contact"
            confidence = "medium"
            evidence.append("site plant mostly driven by contact rather than utility")

        else:
            likely_plan = "site_commitment_low_detail"
            plan_family = "execute"
            confidence = "low"
            evidence.append("plant round, but execute detail is weak")

        if len(postplant_events) >= 2:
            evidence.append(f"{len(postplant_events)} post-plant events")

    else:
        primary_area = dominant_preplant_area or dominant_contact_area or dominant_utility_area or "unknown_area"

        if (
            len(preplant_events) >= 8
            and distinct_preplant_areas >= 3
            and preplant_unique_enemy_actors >= 3
            and len(early_contacts) + len(early_utility) >= 2
        ):
            likely_plan = "default_map_control"
            plan_family = "default"
            confidence = "medium"
            evidence.append(f"enemy activity spread across {distinct_preplant_areas} areas")
            evidence.append(f"{preplant_unique_enemy_actors} enemy actors involved")

        elif (
            first_contact_progress is not None
            and first_contact_progress <= 0.35
            and len(preplant_contacts) >= 2
            and len(preplant_utility) <= 2
        ):
            likely_plan = "early_contact_or_pick_attempt"
            plan_family = "pick"
            confidence = "medium"
            evidence.append("early contact with limited utility")

        elif len(preplant_contacts) >= 2 and len(preplant_utility) <= 1:
            likely_plan = "contact_or_pick_play"
            plan_family = "contact"
            confidence = "medium"
            evidence.append("multiple contacts with little utility")

        elif len(preplant_utility) >= 4 and dominant_utility_area:
            likely_plan = "area_pressure_or_fake"
            plan_family = "pressure"
            confidence = "low"
            evidence.append(f"utility concentration around {dominant_utility_area} without plant")

        elif len(preplant_events) >= 4:
            likely_plan = "nonplant_pressure_round"
            plan_family = "pressure"
            confidence = "low"
            evidence.append("some enemy pressure, but no clear execute/default pattern")

        else:
            likely_plan = "unknown_low_signal"
            plan_family = "unknown"
            confidence = "low"
            evidence.append("not enough enemy-side signal")

    if "enemy_side_unknown" in quality_flags:
        confidence = "low"
        evidence.append("enemy side unknown for this round")

    if len(events) < 3:
        confidence = "low"
        quality_flags.append("low_event_count")

    if likely_plan == "split_or_layered_execute" and "contact_area_spread_may_be_noisy" in quality_flags:
        confidence = "low"
        evidence.append("split label downgraded because contact area spread may be noisy")

    if confidence == "high" and len(evidence) < 3:
        confidence = "medium"

    return {
        "likely_enemy_plan": likely_plan,
        "plan_family": plan_family,
        "confidence": confidence,
        "primary_area": primary_area,
        "bombsite": bombsite,
        "has_plant": bool(has_plant),
        "plant_phase": phase_from_progress(plant_progress),
        "metrics": {
            "events_total": len(events),
            "utility_events_total": len(utility_events),
            "contact_events_total": len(contact_events),
            "enemy_contact_events_total": len(enemy_contact_events),
            "preplant_utility_total": len(preplant_utility),
            "preplant_contact_total": len(preplant_contacts),
            "preplant_enemy_contact_total": len(preplant_enemy_contacts),
            "burst_utility_before_plant_20s": len(burst_utility_before_plant),
            "contacts_before_plant_20s": len(contacts_before_plant_window),
            "enemy_contacts_before_plant_20s": len(enemy_contacts_before_plant_window),
            "preplant_unique_enemy_actors": preplant_unique_enemy_actors,
            "window_unique_enemy_actors": window_unique_enemy_actors,
            "distinct_preplant_areas": distinct_preplant_areas,
            "distinct_contact_areas": distinct_contact_areas,
            "distinct_enemy_contact_areas": distinct_enemy_contact_areas,
            "distinct_utility_areas": distinct_utility_areas,
            "first_contact_tick": first_contact_tick,
            "first_utility_tick": first_utility_tick,
            "plant_tick": plant_tick,
            "plant_progress": round(plant_progress, 3) if plant_progress is not None else None,
            "first_contact_progress": round(first_contact_progress, 3) if first_contact_progress is not None else None,
        },
        "area_profile": {
            "top_areas": top_counter(area_counter),
            "top_contact_areas": top_counter(contact_area_counter),
            "top_enemy_contact_areas": top_counter(enemy_contact_area_counter),
            "top_utility_areas": top_counter(utility_area_counter),
            "dominant_contact_area": dominant_contact_area,
            "dominant_utility_area": dominant_utility_area,
            "dominant_preplant_area": dominant_preplant_area,
        },
        "evidence": evidence,
        "reasoning_quality_flags": quality_flags,
    }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player
    player_norm = norm_name(player)

    parsed_dir = root / "data" / "parsed" / match_id
    layers_dir = root / "data" / "layers" / match_id
    analysis_dir = root / "data" / "analysis" / match_id

    warnings: List[str] = []

    rounds_csv = latest_file(layers_dir, f"canonical_round_timeline_{player}_v*.csv")
    utility_csv = latest_file(layers_dir, "canonical_utility_timeline_v*.csv")

    rounds = read_csv_optional(rounds_csv)
    utility = read_csv_optional(utility_csv)
    kills = read_parquet_optional(parsed_dir / "kills.parquet")
    damages = read_parquet_optional(parsed_dir / "damages.parquet")
    bomb = read_parquet_optional(parsed_dir / "bomb.parquet")

    if rounds is None:
        raise FileNotFoundError("MISSING canonical round timeline csv")

    dfs = {
        "kills": kills,
        "damages": damages,
        "bomb": bomb,
        "utility": utility,
    }

    for name, df in dfs.items():
        if df is None:
            warnings.append(f"missing optional source: {name}")

    round_cols = detect_cols(rounds, "rounds")
    side_index = build_player_side_index({"kills": kills, "damages": damages})

    round_contexts: Dict[int, Dict[str, Any]] = {}

    for _, row in rounds.iterrows():
        d = row.to_dict()
        rn = safe_int(get(d, round_cols.get("round")))
        if rn is None:
            continue

        player_side = norm_side(get(d, round_cols.get("player_side")))
        e_side = enemy_side(player_side)

        start_tick = safe_int(get(d, round_cols.get("freeze_end_tick")))
        if start_tick is None:
            start_tick = safe_int(get(d, round_cols.get("start_tick")))

        end_tick = safe_int(get(d, round_cols.get("end_tick")))
        plant_tick = safe_int(get(d, round_cols.get("plant_tick")))
        bombsite = clean_str(get(d, round_cols.get("bombsite")))

        has_plant_raw = get(d, round_cols.get("has_plant"))
        has_plant = False
        if isinstance(has_plant_raw, bool):
            has_plant = has_plant_raw
        elif clean_str(has_plant_raw).lower() in ("true", "1", "yes", "plant", "planted"):
            has_plant = True
        elif plant_tick is not None:
            has_plant = True

        round_contexts[rn] = {
            "round_num": rn,
            "player_side": player_side,
            "enemy_side": e_side,
            "round_result": clean_str(get(d, round_cols.get("result"))),
            "start_tick": start_tick,
            "end_tick": end_tick,
            "plant_tick": plant_tick,
            "has_plant": has_plant,
            "bombsite": bombsite,
            "events": [],
        }

    def add_event(rn: Optional[int], tick: Optional[int], kind: str, actor: str, actor_side: str, area: str, event_type: str, source: str, note: str = "") -> None:
        if rn is None or tick is None:
            return
        if rn not in round_contexts:
            return

        ctx = round_contexts[rn]
        start_tick = ctx.get("start_tick")
        end_tick = ctx.get("end_tick")
        plant_tick = ctx.get("plant_tick")

        progress = round_progress(tick, start_tick, end_tick)
        phase = "postplant" if plant_tick is not None and tick >= plant_tick else phase_from_progress(progress)

        ctx["events"].append({
            "tick": int(tick),
            "time_sec_assumed": round(int(tick) / ASSUMED_TICK_RATE, 3),
            "kind": kind,
            "event_type": event_type,
            "source": source,
            "actor": actor,
            "actor_side": actor_side,
            "area": normalize_area(area),
            "phase": phase,
            "progress": round(progress, 3) if progress is not None else None,
            "note": note,
        })

    if kills is not None:
        c = detect_cols(kills, "kills")

        for i, row in kills.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None or rn not in round_contexts:
                continue

            ctx = round_contexts[rn]
            e_side = ctx.get("enemy_side")
            if not e_side:
                continue

            attacker = clean_str(get(d, c.get("attacker")))
            victim = clean_str(get(d, c.get("victim")))
            attacker_side = infer_actor_side(rn, attacker, get(d, c.get("attacker_side")), side_index)
            victim_side = infer_actor_side(rn, victim, get(d, c.get("victim_side")), side_index)
            area = clean_str(get(d, c.get("place")))
            weapon = clean_str(get(d, c.get("weapon")))

            if attacker_side == e_side:
                add_event(rn, tick, "enemy_contact", attacker, attacker_side, area, "enemy_kill", "kills", f"victim={victim}; weapon={weapon}")

            if victim_side == e_side:
                add_event(rn, tick, "team_contact", victim, victim_side, area, "enemy_died", "kills", f"attacker={attacker}; weapon={weapon}")

            if norm_name(attacker) == player_norm or norm_name(victim) == player_norm:
                opponent = victim if norm_name(attacker) == player_norm else attacker
                opponent_side = victim_side if norm_name(attacker) == player_norm else attacker_side
                add_event(rn, tick, "player_contact", opponent, opponent_side, area, "player_kill_or_death", "kills", f"weapon={weapon}")

    if damages is not None:
        c = detect_cols(damages, "damages")

        for i, row in damages.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None or rn not in round_contexts:
                continue

            ctx = round_contexts[rn]
            e_side = ctx.get("enemy_side")
            if not e_side:
                continue

            damage = safe_float(get(d, c.get("damage")), 0.0)
            if damage is not None and damage < 25:
                continue

            attacker = clean_str(get(d, c.get("attacker")))
            victim = clean_str(get(d, c.get("victim")))
            attacker_side = infer_actor_side(rn, attacker, get(d, c.get("attacker_side")), side_index)
            victim_side = infer_actor_side(rn, victim, get(d, c.get("victim_side")), side_index)
            area = clean_str(get(d, c.get("place")))

            if attacker_side == e_side:
                add_event(rn, tick, "enemy_contact", attacker, attacker_side, area, "enemy_damage", "damages", f"victim={victim}; damage={damage}")

            if victim_side == e_side:
                add_event(rn, tick, "team_contact", victim, victim_side, area, "enemy_damaged", "damages", f"attacker={attacker}; damage={damage}")

            if norm_name(attacker) == player_norm or norm_name(victim) == player_norm:
                opponent = victim if norm_name(attacker) == player_norm else attacker
                opponent_side = victim_side if norm_name(attacker) == player_norm else attacker_side
                add_event(rn, tick, "player_contact", opponent, opponent_side, area, "player_damage_context", "damages", f"damage={damage}")

    if utility is not None:
        c = detect_cols(utility, "utility")
        seen = set()

        for i, row in utility.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None or rn not in round_contexts:
                continue

            ctx = round_contexts[rn]
            e_side = ctx.get("enemy_side")
            if not e_side:
                continue

            actor = clean_str(get(d, c.get("player")))
            actor_side = infer_actor_side(rn, actor, get(d, c.get("side")), side_index)
            if actor_side != e_side:
                continue

            event_kind = clean_str(get(d, c.get("event_kind")))
            grenade_type = clean_str(get(d, c.get("grenade_type")))
            area = clean_str(get(d, c.get("place")))

            key = (rn, tick, norm_name(actor), event_kind, grenade_type, area)
            if key in seen:
                continue
            seen.add(key)

            add_event(rn, tick, "enemy_utility", actor, actor_side, area, "enemy_utility", "canonical_utility_timeline", f"event_kind={event_kind}; grenade_type={grenade_type}")

    if bomb is not None:
        c = detect_cols(bomb, "bomb")

        for i, row in bomb.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None or rn not in round_contexts:
                continue

            actor = clean_str(get(d, c.get("player")))
            actor_side = infer_actor_side(rn, actor, get(d, c.get("side")), side_index)
            event = clean_str(get(d, c.get("event"))).lower()
            site = clean_str(get(d, c.get("site")))
            area = clean_str(get(d, c.get("place"))) or site

            if "plant" in event or "defuse" in event or "bomb" in event:
                add_event(rn, tick, "objective", actor, actor_side, area, "objective_event", "bomb", f"event={event}; site={site}")

    round_intents: List[Dict[str, Any]] = []

    for rn in sorted(round_contexts.keys()):
        ctx = round_contexts[rn]
        ctx["events"].sort(key=lambda e: (e["tick"], e["kind"], e["event_type"]))
        inferred = classify_round(ctx)

        review_weight = 0
        if inferred["confidence"] == "high":
            review_weight += 3
        elif inferred["confidence"] == "medium":
            review_weight += 2
        else:
            review_weight += 1

        if inferred["has_plant"]:
            review_weight += 2

        if inferred["likely_enemy_plan"] in ("split_or_layered_execute", "late_execute", "contact_into_site", "default_map_control"):
            review_weight += 2

        if inferred["reasoning_quality_flags"]:
            review_weight -= 1

        review_weight = max(1, review_weight)

        round_intents.append({
            "round_num": rn,
            "player_side": ctx.get("player_side"),
            "enemy_side": ctx.get("enemy_side"),
            "round_result": ctx.get("round_result"),
            "likely_enemy_plan": inferred["likely_enemy_plan"],
            "plan_family": inferred["plan_family"],
            "confidence": inferred["confidence"],
            "primary_area": inferred["primary_area"],
            "bombsite": inferred["bombsite"],
            "has_plant": inferred["has_plant"],
            "plant_phase": inferred["plant_phase"],
            "review_weight": review_weight,
            "metrics": inferred["metrics"],
            "area_profile": inferred["area_profile"],
            "evidence": inferred["evidence"],
            "reasoning_quality_flags": inferred["reasoning_quality_flags"],
            "events_sample": ctx["events"][:20],
            "known_limitations": [
                "enemy intent is inferred from observable demo events, not actual enemy comms",
                "area/place labels depend on parser/canonical layer quality",
                "split labels are conservative and downgraded when area spread looks noisy"
            ],
        })

    plan_counts = Counter(x["likely_enemy_plan"] for x in round_intents)
    family_counts = Counter(x["plan_family"] for x in round_intents)
    confidence_counts = Counter(x["confidence"] for x in round_intents)
    plant_phase_counts = Counter(x["plant_phase"] for x in round_intents if x["plant_phase"])
    quality_flag_counts = Counter(flag for x in round_intents for flag in x.get("reasoning_quality_flags", []))

    top_review_rounds = sorted(
        round_intents,
        key=lambda x: (x["review_weight"], x["metrics"].get("events_total", 0)),
        reverse=True
    )[:12]

    summary = {
        "version": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "rounds_total": len(round_intents),
        "plan_counts": dict(plan_counts),
        "plan_family_counts": dict(family_counts),
        "confidence_counts": dict(confidence_counts),
        "plant_phase_counts": dict(plant_phase_counts),
        "quality_flag_counts": dict(quality_flag_counts),
        "high_confidence_rounds": [x["round_num"] for x in round_intents if x["confidence"] == "high"],
        "medium_or_high_confidence_rounds": [x["round_num"] for x in round_intents if x["confidence"] in ("medium", "high")],
        "top_review_rounds": [
            {
                "round_num": x["round_num"],
                "likely_enemy_plan": x["likely_enemy_plan"],
                "confidence": x["confidence"],
                "primary_area": x["primary_area"],
                "review_weight": x["review_weight"],
                "quality_flags": x["reasoning_quality_flags"],
                "evidence": x["evidence"],
            }
            for x in top_review_rounds
        ],
        "warnings": warnings,
        "known_limitations_v0_2": [
            "This layer infers likely enemy plan from events; it does not know enemy voice comms.",
            "Split/pressure labels are conservative and may be downgraded if area spread is noisy.",
            "Future versions should use full ticks/view/movement to infer map control, spacing, and executes more precisely.",
        ],
    }

    package = {
        "meta": {
            "version": ANALYZER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "purpose": "conservative enemy plan/intent hypothesis layer for coach reasoning",
        },
        "summary": summary,
        "round_intents": round_intents,
        "source_files": {
            "round_timeline": rel(rounds_csv, root),
            "canonical_utility_timeline": rel(utility_csv, root),
            "kills": rel(parsed_dir / "kills.parquet", root),
            "damages": rel(parsed_dir / "damages.parquet", root),
            "bomb": rel(parsed_dir / "bomb.parquet", root),
        }
    }

    out_json = analysis_dir / f"enemy_intent_{player}_v0_2.json"
    out_current = analysis_dir / "enemy_intent_current.json"
    out_csv = analysis_dir / f"enemy_intent_{player}_v0_2.csv"

    write_json(out_json, package)
    write_json(out_current, package)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "round_num",
            "player_side",
            "enemy_side",
            "round_result",
            "likely_enemy_plan",
            "plan_family",
            "confidence",
            "primary_area",
            "bombsite",
            "has_plant",
            "plant_phase",
            "review_weight",
            "events_total",
            "utility_events_total",
            "contact_events_total",
            "enemy_contact_events_total",
            "preplant_utility_total",
            "preplant_contact_total",
            "preplant_enemy_contact_total",
            "burst_utility_before_plant_20s",
            "contacts_before_plant_20s",
            "window_unique_enemy_actors",
            "preplant_unique_enemy_actors",
            "distinct_preplant_areas",
            "distinct_contact_areas",
            "distinct_enemy_contact_areas",
            "distinct_utility_areas",
            "quality_flags",
            "evidence"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for x in round_intents:
            m = x["metrics"]
            writer.writerow({
                "round_num": x["round_num"],
                "player_side": x["player_side"],
                "enemy_side": x["enemy_side"],
                "round_result": x["round_result"],
                "likely_enemy_plan": x["likely_enemy_plan"],
                "plan_family": x["plan_family"],
                "confidence": x["confidence"],
                "primary_area": x["primary_area"],
                "bombsite": x["bombsite"],
                "has_plant": x["has_plant"],
                "plant_phase": x["plant_phase"],
                "review_weight": x["review_weight"],
                "events_total": m.get("events_total"),
                "utility_events_total": m.get("utility_events_total"),
                "contact_events_total": m.get("contact_events_total"),
                "enemy_contact_events_total": m.get("enemy_contact_events_total"),
                "preplant_utility_total": m.get("preplant_utility_total"),
                "preplant_contact_total": m.get("preplant_contact_total"),
                "preplant_enemy_contact_total": m.get("preplant_enemy_contact_total"),
                "burst_utility_before_plant_20s": m.get("burst_utility_before_plant_20s"),
                "contacts_before_plant_20s": m.get("contacts_before_plant_20s"),
                "window_unique_enemy_actors": m.get("window_unique_enemy_actors"),
                "preplant_unique_enemy_actors": m.get("preplant_unique_enemy_actors"),
                "distinct_preplant_areas": m.get("distinct_preplant_areas"),
                "distinct_contact_areas": m.get("distinct_contact_areas"),
                "distinct_enemy_contact_areas": m.get("distinct_enemy_contact_areas"),
                "distinct_utility_areas": m.get("distinct_utility_areas"),
                "quality_flags": " | ".join(x.get("reasoning_quality_flags", [])),
                "evidence": " | ".join(x.get("evidence", [])),
            })

    return {
        "status": "ok",
        "analyzer": ANALYZER_VERSION,
        "match_id": match_id,
        "player": player,
        "summary": summary,
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "csv": rel(out_csv, root),
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
