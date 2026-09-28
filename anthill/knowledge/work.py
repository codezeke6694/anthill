"""What is being worked on, what the owner decided, and what to avoid.

The map answers *where* code lives and the card answers *how* to change it.
Neither answered the first question a cold agent has: *what am I here to do?*
Measured 28 Sep 2026: a new chat asked "where are we" read the board, which
knew nothing of the day's real work -- a placement rule shipped in shadow mode
that afternoon by another session -- and reported it as not started. The truth
was in Claude's private notes, which Anthill could neither see nor check, and
the one note Anthill did hold about that work had gone false five hours after
it was written.

So the project's state lives here, as pages every session reads and every
commit checks:

  work/<id>.md       a piece of work in flight: what, where, how, the next
                     step, what waits on the owner, the traps, its history
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
    base = knowledge_dir / kind
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
    log = _git(root, "log", "--format=%h %s", f"{true_at}..{branch}")
    behind = [ln for ln in log.splitlines() if ln.strip()]
    return {"behind": behind} if behind else {}


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


def untracked(root: Path, tracked: set[str], days: int = 7) -> list[dict[str, Any]]:
    """Local branches with recent commits that no work page names."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    refs = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    for branch in refs.split():
        if branch in tracked or branch in ("main", "master"):
            continue
        # A branch already inside a tracked one is that work's history, not
        # separate work: work/two-views sits inside work/geotag-test-set.
        if any(subprocess.run(["git", "merge-base", "--is-ancestor", branch, t], cwd=root,
                              capture_output=True).returncode == 0 for t in tracked):
            continue
        recent = [ln for ln in _git(root, "log", "--format=%h %s", f"--since={since}",
                                    branch, "--not", "main").splitlines() if ln.strip()]
        if recent:
            out.append({"branch": branch, "commits": len(recent), "latest": recent[0]})
    return out


def where(ctx: Any) -> dict[str, Any]:
    kd, root = ctx.knowledge_dir, ctx.root
    work = load(kd, WORK_DIR)
    decisions = load(kd, DECISIONS_DIR)
    active, finished = [], []
    for p in work:
        fm = p["frontmatter"]
        s = p["sections"]
        row = {
            "id": fm.get("id") or p["path"].stem,
            "title": fm.get("title", ""),
            "state": fm.get("state", "in-progress"),
            "branch": fm.get("branch", ""),
            "next": fm.get("next", ""),
            "updated": str(fm.get("updated", "")),
            "waiting_on_owner": _bullets(s.get("waiting on the owner", "")),
            "traps": _bullets(s.get("traps", "")),
            "page": str(p["path"].relative_to(root)),
            "drift": drift(root, p),
            "broken_citations": broken_citations(root, p),
            "confirmed_by_owner": bool(str(fm.get("intent_attested_by") or "").strip()),
        }
        (active if row["state"] in ACTIVE else finished).append(row)
    order = {"waiting-on-owner": 0, "in-progress": 1, "paused": 2}
    active.sort(key=lambda r: (order.get(r["state"], 3), r["updated"]), reverse=False)
    tracked = {r["branch"] for r in active + finished if r["branch"]}
    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    unpushed = len([ln for ln in _git(root, "log", "--oneline", "--branches",
                                      "--not", "--remotes").splitlines() if ln.strip()])
    return {
        "branch": head,
        "unpushed_commits": unpushed,
        "work": active,
        "finished": [{"id": r["id"], "title": r["title"]} for r in finished],
        "untracked": untracked(root, tracked),
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


def render(w: dict[str, Any], board: dict[str, Any] | None = None) -> str:
    L = ["# Where we are", ""]
    L.append(f"You are on `{w['branch']}`. {w['unpushed_commits']} commit(s) exist only on "
             "this machine." if w["unpushed_commits"] else f"You are on `{w['branch']}`.")
    L += ["", "## Work in progress", ""]
    if not w["work"]:
        L.append("No work page is open. If you are starting something, it needs one "
                 "(the keeper writes it).")
    for r in w["work"]:
        L.append(f"**{r['title']}** — {r['state'].replace('-', ' ')}"
                 + (f" · `{r['branch']}`" if r["branch"] else "")
                 + (f" · updated {r['updated']}" if r["updated"] else ""))
        if r["next"]:
            L.append(f"  - Next: {r['next']}")
        for q in r["waiting_on_owner"]:
            L.append(f"  - Waiting on the owner: {q}")
        d = r["drift"]
        if d.get("behind"):
            L.append(f"  - ⚠ This page may be behind: {len(d['behind'])} commit(s) on its "
                     f"branch since it was last true — latest: {d['behind'][0]}")
        elif d.get("branch_missing"):
            L.append(f"  - ⚠ Its branch `{d['branch_missing']}` no longer exists.")
        elif d.get("never_pinned"):
            L.append("  - ⚠ Never pinned to a commit, so drift cannot be checked.")
        for c in r["broken_citations"]:
            L.append(f"  - ⚠ Cites code that is gone: {c}")
        L.append(f"  - Read: `{r['page']}`")
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
    if w["traps"]:
        L += ["", "## Traps", ""]
        for t in w["traps"]:
            L.append(f"- {t['trap']}  _({t['work']})_")
    if w.get("howto"):
        L += ["", "## How-to", ""]
        L += [f"- {h['title']} — `{h['page']}`" for h in w["howto"]]
    if board:
        L += ["", "## The board", "",
              f"{board.get('done', 0)} of {board.get('total', 0)} units done"
              + (f"; ready: {', '.join(board['ready'])}" if board.get("ready") else "")
              + (f"; escalated: {', '.join(board['escalated'])}" if board.get("escalated") else "")
              + ". The board holds only work that was loaded onto it; the pages above "
                "are the fuller record."]
    L += ["", "Then: `anthill orient` for the map, `anthill start \"<task>\"` for the place."]
    return "\n".join(L) + "\n"
