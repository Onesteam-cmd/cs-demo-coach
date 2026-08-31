from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_step(name: str, cmd: list[str], expected: list[Path] | None = None, force: bool = False) -> None:
    expected = expected or []

    if expected and not force and all(p.exists() for p in expected):
        print(f"=== SKIP: {name} ===")
        for p in expected:
            print(f"  exists: {p}")
        return

    print("")
    print(f"=== RUN: {name} ===")
    print(" ".join(cmd))

    subprocess.run(cmd, check=True)


def find_primary_player(report_dir: Path, explicit_player: str | None) -> str | None:
    if explicit_player:
        return explicit_player

    settings_path = Path("config/project_settings.json")
    aliases: list[str] = []

    if settings_path.exists():
        settings = read_json(settings_path)
        aliases = [str(x) for x in settings.get("primary_player_names", [])]

    focus = read_json(report_dir / "player_focus_v0_3.json")
    players = [str(x.get("name")) for x in focus.get("players", []) if x.get("name")]
    lower_to_name = {x.lower(): x for x in players}

    for alias in aliases:
        if alias.lower() in lower_to_name:
            return lower_to_name[alias.lower()]

    return players[0] if players else None


def print_final_summary(report_dir: Path, player_name: str | None) -> None:
    print("")
    print("=== PIPELINE COMPLETE ===")
    print(f"Report dir: {report_dir}")

    focus_path = report_dir / "player_focus_v0_3.json"
    contact_path = report_dir / "contact_visibility_v0_3_strict.json"

    focus = read_json(focus_path)
    contact = read_json(contact_path)

    if contact:
        summary = contact.get("summary", {})
        print("")
        print("Strict contact summary:")
        print(f"  Strict contacts: {summary.get('strict_contacts')}")
        print(f"  Priority contacts: {summary.get('priority_contacts')}")
        print(f"  Players: {summary.get('players')}")

    if focus and player_name:
        player = None
        for p in focus.get("players", []):
            if str(p.get("name")) == player_name:
                player = p
                break

        if player:
            print("")
            print(f"Primary player: {player_name}")
            print(f"  Main diagnosis: {player.get('main_diagnosis')}")

            basic = player.get("basic", {})
            contact = player.get("contact", {})
            mechanics = player.get("mechanics", {})

            print(f"  K/D: {basic.get('kills')} / {basic.get('deaths')}")
            print(f"  ADR: {basic.get('adr')}")
            print(f"  Strict score: {contact.get('strict_contact_score')}")
            print(f"  Lost%: {contact.get('lost_rate')}")
            print(f"  No response%: {contact.get('no_response_rate')}")
            print(f"  Delayed%: {contact.get('delayed_rate')}")
            print(f"  Moving%: {contact.get('moving_rate')}")
            print(f"  Bad CS: {mechanics.get('bad_counter_strafe_candidates')}")

            top = player.get("top_issues", [])
            if top:
                print("")
                print("Top issues:")
                for issue in top[:3]:
                    print(f"  - {issue.get('title')} | severity={issue.get('severity')} | source={issue.get('source')}")


def try_open(path: Path) -> None:
    try:
        if path.exists():
            os.startfile(str(path.resolve()))
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("demo_path", type=Path, help="Path to .dem file")
    parser.add_argument("--match-id", type=str, default=None)
    parser.add_argument("--player", type=str, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    demo_path: Path = args.demo_path

    if not demo_path.exists():
        raise SystemExit(f"Demo not found: {demo_path}")

    demo_name = demo_path.stem
    match_id = args.match_id or f"{demo_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    parsed_dir = Path("data/parsed") / demo_name
    report_dir = Path("data/reports") / demo_name

    py = sys.executable

    print("=== CS Demo Coach Full Pipeline v0.1 ===")
    print(f"Demo: {demo_path}")
    print(f"Demo name: {demo_name}")
    print(f"Match ID: {match_id}")
    print(f"Parsed dir: {parsed_dir}")
    print(f"Report dir: {report_dir}")
    print(f"Force: {args.force}")

    run_step(
        "Awpy parse demo",
        [py, "backend/parser_core/parse_demo.py", str(demo_path)],
        [parsed_dir / "parse_summary.json"],
        args.force,
    )

    run_step(
        "Demoparser2 view layer",
        [py, "backend/parser_core/parse_view_angles_demoparser2.py", str(demo_path), "--out-dir", str(parsed_dir)],
        [parsed_dir / "view_ticks_demoparser2.parquet"],
        args.force,
    )

    run_step(
        "Match report v1.1",
        [py, "backend/match_model/build_match_model_v1_1.py", str(parsed_dir)],
        [report_dir / "report_v1_1.json", report_dir / "report_v1_1.html"],
        args.force,
    )

    run_step(
        "Mechanics v0.1",
        [py, "backend/analyzers/mechanics_v0_1.py", str(parsed_dir)],
        [report_dir / "mechanics_v0_1.json", report_dir / "mechanics_v0_1.html"],
        args.force,
    )

    run_step(
        "Duel model v0.1",
        [py, "backend/analyzers/duel_model_v0_1.py", str(parsed_dir)],
        [report_dir / "duel_model_v0_1.json", report_dir / "kill_duels_v0_1.parquet"],
        args.force,
    )

    run_step(
        "Contact visibility v0.1",
        [py, "backend/analyzers/contact_visibility_v0_1.py", str(parsed_dir)],
        [report_dir / "contacts_v0_1.parquet", report_dir / "contact_visibility_v0_1.json"],
        args.force,
    )

    run_step(
        "Contact visibility v0.2",
        [py, "backend/analyzers/contact_visibility_v0_2.py", str(report_dir)],
        [report_dir / "contacts_v0_2.parquet", report_dir / "contact_visibility_v0_2.json"],
        args.force,
    )

    run_step(
        "Contact visibility v0.3 strict",
        [py, "backend/analyzers/contact_visibility_v0_3_strict.py", str(report_dir)],
        [report_dir / "contacts_v0_3_strict.parquet", report_dir / "contact_visibility_v0_3_strict.json"],
        args.force,
    )

    run_step(
        "Player focus v0.3",
        [py, "backend/reports/player_focus_v0_3.py", str(report_dir)],
        [report_dir / "player_focus_v0_3.json", report_dir / "player_focus_v0_3.html"],
        args.force,
    )

    player_name = find_primary_player(report_dir, args.player)

    progress_cmd = [py, "backend/reports/progress_tracking_v0_1.py", str(report_dir), "--match-id", match_id]
    if args.player:
        progress_cmd.extend(["--player", args.player])

    run_step(
        "Progress tracking v0.1",
        progress_cmd,
        [],
        True,
    )

    print_final_summary(report_dir, player_name)

    if not args.no_open:
        try_open(report_dir / "player_focus_v0_3.html")
        if player_name:
            try_open(Path("data/progress") / f"progress_{player_name}.html")


if __name__ == "__main__":
    main()
