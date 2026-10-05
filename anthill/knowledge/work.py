"""What is being worked on, what the owner decided, and what to avoid.

The map answers *where* code lives and the card answers *how* to change it.
Neither answered the first question a cold agent has: *what am I here to do?*
Measured 28 Sep 2026: a new chat asked "where are we" read the board, which
knew nothing of the day's real work -- a new rule shipped in shadow mode
that afternoon by another session -- and reported it as not started. The truth
was in Claude's private notes, which Anthill could neither see nor check, and
the one note Anthill did hold about that work had gone false five hours after
it was written.

So the project's state lives here, as pages every session reads and every
commit checks:

  work/<id>.md       a piece of work in flight: what, where, how, the next
                     step, what waits on the owner, the traps, its history.
                     Its `state` is what the NEXT step waits on -- a page
                     marked waiting-on-owner whose next step needed nobody
                     made a cold chat report finished work as blocked.
  decisions/<id>.md  something the owner decided, in their words, and why

A work page records the commit it was last true at (`true_at`). Commits on its
branch after that are drift, and `where` says so -- the page is never quietly
behind. A branch with recent commits that no page names is untracked work, and
`where` says that too, because it is exactly what fooled the board.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from anthill.knowledge import pages

WORK_DIR = "work"
DECISIONS_DIR = "decisions"
ACTIVE = ("in-progress", "waiting-on-owner", "paused")
_CITE = re.compile(r"\((?:sg|cite|code):\s*([^)\s]+::[^)\s]+)\)")
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def sections(text: str) -> dict[str, str]:
    """`## Heading` -> its body, for the headings a page is written in."""
    marks = list(_SECTION.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1).strip().lower()] = text[m.end():end].strip()
    return out


def _bullets(body: str) -> list[str]:
    items, cur = [], ""
    for line in body.splitlines():
        if re.match(r"^\s*[-*]\s+", line):
            if cur:
                items.append(cur.strip())
            cur = re.sub(r"^\s*[-*]\s+", "", line)
        elif line.strip() and cur:
            cur += " " + line.strip()
    if cur:
        items.append(cur.strip())
    return items


def load(knowledge_dir: Path, kind: str) -> list[dict[str, Any]]:
    return load_dir(knowledge_dir / kind)


def load_work(ctx: Any) -> list[dict[str, Any]]:
    """Pages about work: sprint pages on the new layout, work pages on the old."""
    from anthill.sprint import page as _sprint
    out: list[dict[str, Any]] = []
    for d in _sprint.page_dirs(ctx):
        out += load_dir(d)
    return out


def _steps(path: Path) -> dict[str, int]:
    sp = path.with_suffix(".json")
    if not sp.exists():
        return {}
    try:
        import json
        steps = json.loads(sp.read_text(encoding="utf-8")).get("steps") or []
    except (OSError, ValueError):
        return {}
    return {"done": sum(1 for x in steps if x.get("done")), "total": len(steps)} if steps else {}


def load_dir(base: Path) -> list[dict[str, Any]]:
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm = pages.parse_frontmatter(text)
        if not fm:
            continue
        body = text.split("---", 2)[2] if text.startswith("---") else text
        out.append({"path": path, "frontmatter": fm, "sections": sections(body),
                    "cites": sorted(set(_CITE.findall(body))), "text": text})
    return out


def drift(root: Path, page: dict[str, Any]) -> dict[str, Any]:
    """Commits on the page's branch since the commit it was last true at."""
    fm = page["frontmatter"]
    branch, true_at = str(fm.get("branch") or ""), str(fm.get("true_at") or "")
    if not branch:
        return {}
    if not _git(root, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}").strip():
        return {"branch_missing": branch}
    if not true_at:
        return {"never_pinned": True}
    if not _git(root, "rev-parse", "--verify", "--quiet", f"{true_at}^{{commit}}").strip():
        return {"unknown_commit": true_at}
    scope = page_scope(page)
    args = ["log", "--format=%h %s", f"{true_at}..{branch}"]
    # Only commits that touch what the page is about. Measured: a commit that
    # changed CLAUDE.md alone flagged a work page as behind, and a
    # warning that fires on every commit is one nobody reads.
    if scope:
        args += ["--", *scope]
    behind = [ln for ln in _git(root, *args).splitlines() if ln.strip()]
    return {"behind": behind} if behind else {}


