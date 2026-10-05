"""`anthill migrate`: move a project from the old layout to the new one.

The owner, 5 Oct: one project has one Anthill, and every file it makes either
travels with the project's git or stays on one laptop.

    owner/      travels   charter, settings, roles, history -- the owner's
    sprints/    travels   one page per sprint
    knowledge/  travels   decisions, warnings, code pages, lessons, plans
    skills/     travels   this project's own skills
    local/      stays     the log, the map, the board, the owner's page

Without `--apply` it only says what would move. With it, it moves the files,
rewrites the board's own records of where things are, and re-renders the rules
files so they name the new paths. Nothing is deleted: every file is moved, and
anything it does not recognise is left where it is and named.

It refuses while something could break mid-move: a git worktree living inside
`.anthill/` (moving it orphans the checkout), or another chat that used Anthill
in the last few minutes (pass `--now` once you know it has stopped).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthill import context as _ctx

# (old, new), relative to `.anthill/` unless the old path starts with `/`,
# which means relative to the project root. Order matters: `plans/` moves
# before the documents that go into it.
MOVES: list[tuple[str, str]] = [
    ("anthill.config.json", "owner/settings.json"),
    ("/CONSTITUTION.md", "owner/charter.md"),
    ("roles", "owner/roles"),
    ("config-history.json", "owner/history/config-history.json"),
    ("charter-history.json", "owner/history/charter-history.json"),
    ("log", "knowledge/log"),
    ("maps", "knowledge/maps"),
    ("plans", "knowledge/plans"),
    ("idea.md", "knowledge/plans/idea.md"),
    ("prd", "knowledge/plans/prd"),
    # The Obsidian vault becomes all of .anthill/, so sprints and knowledge
    # link to each other; the owner's vault settings come up with it.
    ("knowledge/.obsidian", ".obsidian"),
    ("control-fingerprints.json", "local/control-fingerprints.json"),
    ("goals", "local/goals"),
    ("build/maps", "local/map"),
    ("build/upkeep.json", "local/upkeep.json"),
    ("build/ui.json", "local/page/ui.json"),
    ("build/ui.log", "local/page/ui.log"),
    ("build/catalogue", "local/catalogue"),
    ("build/work", "local/board/work"),
    ("contracts", "local/board/contracts"),
    ("units", "local/board/units"),
    ("audits", "local/board/audits"),
    ("sprints", "local/board/sprints"),
    # Last, so every command above still logs to the old trail.
    ("trail.jsonl", "local/log.jsonl"),
]

# Already where the new layout wants them.
STAYS = {"knowledge", "skills", ".gitignore", "build"}

QUIET_MINUTES = 10


def _src(ctx: _ctx.Context, old: str) -> Path:
    return ctx.root / old[1:] if old.startswith("/") else ctx.state / old


def _worktrees_inside(ctx: _ctx.Context) -> list[str]:
    r = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=ctx.root,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    state = str(ctx.state.resolve())
    return [line.split(" ", 1)[1] for line in r.stdout.splitlines()
            if line.startswith("worktree ") and line.split(" ", 1)[1].startswith(state)]


def _recent_other_chat(ctx: _ctx.Context) -> dict | None:
    """The last event from another chat, if it was in the last few minutes."""
    p = ctx.trail_path
    if not p.exists():
        return None
    mine = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_SESSION_ID") or ""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=QUIET_MINUTES)
    try:
        with p.open("rb") as fh:
            start = max(0, p.stat().st_size - 200_000)
            fh.seek(start)
            lines = fh.read().decode("utf-8", "replace").splitlines()
            if start:
                lines = lines[1:]           # the first line is cut in half
    except OSError:
        return None
    for line in reversed(lines):
        try:
            ev = json.loads(line)
            at = datetime.fromisoformat(ev.get("t", ""))
        except (ValueError, TypeError):
            continue
        if at < cutoff:
            return None
        if ev.get("session") and ev.get("session") != mine:
            return {"at": ev.get("t"), "tool": ev.get("tool"), "session": ev.get("session"),
                    "verb": ev.get("verb") or ev.get("kind")}
    return None


def _tracked(ctx: _ctx.Context, rel: str) -> bool:
    return subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ctx.root,
                          capture_output=True).returncode == 0


def _ignores_whole_state(ctx: _ctx.Context) -> bool:
    gi = ctx.root / ".gitignore"
    if not gi.exists():
        return False
    lines = {ln.strip() for ln in gi.read_text(encoding="utf-8", errors="replace").splitlines()}
    return bool(lines & {".anthill", ".anthill/", "/.anthill", "/.anthill/"})


def plan(ctx: _ctx.Context) -> dict:
    moves, notes = [], []
    for old, new in MOVES:
        src = _src(ctx, old)
        if not src.exists():
            continue
        dest = ctx.state / new
        moves.append({"from": str(src.relative_to(ctx.root)),
                      "to": str(dest.relative_to(ctx.root)),
                      "merge": dest.exists() and src.is_dir()})
    known_top = {m[0].split("/")[0] for m in MOVES if not m[0].startswith("/")}
    left = sorted(p.name for p in ctx.state.iterdir()
                  if p.name not in known_top | STAYS) if ctx.state.exists() else []
    if left:
        notes.append("left where they are, not part of any layout: " + ", ".join(left))
    if _tracked(ctx, "CONSTITUTION.md"):
        notes.append("CONSTITUTION.md is in this project's git: git will see it deleted and "
                     ".anthill/owner/charter.md added. Commit both together.")
    if _ignores_whole_state(ctx):
        notes.append("this project's .gitignore hides all of `.anthill/`, so the shared folders "
                     "will not travel until that line is changed to `.anthill/local/`. That file is "
                     "the project's, so Anthill leaves it to the owner.")
    return {"layout": ctx.layout, "moves": moves, "notes": notes,
            "blocked_by": {"worktrees_inside_anthill": _worktrees_inside(ctx),
                           "another_chat_active": _recent_other_chat(ctx)}}


def _move(src: Path, dest: Path, refused: list[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.move(str(src), str(dest))
        return
    if src.is_dir() and dest.is_dir():
        for child in sorted(src.iterdir()):
            _move(child, dest / child.name, refused)
        try:
            src.rmdir()
        except OSError:
            pass
        return
    refused.append(f"{src} (a file is already at {dest})")


def _rewrite_board_paths(ctx: _ctx.Context) -> int:
    """The board writes absolute paths into its own records; point them home."""
    board = ctx.state / "local" / "board"
    if not board.exists():
        return 0
    state = str(ctx.state)
    pairs = [(f"{state}/{old.rstrip('/')}", f"{state}/{new.rstrip('/')}")
             for old, new in MOVES if not old.startswith("/")]
    pairs.sort(key=lambda p: -len(p[0]))
    changed = 0
    for p in board.rglob("*.json"):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new_text = text
        for i, (a, _b) in enumerate(pairs):
            new_text = new_text.replace(a, f"\x00{i}\x00")
        for i, (_a, b) in enumerate(pairs):
            new_text = new_text.replace(f"\x00{i}\x00", b)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed += 1
    return changed


def to_sprints(ctx: _ctx.Context) -> list[str]:
    """Work pages and goals become sprints (owner, 5 Oct): a work page is a
    short sprint already, and a goal is a sprint driven end to end."""
    from anthill.sprint import page as sp
    from anthill.knowledge import pages as _pages
    s = ctx.state
    out: list[str] = []
    work = s / "knowledge" / "work"
    for p in sorted(work.glob("*.md")) if work.exists() else []:
        text = p.read_text(encoding="utf-8")
        fm = _pages.parse_frontmatter(text) or {}
        home = s / "sprints" / ("done" if str(fm.get("state")) == "done" else "active")
        home.mkdir(parents=True, exist_ok=True)
        if not fm.get("kind") and text.startswith("---"):
            text = "---\nkind: short" + text[3:]
        dest = home / p.name
        if dest.exists():
            out.append(f"kept {p.relative_to(ctx.root)}: a sprint called {p.stem} already exists")
            continue
        dest.write_text(text, encoding="utf-8")
        p.unlink()
        out.append(f"work page {p.stem} -> sprints/{home.name}/")
    try:
        work.rmdir()
    except OSError:
        pass
    goals = s / "local" / "goals"
    keep = s / "local" / "goals-before-sprints"
    for gp in sorted(goals.glob("*.json")) if goals.exists() else []:
        try:
            g = json.loads(gp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sid = sp.slug(g.get("id") or gp.stem)
        if (s / "sprints" / "active" / f"{sid}.md").exists() or (s / "sprints" / "done" / f"{sid}.md").exists():
            sid = f"goal-{sid}"[:60]
        g["id"] = sid
        g.setdefault("kind", "short")
        g["driving"] = g.get("status") in ("active", "blocked")
        # Saved through the sprint code, on a context that now reads v2 paths.
        sp.save(_ctx.resolve(ctx.root), g)
        keep.mkdir(parents=True, exist_ok=True)
        gp.replace(keep / gp.name)
        out.append(f"goal {gp.stem} -> sprint {sid} ({g.get('status')})")
    try:
        goals.rmdir()
    except OSError:
        pass
    return out


def apply(ctx: _ctx.Context, now: bool = False) -> dict:
    p = plan(ctx)
    if ctx.layout == "v2":
        return {"migrated": False, "why": "already on the new layout"}
    if not ctx.installed:
        return {"migrated": False, "why": f"Anthill is not installed in {ctx.root}"}
    if p["blocked_by"]["worktrees_inside_anthill"]:
        return {"migrated": False, "why": "git worktrees live inside .anthill/ and moving them "
                "would orphan them; finish or remove them first (`git worktree remove <path>`)",
                "worktrees": p["blocked_by"]["worktrees_inside_anthill"]}
    if p["blocked_by"]["another_chat_active"] and not now:
        return {"migrated": False, "why": f"another chat used Anthill in the last {QUIET_MINUTES} "
                "minutes; moving files under it could break its work. Wait, or pass --now once "
                "you know it has stopped.", "last": p["blocked_by"]["another_chat_active"]}

    name = (ctx.config.get("project") or {}).get("name") or ctx.root.name
    refused: list[str] = []
    moved = []
    for old, new in MOVES:
        src = _src(ctx, old)
        if src.exists():
            _move(src, ctx.state / new, refused)
            moved.append(f"{old} -> {new}")
    build = ctx.state / "build"
    if build.exists() and not any(build.iterdir()):
        build.rmdir()
    board_files = _rewrite_board_paths(ctx)
    sprints = to_sprints(ctx)

    # The rules files, hooks, locks and ignore lists all name paths; the new
    # code re-renders them, in its own process, from the moved settings.
    tool = Path(__file__).resolve().parents[1] / "bin" / "anthill"
    r = subprocess.run([str(tool), "install", "--force", "--name", name], cwd=ctx.root,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return {"migrated": True, "moved": moved, "refused": refused, "sprints": sprints,
            "board_records_rewritten": board_files,
            "reinstalled": r.returncode == 0,
            "install_output": (r.stdout + r.stderr).strip()[-600:] if r.returncode else "",
            "notes": p["notes"]}


def render(p: dict) -> str:
    L = [f"Layout now: {p['layout']}" + ("  (nothing to move)" if p["layout"] == "v2" else "")]
    for m in p["moves"]:
        L.append(f"  {m['from']:<42} -> {m['to']}" + ("   (merged into what is there)" if m["merge"] else ""))
    b = p["blocked_by"]
    if b["worktrees_inside_anthill"]:
        L.append("Blocked: git worktrees inside .anthill/: " + ", ".join(b["worktrees_inside_anthill"]))
    if b["another_chat_active"]:
        a = b["another_chat_active"]
        L.append(f"Blocked: another chat ({a['tool']}, {a['session'][:8]}) ran `{a['verb']}` at {a['at']}")
    for n in p["notes"]:
        L.append("Note: " + n)
    if p["layout"] != "v2":
        L.append("Run `anthill migrate --apply` to move them.")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    ctx = _ctx.resolve(None)
    if "--apply" in argv:
        out = apply(ctx, now="--now" in argv)
        print(json.dumps(out, indent=2))
        return 0 if out.get("migrated") else 1
    p = plan(ctx)
    print(json.dumps(p, indent=2) if "--json" in argv else render(p))
    return 0
