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
    mp = ctx.gen_maps_dir / "codebase.json"
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
                      "recent": sorted(events, key=lambda e: e.get("t", ""))[-15:],
                      "last_commit": max((e for e in events if e.get("kind") == "commit"),
                                         key=lambda e: e.get("t", ""), default=None)},
            "score": _score(events),
            "goals": _goals(ctx),
            "todo": _todo(w, ctx)}


def _todo(where: dict[str, Any], ctx: _ctx.Context) -> dict[str, Any]:
    from anthill import goal
    from anthill.ui import todo
    try:
        return todo.build(where, goal.all_goals(ctx))
    except Exception as exc:                  # noqa: BLE001 -- a bad note must not blank the page
        return {"todo": [], "answered": [], "review": [], "error": str(exc)}


def _goals(ctx: _ctx.Context) -> list[dict[str, Any]]:
    from anthill import goal
    try:
        return [{**g, "next": goal.next_step(g)} for g in goal.all_goals(ctx)[:12]]
    except Exception:                         # noqa: BLE001
        return []


def _score(events: list[dict[str, Any]]) -> dict[str, Any]:
    from anthill import scorecard
    try:
        return scorecard.scorecard(events)
    except Exception as exc:                  # noqa: BLE001 -- a bad line must not blank the page
        return {"error": str(exc)}


# ------------------------------------------------------------------ the server

class _Handler(BaseHTTPRequestHandler):
    ctx: _ctx.Context
    key: str = ""                                    # empty: view only, no button works
    port: int = 0
    _cache: tuple[float, bytes] = (0.0, b"")

    def log_message(self, *_a: Any) -> None:       # quiet: this is not a web app
        pass

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_POST(self) -> None:                      # noqa: N802
        """A button. Refused unless it carries the key from the owner's terminal.

        Three more locks, each for a different way in. The Host must be this
        machine at this port, so a web page that rebinds its own name to
        127.0.0.1 is refused. The key travels in a custom header, which a page
        from any other site cannot send here without a preflight this server
        never answers. And the body must be small JSON.
        """
        import hmac
        from anthill.ui import actions
        # Read the body before any refusal: answering while the client is still
        # sending resets the connection, and the refusal never arrives.
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        raw = self.rfile.read(n) if 0 < n <= 16384 else b""
        host = self.headers.get("Host", "")
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return self._json(403, {"error": "wrong host"})
        if not self.key:
            return self._json(403, {"error": "buttons are off: this page was not started "
                                             "from your terminal, so it has no key"})
        if not hmac.compare_digest(self.headers.get("X-Anthill-Key", ""), self.key):
            return self._json(403, {"error": "wrong or missing key -- open the address "
                                             "your terminal printed"})
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self._json(415, {"error": "json only"})
        if n <= 0 or n > 16384:
            return self._json(413, {"error": "empty or too large"})
        try:
            body = json.loads(raw)
        except ValueError:
            return self._json(400, {"error": "not json"})
        by = ((self.ctx.config.get("project") or {}).get("owner")) or "owner"
        try:
            if self.path == "/api/answer":
                out = actions.answer(self.ctx, body.get("work", ""), body.get("question", ""),
                                     body.get("answer", ""))
            elif self.path == "/api/sign":
                out = actions.sign(self.ctx, body.get("page", ""), by)
            elif self.path == "/api/ack":
                from anthill import goal
                try:
                    g = goal.acknowledge(self.ctx, body.get("goal", ""), int(body.get("index", -1)))
                except (LookupError, ValueError, OSError) as exc:
                    raise actions.Refused(str(exc))
                out = {"goal": g["id"], "acknowledged": int(body.get("index", -1))}
            elif self.path in ("/api/goal-answer", "/api/overturn"):
                from anthill import goal
                try:
                    g = (goal.owner_answer(self.ctx, body.get("goal", ""), str(body.get("answer", "")))
                         if self.path == "/api/goal-answer" else
                         goal.overturn(self.ctx, body.get("goal", ""), int(body.get("index", -1)),
                                       str(body.get("note", ""))))
                except (LookupError, ValueError, OSError) as exc:
                    raise actions.Refused(str(exc))
                if self.path == "/api/goal-answer" and not str(body.get("answer", "")).strip():
                    raise actions.Refused("the answer is empty")
                out = {"goal": g["id"], "status": g["status"]}
            elif self.path == "/api/reopen":
                out = actions.reopen(self.ctx, body.get("unit", ""), body.get("reason", ""), by,
                                     str(REPO_ROOT / "bin" / "anthill"))
            else:
                return self._json(404, {"error": "no such button"})
        except actions.Refused as exc:
            return self._json(400, {"error": str(exc)})
        _Handler._cache = (0.0, b"")
        return self._json(200, out)

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
    return ctx.page_dir / "ui.json"


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