# A path named in backticks on a page: anything with a folder in it, or a
# source file. It once listed one project's top folders by name, so on any
# other project a page's named paths counted for nothing.
_PATHISH = re.compile(r"`([A-Za-z0-9_.*-]+(?:/[A-Za-z0-9_.*-]+)+/?|[A-Za-z0-9_-]+\.(?:py|ts|tsx|js|jsx|mjs|go|rs|rb|java|kt|swift|sh|sql))`")


def page_scope(page: dict[str, Any]) -> list[str]:
    """The directories a work page is about: those of every file it cites or
    names. Empty means the page cites nothing, and every commit counts."""
    files = {c.split("::", 1)[0] for c in page["cites"]}
    files |= {m for m in _PATHISH.findall(page["text"]) if "/" in m or m.endswith(".py")}
    dirs = set()
    for f in files:
        f = f.rstrip("/").split("*")[0]
        parent = str(Path(f).parent) if "." in Path(f).name else f
        dirs.add(parent if parent not in ("", ".") else f)
    return sorted(d for d in dirs if d)


def broken_citations(root: Path, page: dict[str, Any]) -> list[str]:
    """Citations on a page that no longer resolve to code."""
    from anthill.navigate import structure
    gone = []
    for sid in page["cites"]:
        try:
            if not structure.fingerprint(sid, with_callers=False).get("exists"):
                gone.append(sid)
        except ValueError:
            gone.append(sid)
    return gone


def base_branch(root: Path, configured: str = "") -> str:
    """The branch work is measured against: the configured one if it exists,
    else main, master, develop or trunk. Measured: a repository with no `main`
    made `git log --not main` fail, and untracked work silently vanished."""
    for cand in [configured, "main", "master", "develop", "trunk"]:
        if cand and _git(root, "rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}").strip():
            return cand
    return ""


