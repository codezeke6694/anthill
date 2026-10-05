"""The trail: one running log of what happened in this project.

Four separate things wanted the same record and none had it:

  * the owner could not tell whether Anthill or they themselves were making the
    work faster -- nothing measured either;
  * a check that crashed said so to a hook that threw the output away, so
    the blueprint check was dead for every claim and nobody knew;
  * a chat whose memory was compressed, or a different tool picking the work
    up tomorrow, had no record of what the last session was in the middle of;
  * no agent could say when its own task started -- three of three guessed.

So every `anthill` command writes one line here as it finishes -- the hooks
call `anthill` too, so their failures land here instead of in /dev/null --
and the post-commit hook writes one per commit. Nothing asks the agent: the
tool and the chat come from the environment each one sets, and git hooks
inherit it. That is what makes this work for any tool, not only Claude.

Append-only JSON lines in `.anthill/trail.jsonl`. A torn final line is
skipped on read. Writing never raises: the trail must never cost a command.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from anthill import context as _ctx

FILE = "trail.jsonl"

# What reaches a chat as if typed by the owner but is not them: a helper
# agent's report handed back, a background task finishing, the harness's own
# notes. Counted as the owner speaking, one two-hour goal the owner started
# with a single message read as 49 of theirs.
RELAYED = ("<agent-message", "<task-notification", "<system-reminder", "<command-",
           "[Request interrupted", "Another Claude session sent a message")


def owner_spoke(ev: dict) -> bool:
    return ev.get("kind") == "prompt" and not str(ev.get("text") or "").lstrip().startswith(RELAYED)
ARGS_MAX = 160


def path(ctx: _ctx.Context) -> Path:
    return ctx.trail_path


def who() -> dict[str, str]:
    """Which tool, and which chat, from what the tool itself puts in the environment."""
    env = os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_SESSION_ID"):
        tool = "claude-code"
    elif any(k.startswith("CODEX_") for k in env):
        tool = "codex"
    elif any(k.startswith("CURSOR_") for k in env):
        tool = "cursor"
    elif env.get("AI_AGENT"):
        tool = env["AI_AGENT"].split("_", 1)[0]
    else:
        tool = "terminal"
    session = (env.get("ANTHILL_SESSION") or env.get("CLAUDE_CODE_SESSION_ID")
               or env.get("CODEX_SESSION_ID") or "")
    return {"tool": tool, "session": session}


def _branch(root: Path) -> str:
    try:
        r = subprocess.run(["git", "branch", "--show-current"], cwd=root,
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def record(kind: str, ctx: _ctx.Context | None = None, session: str = "", **fields: Any) -> None:
    """Append one event. Never raises; a project without Anthill writes nothing.

    `session` is for hooks, which are told the chat's id on stdin rather than
    in the environment."""
    try:
        ctx = ctx or _ctx.resolve(None)
        if not ctx.installed:
            return
        w = who()
        if session:
            w["session"] = session
        ev = {"t": datetime.now().astimezone().isoformat(timespec="seconds"),
              "kind": kind, **w, "branch": _branch(ctx.root), **fields}
        with path(ctx).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, default=str) + "\n")
    except Exception:                     # noqa: BLE001 -- the trail must never cost a command
        pass


def read(ctx: _ctx.Context, limit: int = 0) -> list[dict[str, Any]]:
    p = path(ctx)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue                      # a torn line from an interrupted write
    return out[-limit:] if limit else out


def command_args(argv: list[str]) -> str:
    s = " ".join(argv)
    return s if len(s) <= ARGS_MAX else s[:ARGS_MAX - 1] + "…"


# The commands whose result says whether Anthill itself is healthy. The page
# shows the latest run of each, red if it crashed.
CHECKS = ("blueprint", "map", "upkeep", "where", "work")


def health(ctx: _ctx.Context, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The latest result of each check, and every crash in the last week."""
    events = read(ctx) if events is None else events
    latest: dict[str, dict[str, Any]] = {}
    crashes: list[dict[str, Any]] = []
    week_ago = datetime.now().astimezone().timestamp() - 7 * 86400
    for ev in events:
        if ev.get("kind") != "command":
            continue
        verb = ev.get("verb", "")
        if verb in CHECKS:
            latest[verb] = ev
        if ev.get("crashed"):
            try:
                when = datetime.fromisoformat(ev["t"]).timestamp()
            except (KeyError, ValueError):
                when = 0
            if when >= week_ago:
                crashes.append(ev)
    return {"checks": [latest[v] for v in CHECKS if v in latest], "crashes": crashes[-20:]}


def _on_commit(ctx: _ctx.Context) -> int:
    def git(*a: str) -> str:
        r = subprocess.run(["git", *a], cwd=ctx.root, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    try:
        sha = git("rev-parse", "--short", "HEAD")
        subject = git("log", "-1", "--format=%s")
        files = [f for f in git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines() if f]
    except (OSError, subprocess.SubprocessError):
        return 0
    record("commit", ctx, sha=sha, subject=subject[:ARGS_MAX], files=len(files),
           paths=files[:20])
    return 0


def render(events: list[dict[str, Any]]) -> str:
    lines = []
    for ev in events:
        t = ev.get("t", "")[5:16].replace("T", " ")
        who_ = ev.get("tool", "?") + (":" + ev["session"][:8] if ev.get("session") else "")
        if ev.get("kind") == "commit":
            what = f"commit {ev.get('sha', '')}  {ev.get('subject', '')}"
        elif ev.get("kind") == "command":
            mark = "CRASHED " if ev.get("crashed") else ("" if ev.get("rc") in (0, None) else f"exit {ev.get('rc')} ")
            what = f"{mark}anthill {ev.get('args', '')}"
        elif ev.get("kind") == "session":
            what = f"chat {ev.get('source', 'startup')}"
        elif ev.get("kind") == "prompt":
            what = f"owner: {ev.get('text', '')}"
        else:
            what = f"{ev.get('kind')} {ev.get('text') or ''}".rstrip()
        lines.append(f"{t}  {who_:<22} {what}")
    return "\n".join(lines) + ("\n" if lines else "the trail is empty\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ctx = _ctx.resolve(None)
    if argv and argv[0] == "commit":          # the post-commit hook
        return _on_commit(ctx)
    if argv and argv[0] in ("-h", "--help"):
        print("anthill trail [--json] [-n N]   what happened here, newest last\n"
              "anthill trail health [--json]   the latest run of each check, and any crash")
        return 0
    n = 40
    if "-n" in argv:
        try:
            n = int(argv[argv.index("-n") + 1])
        except (IndexError, ValueError):
            print("anthill trail: -n needs a number", file=sys.stderr)
            return 2
    if argv and argv[0] == "health":
        h = health(ctx)
        if "--json" in argv:
            print(json.dumps(h, indent=2))
        else:
            print(render(h["checks"]), end="")
            print(f"{len(h['crashes'])} crash(es) in the last week")
        return 1 if h["crashes"] else 0
    events = read(ctx, n)
    print(json.dumps(events, indent=2) if "--json" in argv else render(events), end="" if "--json" not in argv else "\n")
    return 0
