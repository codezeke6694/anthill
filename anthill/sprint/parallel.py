"""Parallel pieces: one lead chat, many helpers (owner, 5 Oct).

The owner tells one chat "work on this sprint". That chat becomes the lead;
Anthill tells it which parts of the sprint can run at once and hands each
helper it starts a short brief. The owner never opens extra chats.

    anthill sprint piece add <sprint> "<title>" --owns "<glob>" --check "<cmd>" [--after <piece>]
    anthill sprint waves <sprint>          what can run at once, wave by wave
    anthill sprint brief <sprint> <piece>  what one helper is told
    anthill sprint referee <sprint> <piece> --branch <helper's branch>
    anthill sprint ask <sprint> <piece> "<question>"   a helper's question, to the owner

Anthill is the planner and the referee; the lead is the foreman; the helpers
do the pieces. A piece is accepted only if every file it changed is one it
owns and its check passes on its own branch; it is then merged onto the
sprint's holding branch, `sprint/<id>`, and a clash with what is already there
is stopped and shown. Nothing here touches `main` or the owner's working
folder: every merge and every check runs in a throwaway worktree.
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePath
from typing import Any

from anthill import context as _ctx
from anthill.sprint import page as sp


def _git(root: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def _pid(text: str) -> str:
    return sp.slug(text)[:40]


def holding_branch(sid: str) -> str:
    return f"sprint/{sid}"


# ------------------------------------------------------------- the plan

def _matches(path: str, glob: str) -> bool:
    g = glob.rstrip("/")
    if g.endswith("/**"):
        return path == g[:-3] or path.startswith(g[:-3] + "/")
    try:
        if PurePath(path).full_match(g):
            return True
    except AttributeError:                    # Python < 3.13
        pass
    return fnmatch.fnmatch(path, g) or path == g


def owns(piece: dict[str, Any], path: str) -> bool:
    return any(_matches(path, g) for g in piece.get("owns") or [])


def _overlap(ctx: _ctx.Context, a: list[str], b: list[str]) -> list[str]:
    """Files, existing or about to be, that two pieces would both own."""
    _, listed = _git(ctx.root, "ls-files")
    files = [f for f in listed.splitlines() if f]
    both = sorted(f for f in files if any(_matches(f, x) for x in a) and any(_matches(f, y) for y in b))
    if both:
        return both
    # Not on disk yet: two globs on the same folder, or one inside the other.
    def root_of(g: str) -> str:
        return g.split("*", 1)[0].rstrip("/")
    for x in a:
        for y in b:
            rx, ry = root_of(x), root_of(y)
            if x == y or (rx and ry and (rx == ry or rx.startswith(ry + "/") or ry.startswith(rx + "/"))
                          and ("*" in x or "*" in y)):
                return [f"{x} / {y}"]
    return []


def add_piece(ctx: _ctx.Context, sid: str, title: str, owns_: list[str], check: str,
              after: list[str] | None = None) -> dict[str, Any]:
    g = sp.load(ctx, sid)
    if g.get("kind") != "planned":
        raise ValueError("pieces belong to a planned sprint; start one with --kind planned")
    if not owns_ or not check.strip():
        raise ValueError("a piece needs the files it owns (--owns) and the check that proves it (--check)")
    pieces = g.setdefault("pieces", [])
    pid = _pid(title)
    if any(p["id"] == pid for p in pieces):
        raise ValueError(f"this sprint already has a piece called {pid}")
    for a in after or []:
        if not any(p["id"] == a for p in pieces):
            raise ValueError(f"no piece called {a} to wait for")
    piece = {"id": pid, "title": title.strip(), "owns": owns_, "check": check.strip(),
             "after": list(after or []), "status": "todo"}
    pieces.append(piece)
    waves(ctx, g)                              # refuses a plan two pieces of one wave would share
    sp.save(ctx, g)
    return piece


def waves(ctx: _ctx.Context, g: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Pieces in the order they can run: each wave waits only on earlier ones.

    Two pieces in one wave that would touch the same file are refused: they
    would merge into a clash, and the helpers cannot see each other.
    """
    pieces = {p["id"]: p for p in g.get("pieces") or []}
    placed: dict[str, int] = {}
    left = list(pieces)
    out: list[list[dict[str, Any]]] = []
    while left:
        ready = [pid for pid in left if all(a in placed for a in pieces[pid]["after"])]
        if not ready:
            raise ValueError("these pieces wait on each other in a circle: " + ", ".join(left))
        wave = [pieces[pid] for pid in ready]
        for i, p in enumerate(wave):
            for q in wave[i + 1:]:
                shared = _overlap(ctx, p["owns"], q["owns"])
                if shared:
                    raise ValueError(f"`{p['id']}` and `{q['id']}` would run at once and both own "
                                     f"{', '.join(shared[:3])}: make one wait for the other "
                                     f"(--after) or split the files")
        for p in wave:
            placed[p["id"]] = len(out)
        out.append(wave)
        left = [pid for pid in left if pid not in placed]
    return out