def untracked(root: Path, tracked: set[str], days: int = 7, base: str = "") -> list[dict[str, Any]]:
    """Local branches with recent commits that no work page names."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    refs = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    for branch in refs.split():
        if branch in tracked or branch == base:
            continue
        # A branch already inside a tracked one is that work's history, not
        # separate work: one feature branch can sit inside another.
        if any(subprocess.run(["git", "merge-base", "--is-ancestor", branch, t], cwd=root,
                              capture_output=True).returncode == 0 for t in tracked):
            continue
        args = ["log", "--format=%h %s", f"--since={since}", branch]
        if base:
            args += ["--not", base]
        recent = [ln for ln in _git(root, *args).splitlines() if ln.strip()]
        if recent:
            out.append({"branch": branch, "commits": len(recent), "latest": recent[0]})
    return out


def board(ctx: Any) -> dict[str, Any]:
    """The job board as it stands: every unit that is not done, and why."""
    import json
    from anthill.knowledge import claims
    from anthill.orchestrate import orchestrator
    root_dir = claims.WORK_ROOT / re.sub(r"[^A-Za-z0-9._-]+", "-", ctx.root.name)
    contract = root_dir / "contract.json"
    if not contract.exists():
        return {}
    try:
        st = orchestrator.Store(ctx.root, root=root_dir)
        status = orchestrator.status(st)
        units = {u["id"]: u for u in json.loads(contract.read_text()).get("units") or []}
    except (Exception, SystemExit):
        return {}
    def title(uid: str) -> str:
        return str((units.get(uid) or {}).get("title") or "")
    def since(uid: str) -> str:
        sp = root_dir / "state" / f"{uid.replace('/', '_')}.json"
        try:
            d = json.loads(sp.read_text())
        except (OSError, ValueError):
            return ""
        return str(d.get("updated_at") or d.get("escalated_at") or d.get("claimed_at") or "")[:10]
    def why_escalated(uid: str) -> str:
        ep = root_dir / "escalations" / f"{uid}.md"
        if not ep.exists():
            return ""
        text = ep.read_text(encoding="utf-8")
        m = re.search(r"```\s*\n(.+?)\n", text)
        line = m.group(1).strip() if m else ""
        return re.sub(r",?\s*measured against [0-9a-f]{7,40}:?", "", line).strip()[:140]
    by = status.get("by_status") or {}
    blocked = [uid for uid in units if (st.read_state(uid) or {}).get("status") == "blocked"
               and uid not in (status.get("ready") or [])] if hasattr(st, "read_state") else []
    return {
        "done": by.get("done", 0), "total": status.get("unit_count", 0),
        "ready": [{"id": u, "title": title(u)} for u in status.get("ready") or []],
        "in_flight": [{"id": u, "title": title(u)} for u in status.get("in_flight") or []],
        "escalated": [{"id": u, "title": title(u), "since": since(u), "why": why_escalated(u)}
                      for u in status.get("escalated") or []],
        "blocked": [{"id": u, "title": title(u),
                     "needs": [n for n in (units[u].get("needs_iface") or [])]} for u in blocked],
    }


def disagreements(pages_: list[dict[str, Any]], b: dict[str, Any]) -> list[str]:
    """Where the board and the work pages tell a cold agent different things."""
    out = []
    by_unit = {u: r for r in pages_ for u in r.get("units") or []}
    for u in b.get("ready") or []:
        r = by_unit.get(u["id"])
        if r and r["state"] in ("paused", "waiting-on-owner"):
            out.append(f"The board says `{u['id']}` is ready, but its work page says "
                       f"{r['state'].replace('-', ' ')}: {(r['next'] or r['title']).rstrip('.')}. "
                       f"Follow the page.")
    for u in b.get("escalated") or []:
        r = by_unit.get(u["id"])
        if r:
            out.append(f"`{u['id']}` has been escalated since {u['since'] or '?'}, and the work "
                       f"it belongs to has moved on without the board ({r['title']}, "
                       f"{r['state'].replace('-', ' ')}). The owner can reopen or close it.")
    return out


def uncommitted(root: Path, active: list[dict[str, Any]], pages_: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tracked files changed but not committed, and the work each belongs to.

    Measured: a chat asked "where are we" saw a 20-line edit to placing.py
    only because it happened to run git status; another session was mid-edit
    on the same work at that moment. Two sessions on one file is the
    collision this exists to prevent.
    """
    out = []
    scopes = {pg["frontmatter"].get("id") or pg["path"].stem: page_scope(pg) for pg in pages_}
    for line in _git(root, "status", "--porcelain", "--untracked-files=no").splitlines():
        f = line[3:].strip().strip('"')
        if not f or f.startswith(".anthill/"):
            continue
        owners = [pid for pid, dirs in scopes.items()
                  if any(f == d or f.startswith(d.rstrip("/") + "/") for d in dirs)]
        out.append({"file": f, "work": owners})
    return out


