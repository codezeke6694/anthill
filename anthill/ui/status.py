"""The owner's page, as the owner reads it (6 Oct 2026).

The owner could not make sense of a page organised around Anthill's insides --
five tabs, "Running now" beside "Work in progress", messages per commit. What
they want to see, in their words: what is pending on them ("some gets ignored
or missed out"), "a job board, what is being worked on, my sprints, a status
update", "analytics showing it really is helping", their decisions and the
traps. So the page answers exactly that, in that order:

    needs      questions, decisions made for them to check, work that looks finished
    board      sprints in progress, paused, finished this week
    impact     what Anthill did that would otherwise have been lost or gone wrong
    happened   saves, refusals, sprints and answers, in plain words

A number is shown with the data it rests on, and a measure with too little
data says so instead of guessing.
"""
from __future__ import annotations

import json
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

STUCK_DAYS = 3
MIN_SAMPLE = 20


def _git(root, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _when(t: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(t))
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(str(t)[:10])
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------- header

def header(ctx: Any, w: dict[str, Any]) -> dict[str, Any]:
    from anthill.knowledge import work
    base = work.base_branch(ctx.root, str((ctx.config.get("execution") or {}).get("base_branch") or ""))
    unmerged = []
    for b in _git(ctx.root, "for-each-ref", "--format=%(refname:short)", "refs/heads").split():
        if base and b != base and (n := _git(ctx.root, "rev-list", "--count", f"{base}..{b}")) not in ("", "0"):
            unmerged.append({"branch": b, "commits": int(n)})
    try:
        from anthill import version
        v = version.status(ctx)
    except Exception:                       # noqa: BLE001
        v = {}
    return {"branch": w.get("branch", ""), "base": base, "unpushed": w.get("unpushed_commits", 0),
            "unmerged": unmerged, "anthill": v}


# ------------------------------------------------------------------ board

def _sprints(ctx: Any) -> list[dict[str, Any]]:
    if not ctx.v2:
        return []
    from anthill.sprint import page
    try:
        return page.all_sprints(ctx)
    except Exception:                       # noqa: BLE001
        return []


def _idle_days(ctx: Any, row: dict[str, Any], g: dict[str, Any] | None) -> int | None:
    stamps = [_when(row.get("updated") or ""), _when((g or {}).get("updated") or "")]
    if row.get("branch") and not row.get("branch_gone"):
        stamps.append(_when(_git(ctx.root, "log", "-1", "--format=%cI", row["branch"])))
    stamps = [s for s in stamps if s]
    return (_now() - max(stamps)).days if stamps else None


def board(ctx: Any, w: dict[str, Any]) -> dict[str, Any]:
    sprints = {g["id"]: g for g in _sprints(ctx)}
    cards = {"in_progress": [], "paused": []}
    for r in w.get("work") or []:
        g = sprints.get(r["id"])
        idle = _idle_days(ctx, r, g)
        card = {"id": r["id"], "title": r["title"], "kind": r.get("kind") or "", "steps": r.get("steps") or {},
                "next": r.get("next") or "", "branch": r.get("branch") or "",
                "waits_on_you": r["state"] == "waiting-on-owner" or bool(r.get("waiting_on_owner")),
                "looks_finished": str(((g or {}).get("looks_finished") or "")),
                "driven": bool((g or {}).get("driving")), "idle_days": idle,
                "stuck": idle is not None and idle >= STUCK_DAYS, "page": r.get("page", "")}
        cards["paused" if r["state"] == "paused" else "in_progress"].append(card)
    week_ago = _now() - timedelta(days=7)
    finished = []
    for g in sprints.values():
        if g.get("status") != "done":
            continue
        when = _when((g.get("result") or {}).get("t") or g.get("updated") or "")
        if when and when >= week_ago:
            finished.append({"id": g["id"], "title": g.get("title", ""), "when": when.isoformat(),
                             "closed_by": (g.get("result") or {}).get("closed_by") or ""})
    finished.sort(key=lambda x: x["when"], reverse=True)
    return {**cards, "finished_week": finished}


def to_close(ctx: Any) -> list[dict[str, Any]]:
    """Sprints an agent says are finished, for the owner to close or keep open."""
    return [{"id": g["id"], "title": g.get("title", ""), "because": g["looks_finished"]}
            for g in _sprints(ctx) if g.get("looks_finished") and g.get("status") != "done"]


# ----------------------------------------------------------------- impact

def impact(events: list[dict[str, Any]], todo: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    live = [e for e in events if not e.get("imported")]
    since = min((e.get("t", "") for e in live), default="")[:10]
    guards = [e for e in live if e.get("kind") == "command" and e.get("verb") == "guard" and e.get("rc") == 1]
    pushes = [e for e in guards if "--push" in str(e.get("args") or "")]
    sessions = [e for e in live if e.get("kind") == "session"]
    picked = Counter(e.get("source") for e in sessions if e.get("source") in ("resume", "compact"))
    answered = [e for e in live if e.get("kind") == "answer" and e.get("via") == "owner page"]
    decided = [e for e in live if e.get("kind") == "decided"]
    overturned = [e for e in live if e.get("kind") == "overturned"]
    corrections = [e for e in live if e.get("kind") == "correction"]

    # Fresh chat to first saved change: only chats that started fresh, and only
    # once there are enough of them. A design talk that runs for hours before
    # the first save made the median swing from 17 minutes to 9 hours.
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        if e.get("session"):
            by_session[e["session"]].append(e)
    fresh = []
    started = {e.get("session") for e in sessions if e.get("source") == "startup"}
    for s, evs in by_session.items():
        if s not in started:
            continue
        evs.sort(key=lambda e: e.get("t", ""))
        first = next((e for e in evs if e.get("kind") == "prompt"), None)
        save = next((e for e in evs if e.get("kind") == "commit" and first and e.get("t", "") >= first.get("t", "")), None)
        if first and save:
            a, z = _when(first["t"]), _when(save["t"])
            if a and z:
                fresh.append((z - a).total_seconds() / 60)

    weeks: Counter = Counter()
    for e in events:
        if e.get("kind") == "commit" and (d := _when(e.get("t", ""))):
            weeks[d.strftime("%G-W%V")] += 1
    last6 = sorted(weeks)[-6:]
    stuck = [c["title"] for c in b.get("in_progress", []) + b.get("paused", []) if c.get("stuck")]
    return {
        "since": since,
        "pushes_stopped": {"n": len(pushes), "from": pushes[0]["t"][:10] if pushes else "",
                           "to": pushes[-1]["t"][:10] if pushes else ""},
        "saves_stopped": len(guards) - len(pushes),
        "picked_up": {"n": sum(picked.values()), "resumed": picked.get("resume", 0),
                      "compressed": picked.get("compact", 0), "chats": len(sessions)},
        "questions_held": {"n": len(todo.get("todo") or []), "answered_on_page": len(answered)},
        "decided_for_you": {"n": len(decided), "overturned": len(overturned),
                            "to_check": len(todo.get("review") or [])},
        "corrections": len(corrections),
        "sprints": {"finished_week": len(b.get("finished_week") or []), "stuck": stuck},
        "fresh_chat": ({"median_min": round(statistics.median(fresh)), "n": len(fresh)}
                       if len(fresh) >= MIN_SAMPLE else {"median_min": None, "n": len(fresh)}),
        "saves_per_week": [{"week": wk.split("-")[1], "n": weeks[wk]} for wk in last6],
    }


# --------------------------------------------------------------- happened

def happened(events: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    out = []
    for e in sorted(events, key=lambda e: e.get("t", ""), reverse=True):
        k, line = e.get("kind"), None
        if k == "commit":
            line = ("saved", str(e.get("subject") or ""))
        elif k == "command" and e.get("verb") == "guard" and e.get("rc") == 1:
            push = "--push" in str(e.get("args") or "")
            line = ("stopped", f"A {'push' if push else 'save'} from {e.get('branch', '?')} was refused"
                    + (": only you push" if push else ""))
        elif k == "hook-skipped":
            line = ("warning", str(e.get("text") or "a save skipped the checks"))
        elif k == "sprint" and e.get("action") in ("new", "closed", "finished", "go", "lock", "piece-accepted"):
            words = {"new": "started", "closed": "closed", "finished": "proposed as finished",
                     "go": "driven end to end", "lock": "check locked", "piece-accepted": "piece accepted"}
            line = ("sprint", f"{e.get('sprint', '')} {words[e['action']]}"
                    + (f": {e.get('text')}" if e.get("text") and e["action"] in ("new", "closed", "finished") else ""))
        elif k == "answer" and e.get("via") == "owner page":
            line = ("you", f"answered “{str(e.get('question') or '')[:80]}”: {e.get('text', '')}")
        elif k == "signed":
            line = ("you", f"signed {e.get('page', '')}")
        elif k == "decided":
            line = ("decided", f"for you: {e.get('text', '')}")
        elif k == "correction":
            line = ("corrected", f"{e.get('page', '')}: now “{e.get('now', '')}”")
        if line:
            out.append({"t": e.get("t", ""), "kind": line[0], "text": line[1][:200]})
            if len(out) >= limit:
                break
    return out


def build(ctx: Any, w: dict[str, Any], todo: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    b = board(ctx, w)
    close = to_close(ctx)
    finished_ids = {c["id"] for c in close}
    questions = [{**q, "maybe_stale": q.get("ref") in finished_ids} for q in todo.get("todo") or []]
    return {
        "header": header(ctx, w),
        "needs": {"questions": questions, "review": todo.get("review") or [], "close": close},
        "board": b,
        "impact": impact(events, todo, b),
        "decisions": w.get("decisions") or [],
        "warnings": w.get("traps") or [],
        "happened": happened(events),
    }