# ------------------------------------------------------------ the briefs

def brief(ctx: _ctx.Context, sid: str, pid: str) -> str:
    g = sp.load(ctx, sid)
    p = next((x for x in g.get("pieces") or [] if x["id"] == pid), None)
    if p is None:
        raise LookupError(f"sprint {sid} has no piece {pid}")
    from anthill.knowledge import work
    w = work.where(ctx)
    globs = p["owns"]
    roots = {gl.split("*", 1)[0].rstrip("/") for gl in globs}

    def touches(text: str) -> bool:
        return any(r and r in text for r in roots)
    traps = [t["trap"] for t in w.get("traps") or []
             if (t["work"] == sid) or (t["work"] == "everywhere" and touches(t["trap"]))]
    decisions = [d["title"] for d in w.get("decisions") or [] if touches(d.get("title", ""))]
    branch = f"piece/{sid}/{pid}"
    L = [f"# Piece `{pid}` of sprint `{sid}`: {p['title']}", "",
         f"Sprint: {g['title']}.", "",
         "## What you may change", "",
         *[f"- `{x}`" for x in globs], "",
         "Nothing else. A file outside these is refused when your work comes back, and the piece "
         "is not accepted.", "",
         "## What proves it done", "", f"```bash\n{p['check']}\n```", "",
         "## How", "",
         f"1. Work on a branch of your own: `git switch -c {branch}`.",
         "2. Build the piece, inside the files above. Commit as you go.",
         "3. Run the check until it passes. Do not edit the check, or a test it runs that "
         "you do not own.",
         f"4. End your report with one line: `BRANCH: {branch}`.",
         "5. Need a decision only the owner can make? Stop, and end your report with "
         "`QUESTION: <the question, with your recommendation>`. Do not guess.",
         "6. Do not push, do not merge, do not touch `main`. The lead and Anthill do that.", ""]
    if traps:
        L += ["## Warnings that touch these files", "", *[f"- {t}" for t in traps], ""]
    if decisions:
        L += ["## The owner's decisions on this", "", *[f"- {d}" for d in decisions], ""]
    return "\n".join(L)


def lead_plan(ctx: _ctx.Context, sid: str) -> str:
    g = sp.load(ctx, sid)
    ws = waves(ctx, g)
    L = [f"Sprint `{sid}`: {len(g.get('pieces') or [])} piece(s) in {len(ws)} wave(s). "
         f"Accepted pieces land on `{holding_branch(sid)}`.", ""]
    for i, wave in enumerate(ws, 1):
        L.append(f"Wave {i}: " + ", ".join(f"{p['id']} [{p['status']}]" for p in wave))
    nxt = next((w for w in ws if any(p["status"] != "done" for p in w)), None)
    if nxt:
        todo = [p for p in nxt if p["status"] in ("todo", "refused")]
        L += ["", "Next: start one helper per piece below, all at once, each in its own copy of "
              "the project, each given only its brief:", ""]
        L += [f"  anthill sprint brief {sid} {p['id']}" for p in todo] or ["  (pieces of this wave are out with helpers)"]
        L += ["", f"As each reports `BRANCH: <name>`: anthill sprint referee {sid} <piece> --branch <name>",
              f"If it reports `QUESTION: ...`: anthill sprint ask {sid} <piece> \"<the question>\""]
    else:
        L += ["", f"Every piece is in. Review `{holding_branch(sid)}`, then `anthill sprint done --sprint {sid}`."]
    return "\n".join(L)


# ----------------------------------------------------------- the referee

def _worktree(ctx: _ctx.Context, ref: str, detach: bool = True) -> Path:
    d = Path(tempfile.mkdtemp(prefix="anthill-referee-"))
    shutil.rmtree(d)
    args = ["worktree", "add", "--quiet"] + (["--detach"] if detach else []) + [str(d), ref]
    rc, out = _git(ctx.root, *args)
    if rc != 0:
        raise RuntimeError(out[-300:])
    return d


def _drop(ctx: _ctx.Context, d: Path) -> None:
    _git(ctx.root, "worktree", "remove", "--force", str(d))
    shutil.rmtree(d, ignore_errors=True)