def where(ctx: Any) -> dict[str, Any]:
    kd, root = ctx.knowledge_dir, ctx.root
    work = load_work(ctx)
    decisions = load(kd, DECISIONS_DIR)
    active, finished = [], []
    for p in work:
        fm = p["frontmatter"]
        s = p["sections"]
        row = {
            "id": fm.get("id") or p["path"].stem,
            "title": fm.get("title", ""),
            "kind": str(fm.get("kind") or ""),
            "steps": _steps(p["path"]),
            "check": str(fm.get("check") or ""),
            "state": fm.get("state", "in-progress"),
            "branch": fm.get("branch", ""),
            "next": fm.get("next", ""),
            "updated": str(fm.get("updated", "")),
            "waiting_on_owner": _bullets(s.get("waiting on the owner", "")),
            "owner_answers": _bullets(s.get("owner's answers", "")),
            "traps": _bullets(s.get("traps", "")),
            "page": str(p["path"].relative_to(root)),
            "drift": drift(root, p),
            "broken_citations": broken_citations(root, p),
            "confirmed_by_owner": bool(str(fm.get("intent_attested_by") or "").strip()),
            "units": [u.strip() for u in re.split(r"[,\s]+", str(fm.get("units") or fm.get("unit") or "").strip("[]")) if u.strip()],
        }
        (active if row["state"] in ACTIVE else finished).append(row)
    order = {"waiting-on-owner": 0, "in-progress": 1, "paused": 2}
    active.sort(key=lambda r: (order.get(r["state"], 3), r["updated"]), reverse=False)
    tracked = {r["branch"] for r in active + finished if r["branch"]}
    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    unpushed = len([ln for ln in _git(root, "log", "--oneline", "--branches",
                                      "--not", "--remotes").splitlines() if ln.strip()])
    b = board(ctx)
    return {
        "uncommitted": uncommitted(root, active, work),
        # A fresh install has history and no pages; this is its only "what".
        "recent": [] if active else [ln for ln in _git(root, "log", "-8", "--format=%ad  %s",
                                                           "--date=short").splitlines() if ln.strip()],
        "board": b,
        "board_disagrees": disagreements(active, b) if b else [],
        "branch": head,
        "unpushed_commits": unpushed,
        "work": active,
        "finished": [{"id": r["id"], "title": r["title"]} for r in finished],
        "untracked": untracked(root, tracked, base=base_branch(
            root, str((getattr(ctx, "config", {}) or {}).get("execution", {}).get("base_branch") or ""))),
        "decisions": [{"id": d["frontmatter"].get("id") or d["path"].stem,
                       "title": d["frontmatter"].get("title", ""),
                       "decided": str(d["frontmatter"].get("decided", "")),
                       "page": str(d["path"].relative_to(root))} for d in decisions],
        "traps": [{"work": r["id"], "trap": t} for r in active for t in r["traps"]]
                 + [{"work": "everywhere", "trap": t} for t in _shared_traps(kd)],
        "howto": [{"title": h["frontmatter"].get("title", ""),
                   "page": str(h["path"].relative_to(root))} for h in load(kd, "howto")],
    }


def _shared_traps(knowledge_dir: Path) -> list[str]:
    """Traps that belong to no one piece of work, from TRAPS.md."""
    path = knowledge_dir / "TRAPS.md"
    if not path.exists():
        return []
    return _bullets(path.read_text(encoding="utf-8").split("---", 2)[-1])


FOCUS_OTHERS = 2       # besides this branch's sprints, the most recently touched shown in full


