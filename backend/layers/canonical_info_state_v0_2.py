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


LAYER_VERSION = "canonical_info_state_v0_2"
ASSUMED_TICK_RATE = 64.0


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Path, root: Path) -> str:
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


def table_columns(df: Optional[pd.DataFrame]) -> List[str]:
    if df is None:
        return []
    return [str(c) for c in df.columns]


def detect_cols(df: Optional[pd.DataFrame], kind: str) -> Dict[str, Optional[str]]:
    cols = table_columns(df)

    if kind in ("kills", "damages"):
        return {
            "round": find_col(cols, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "tick": find_col(cols, ["tick", "game_tick", "gameTick"], ["tick"]),
            "attacker": find_col(cols, ["attacker_name", "attackerName", "attacker"], ["attacker"]),
            "victim": find_col(cols, ["victim_name", "victimName", "victim"], ["victim"]),
            "attacker_side": find_col(cols, ["attacker_side", "attackerSide", "attacker_team_side"], ["attacker_side", "attackerside"]),
            "victim_side": find_col(cols, ["victim_side", "victimSide", "victim_team_side"], ["victim_side", "victimside"]),
            "weapon": find_col(cols, ["weapon", "weapon_name", "weaponName"], ["weapon"]),
            "damage": find_col(cols, ["damage", "dmg_health", "health_damage", "hp_damage"], ["damage", "dmg"]),
            "attacker_x": find_col(cols, ["attacker_x", "attackerX", "attacker_pos_x"], ["attacker_x", "attackerx"]),
            "attacker_y": find_col(cols, ["attacker_y", "attackerY", "attacker_pos_y"], ["attacker_y", "attackery"]),
            "attacker_z": find_col(cols, ["attacker_z", "attackerZ", "attacker_pos_z"], ["attacker_z", "attackerz"]),
            "victim_x": find_col(cols, ["victim_x", "victimX", "victim_pos_x"], ["victim_x", "victimx"]),
            "victim_y": find_col(cols, ["victim_y", "victimY", "victim_pos_y"], ["victim_y", "victimy"]),
            "victim_z": find_col(cols, ["victim_z", "victimZ", "victim_pos_z"], ["victim_z", "victimz"]),
            "place": find_col(cols, ["place", "area", "site"], ["place", "area", "site"]),
        }

    if kind == "bomb":
        return {
            "round": find_col(cols, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "tick": find_col(cols, ["tick", "game_tick", "gameTick"], ["tick"]),
            "player": find_col(cols, ["player_name", "playerName", "player"], ["player"]),
            "side": find_col(cols, ["player_side", "side", "team_side"], ["side"]),
            "event": find_col(cols, ["event", "bomb_event", "bombEvent", "event_name"], ["event", "plant", "defuse", "bomb"]),
            "site": find_col(cols, ["site", "bombsite", "bomb_site"], ["site"]),
            "x": find_col(cols, ["x", "player_x"], ["_x", "x"]),
            "y": find_col(cols, ["y", "player_y"], ["_y", "y"]),
            "z": find_col(cols, ["z", "player_z"], ["_z", "z"]),
            "place": find_col(cols, ["place", "area"], ["place", "area"]),
        }

    if kind == "utility":
        return {
            "round": find_col(cols, ["round_num", "roundNumber", "round_number", "round"], ["round"]),
            "tick": find_col(cols, ["tick", "start_tick", "throw_tick", "game_tick", "gameTick"], ["tick"]),
            "event_kind": find_col(cols, ["event_kind", "kind"], ["event_kind", "kind"]),
            "player": find_col(cols, ["player", "player_name", "thrower", "thrower_name", "owner"], ["player", "thrower", "owner"]),
            "side": find_col(cols, ["player_side", "side", "team_side"], ["side"]),
            "grenade_type": find_col(cols, ["grenade_type", "utility_type", "type"], ["grenade", "utility", "type"]),
            "x": find_col(cols, ["x", "player_x", "thrower_x"], ["_x", "x"]),
            "y": find_col(cols, ["y", "player_y", "thrower_y"], ["_y", "y"]),
            "z": find_col(cols, ["z", "player_z", "thrower_z"], ["_z", "z"]),
            "place": find_col(cols, ["place", "area", "site"], ["place", "area", "site"]),
        }

    return {}


def load_round_sides(root: Path, match_id: str, player: str) -> Dict[int, str]:
    layer_dir = root / "data" / "layers" / match_id
    csv_path = latest_file(layer_dir, f"canonical_round_timeline_{player}_v*.csv")
    if not csv_path:
        return {}

    df = pd.read_csv(csv_path)
    cols = [str(c) for c in df.columns]
    round_col = find_col(cols, ["round_num", "round"], ["round"])
    side_col = find_col(cols, ["player_side"], ["player_side", "side"])

    if not round_col or not side_col:
        return {}

    out: Dict[int, str] = {}
    for _, row in df.iterrows():
        rn = safe_int(row.get(round_col))
        side = norm_side(row.get(side_col))
        if rn is not None and side:
            out[rn] = side

    return out


def build_player_side_index(dfs: Dict[str, Optional[pd.DataFrame]]) -> Dict[Tuple[int, str], str]:
    player_sides: Dict[Tuple[int, str], str] = {}

    for kind in ("kills", "damages"):
        df = dfs.get(kind)
        if df is None:
            continue
        c = detect_cols(df, kind)
        if not c.get("round"):
            continue

        for _, row in df.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            if rn is None:
                continue

            attacker = clean_str(get(d, c.get("attacker")))
            victim = clean_str(get(d, c.get("victim")))
            attacker_side = norm_side(get(d, c.get("attacker_side")))
            victim_side = norm_side(get(d, c.get("victim_side")))

            if attacker and attacker_side:
                player_sides[(rn, norm_name(attacker))] = attacker_side
            if victim and victim_side:
                player_sides[(rn, norm_name(victim))] = victim_side

    return player_sides


def infer_actor_side(round_num: int, actor: str, explicit_side: Any, player_side_index: Dict[Tuple[int, str], str]) -> str:
    side = norm_side(explicit_side)
    if side:
        return side
    return player_side_index.get((round_num, norm_name(actor)), "")


def freshness_from_age(age_sec: Optional[float]) -> str:
    if age_sec is None:
        return "no_prior_info"
    if age_sec <= 3:
        return "fresh"
    if age_sec <= 8:
        return "recent"
    if age_sec <= 20:
        return "stale"
    return "expired"


def confidence_rank(conf: str) -> int:
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
        "unknown": 0,
    }.get(conf, 0)


def add_observation(
    observations: List[Dict[str, Any]],
    event_id: str,
    round_num: Optional[int],
    tick: Optional[int],
    event_kind: str,
    info_subject: str,
    subject_side: str,
    observed_by: str,
    observer_side: str,
    info_source: str,
    confidence: str,
    source_table: str,
    area: str = "",
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None,
    raw_note: str = "",
) -> None:
    if round_num is None or tick is None or not info_subject:
        return

    observations.append({
        "event_id": event_id,
        "round_num": int(round_num),
        "tick": int(tick),
        "time_sec_assumed": round(float(tick) / ASSUMED_TICK_RATE, 3),
        "event_kind": event_kind,
        "source_table": source_table,
        "info_subject": info_subject,
        "subject_side": subject_side,
        "observed_by": observed_by,
        "observer_side": observer_side,
        "info_source": info_source,
        "confidence": confidence,
        "area": area,
        "x": x,
        "y": y,
        "z": z,
        "raw_note": raw_note,
    })


def add_focus_event(
    focus_events: List[Dict[str, Any]],
    event_id: str,
    round_num: Optional[int],
    tick: Optional[int],
    kind: str,
    opponent: str,
    opponent_side: str,
    extra: Dict[str, Any],
) -> None:
    if round_num is None or tick is None or not opponent:
        return
    item = {
        "event_id": event_id,
        "round_num": int(round_num),
        "tick": int(tick),
        "focus_event_kind": kind,
        "opponent": opponent,
        "opponent_side": opponent_side,
    }
    item.update(extra)
    focus_events.append(item)


def build(args: argparse.Namespace) -> Dict[str, Any]:
    root = project_root()
    match_id = args.match_id
    player = args.player
    player_norm = norm_name(player)

    parsed_dir = root / "data" / "parsed" / match_id
    layer_dir = root / "data" / "layers" / match_id
    out_dir = root / "data" / "layers" / match_id

    warnings: List[str] = []

    table_paths = {
        "kills": parsed_dir / "kills.parquet",
        "damages": parsed_dir / "damages.parquet",
        "bomb": parsed_dir / "bomb.parquet",
    }

    dfs = {name: read_parquet_optional(path) for name, path in table_paths.items()}

    utility_csv = latest_file(layer_dir, "canonical_utility_timeline_v*.csv")
    utility_df = read_csv_optional(utility_csv)
    dfs["utility"] = utility_df

    missing = [name for name, df in dfs.items() if df is None]
    if missing:
        warnings.append("missing optional tables/layers: " + ", ".join(missing))

    round_player_side = load_round_sides(root, match_id, player)
    if not round_player_side:
        warnings.append("could not load player side by round from canonical_round_timeline")

    player_side_index = build_player_side_index(dfs)

    observations: List[Dict[str, Any]] = []
    focus_events: List[Dict[str, Any]] = []

    kills = dfs.get("kills")
    if kills is not None:
        c = detect_cols(kills, "kills")

        for i, row in kills.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None:
                continue

            p_side = round_player_side.get(rn, "")
            e_side = enemy_side(p_side)

            attacker = clean_str(get(d, c.get("attacker")))
            victim = clean_str(get(d, c.get("victim")))
            attacker_side = infer_actor_side(rn, attacker, get(d, c.get("attacker_side")), player_side_index)
            victim_side = infer_actor_side(rn, victim, get(d, c.get("victim_side")), player_side_index)
            weapon = clean_str(get(d, c.get("weapon")))
            place = clean_str(get(d, c.get("place")))

            ax = safe_float(get(d, c.get("attacker_x")))
            ay = safe_float(get(d, c.get("attacker_y")))
            az = safe_float(get(d, c.get("attacker_z")))
            vx = safe_float(get(d, c.get("victim_x")))
            vy = safe_float(get(d, c.get("victim_y")))
            vz = safe_float(get(d, c.get("victim_z")))

            event_id = f"kill_{i}"
            attacker_is_player = norm_name(attacker) == player_norm
            victim_is_player = norm_name(victim) == player_norm

            if attacker_is_player and victim:
                add_observation(observations, event_id, rn, tick, "player_kill_contact", victim, victim_side or e_side, "player", p_side, "player_killed_enemy", "high", "kills", place, vx, vy, vz, f"weapon={weapon}")
                add_focus_event(focus_events, event_id, rn, tick, "player_kill", victim, victim_side or e_side, {"weapon": weapon})

            if victim_is_player and attacker:
                add_observation(observations, event_id, rn, tick, "player_death_contact", attacker, attacker_side or e_side, "player", p_side, "enemy_killed_player", "high", "kills", place, ax, ay, az, f"weapon={weapon}")
                add_focus_event(focus_events, event_id, rn, tick, "player_death", attacker, attacker_side or e_side, {"weapon": weapon})

            if p_side and e_side:
                if attacker and attacker_side == e_side and victim_side == p_side:
                    add_observation(observations, event_id, rn, tick, "enemy_killed_teammate", attacker, attacker_side, "player_team", p_side, "killfeed_enemy_position_proxy", "medium", "kills", place, ax, ay, az, f"victim={victim}; weapon={weapon}")

                if victim and victim_side == e_side and attacker_side == p_side:
                    add_observation(observations, event_id, rn, tick, "teammate_killed_enemy", victim, victim_side, "player_team", p_side, "killfeed_enemy_death_position", "high", "kills", place, vx, vy, vz, f"attacker={attacker}; weapon={weapon}")

    damages = dfs.get("damages")
    if damages is not None:
        c = detect_cols(damages, "damages")

        for i, row in damages.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None:
                continue

            p_side = round_player_side.get(rn, "")
            e_side = enemy_side(p_side)

            attacker = clean_str(get(d, c.get("attacker")))
            victim = clean_str(get(d, c.get("victim")))
            attacker_side = infer_actor_side(rn, attacker, get(d, c.get("attacker_side")), player_side_index)
            victim_side = infer_actor_side(rn, victim, get(d, c.get("victim_side")), player_side_index)
            damage = safe_float(get(d, c.get("damage")), 0.0)
            place = clean_str(get(d, c.get("place")))

            ax = safe_float(get(d, c.get("attacker_x")))
            ay = safe_float(get(d, c.get("attacker_y")))
            az = safe_float(get(d, c.get("attacker_z")))
            vx = safe_float(get(d, c.get("victim_x")))
            vy = safe_float(get(d, c.get("victim_y")))
            vz = safe_float(get(d, c.get("victim_z")))

            event_id = f"damage_{i}"
            attacker_is_player = norm_name(attacker) == player_norm
            victim_is_player = norm_name(victim) == player_norm

            if attacker_is_player and victim:
                add_observation(observations, event_id, rn, tick, "player_damaged_enemy", victim, victim_side or e_side, "player", p_side, "player_damage_contact", "medium", "damages", place, vx, vy, vz, f"damage={damage}")
                add_focus_event(focus_events, event_id, rn, tick, "player_damage_dealt", victim, victim_side or e_side, {"damage": damage})

            if victim_is_player and attacker:
                add_observation(observations, event_id, rn, tick, "enemy_damaged_player", attacker, attacker_side or e_side, "player", p_side, "enemy_damage_contact", "medium", "damages", place, ax, ay, az, f"damage={damage}")
                add_focus_event(focus_events, event_id, rn, tick, "player_damage_taken", attacker, attacker_side or e_side, {"damage": damage})

            if p_side and e_side:
                if attacker and attacker_side == e_side and victim_side == p_side:
                    add_observation(observations, event_id, rn, tick, "enemy_damaged_teammate", attacker, attacker_side, "player_team", p_side, "damage_enemy_position_proxy", "medium", "damages", place, ax, ay, az, f"victim={victim}; damage={damage}")

                if victim and victim_side == e_side and attacker_side == p_side:
                    add_observation(observations, event_id, rn, tick, "teammate_damaged_enemy", victim, victim_side, "player_team", p_side, "damage_enemy_hit_position", "medium", "damages", place, vx, vy, vz, f"attacker={attacker}; damage={damage}")

    utility = dfs.get("utility")
    if utility is not None:
        c = detect_cols(utility, "utility")
        used_utility_keys = set()

        for i, row in utility.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None:
                continue

            event_kind = clean_str(get(d, c.get("event_kind")))
            actor = clean_str(get(d, c.get("player")))
            grenade_type = clean_str(get(d, c.get("grenade_type")))
            actor_side = infer_actor_side(rn, actor, get(d, c.get("side")), player_side_index)

            p_side = round_player_side.get(rn, "")
            e_side = enemy_side(p_side)

            if not actor or not e_side or actor_side != e_side:
                continue

            # Canonical utility may include active smoke/fire rows. Keep only one proxy per actor/type/tick/kind.
            dedupe_key = (rn, tick, norm_name(actor), event_kind, grenade_type)
            if dedupe_key in used_utility_keys:
                continue
            used_utility_keys.add(dedupe_key)

            place = clean_str(get(d, c.get("place")))
            x = safe_float(get(d, c.get("x")))
            y = safe_float(get(d, c.get("y")))
            z = safe_float(get(d, c.get("z")))

            confidence = "low"
            if "flash" in grenade_type.lower() or "smoke" in grenade_type.lower() or "inferno" in event_kind.lower():
                confidence = "low"

            add_observation(
                observations,
                f"utility_{i}",
                rn,
                tick,
                "enemy_utility_presence_proxy",
                actor,
                actor_side,
                "player_team",
                p_side,
                "canonical_enemy_utility_proxy",
                confidence,
                "canonical_utility_timeline",
                place,
                x,
                y,
                z,
                f"event_kind={event_kind}; grenade_type={grenade_type}"
            )

    bomb = dfs.get("bomb")
    if bomb is not None:
        c = detect_cols(bomb, "bomb")

        for i, row in bomb.iterrows():
            d = row.to_dict()
            rn = safe_int(get(d, c.get("round")))
            tick = safe_int(get(d, c.get("tick")))
            if rn is None or tick is None:
                continue

            p_side = round_player_side.get(rn, "")
            actor = clean_str(get(d, c.get("player")))
            actor_side = infer_actor_side(rn, actor, get(d, c.get("side")), player_side_index)
            event = clean_str(get(d, c.get("event"))).lower()
            site = clean_str(get(d, c.get("site")))
            place = clean_str(get(d, c.get("place"))) or site
            x = safe_float(get(d, c.get("x")))
            y = safe_float(get(d, c.get("y")))
            z = safe_float(get(d, c.get("z")))

            if "plant" in event or "defuse" in event or "bomb" in event:
                confidence = "high" if "plant" in event or "defuse" in event else "medium"
                subject = actor if actor else f"{event or 'bomb_event'}_actor"
                side = actor_side if actor_side else ("t" if "plant" in event else "")

                add_observation(observations, f"bomb_{i}", rn, tick, "objective_info", subject, side, "player_team", p_side, "objective_event", confidence, "bomb", place, x, y, z, f"event={event}; site={site}")

    observations.sort(key=lambda x: (x["round_num"], x["tick"], x["event_id"]))
    focus_events.sort(key=lambda x: (x["round_num"], x["tick"], x["event_id"]))

    obs_by_round: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        obs_by_round[int(obs["round_num"])].append(obs)

    focus_snapshots: List[Dict[str, Any]] = []

    for focus in focus_events:
        rn = int(focus["round_num"])
        tick = int(focus["tick"])
        opponent = clean_str(focus.get("opponent"))

        last_by_subject: Dict[str, Dict[str, Any]] = {}

        for obs in obs_by_round.get(rn, []):
            obs_tick = int(obs["tick"])

            # Strictly before the focus event. The focus event itself is not prior info.
            if obs_tick >= tick:
                break

            subject_key = norm_name(obs["info_subject"])
            if not subject_key:
                continue

            existing = last_by_subject.get(subject_key)
            if existing is None:
                last_by_subject[subject_key] = obs
            else:
                if obs_tick > int(existing["tick"]):
                    last_by_subject[subject_key] = obs
                elif obs_tick == int(existing["tick"]) and confidence_rank(obs["confidence"]) > confidence_rank(existing["confidence"]):
                    last_by_subject[subject_key] = obs

        known_enemies = []
        for subject_key, obs in last_by_subject.items():
            age_sec = round((tick - int(obs["tick"])) / ASSUMED_TICK_RATE, 3)
            known_enemies.append({
                "enemy": obs["info_subject"],
                "last_tick": obs["tick"],
                "age_sec": age_sec,
                "freshness": freshness_from_age(age_sec),
                "source": obs["info_source"],
                "confidence": obs["confidence"],
                "area": obs.get("area", ""),
                "x": obs.get("x"),
                "y": obs.get("y"),
                "z": obs.get("z"),
            })

        known_enemies.sort(key=lambda x: (x["age_sec"], -confidence_rank(x["confidence"])))

        opponent_key = norm_name(opponent)
        opponent_last = last_by_subject.get(opponent_key)
        opponent_info = None

        if opponent_last:
            age_sec = round((tick - int(opponent_last["tick"])) / ASSUMED_TICK_RATE, 3)
            opponent_info = {
                "enemy": opponent_last["info_subject"],
                "last_tick": opponent_last["tick"],
                "age_sec": age_sec,
                "freshness": freshness_from_age(age_sec),
                "source": opponent_last["info_source"],
                "confidence": opponent_last["confidence"],
                "area": opponent_last.get("area", ""),
                "x": opponent_last.get("x"),
                "y": opponent_last.get("y"),
                "z": opponent_last.get("z"),
            }

        context = opponent_info["freshness"] if opponent_info else "no_prior_info"

        focus_snapshots.append({
            "snapshot_id": f"info_snapshot_{len(focus_snapshots) + 1}",
            "round_num": rn,
            "tick": tick,
            "time_sec_assumed": round(tick / ASSUMED_TICK_RATE, 3),
            "focus_event_id": focus["event_id"],
            "focus_event_kind": focus["focus_event_kind"],
            "opponent": opponent,
            "opponent_side": focus.get("opponent_side", ""),
            "opponent_info_context": context,
            "opponent_last_known": opponent_info,
            "known_enemies_count": len(known_enemies),
            "known_enemies_before_event": known_enemies[:8],
            "interpretation_v0_2": {
                "info_was_actionable": context in ("fresh", "recent"),
                "info_was_stale_or_absent": context in ("stale", "expired", "no_prior_info"),
                "could_have_rotated_or_repositioned": context in ("stale", "expired", "no_prior_info"),
                "note": (
                    "по противнику была свежая/недавняя prior-инфа до события"
                    if context in ("fresh", "recent")
                    else "до события по противнику не было актуальной prior-инфы или она устарела"
                )
            }
        })

    event_kind_counts = Counter(obs["event_kind"] for obs in observations)
    source_counts = Counter(obs["source_table"] for obs in observations)
    confidence_counts = Counter(obs["confidence"] for obs in observations)
    focus_kind_counts = Counter(s["focus_event_kind"] for s in focus_snapshots)
    opponent_context_counts = Counter(s["opponent_info_context"] for s in focus_snapshots)

    player_death_snapshots = [s for s in focus_snapshots if s["focus_event_kind"] == "player_death"]
    death_context_counts = Counter(s["opponent_info_context"] for s in player_death_snapshots)

    summary = {
        "version": LAYER_VERSION,
        "match_id": match_id,
        "player": player,
        "tick_rate_assumed": ASSUMED_TICK_RATE,
        "observations_total": len(observations),
        "focus_snapshots_total": len(focus_snapshots),
        "player_death_snapshots_total": len(player_death_snapshots),
        "event_kind_counts": dict(event_kind_counts),
        "source_counts": dict(source_counts),
        "confidence_counts": dict(confidence_counts),
        "focus_event_kind_counts": dict(focus_kind_counts),
        "opponent_info_context_counts": dict(opponent_context_counts),
        "death_opponent_info_context_counts": dict(death_context_counts),
        "rounds_with_player_side": len(round_player_side),
        "canonical_utility_source": rel(utility_csv, root) if utility_csv else None,
        "warnings": warnings,
        "known_limitations_v0_2": [
            "sound/voice comms are not reconstructed",
            "utility observations are low-confidence presence proxies",
            "snapshot uses only prior observations with tick < focus_event_tick",
            "tick rate is assumed as 64 unless later provided by parser metadata",
            "this estimates what could be known from parsed events, not actual team comms",
        ],
    }

    package = {
        "meta": {
            "version": LAYER_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "match_id": match_id,
            "player": player,
            "purpose": "canonical prior information-state reconstruction for coach reasoning",
        },
        "summary": summary,
        "observations": observations,
        "focus_snapshots": focus_snapshots,
    }

    out_json = out_dir / f"canonical_info_state_{player}_v0_2.json"
    out_csv = out_dir / f"canonical_info_state_{player}_v0_2.csv"
    out_current = out_dir / "canonical_info_state_current.json"

    write_json(out_json, package)
    write_json(out_current, package)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "snapshot_id",
            "round_num",
            "tick",
            "focus_event_kind",
            "opponent",
            "opponent_info_context",
            "opponent_last_tick",
            "opponent_info_age_sec",
            "opponent_info_source",
            "opponent_info_confidence",
            "opponent_info_area",
            "known_enemies_count",
            "info_was_actionable",
            "info_was_stale_or_absent",
            "could_have_rotated_or_repositioned",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for s in focus_snapshots:
            last = s.get("opponent_last_known") or {}
            interp = s.get("interpretation_v0_2") or {}

            writer.writerow({
                "snapshot_id": s.get("snapshot_id"),
                "round_num": s.get("round_num"),
                "tick": s.get("tick"),
                "focus_event_kind": s.get("focus_event_kind"),
                "opponent": s.get("opponent"),
                "opponent_info_context": s.get("opponent_info_context"),
                "opponent_last_tick": last.get("last_tick"),
                "opponent_info_age_sec": last.get("age_sec"),
                "opponent_info_source": last.get("source"),
                "opponent_info_confidence": last.get("confidence"),
                "opponent_info_area": last.get("area"),
                "known_enemies_count": s.get("known_enemies_count"),
                "info_was_actionable": interp.get("info_was_actionable"),
                "info_was_stale_or_absent": interp.get("info_was_stale_or_absent"),
                "could_have_rotated_or_repositioned": interp.get("could_have_rotated_or_repositioned"),
            })

    result = {
        "status": "ok",
        "layer": LAYER_VERSION,
        "match_id": match_id,
        "player": player,
        "summary": summary,
        "created": {
            "json": rel(out_json, root),
            "current": rel(out_current, root),
            "csv": rel(out_csv, root),
        }
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", default="example_match")
    parser.add_argument("--player", default="Player")
    args = parser.parse_args()

    result = build(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
