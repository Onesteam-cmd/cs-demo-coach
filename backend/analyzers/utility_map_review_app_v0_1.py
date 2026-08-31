from __future__ import annotations

import argparse
import csv
import html
import socket
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


STATUS_OPTIONS = ["new", "checked", "skip"]
YES_NO_OPTIONS = ["", "yes", "no", "unknown"]

PURPOSE_OPTIONS = [
    "",
    "block_vision",
    "stop_push",
    "clear_angle",
    "retake",
    "postplant",
    "fake",
    "damage",
    "delay",
    "unknown",
]

QUALITY_OPTIONS = [
    "",
    "good",
    "partial",
    "bad",
    "unknown",
]

PROBLEM_OPTIONS = [
    "",
    "none",
    "missed_lineup",
    "gap",
    "too_late",
    "too_early",
    "no_value",
    "wrong_place",
    "bad_timing",
    "unknown",
]

KEEP_OPTIONS = ["", "yes", "no"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]

    return fields, rows


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    tmp.replace(path)


def option_html(options: list[str], selected: str) -> str:
    out = []
    for opt in options:
        label = opt if opt else "—"
        selected_attr = " selected" if opt == selected else ""
        out.append(f'<option value="{esc(opt)}"{selected_attr}>{esc(label)}</option>')
    return "\n".join(out)


def stats(rows: list[dict[str, str]]) -> dict[str, int]:
    checked = sum(1 for r in rows if r.get("review_status") == "checked")
    skipped = sum(1 for r in rows if r.get("review_status") == "skip")
    good = sum(1 for r in rows if r.get("quality") == "good")
    partial = sum(1 for r in rows if r.get("quality") == "partial")
    bad = sum(1 for r in rows if r.get("quality") == "bad")
    return {
        "total": len(rows),
        "checked": checked,
        "skipped": skipped,
        "new": len(rows) - checked - skipped,
        "good": good,
        "partial": partial,
        "bad": bad,
    }


def next_new(rows: list[dict[str, str]], current: int) -> int:
    for i in range(current + 1, len(rows)):
        if rows[i].get("review_status", "new") == "new":
            return i
    for i in range(0, len(rows)):
        if rows[i].get("review_status", "new") == "new":
            return i
    return min(current + 1, len(rows) - 1)