def _cut(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def focus(w: dict[str, Any]) -> set[str]:
    """Sprints worth reading in full: this branch's, and the latest few others."""
    here = {r["id"] for r in w["work"] if r["branch"] and r["branch"] == w["branch"]}
    others = sorted((r for r in w["work"] if r["id"] not in here),
                    key=lambda r: r["updated"], reverse=True)[:FOCUS_OTHERS]
    return here | {r["id"] for r in others}


def render(w: dict[str, Any], _unused: Any = None, full: bool = False) -> str:
    """The page a chat reads before anything else.

    It has a budget (C1): it used to print every page in full and every trap of
    every page, 136 lines on one project and growing with every sprint. Now the
    sprints this chat is likely here for are in full, the rest are one line,
    and every question for the owner is listed once, in one place. `--all`
    prints everything.
    """
    shown = {r["id"] for r in w["work"]} if full else focus(w)
    L = ["# Where we are", ""]
    L.append(f"You are on `{w['branch']}`. {w['unpushed_commits']} commit(s) exist only on "
             "this machine." if w["unpushed_commits"] else f"You are on `{w['branch']}`.")
    if w.get("uncommitted"):
        L += ["", "## Being edited right now", "",
              "These files have changes nobody has committed. Another session may be "
              "working on them this minute: do not edit them without asking the owner.", ""]
        for u in w["uncommitted"]:
            L.append(f"- `{u['file']}`" + (f" — {', '.join(u['work'])}" if u["work"] else ""))
    asks = [(r, q) for r in w["work"] for q in r["waiting_on_owner"]]
    if asks:
        L += ["", "## Waiting on the owner", ""]
        L += [f"- {_cut(q, 240)}  _({r['id']})_" for r, q in asks]
    L += ["", "## Work in progress", ""]
    if not w["work"]:
        L.append("No work page is open yet. After your next commit the keeper writes one "
                 "for any branch with work on it; until then, the history below is the "
                 "record.")
    brief = []
    for r in w["work"]:
        kind = f"{r['kind']} sprint · " if r.get("kind") else ""
        st = r.get("steps") or {}
        head = (f"**{r['title']}** — {kind}{r['state'].replace('-', ' ')}"
                + (f" · {st['done']}/{st['total']} steps" if st else ""))
        if r["id"] not in shown:
            brief.append(f"- {head}" + (f" — next: {_cut(r['next'], 110)}" if r["next"] else "")
                         + f" (`{r['page']}`)")
            continue
        L.append(head + (f" · `{r['branch']}`" if r["branch"] else "")
                 + (f" · updated {r['updated']}" if r["updated"] else ""))
        if r["next"]:
            L.append(f"  - Next: {_cut(r['next'], 400) if not full else r['next']}")
        answers = r.get("owner_answers") or []
        for a in (answers if full else answers[-3:]):
            L.append(f"  - The owner answered: {_cut(a, 240) if not full else a}")
        d = r["drift"]
        if d.get("behind"):
            L.append(f"  - ⚠ This page may be behind: {len(d['behind'])} commit(s) on its "
                     f"branch since it was last true — latest: {d['behind'][0]}")
        elif d.get("branch_missing"):
            L.append(f"  - ⚠ Its branch `{d['branch_missing']}` no longer exists.")
        elif d.get("never_pinned"):
            L.append("  - ⚠ Never pinned to a commit, so drift cannot be checked.")
        gone = r["broken_citations"]
        if gone and not full and len(gone) > 2:
            L.append(f"  - ⚠ Cites {len(gone)} pieces of code that are gone: "
                     + ", ".join(gone[:2]) + f", and {len(gone) - 2} more")
        else:
            for c in gone:
                L.append(f"  - ⚠ Cites code that is gone: {c}")
        L.append(f"  - Read: `{r['page']}`")
    if brief:
        L += ["", "Also open:" if len(brief) < len(w["work"]) else "", *brief]
    if not w["work"] and w.get("recent"):
        L += ["", "## What has been happening (from git, no pages yet)", ""]
        L += [f"- {r}" for r in w["recent"]]
    if w["untracked"]:
        L += ["", "## Work no page describes", "",
              "Recent commits on these branches are not on any work page. Read their log "
              "before assuming anything about them.", ""]
        for u in w["untracked"]:
            L.append(f"- `{u['branch']}` — {u['commits']} commit(s) this week, latest: {u['latest']}")
    if w["decisions"]:
        L += ["", "## What the owner has decided", ""]
        for d in w["decisions"]:
            L.append(f"- {d['title']}" + (f" ({d['decided']})" if d["decided"] else ""))
    traps = [t for t in w["traps"] if t["work"] == "everywhere" or t["work"] in shown]
    hidden = len(w["traps"]) - len(traps)
    if traps or hidden:
        L += ["", "## Traps", ""]
        for t in traps:
            L.append(f"- {_cut(t['trap'], 300) if not full else t['trap']}  _({t['work']})_")
        if hidden:
            L.append(f"- …and {hidden} more on the other sprints: read a sprint's page before "
                     "working on it, or `anthill where --all`.")
    if w.get("howto"):
        L += ["", "## How-to", ""]
        L += [f"- {h['title']} — `{h['page']}`" for h in w["howto"]]
    b = w.get("board") or {}
    if b:
        L += ["", "## The job board", "",
              f"{b['done']} of {b['total']} units done. The board holds only work loaded onto "
              "it with `anthill sprint`; work pages above that name no unit are real work "
              "the board does not track.", ""]
        for u in b["ready"]:
            L.append(f"- **ready** `{u['id']}` — {u['title']}")
        for u in b["in_flight"]:
            L.append(f"- **in flight** `{u['id']}` — {u['title']}")
        for u in b["escalated"]:
            L.append(f"- **escalated** `{u['id']}` since {u['since'] or '?'} — {u['title']}"
                     + (f"  _({u['why']})_" if u["why"] else ""))
        for u in b["blocked"]:
            need = f" — waits on {', '.join(u['needs'])}" if u["needs"] else " — not in the current plan"
            L.append(f"- **blocked** `{u['id']}`{need}")
        if w.get("board_disagrees"):
            L += ["", "**Where the board and the pages disagree:**", ""]
            L += [f"- ⚠ {d}" for d in w["board_disagrees"]]
    L += ["", "Then: `anthill orient` for the map, `anthill start \"<task>\"` for the place."]
    return "\n".join(L) + "\n"
