#!/usr/bin/env python3
"""Stray agent artefacts, and where they belong.

Found by watching a real session: the planner produced a sprint plan, an
`idea.md`, and a four-file PRD -- all good work, all written to the project
root, which is not where any of it belongs.

The cause is a gap in the ownership model rather than a careless agent.
`owns` is enforced by `check_ownership`, which compares a worktree's diff
against a unit's declared paths -- so it binds a *builder inside a unit* and
nothing else. A planner works in the main tree with no unit and therefore no
boundary, and nothing in the role files said where documents go. An unstated
convention is not a convention.

So this module does two things: names the sanctioned locations, and reports what
is sitting outside them. Reporting rather than refusing, because the artefacts
themselves are usually wanted -- it is their location that is wrong, and
deleting an agent's planning work to enforce tidiness would be its own failure.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

# Where each kind of agent-authored document belongs, and why it is not the root.
DESTINATIONS: list[tuple[str, str, str]] = [
    ("idea.md",          "idea.md",     "the locked idea — one file, so it keeps its name"),
    ("sprint-plan.md",   "plans/",      "a sprint plan is reference, not state"),
    ("sprint_plan.md",   "plans/",      "a sprint plan is reference, not state"),
    ("PRD",              "prd/",        "product requirements the planner authored"),
    ("prd",              "prd/",        "product requirements the planner authored"),
    ("backlog.yaml",     "sprints/",    "sprint state"),
    ("backlog.yml",      "sprints/",    "sprint state"),
    ("planner-brief.md", "sprints/",    "the planner's working state"),
    ("agent-log.md",     "log/",        "delivery log"),
    ("active-skills.yaml", "active-skills.yaml", "session skill policy"),
]

# The same homes in the v2 layout: documents a person wrote travel with the
# project under knowledge/, board state stays on this laptop.
V2_HOME = {
    "idea.md": "knowledge/plans/idea.md",
    "plans/": "knowledge/plans/",
    "prd/": "knowledge/plans/prd/",
    "sprints/": "local/board/sprints/",
    "log/": "knowledge/log/",
    "active-skills.yaml": "skills/active-skills.yaml",
}


def _plans(ctx: _ctx.Context) -> str:
    return ".anthill/knowledge/plans" if ctx.v2 else ".anthill/plans"

# Root entries that legitimately belong at the root and must never be moved.
# Tool caches. Reported as stray documents until listed, which is noise that
# makes the real finding harder to see.
ARTEFACT_DIRS = {
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__", ".tox",
    ".coverage", "htmlcov", "dist", "build", ".next", ".vite", ".turbo",
}

SANCTIONED_ROOT = {
    "CONSTITUTION.md", "CLAUDE.md", "AGENTS.md", "README.md", "LICENSE",
    ".gitignore", ".gitattributes", ".env", ".env.example", ".git", ".claude",
    ".anthill", "planning documents", "anthill",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "package.json", "package-lock.json", "tsconfig.json", "Makefile",
    "conftest.py", "pytest.ini", "tests", "web", "node_modules",
}

# Extensions that suggest an agent-authored document rather than product code.
DOC_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".txt"}


def _destination(ctx: _ctx.Context, name: str,
                 is_dir: bool = False) -> tuple[Path, str] | None:
    """Where `name` should live.

    A directory whose destination is itself a directory is *renamed* into place
    rather than nested inside it -- `PRD/` becomes `.anthill/prd/`, not
    `.anthill/prd/PRD/`, which is the sort of result that makes a tidy command
    feel worse than the mess.
    """
    for pattern, dest, why in DESTINATIONS:
        if name.lower() != pattern.lower():
            continue
        if ctx.v2:
            dest = V2_HOME.get(dest, dest)
        if not dest.endswith("/"):
            return ctx.state / dest, why           # a named single file
        target = ctx.state / dest.rstrip("/")
        return (target if is_dir else target / name), why
    return None


def scan(ctx: _ctx.Context) -> dict:
    """Root entries that look like agent output sitting outside the state dir."""
    source_dirs, source_top, _ = ctx.source_roots()
    keep = SANCTIONED_ROOT | ARTEFACT_DIRS | set(source_dirs) | set(source_top)

    known, unknown = [], []
    for child in sorted(ctx.root.iterdir()):
        name = child.name
        if name in keep or name.startswith(".git"):
            continue
        if name in {".anthill", ".claude"}:
            continue
        placed = _destination(ctx, name, child.is_dir())
        if placed:
            dest, why = placed
            known.append({"name": name, "is_dir": child.is_dir(),
                          "destination": str(dest.relative_to(ctx.root)),
                          "why": why})
        elif child.is_file() and child.suffix.lower() in DOC_SUFFIXES:
            unknown.append({"name": name,
                            "suggestion": f"{_plans(ctx)}/{name}",
                            "why": "an agent-authored document with no declared home"})
        elif child.is_dir() and not any(child.rglob("*.py")):
            unknown.append({"name": name,
                            "suggestion": f"{_plans(ctx)}/{name}",
                            "why": "a directory of documents, not source"})

    return {
        "root": str(ctx.root),
        "misplaced": known,
        "unrecognised": unknown,
        "clean": not known and not unknown,
        "note": ("`owns` binds a builder inside a unit worktree. A planner works "
                 "in the main tree with no unit, so nothing stops it writing to "
                 "the root — which is why the locations are stated in the role "
                 "files and checked here."),
    }


def move(ctx: _ctx.Context, include_unrecognised: bool = False,
         write: bool = True) -> dict:
    """Relocate what has a declared destination. Never deletes."""
    found = scan(ctx)
    moved, failed = [], []
    items = list(found["misplaced"])
    if include_unrecognised:
        items += [{"name": u["name"], "destination": u["suggestion"],
                   "why": u["why"], "is_dir": (ctx.root / u["name"]).is_dir()}
                  for u in found["unrecognised"]]

    for item in items:
        src = ctx.root / item["name"]
        # `destination` is already root-relative as scan reported it; trusting it
        # keeps what is moved identical to what was shown.
        dest = ctx.root / item["destination"]
        if not str(dest.resolve()).startswith(str(ctx.state.resolve())):
            failed.append({"name": item["name"],
                           "reason": f"refusing to move outside {ctx.state}"})
            continue
        if not src.exists():
            continue
        if dest.exists():
            failed.append({"name": item["name"], "reason": f"{dest} already exists"})
            continue
        if write:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        moved.append({"from": item["name"],
                      "to": str(dest.relative_to(ctx.root)), "why": item["why"]})
    return {"moved": moved, "failed": failed, "written": write,
            "count": len(moved),
            "reminder": ("references to the old paths are not rewritten — grep for "
                         "them if anything cited these files")
            if moved else ""}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Find agent artefacts written outside the state directory.")
    ap.add_argument("--project", default="")
    ap.add_argument("--move", action="store_true", help="Relocate what has a home")
    ap.add_argument("--all", action="store_true",
                    help="With --move, also relocate unrecognised documents")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2

    if args.move:
        print(json.dumps(move(ctx, args.all, write=not args.dry_run), indent=2))
        return 0
    out = scan(ctx)
    print(json.dumps(out, indent=2))
    return 0 if out["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
