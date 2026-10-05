"""Sprints: every piece of work, as one page any chat can pick up.

The owner, 5 Oct: all work is a sprint, of three kinds --

    planned   big work laid out in advance; the test is written before the code
    short     the daily work: one feature, steps found by looking at the screen
    bug       something is broken; the first step is a test that shows it

-- and documentation is sprint pages plus a shared shelf of knowledge that
outlives them. A sprint replaces two older things at once: the work page
(what, where, the next step, what waits on the owner) and the goal (its steps
and the check that proves it done). The goal used to belong to the chat that
set it, so no other chat, and no other tool, could tick a step on it.

On disk, in `.anthill/sprints/` (travels with the project's git):

    active/<id>.md     the page: what people read, in Obsidian or anywhere
    active/<id>.json   its steps, check, decisions taken, questions, result
    done/<id>.*        closed sprints, the same two files

and in `.anthill/local/drive/<id>.json` (this laptop only): which chat is
driving it end to end, and how often the Stop hook has sent that chat back --
facts about one chat, which mean nothing to a teammate.

The page's header and two of its sections -- Steps, and Decisions taken for
the owner -- are written from the state file, between markers, every time it
changes. Everything else on the page is prose, and is left alone.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from anthill import context as _ctx

KINDS = ("planned", "short", "bug")
# Keys that describe one chat on one laptop, kept out of the shared file.
LOCAL_KEYS = ("session", "tool", "stalls", "last_push_back", "driving")
# The goal statuses the rest of Anthill already speaks, and the page state each means.
STATE_OF = {"active": "in-progress", "blocked": "waiting-on-owner", "stalled": "in-progress",
            "stopped": "paused", "done": "done"}

_BLOCK = "<!-- anthill:{name} -- written from the sprint's state; edit with `anthill sprint` -->"
_END = "<!-- /anthill:{name} -->"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-") or "sprint"


def check_id(sid: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", sid or ""):
        raise ValueError(f"not a sprint id: {sid!r}")
    return sid


def active_dir(ctx: _ctx.Context) -> Path:
    return ctx.sprint_pages_dir / "active"


def done_dir(ctx: _ctx.Context) -> Path:
    return ctx.sprint_pages_dir / "done"


def drive_dir(ctx: _ctx.Context) -> Path:
    return ctx.local_dir / "drive"


def page_dirs(ctx: _ctx.Context) -> list[Path]:
    """Where pages about work live: sprint folders on v2, `knowledge/work` on v1."""
    if ctx.v2:
        return [active_dir(ctx), done_dir(ctx)]
    return [ctx.knowledge_dir / "work"]


def find(ctx: _ctx.Context, sid: str) -> Path | None:
    """The page for a sprint, wherever it is."""
    check_id(sid)
    for d in page_dirs(ctx):
        p = d / f"{sid}.md"
        if p.exists():
            return p
    return None


# ------------------------------------------------------------- the page

def _frontmatter(text: str) -> tuple[list[str], str]:
    if not text.startswith("---"):
        return [], text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return [], text
    return parts[1].strip("\n").splitlines(), parts[2]


def _set_fields(lines: list[str], fields: dict[str, str]) -> list[str]:
    """Set `key: value` lines, keeping order, comments and every other key."""
    out, done = [], set()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if m and m.group(1) in fields:
            key = m.group(1)
            # drop continuation lines of the old value
            i += 1
            while i < len(lines) and lines[i].startswith((" ", "\t")) and lines[i].strip():
                i += 1
            if fields[key] != "":
                out.append(f"{key}: {fields[key]}")
            done.add(key)
            continue
        out.append(line)
        i += 1
    for key, val in fields.items():
        if key not in done and val != "":
            out.append(f"{key}: {val}")
    return out


def _put_block(body: str, name: str, heading: str, content: str) -> str:
    start, end = _BLOCK.format(name=name), _END.format(name=name)
    block = f"{start}\n{content.rstrip()}\n{end}"
    if start in body and end in body:
        head, rest = body.split(start, 1)
        return head + block + rest.split(end, 1)[1]
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.M | re.I)
    if m:
        return body[:m.end()] + "\n\n" + block + "\n" + body[m.end():]
    return body.rstrip() + f"\n\n## {heading}\n\n{block}\n"


def _yaml(val: str) -> str:
    val = " ".join(str(val).split())
    return json.dumps(val, ensure_ascii=False) if re.search(r"[:#\[\]{}]|^\s|^[\"']", val) else val


def render_page(ctx: _ctx.Context, g: dict[str, Any], text: str = "") -> str:
    """The page with its header and its generated sections brought up to date."""
    lines, body = _frontmatter(text)
    if not lines and not body.strip():
        body = (f"\n# {g['title']}\n\n## What\n\n{g.get('what') or '_What this sprint is for, in the owner’s words._'}\n\n"
                "## Steps\n\n## Waiting on the owner\n\n## Owner's answers\n\n"
                "## Decisions taken for the owner\n\n## Traps\n\n## Learned\n\n"
                "_What should outlive this sprint: start a line with `Warning:`, "
                "`Decision:` or `Rule:` and closing the sprint files it on the shared shelf._\n\n"
                "## History\n\n" + f"- {g.get('created', _now())[:10]} sprint started ({g.get('kind', 'short')})\n")
    fields = {"id": g["id"], "title": _yaml(g.get("title", "")), "kind": g.get("kind", "short"),
              "state": STATE_OF.get(g.get("status", "active"), "in-progress"),
              "branch": g.get("branch", ""), "check": _yaml(g.get("done_when", "")),
              "next": _yaml(_next_step_text(g)),
              "updated": _now()[:10]}
    lines = _set_fields(lines, fields)
    steps = "\n".join(f"- [{'x' if s.get('done') else ' '}] {s['text']}" for s in g.get("steps") or []) \
        or "_No steps yet._"
    body = _put_block(body, "steps", "Steps", steps)
    dec = [f"- {d['what']} — because {d['because']}"
           + (f" — **overturned by the owner:** {d['overturned']['note']}" if d.get("overturned") else "")
           + (" — the owner agreed" if d.get("acknowledged") and not d.get("overturned") else "")
           for d in g.get("decided") or []]
    if dec:
        body = _put_block(body, "decided", "Decisions taken for the owner", "\n".join(dec))
    pieces = g.get("pieces") or []
    if pieces:
        body = _put_block(body, "pieces", "Pieces", "\n".join(
            f"- **{x['id']}** [{x.get('status', 'todo')}] — {x['title']} · owns "
            + ", ".join(f"`{o}`" for o in x["owns"])
            + (f" · after {', '.join(x['after'])}" if x.get("after") else "")
            + (f" — {x['why']}" if x.get("why") else "") for x in pieces))
    asks = [b for b in g.get("blockers") or []]
    if asks:
        body = _put_block(body, "asks", "Waiting on the owner",
                          "\n".join(f"- {b['question']}" for b in asks if not b.get("answer"))
                          or "_Nothing open._")
        answered = [b for b in asks if b.get("answer")]
        if answered:
            body = _put_block(body, "answers", "Owner's answers",
                              "\n".join(f"- “{b['question'][:160]}”: {b['answer']}" for b in answered))
    return "---\n" + "\n".join(lines) + "\n---" + body


def _next_step_text(g: dict[str, Any]) -> str:
    """The first unticked step; else the page's own `next:`; else the check."""
    for s in g.get("steps") or []:
        if not s.get("done"):
            return s["text"]
    if g.get("status") == "done":
        return ""
    if g.get("steps"):
        return "run the check: `anthill sprint done`"
    return str(g.get("next") or "")