def referee(ctx: _ctx.Context, sid: str, pid: str, branch: str) -> dict[str, Any]:
    from anthill import trail
    g = sp.load(ctx, sid)
    p = next((x for x in g.get("pieces") or [] if x["id"] == pid), None)
    if p is None:
        raise LookupError(f"sprint {sid} has no piece {pid}")
    hold = holding_branch(sid)
    if _git(ctx.root, "rev-parse", "--verify", "--quiet", f"refs/heads/{hold}")[0] != 0:
        base = g.get("branch") or "HEAD"
        rc, out = _git(ctx.root, "branch", hold, base)
        if rc != 0:
            raise RuntimeError(f"could not make the holding branch from {base}: {out}")
    if _git(ctx.root, "rev-parse", "--verify", "--quiet", branch)[0] != 0:
        return _verdict(ctx, g, p, False, f"there is no branch `{branch}`", branch)
    _, mb = _git(ctx.root, "merge-base", hold, branch)
    _, changed = _git(ctx.root, "diff", "--name-only", f"{mb}..{branch}")
    files = [f for f in changed.splitlines() if f]
    if not files:
        return _verdict(ctx, g, p, False, "the branch changes nothing", branch)
    outside = [f for f in files if not owns(p, f)]
    if outside:
        return _verdict(ctx, g, p, False, "it changed files it does not own: " + ", ".join(outside[:5]), branch)
    wt = _worktree(ctx, branch)
    try:
        r = subprocess.run(p["check"], shell=True, cwd=wt, capture_output=True, text=True,
                           env=ctx.exec_env(), timeout=1800)
        if r.returncode != 0:
            tail = (r.stdout + r.stderr).strip()[-400:]
            return _verdict(ctx, g, p, False, f"its check failed on its own branch: {tail}", branch)
    finally:
        _drop(ctx, wt)
    wt = _worktree(ctx, hold, detach=False)
    try:
        rc, out = _git(wt, "-c", "user.name=anthill", "-c", "user.email=anthill@localhost",
                       "merge", "--no-ff", "-m", f"Piece {pid} of sprint {sid}: {p['title']}", branch)
        if rc != 0:
            _, clash = _git(wt, "diff", "--name-only", "--diff-filter=U")
            _git(wt, "merge", "--abort")
            return _verdict(ctx, g, p, False, "it clashes with what is already on the holding branch: "
                            + (", ".join(clash.splitlines()[:5]) or out[-200:]), branch)
    finally:
        _drop(ctx, wt)
    trail.record("sprint", ctx, sprint=sid, action="piece-accepted", piece=pid, branch=branch)
    return _verdict(ctx, g, p, True, f"merged onto `{hold}`", branch)


def _verdict(ctx, g, p, ok: bool, why: str, branch: str) -> dict[str, Any]:
    p["status"], p["why"], p["branch"] = ("done" if ok else "refused"), why, branch
    sp.save(ctx, g)
    return {"piece": p["id"], "accepted": ok, "why": why}


def ask(ctx: _ctx.Context, sid: str, pid: str, question: str) -> dict[str, Any]:
    from anthill import goal
    g = sp.load(ctx, sid)
    p = next((x for x in g.get("pieces") or [] if x["id"] == pid), None)
    if p is None:
        raise LookupError(f"sprint {sid} has no piece {pid}")
    p["status"] = "asking"
    sp.save(ctx, g)
    goal.block(ctx, f"[piece {pid}] {question.strip()}", gid=sid)
    return {"piece": pid, "asked": question.strip()}


# ------------------------------------------------------------------- cli

def main(verb: str, argv: list[str]) -> int:
    import json
    import sys
    from anthill import goal as G
    ctx = _ctx.resolve(None)
    words = [a for i, a in enumerate(argv) if not a.startswith("--")
             and not (i and argv[i - 1] in ("--owns", "--check", "--after", "--branch"))]
    try:
        if verb == "piece":
            if not words or words[0] != "add" or len(words) < 3:
                print('anthill sprint piece add <sprint> "<title>" --owns "<glob>" --check "<cmd>" [--after <piece>]',
                      file=sys.stderr)
                return 2
            out = add_piece(ctx, words[1], " ".join(words[2:]), G._all(argv, "--owns"),
                            G._opt(argv, "--check"), G._all(argv, "--after"))
            print(json.dumps(out, indent=2))
        elif verb == "waves":
            print(lead_plan(ctx, words[0]))
        elif verb == "brief":
            print(brief(ctx, words[0], words[1]))
        elif verb == "referee":
            out = referee(ctx, words[0], words[1], G._opt(argv, "--branch"))
            print(json.dumps(out, indent=2))
            return 0 if out["accepted"] else 1
        elif verb == "ask":
            print(json.dumps(ask(ctx, words[0], words[1], " ".join(words[2:]))))
        else:
            return 2
    except (LookupError, ValueError, RuntimeError, IndexError) as exc:
        print(f"anthill sprint {verb}: {exc}", file=sys.stderr)
        return 2
    return 0