def new_key() -> str:
    import secrets
    return secrets.token_urlsafe(18)


def serve(ctx: _ctx.Context, port: int, parent: int = 0, key: str = "") -> int:
    """Run in the foreground until stopped, or until `parent` exits.

    `key` is held in this process's memory only -- never written to ui.json
    or anywhere an agent could read it back."""
    _Handler.ctx = ctx
    _Handler.key = key
    _Handler.port = port
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


def _in_a_terminal() -> bool:
    """Whether a person is at the other end. An agent's shell is not a terminal,
    so a page an agent starts gets no key and no working buttons.

    Either end counts: a start script captures stdout to show the address
    (`ui_line="$(anthill ui start ...)"`) while its stdin is still the owner's
    keyboard."""
    try:
        return sys.stdin.isatty() or sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def start(ctx: _ctx.Context, port: int = 0, parent: int = 0, detach: bool = False,
          key: str | None = None) -> dict[str, Any]:
    rec = running(ctx)
    if rec:
        return {**rec, "already": True}
    port = free_port(port)
    if key is None:
        key = new_key() if _in_a_terminal() else ""
    if not detach:
        url = f"http://127.0.0.1:{port}/" + (f"#key={key}" if key else "")
        print(f"anthill ui: {url}  (Ctrl-C to stop)", file=sys.stderr)
        serve(ctx, port, parent, key)
        return {"stopped": True}
    log = ctx.page_dir / "ui.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    tool = str(REPO_ROOT / "bin" / "anthill")
    args = [tool, "ui", "serve", "--port", str(port), "--key-on-stdin"] + (["--with-parent", str(parent)] if parent else [])
    with open(log, "ab") as fh:
        # The key goes to the server on its stdin, once: not in its arguments or
        # its environment, which any process of the same user can list.
        p = subprocess.Popen(args, cwd=ctx.root, stdout=fh, stderr=fh, stdin=subprocess.PIPE,
                             start_new_session=True)
        p.stdin.write((key + "\n").encode())
        p.stdin.close()
    for _ in range(40):
        rec = running(ctx)
        if rec:
            return {**rec, "key": key}
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
    sv.add_argument("--key-on-stdin", action="store_true")
    sub.add_parser("stop", help="Stop it and free its port")
    sub.add_parser("status", help="Is it up, and where")
    args = ap.parse_args(argv)
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        print(f"anthill ui: anthill is not installed in {ctx.root}", file=sys.stderr)
        return 2
    cmd = args.cmd or "start"
    if cmd == "serve":
        key = sys.stdin.readline().strip() if args.key_on_stdin else ""
        return serve(ctx, args.port, args.with_parent, key)
    if cmd == "start":
        out = start(ctx, getattr(args, "port", 0), getattr(args, "with_parent", 0),
                    getattr(args, "detach", False))
        # The address is always the last word on stdout: a start script shows
        # `${line##* }`. Everything else goes to stderr.
        if out.get("already"):
            print("anthill ui: already up -- its buttons need the address printed when it "
                  "started; stop and start it from your terminal for a new one", file=sys.stderr)
            print(f"anthill ui: already up at {out['url']}")
        elif out.get("url"):
            if out.get("key"):
                print("anthill ui: the key in this address is what makes the buttons yours; "
                      "don't paste it into a chat", file=sys.stderr)
                print(f"anthill ui: {out['url']}#key={out['key']}")
            else:
                print("anthill ui: view only -- started outside a terminal, so there is no key",
                      file=sys.stderr)
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
