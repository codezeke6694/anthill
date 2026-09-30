"""Goal mode: once the owner says "do it end to end", stopping needs a reason.

The owner's measured complaint, 30 Sep: an agent told to do something end to
end does one step and reports back, so the owner circles back again and
again -- "most of the time in my development happens when things are idle".

A goal is written down with what "done" means -- a command that proves it,
a test or a score -- and its steps. The agent works through it. It may decide
for the owner what their written decisions already settle, and technical
choices, and it logs each one so the owner can overturn it. It stops for
three things only: the goal is done (the command passes), a question only the
owner can answer (a hard stop), or it has stopped making progress.

What keeps it going is Claude's Stop hook (`anthill goal --hook`): a turn that
ends with the goal unfinished and no blocker recorded is sent back with the
next step. The hook is the backstop, not the motor -- the rule in CLAUDE.md
says to keep going -- and it has a brake: if nothing was committed, noted or
decided since it last sent the agent back, it lets the turn end and marks the
goal stalled, so a stuck agent cannot spin.

Goals live in `.anthill/goals/<id>.json`; every change is on the trail.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from anthill import context as _ctx
from anthill import trail

# What an agent never decides for the owner, however sure it is. Each becomes
# a question on the owner's page, and the goal waits.
HARD_STOPS = [
    "a choice customers would see (what a screen shows, how the product behaves for them)",
    "changing live data",
    "spending money or signing up for a paid service",
    "pushing, or merging into main",
    "deleting anything that cannot be restored",
]
STALL_LIMIT = 3          # times sent back with no progress before the hook lets go
ACTIVE, BLOCKED, DONE, STALLED, STOPPED = "active", "blocked", "done", "stalled", "stopped"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def goals_dir(ctx: _ctx.Context) -> Path:
    return ctx.state / "goals"


def _path(ctx: _ctx.Context, gid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,60}", gid or ""):
        raise ValueError(f"not a goal id: {gid!r}")
    return goals_dir(ctx) / f"{gid}.json"


def load(ctx: _ctx.Context, gid: str) -> dict[str, Any]:
    return json.loads(_path(ctx, gid).read_text(encoding="utf-8"))


def save(ctx: _ctx.Context, g: dict[str, Any]) -> None:
    p = _path(ctx, g["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    g["updated"] = _now()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, indent=2), encoding="utf-8")
    tmp.replace(p)


def all_goals(ctx: _ctx.Context) -> list[dict[str, Any]]:
    d = goals_dir(ctx)
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda g: g.get("updated", ""), reverse=True)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-") or "goal"
    return s


def current(ctx: _ctx.Context, session: str = "") -> dict[str, Any] | None:
    """The goal this chat is working toward: its own open goal, newest first."""
    session = session or trail.who()["session"]
    for g in all_goals(ctx):
        if g.get("status") in (ACTIVE, BLOCKED) and session and g.get("session") == session:
            return g
    return None


# ------------------------------------------------------------------ verbs

def set_goal(ctx: _ctx.Context, title: str, done_when: str, steps: list[str],
             session: str = "") -> dict[str, Any]:
    who = trail.who()
    session = session or who["session"]
    base = _slug(title)
    gid, n = base, 2
    while _path(ctx, gid).exists():
        gid, n = f"{base}-{n}", n + 1
    g = {"id": gid, "title": title.strip(), "done_when": done_when.strip(),
         "steps": [{"text": s.strip(), "done": False} for s in steps if s.strip()],
         "status": ACTIVE, "session": session, "tool": who["tool"],
         "branch": trail._branch(ctx.root), "created": _now(), "decided": [], "blockers": [],
         "answers": [], "stalls": 0, "last_push_back": None, "result": None}
    save(ctx, g)
    trail.record("goal", ctx, session=session, goal=gid, action="set", text=g["title"])
    return g


def _open(ctx: _ctx.Context, gid: str = "") -> dict[str, Any]:
    g = load(ctx, gid) if gid else current(ctx)
    if not g:
        raise LookupError("this chat has no open goal -- start one with anthill goal set")
    return g


def step(ctx: _ctx.Context, text: str = "", done: int = 0, gid: str = "") -> dict[str, Any]:
    g = _open(ctx, gid)
    if done:
        if not 1 <= done <= len(g["steps"]):
            raise LookupError(f"there is no step {done}")
        g["steps"][done - 1]["done"] = True
        what = f"step {done} done: {g['steps'][done - 1]['text']}"
    else:
        g["steps"].append({"text": text.strip(), "done": False})
        what = f"step added: {text.strip()}"
    save(ctx, g)
    trail.record("goal", ctx, session=g["session"], goal=g["id"], action="step", text=what)
    return g


def decided(ctx: _ctx.Context, what: str, because: str, gid: str = "") -> dict[str, Any]:
    """A decision the agent took for the owner. Logged, shown, and overturnable."""
    g = _open(ctx, gid)
    entry = {"t": _now(), "what": what.strip(), "because": because.strip(), "overturned": None}
    g["decided"].append(entry)
    save(ctx, g)
    trail.record("decided", ctx, session=g["session"], goal=g["id"], text=entry["what"],
                 because=entry["because"])
    return g


def block(ctx: _ctx.Context, question: str, gid: str = "") -> dict[str, Any]:
    g = _open(ctx, gid)
    g["blockers"].append({"t": _now(), "question": question.strip(), "answer": None})
    g["status"] = BLOCKED
    save(ctx, g)
    trail.record("goal", ctx, session=g["session"], goal=g["id"], action="blocked", text=question.strip())
    return g


def finish(ctx: _ctx.Context, gid: str = "") -> dict[str, Any]:
    """Done only if the done-when command passes. The agent does not get to say so."""
    g = _open(ctx, gid)
    cmd = g.get("done_when") or ""
    if not cmd:
        raise LookupError("this goal has no done-when check; add one with anthill goal set --done-when")
    try:
        r = subprocess.run(cmd, shell=True, cwd=ctx.root, capture_output=True, text=True, timeout=1800)
        ok, tail = r.returncode == 0, (r.stdout + r.stderr).strip()[-600:]
    except subprocess.TimeoutExpired:
        ok, tail = False, "the check ran over 30 minutes"
    g["result"] = {"t": _now(), "passed": ok, "output": tail}
    if ok:
        g["status"] = DONE
    save(ctx, g)
    trail.record("goal", ctx, session=g["session"], goal=g["id"], action="done" if ok else "check-failed",
                 text=tail[-160:])
    return g


def stop(ctx: _ctx.Context, why: str, gid: str = "") -> dict[str, Any]:
    g = _open(ctx, gid)
    g["status"], g["stopped_because"] = STOPPED, why.strip()
    save(ctx, g)
    trail.record("goal", ctx, session=g["session"], goal=g["id"], action="stopped", text=why.strip())
    return g


# ----------------------------------------------------- the owner's answers

def owner_answer(ctx: _ctx.Context, gid: str, answer: str) -> dict[str, Any]:
    """The owner answers a goal's open question from their page. The goal is
    open again; the next chat on it -- or this one, when it resumes -- reads it."""
    g = load(ctx, gid)
    open_q = [b for b in g["blockers"] if not b.get("answer")]
    if not open_q:
        raise LookupError("that goal is not waiting on a question")
    open_q[-1]["answer"] = answer.strip()
    open_q[-1]["answered"] = _now()
    g["status"] = ACTIVE
    g["answers"].append({"t": _now(), "question": open_q[-1]["question"], "answer": answer.strip()})
    save(ctx, g)
    trail.record("answer", ctx, goal=gid, question=open_q[-1]["question"][:240], text=answer.strip()[:400],
                 via="owner page")
    return g


def overturn(ctx: _ctx.Context, gid: str, index: int, note: str) -> dict[str, Any]:
    g = load(ctx, gid)
    if not 0 <= index < len(g["decided"]):
        raise LookupError("no such decision")
    g["decided"][index]["overturned"] = {"t": _now(), "note": note.strip()}
    if g["status"] in (DONE, STALLED):
        g["status"] = ACTIVE          # the owner changed something; the goal is not settled
    save(ctx, g)
    trail.record("overturned", ctx, goal=gid, text=g["decided"][index]["what"][:240], note=note.strip()[:300],
                 via="owner page")
    return g


# ------------------------------------------------------------------ hook

def _progress_since(ctx: _ctx.Context, g: dict[str, Any], since: str | None) -> bool:
    if not since:
        return True
    for e in trail.read(ctx):
        # Strictly before: the trail keeps whole seconds, and a note in the same
        # second as the last push back is progress made after it.
        if e.get("t", "") < since or e.get("session") != g["session"]:
            continue
        if e.get("kind") in ("commit", "note", "decided", "correction") or \
           (e.get("kind") == "goal" and e.get("action") in ("step", "blocked", "done", "check-failed")):
            return True
    return False


def next_step(g: dict[str, Any]) -> str:
    for i, s in enumerate(g["steps"], 1):
        if not s["done"]:
            return f"step {i}: {s['text']}"
    return "every step is ticked -- run the check with `anthill goal done`"


def push_back(g: dict[str, Any], cmd: str = "anthill") -> str:
    answered = [a for a in g.get("answers", []) if a.get("answer")]
    lines = [
        f"Goal not done: {g['title']}",
        f"Done when this passes: {g['done_when']}" if g.get("done_when") else "No done-when check yet.",
        f"Next: {next_step(g)}",
    ]
    if answered:
        lines.append(f"The owner answered: \"{answered[-1]['question']}\" -> \"{answered[-1]['answer']}\"")
    lines += [
        "Carry on without reporting back. Decide for the owner whatever their written decisions "
        f"or rules already settle, and technical choices; log each with `{cmd} goal decided \"<what>\" "
        "--because \"<which decision or rule>\"`.",
        "Stop only for what the owner alone decides -- " + "; ".join(HARD_STOPS) +
        f" -- by running `{cmd} goal block \"<the question, with your recommendation>\"`.",
        f"Tick steps with `{cmd} goal step --done N`. When you believe it is done, `{cmd} goal done` runs the check.",
    ]
    return "\n".join(lines)


def stop_hook(ctx: _ctx.Context, hook: dict[str, Any]) -> dict[str, Any] | None:
    """Claude's Stop hook. Returns the block decision, or None to let the turn end."""
    session = hook.get("session_id") or ""
    g = current(ctx, session)
    if not g or g["status"] != ACTIVE:
        return None
    if not _progress_since(ctx, g, g.get("last_push_back")):
        g["stalls"] = g.get("stalls", 0) + 1
    else:
        g["stalls"] = 0
    if g["stalls"] >= STALL_LIMIT:
        g["status"] = STALLED
        save(ctx, g)
        trail.record("goal", ctx, session=session, goal=g["id"], action="stalled",
                     text=f"sent back {STALL_LIMIT} times with nothing committed, noted or decided")
        return None
    g["last_push_back"] = _now()
    save(ctx, g)
    trail.record("goal", ctx, session=session, goal=g["id"], action="pushed-back", text=next_step(g))
    return {"decision": "block", "reason": push_back(g)}


