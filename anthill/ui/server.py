"""`anthill ui`: the owner's view of the anthill, on a local page.

Everything `where` knows -- the work in progress, what waits on the owner,
their decisions, the job board and where it disagrees with the pages, what is
being edited right now, the upkeep list, the map's health -- was reachable only
by typing a command or asking an agent. This serves it as one page on this
laptop, refreshed every few seconds. View only: nothing here writes.

Built to be lived with, not babysat:

  * one process per project. `start` when it is already up says where it is
    and starts nothing; its port and pid are recorded in build/ui.json, so
    `stop` always knows what to stop and a stale record cleans itself up.
  * a free port, never a fight. 7070 unless taken, then the next one up.
  * `--with-parent <pid>` ends it when that process ends. A project's start
    script passes its own pid (`$$`), so stopping the app stops this too and
    no port is left held by a server nobody remembers starting.
  * 127.0.0.1 only. Nothing off this machine can reach it.

Simple on purpose, so any agent can extend it: the page is one file
(`index.html`) that reads one endpoint (`/api/state`). To show something new,
add a key to `state()` and a panel that renders it.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

HERE = Path(__file__).resolve().parent
FIRST_PORT, LAST_PORT = 7070, 7099


# ------------------------------------------------------------------ the facts

def state(ctx: _ctx.Context) -> dict[str, Any]:
    """Everything the page shows, in one object."""
    from anthill import upkeep
    from anthill.knowledge import work
    w = work.where(ctx)
    mp = ctx.state / "build" / "maps" / "codebase.json"
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
        map_info = {"nodes": len(m.get("nodes") or []), "built_at": str(m.get("built_at_commit", ""))[:7],
                    "age_min": int((time.time() - mp.stat().st_mtime) // 60)}
    except (OSError, ValueError):
        map_info = {}
    name = ((ctx.config.get("project") or {}).get("name")) or ctx.root.name
    from anthill import trail
    events = trail.read(ctx)
    return {"project": name, "root": str(ctx.root), "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "where": w, "upkeep": upkeep.load(ctx).get("open") or [], "map": map_info,
            "trail": {**trail.health(ctx, events),
                      "recent": sorted(events, key=lambda e: e.get("t", ""))[-15:]},
            "score": _score(events)}


def _score(events: list[dict[str, Any]]) -> dict[str, Any]:
    from anthill import scorecard
    try:
        return scorecard.scorecard(events)
    except Exception as exc:                  # noqa: BLE001 -- a bad line must not blank the page
        return {"error": str(exc)}


# ------------------------------------------------------------------ the server

class _Handler(BaseHTTPRequestHandler):
    ctx: _ctx.Context
    _cache: tuple[float, bytes] = (0.0, b"")

    def log_message(self, *_a: Any) -> None:       # quiet: this is not a web app
        pass

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                       # noqa: N802 (http.server's name)
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path.startswith("/api/state"):
            at, body = _Handler._cache
            if time.time() - at > 3:                 # git is cheap, not free
                body = json.dumps(state(self.ctx), default=str).encode()
                _Handler._cache = (time.time(), body)
            self._send(200, body, "application/json")
        else:
            self._send(404, b"not here", "text/plain")


def _record_path(ctx: _ctx.Context) -> Path:
    return ctx.state / "build" / "ui.json"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def running(ctx: _ctx.Context) -> dict[str, Any] | None:
    """The live record, or None -- a record whose process is gone is removed."""
    p = _record_path(ctx)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if _alive(int(rec.get("pid", 0))) and _answers(int(rec.get("port", 0))):
        return rec
    p.unlink(missing_ok=True)
    return None


def free_port(wanted: int = 0) -> int:
    for port in ([wanted] if wanted else range(FIRST_PORT, LAST_PORT + 1)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # The same rule the server binds with. Without it, a port still
            # cooling down from the last stop read as taken, and every restart
            # walked one port further up.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"anthill ui: no free port in {FIRST_PORT}-{LAST_PORT}"
                     if not wanted else f"anthill ui: port {wanted} is taken")


def serve(ctx: _ctx.Context, port: int, parent: int = 0) -> int:
    """Run in the foreground until stopped, or until `parent` exits."""
    _Handler.ctx = ctx
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    rec = {"pid": os.getpid(), "port": port, "url": f"http://127.0.0.1:{port}/",
           "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "parent": parent}
    rp = _record_path(ctx)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(rec), encoding="utf-8")

    def stop(*_a: Any) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if parent:
        def watch() -> None:
            while _alive(parent):
                time.sleep(2)
            stop()
        threading.Thread(target=watch, daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        try:
            if json.loads(rp.read_text()).get("pid") == os.getpid():
                rp.unlink()
        except (OSError, ValueError):
            pass
    return 0


def start(ctx: _ctx.Context, port: int = 0, parent: int = 0, detach: bool = False) -> dict[str, Any]:
    rec = running(ctx)
    if rec:
        return {**rec, "already": True}
    port = free_port(port)
    if not detach:
        print(f"anthill ui: http://127.0.0.1:{port}/  (Ctrl-C to stop)", file=sys.stderr)
        serve(ctx, port, parent)
        return {"stopped": True}
    log = ctx.state / "build" / "ui.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    tool = str(REPO_ROOT / "bin" / "anthill")
    args = [tool, "ui", "serve", "--port", str(port)] + (["--with-parent", str(parent)] if parent else [])
    with open(log, "ab") as fh:
        subprocess.Popen(args, cwd=ctx.root, stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    for _ in range(40):
        rec = running(ctx)
        if rec:
            return rec
        time.sleep(0.1)
    return {"error": f"did not come up; see {log}"}


def stop(ctx: _ctx.Context) -> dict[str, Any]:
    rec = running(ctx)
    if not rec:
        return {"stopped": False, "why": "not running"}
    os.kill(int(rec["pid"]), signal.SIGTERM)
    for _ in range(30):
        if not _alive(int(rec["pid"])):
            break
        time.sleep(0.1)
    _record_path(ctx).unlink(missing_ok=True)
    return {"stopped": True, "port": rec["port"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="anthill ui", description="The owner's view, on a local page.")
    sub = ap.add_subparsers(dest="cmd")
    st = sub.add_parser("start", help="Start it (or say where it already is)")
    st.add_argument("--port", type=int, default=0)
    st.add_argument("--detach", action="store_true", help="Run in the background")
    st.add_argument("--with-parent", type=int, default=0,
                    help="Stop when this process ends; a start script passes $$")
    sv = sub.add_parser("serve", help=argparse.SUPPRESS)
    sv.add_argument("--port", type=int, required=True)
    sv.add_argument("--with-parent", type=int, default=0)
    sub.add_parser("stop", help="Stop it and free its port")
    sub.add_parser("status", help="Is it up, and where")
    args = ap.parse_args(argv)
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        print(f"anthill ui: anthill is not installed in {ctx.root}", file=sys.stderr)
        return 2
    cmd = args.cmd or "start"
    if cmd == "serve":
        return serve(ctx, args.port, args.with_parent)
    if cmd == "start":
        out = start(ctx, getattr(args, "port", 0), getattr(args, "with_parent", 0),
                    getattr(args, "detach", False))
        if out.get("already"):
            print(f"anthill ui: already up at {out['url']}")
        elif out.get("url"):
            print(f"anthill ui: {out['url']}")
        elif out.get("error"):
            print(f"anthill ui: {out['error']}", file=sys.stderr)
            return 1
        return 0
    if cmd == "stop":
        out = stop(ctx)
        print(f"anthill ui: stopped, port {out['port']} is free" if out["stopped"]
              else "anthill ui: it was not running")
        return 0
    rec = running(ctx)
    print(f"anthill ui: up at {rec['url']} (pid {rec['pid']})" if rec else "anthill ui: not running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