# ------------------------------------------------------------ the state

def _state_path(page: Path) -> Path:
    return page.with_suffix(".json")


def _from_page(ctx: _ctx.Context, page: Path) -> dict[str, Any]:
    """A sprint with no state file yet: a page written by hand, or migrated."""
    from anthill.knowledge import pages as _pages
    fm = _pages.parse_frontmatter(page.read_text(encoding="utf-8")) or {}
    state = str(fm.get("state") or "in-progress")
    status = {"waiting-on-owner": "blocked", "paused": "stopped", "done": "done"}.get(state, "active")
    return {"id": page.stem, "title": str(fm.get("title") or page.stem), "kind": str(fm.get("kind") or "short"),
            "done_when": str(fm.get("check") or ""), "steps": [], "status": status,
            "branch": str(fm.get("branch") or ""), "created": str(fm.get("updated") or ""),
            "next": str(fm.get("next") or ""),
            "decided": [], "blockers": [], "answers": [], "result": None}


def load(ctx: _ctx.Context, sid: str) -> dict[str, Any]:
    page = find(ctx, sid)
    if page is None:
        raise LookupError(f"no sprint called {sid}")
    sp = _state_path(page)
    g = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else _from_page(ctx, page)
    g.setdefault("kind", "short")
    dp = drive_dir(ctx) / f"{sid}.json"
    if dp.exists():
        try:
            g.update(json.loads(dp.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    g.setdefault("session", "")
    g.setdefault("stalls", 0)
    g.setdefault("last_push_back", None)
    g.setdefault("driving", False)
    return g


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def save(ctx: _ctx.Context, g: dict[str, Any]) -> Path:
    """Write the state, the chat-local part, and the page; file it by status."""
    sid = check_id(g["id"])
    g["updated"] = _now()
    closed = g.get("status") in ("done",)
    home = done_dir(ctx) if closed else active_dir(ctx)
    old = find(ctx, sid)
    page = home / f"{sid}.md"
    if old and old != page:
        page.parent.mkdir(parents=True, exist_ok=True)
        old.replace(page)
        if _state_path(old).exists():
            _state_path(old).replace(_state_path(page))
    shared = {k: v for k, v in g.items() if k not in LOCAL_KEYS}
    _atomic(_state_path(page), json.dumps(shared, indent=2) + "\n")
    _atomic(drive_dir(ctx) / f"{sid}.json",
            json.dumps({k: g.get(k) for k in LOCAL_KEYS}, indent=2) + "\n")
    text = page.read_text(encoding="utf-8") if page.exists() else ""
    _atomic(page, render_page(ctx, g, text))
    return page


def all_sprints(ctx: _ctx.Context) -> list[dict[str, Any]]:
    out = []
    for d in page_dirs(ctx):
        for p in sorted(d.glob("*.md")) if d.exists() else []:
            try:
                out.append(load(ctx, p.stem))
            except (OSError, ValueError, LookupError):
                continue
    return sorted(out, key=lambda g: g.get("updated", ""), reverse=True)


def new(ctx: _ctx.Context, title: str, kind: str = "short", check: str = "",
        steps: list[str] | None = None, branch: str = "", what: str = "",
        sid: str = "") -> dict[str, Any]:
    from anthill import trail
    if kind not in KINDS:
        raise ValueError(f"a sprint is one of {', '.join(KINDS)}, not {kind!r}")
    steps = [s for s in (steps or []) if s.strip()]
    if kind == "bug" and not any(re.search(r"\btest\b", s, re.I) for s in steps[:1]):
        # A bug sprint starts by showing the break; without that, "fixed" only
        # means "no longer seen", and it comes back quietly.
        steps.insert(0, "Write a test that shows the break, and see it fail")
    base = check_id(sid) if sid else slug(title)
    sid, n = base, 2
    while find(ctx, sid):
        sid, n = f"{base}-{n}", n + 1
    who = trail.who()
    g = {"id": sid, "title": title.strip(), "kind": kind, "done_when": check.strip(),
         "steps": [{"text": s.strip(), "done": False} for s in steps],
         "status": "active", "branch": branch or trail._branch(ctx.root), "created": _now(),
         "what": what.strip(), "decided": [], "blockers": [], "answers": [], "result": None,
         "session": who["session"], "tool": who["tool"], "stalls": 0,
         "last_push_back": None, "driving": False}
    save(ctx, g)
    trail.record("sprint", ctx, sprint=sid, action="new", sprint_kind=kind, text=g["title"])
    return g


# ---------------------------------------------------- the locked check
#
# The one idea worth keeping from the old test/code split (E2): the agent that
# builds the work must not be able to change what proves it. The owner locks a
# sprint's check -- the command and the files it relies on, an answer key, a
# test set -- and from then on `sprint done` refuses if any of them changed,
# until the owner has looked and locked it again.

def _digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "missing"


def lock_check(ctx: _ctx.Context, sid: str, files: list[str], by: str) -> dict[str, Any]:
    from anthill import trail
    if not by.strip():
        raise ValueError("locking a check is the owner's: --by <owner>")
    g = load(ctx, sid)
    if not g.get("done_when"):
        raise ValueError("this sprint has no check to lock")
    g["lock"] = {"check": g["done_when"], "by": by.strip(), "at": _now(),
                 "files": {f: _digest(ctx.root / f) for f in files}}
    save(ctx, g)
    trail.record("sprint", ctx, sprint=sid, action="lock", by=by.strip(), files=files[:20])
    return g["lock"]


def lock_broken(ctx: _ctx.Context, g: dict[str, Any]) -> list[str]:
    """What changed under a locked check; empty if nothing did, or it is not locked."""
    lock = g.get("lock") or {}
    if not lock:
        return []
    out = []
    if g.get("done_when") != lock.get("check"):
        out.append(f"the check itself (was `{lock.get('check')}`)")
    out += [f for f, d in (lock.get("files") or {}).items() if _digest(ctx.root / f) != d]
    return out


# ------------------------------------------------------- closing a sprint

LEARNED = re.compile(r"^\s*[-*]\s+(Warning|Decision|Rule)\s*:\s*(.+)$", re.I)


def file_learned(ctx: _ctx.Context, g: dict[str, Any]) -> list[str]:
    """Move the sprint's lessons onto the shared shelf, where later sprints see them."""
    page = find(ctx, g["id"])
    if not page:
        return []
    from anthill.knowledge import work as _work
    body = _work.sections(page.read_text(encoding="utf-8")).get("learned", "")
    kd = ctx.knowledge_dir
    filed = []
    day = _now()[:10]
    for line in body.splitlines():
        m = LEARNED.match(line)
        if not m:
            continue
        kind, text = m.group(1).lower(), m.group(2).strip()
        src = f"(from sprint {g['id']}, {day})"
        if kind == "warning":
            p = kd / "TRAPS.md"
            existing = p.read_text(encoding="utf-8") if p.exists() else "# Traps\n\nWarnings for every sprint.\n\n"
            if text not in existing:
                p.write_text(existing.rstrip("\n") + f"\n- {text} {src}\n", encoding="utf-8")
                filed.append(f"warning → {p.relative_to(ctx.root)}")
        elif kind == "decision":
            d = kd / "decisions" / f"{slug(text)}.md"
            if not d.exists():
                d.parent.mkdir(parents=True, exist_ok=True)
                d.write_text(f"---\nid: {slug(text)}\ntitle: {_yaml(text)}\ndecided: {day}\n"
                             f"source: sprint {g['id']}\nintent_attested_by:\n---\n\n"
                             f"{text}\n\n_Recorded when sprint {g['id']} closed. "
                             "The owner signs it to confirm._\n", encoding="utf-8")
                filed.append(f"decision → {d.relative_to(ctx.root)}")
        else:
            p = kd / "LEARNED.md"
            existing = p.read_text(encoding="utf-8") if p.exists() else (
                "# Rules to file\n\nRules learned in sprints, waiting for the keeper to put each "
                "on its code page, with a citation.\n\n")
            if text not in existing:
                p.write_text(existing.rstrip("\n") + f"\n- {text} {src}\n", encoding="utf-8")
                filed.append(f"rule → {p.relative_to(ctx.root)}")
    return filed


# ------------------------------------------------------------------- cli

USAGE = """anthill sprint start "<title>" --kind short|bug|planned --check "<command that proves it>" [--step "..."]... [--what "..."]
anthill sprint go [<id>] [--check "<command>"]     this chat drives it end to end; stopping needs a reason
anthill sprint step "<a step to add>" | --done N  [--sprint <id>]
anthill sprint decided "<what you decided for the owner>" --because "<the decision or rule>"  [--sprint <id>]
anthill sprint block "<the question only the owner can answer, with your recommendation>"  [--sprint <id>]
anthill sprint done  [--sprint <id>]               runs the check; only a pass closes it and files what it learned
anthill sprint stop "<why>"  [--sprint <id>]       pause it
anthill sprint lock [<id>] --file <answer key or test> ... --by <owner>   the owner locks the check
anthill sprint list [--all] [--json]   |   anthill sprint show <id>
A planned sprint with independent pieces, run by one lead chat and its helpers (skill: parallel-sprint):
  anthill sprint piece add <id> "<title>" --owns "<glob>" --check "<cmd>" [--after <piece>]
  anthill sprint waves <id>   |   brief <id> <piece>   |   referee <id> <piece> --branch <b>   |   ask <id> <piece> "<q>"
Any chat, in any tool, may work any sprint. Without --sprint, the one this chat
drives is meant, else the only open sprint on this branch.
"""

VERBS = {"start", "go", "step", "decided", "block", "done", "stop", "list", "show", "help", "lock",
         "piece", "waves", "brief", "referee", "ask"}
PARALLEL = {"piece", "waves", "brief", "referee", "ask"}


def _line(g: dict[str, Any]) -> str:
    st = g.get("steps") or []
    prog = f"{sum(1 for s in st if s.get('done'))}/{len(st)} steps" if st else "no steps"
    drive = " · driven end to end" if g.get("driving") and g.get("status") in ("active", "blocked") else ""
    return (f"{g['id']:<28} {g.get('kind', 'short'):<8} {STATE_OF.get(g.get('status', 'active'), '?'):<17} "
            f"{prog}{drive}\n    next: {_next_step_text(g) or '-'}")


def main(argv: list[str]) -> int:
    from anthill import goal as G, trail
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2
    if not ctx.v2:
        print("anthill sprint: sprint pages need the new layout -- run `anthill migrate`",
              file=sys.stderr)
        return 2
    verb, rest = (argv[0] if argv else "list"), argv[1:]
    if verb in PARALLEL:
        from anthill.sprint import parallel
        return parallel.main(verb, rest)
    gid = G._opt(rest, "--sprint")
    try:
        if verb == "start":
            title = G._words(rest)
            if not title:
                print(USAGE, file=sys.stderr)
                return 2
            g = new(ctx, title, kind=G._opt(rest, "--kind") or "short", check=G._opt(rest, "--check"),
                    steps=G._all(rest, "--step"), what=G._opt(rest, "--what"),
                    sid=G._opt(rest, "--id"), branch=G._opt(rest, "--branch"))
        elif verb == "go":
            words = [w for w in rest if not w.startswith("--")]
            g = load(ctx, words[0]) if words and not gid else G._open(ctx, gid)
            if G._opt(rest, "--check"):
                if g.get("lock") and G._opt(rest, "--check") != g["lock"].get("check"):
                    raise LookupError("this sprint's check is locked by the owner; it cannot be changed here")
                g["done_when"] = G._opt(rest, "--check")
            if not g.get("done_when"):
                raise LookupError("driving a sprint end to end needs a check that proves it done: --check \"<command>\"")
            who = trail.who()
            g.update({"driving": True, "session": who["session"], "tool": who["tool"],
                      "stalls": 0, "last_push_back": None})
            if g.get("status") in ("stopped", "stalled"):
                g["status"] = "active"
            G.save(ctx, g)
            trail.record("sprint", ctx, sprint=g["id"], action="go", text=g["title"])
        elif verb == "lock":
            words = [w for i, w in enumerate(rest) if not w.startswith("--")
                     and not (i and rest[i - 1] in ("--file", "--by", "--sprint"))]
            sid = words[0] if words else (gid or G._open(ctx).get("id"))
            out = lock_check(ctx, sid, G._all(rest, "--file"), G._opt(rest, "--by"))
            print(f"locked: `{out['check']}`" + (f" and {len(out['files'])} file(s)" if out["files"] else ""))
            return 0
        elif verb in ("step", "decided", "block", "done", "stop"):
            return G.main([verb, *rest])
        elif verb == "show":
            words = [w for w in rest if not w.startswith("--")]
            g = load(ctx, words[0]) if words else G._open(ctx, gid)
        elif verb == "list":
            gs = all_sprints(ctx)
            if "--all" not in rest:
                gs = [g for g in gs if g.get("status") != "done"]
            if "--json" in rest:
                print(json.dumps(gs, indent=2))
            else:
                print("\n".join(_line(g) for g in gs) or "no open sprints -- `anthill sprint start` makes one")
            return 0
        else:
            print(USAGE, end="", file=sys.stderr if verb != "help" else sys.stdout)
            return 0 if verb == "help" else 2
    except (LookupError, ValueError) as exc:
        print(f"anthill sprint: {exc}", file=sys.stderr)
        return 2
    print(G.render(g), end="")
    page = find(ctx, g["id"])
    if page:
        print(f"  page: {page.relative_to(ctx.root)}")
    return 0