# ------------------------------------------------------------------- cli

def _opt(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else ""


def _all(argv: list[str], name: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == name]


def _words(argv: list[str]) -> str:
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = a not in ("--json", "--hook")
            continue
        out.append(a)
    return " ".join(out)


def render(g: dict[str, Any]) -> str:
    L = [f"goal {g['id']} [{g['status']}]  {g['title']}",
         f"  done when: {g.get('done_when') or '(none)'}"]
    for i, s in enumerate(g["steps"], 1):
        L.append(f"  {'[x]' if s['done'] else '[ ]'} {i}. {s['text']}")
    for d in g["decided"]:
        L.append(f"  decided for the owner: {d['what']} (because {d['because']})"
                 + (" -- OVERTURNED: " + d["overturned"]["note"] if d.get("overturned") else ""))
    for b in g["blockers"]:
        L.append(f"  waiting on the owner: {b['question']}" + (f" -> answered: {b['answer']}" if b.get("answer") else ""))
    if g.get("result"):
        L.append(f"  last check: {'passed' if g['result']['passed'] else 'failed'}")
    return "\n".join(L) + "\n"


USAGE = """anthill goal set "<the goal>" --done-when "<command that proves it>" [--step "..."]...
anthill goal step "<a step to add>"   |   anthill goal step --done N
anthill goal decided "<what you decided for the owner>" --because "<the decision or rule>"
anthill goal block "<the question only the owner can answer, with your recommendation>"
anthill goal done       runs the done-when check; only a pass closes the goal
anthill goal stop "<why>"
anthill goal [status] [--json]
"""


def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        return 0 if "--hook" in argv else 2
    if "--hook" in argv:
        raw = sys.stdin.read() if sys.stdin and not sys.stdin.isatty() else "{}"
        try:
            hook = json.loads(raw or "{}")
        except ValueError:
            hook = {}
        out = stop_hook(ctx, hook)
        if out:
            print(json.dumps(out))
        return 0
    verb = argv[0] if argv else "status"
    rest = argv[1:]
    try:
        if verb == "set":
            title, dw = _words(rest), _opt(rest, "--done-when")
            if not title or not dw:
                print("anthill goal set needs the goal and --done-when\n" + USAGE, file=sys.stderr)
                return 2
            g = set_goal(ctx, title, dw, _all(rest, "--step"))
        elif verb == "step":
            n = _opt(rest, "--done")
            g = step(ctx, done=int(n)) if n else step(ctx, text=_words(rest))
        elif verb == "decided":
            what, because = _words(rest), _opt(rest, "--because")
            if not what or not because:
                print('anthill goal decided "<what>" --because "<which decision or rule>"', file=sys.stderr)
                return 2
            g = decided(ctx, what, because)
        elif verb == "block":
            q = _words(rest)
            if not q:
                print('anthill goal block "<the question>"', file=sys.stderr)
                return 2
            g = block(ctx, q)
        elif verb == "done":
            g = finish(ctx)
            print(render(g), end="")
            if not g["result"]["passed"]:
                print("not done: the check failed --\n" + g["result"]["output"], file=sys.stderr)
                return 1
            return 0
        elif verb == "stop":
            g = stop(ctx, _words(rest) or "stopped")
        elif verb in ("status", "list"):
            gs = [current(ctx)] if verb == "status" and current(ctx) else all_goals(ctx)
            gs = [g for g in gs if g]
            print(json.dumps(gs, indent=2) if "--json" in rest else ("".join(map(render, gs)) or "no goals\n"), end="")
            return 0
        elif verb in ("-h", "--help", "help"):
            print(USAGE, end="")
            return 0
        else:
            print(f"anthill goal: unknown {verb!r}\n" + USAGE, file=sys.stderr)
            return 2
    except (LookupError, ValueError) as exc:
        print(f"anthill goal: {exc}", file=sys.stderr)
        return 2
    print(render(g), end="")
    return 0