def render_page(csv_path: Path, rows: list[dict[str, str]], index: int, saved: bool = False) -> str:
    if not rows:
        return "<html><body>No rows</body></html>"

    index = max(0, min(index, len(rows) - 1))
    r = rows[index]
    st = stats(rows)

    saved_html = '<div class="saved">Сохранено.</div>' if saved else ""

    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Utility Map Review App v0.1</title>
    <style>
        body {{
            margin: 0;
            padding: 28px;
            font-family: Arial, sans-serif;
            background: #101214;
            color: #f2f2f2;
        }}
        h1, h2 {{
            margin: 0 0 10px 0;
        }}
        code {{
            background: #1e2329;
            padding: 2px 5px;
            border-radius: 5px;
        }}
        .muted {{
            color: #a7adb5;
            font-size: 13px;
        }}
        .saved {{
            margin: 14px 0;
            padding: 10px 12px;
            background: #17381f;
            border: 1px solid #2d7c3a;
            border-radius: 10px;
            color: #b7f5bd;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 12px;
            margin: 18px 0;
        }}
        .card {{
            background: #1a1d21;
            border: 1px solid #2b3138;
            border-radius: 12px;
            padding: 13px;
        }}
        .card-title {{
            color: #a7adb5;
            font-size: 12px;
        }}
        .card-value {{
            font-size: 22px;
            font-weight: 700;
            margin-top: 7px;
            word-break: break-word;
        }}
        .two {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
        }}
        @media (max-width: 900px) {{
            .two {{
                grid-template-columns: 1fr;
            }}
        }}
        .panel {{
            background: #15181c;
            border: 1px solid #2b3138;
            border-radius: 14px;
            padding: 18px;
            margin-top: 18px;
        }}
        label {{
            display: block;
            color: #cdd3db;
            font-size: 13px;
            margin: 12px 0 5px 0;
        }}
        select, textarea {{
            width: 100%;
            box-sizing: border-box;
            background: #0f1318;
            color: #f2f2f2;
            border: 1px solid #2b3138;
            border-radius: 9px;
            padding: 9px;
            font-size: 14px;
        }}
        textarea {{
            min-height: 110px;
            resize: vertical;
        }}
        .btns {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 16px;
        }}
        button, .button-link {{
            background: #2b5cff;
            color: white;
            border: 0;
            border-radius: 10px;
            padding: 10px 14px;
            font-weight: 700;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .secondary {{
            background: #252b33;
        }}
        .danger {{
            background: #7a2b2b;
        }}
        .ok {{
            background: #267a35;
        }}
    </style>
</head>
<body>
    <h1>Utility Map Review App v0.1</h1>
    <div class="muted">
        CSV: <code>{esc(csv_path)}</code><br>
        Event {index + 1} / {len(rows)} ·
        new: <b>{st["new"]}</b> · checked: <b>{st["checked"]}</b> · skipped: <b>{st["skipped"]}</b> ·
        good/partial/bad: <b>{st["good"]}</b>/<b>{st["partial"]}</b>/<b>{st["bad"]}</b>
    </div>

    {saved_html}

    <div class="grid">
        <div class="card"><div class="card-title">Type</div><div class="card-value">{esc(r.get("utility_type"))}</div></div>
        <div class="card"><div class="card-title">Round</div><div class="card-value">R{esc(r.get("round"))}</div></div>
        <div class="card"><div class="card-title">Start tick</div><div class="card-value">{esc(r.get("start_tick"))}</div></div>
        <div class="card"><div class="card-title">Duration</div><div class="card-value">{esc(r.get("duration_ticks"))}</div></div>
        <div class="card"><div class="card-title">Thrower place</div><div class="card-value">{esc(r.get("thrower_place"))}</div></div>
        <div class="card"><div class="card-title">Cluster</div><div class="card-value">{esc(r.get("cluster"))}</div></div>
    </div>

    <div class="grid">
        <div class="card"><div class="card-title">X</div><div class="card-value">{esc(r.get("x"))}</div></div>
        <div class="card"><div class="card-title">Y</div><div class="card-value">{esc(r.get("y"))}</div></div>
        <div class="card"><div class="card-title">Z</div><div class="card-value">{esc(r.get("z"))}</div></div>
        <div class="card"><div class="card-title">Side</div><div class="card-value">{esc(r.get("side"))}</div></div>
    </div>

    <div class="two">
        <div class="panel">
            <h2>Что проверить в демке</h2>
            <p>Открой демку примерно около tick <code>{esc(r.get("start_tick"))}</code>.</p>
            <p>
                Для smoke проверь: закрыл ли он нужный проход, есть ли gap, не прилетел ли поздно/рано, дал ли value.
            </p>
            <p>
                Для inferno проверь: остановил ли push, зачистил ли угол, дал ли delay/damage, не был ли брошен без пользы.
            </p>
            <p><b>event_id:</b><br><code>{esc(r.get("event_id"))}</code></p>
        </div>

        <div class="panel">
            <h2>Manual verdict</h2>
            <form method="POST" action="/save">
                <input type="hidden" name="index" value="{index}">

                <label>review_status</label>
                <select name="review_status">{option_html(STATUS_OPTIONS, r.get("review_status", "new"))}</select>

                <label>known_lineup — это узнаваемый/запланированный lineup?</label>
                <select name="known_lineup">{option_html(YES_NO_OPTIONS, r.get("known_lineup", ""))}</select>

                <label>intended_purpose — зачем был utility?</label>
                <select name="intended_purpose">{option_html(PURPOSE_OPTIONS, r.get("intended_purpose", ""))}</select>

                <label>quality</label>
                <select name="quality">{option_html(QUALITY_OPTIONS, r.get("quality", ""))}</select>

                <label>problem</label>
                <select name="problem">{option_html(PROBLEM_OPTIONS, r.get("problem", ""))}</select>

                <label>coach_note</label>
                <textarea name="coach_note">{esc(r.get("coach_note", ""))}</textarea>

                <label>keep_for_training</label>
                <select name="keep_for_training">{option_html(KEEP_OPTIONS, r.get("keep_for_training", ""))}</select>

                <div class="btns">
                    <button type="submit" name="goto" value="next_new" class="ok">Сохранить и следующий new</button>
                    <button type="submit" name="goto" value="next">Сохранить и следующий</button>
                    <button type="submit" name="goto" value="stay" class="secondary">Сохранить</button>
                    <button type="submit" name="set_skip" value="1" class="danger">Skip</button>
                </div>
            </form>

            <div class="btns">
                <a class="button-link secondary" href="/?i={max(index - 1, 0)}">Назад</a>
                <a class="button-link secondary" href="/?i={min(index + 1, len(rows) - 1)}">Вперёд</a>
                <a class="button-link secondary" href="/?i={next_new(rows, index)}">Следующий new</a>
            </div>
        </div>
    </div>
</body>
</html>
"""


class App:
    def __init__(self, csv_path: Path):
        self.csv_path = csv_path
        self.lock = threading.Lock()

    def load(self) -> tuple[list[str], list[dict[str, str]]]:
        with self.lock:
            return read_rows(self.csv_path)

    def save(self, index: int, form: dict[str, str]) -> None:
        with self.lock:
            fields, rows = read_rows(self.csv_path)

            if not rows:
                return

            index = max(0, min(index, len(rows) - 1))
            row = rows[index]

            for key in [
                "review_status",
                "known_lineup",
                "intended_purpose",
                "quality",
                "problem",
                "coach_note",
                "keep_for_training",
            ]:
                if key in form:
                    row[key] = form[key]

            if form.get("set_skip") == "1":
                row["review_status"] = "skip"

            rows[index] = row
            write_rows(self.csv_path, fields, rows)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def send_html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            try:
                index = int(qs.get("i", ["0"])[0])
            except Exception:
                index = 0

            saved = qs.get("saved", ["0"])[0] == "1"

            _, rows = app.load()
            self.send_html(render_page(app.csv_path, rows, index, saved))

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            data = urllib.parse.parse_qs(raw)
            form = {k: v[-1] if v else "" for k, v in data.items()}

            try:
                index = int(form.get("index", "0"))
            except Exception:
                index = 0

            app.save(index, form)

            _, rows = app.load()
            goto = form.get("goto", "stay")

            if goto == "next_new":
                target = next_new(rows, index)
            elif goto == "next":
                target = min(index + 1, max(len(rows) - 1, 0))
            else:
                target = index

            self.redirect(f"/?i={target}&saved=1")

    return Handler


def free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise RuntimeError("No free port found")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    root = repo_root()
    csv_path = root / "data" / "reviews" / args.match_id / f"utility_map_review_{args.player}_v0_1.csv"

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    port = free_port(args.port)
    app = App(csv_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{port}/"

    print("OK: Utility Map Review App v0.1 started")
    print(f"  Match: {args.match_id}")
    print(f"  Player: {args.player}")
    print(f"  CSV: {csv_path}")
    print(f"  URL: {url}")
    print("")
    print("Keep this PowerShell window open while reviewing.")
    print("Press Ctrl+C to stop.")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
        print("Stopped.")


if __name__ == "__main__":
    main()
