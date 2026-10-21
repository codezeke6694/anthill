"""A project's own notes, used instead of Anthill's notebook (owner, 21 Oct 2026).

Mesh IQ already kept a learning log (402 measured lessons, each naming the file
and function it is about), a handover page per live area, and a folder of module
pages. Anthill installed its own notebook beside them, and every chat got two
answers to "where does this go?". So a project that has notes keeps them: Anthill
finds them, points the rules at them, and puts the lessons about the code a chat
is about to touch on the card that chat reads first.

    anthill notes scan              what notes this project already keeps
    anthill notes lessons "<task>"  the lessons about where that task lives
                                    (also on `anthill start`'s card)

The notes in use are the owner's setting `knowledge.project_notes`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from anthill import context as _ctx

CODE = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rb", ".php", ".java", ".kt", ".rs",
        ".sql", ".sh", ".vue", ".svelte", ".cs", ".swift"}
_ENTRY = re.compile(r"^###\s+(.+?)\s*$", re.M)
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TICKED = re.compile(r"`([^`\n]{2,120})`")
_WORD = re.compile(r"[a-z][a-z0-9]{2,}")
_STOP = set("the and for with that this from into when then than what which where why how are was were "
            "not but all any can its it's has have had our your their there here only also more most "
            "does did doing done one two new old use used using via per each".split())
SKIP_DIRS = {"node_modules", ".git", ".anthill", "anthill", "archive", "backups", ".venv", "venv",
             "__pycache__", "dist", "build"}


def _git_files(root: Path) -> list[str]:
    try:
        r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
                           capture_output=True, text=True, timeout=30)
        out = r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        out = []
    return [f for f in out if Path(f).suffix in CODE and not (set(Path(f).parts) & SKIP_DIRS)]


def _skip(p: Path, root: Path) -> bool:
    return bool(set(p.relative_to(root).parts[:-1]) & SKIP_DIRS)


# ------------------------------------------------------------------ finding notes

def _md_files(root: Path):
    import os
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        for n in names:
            if n.endswith(".md"):
                yield Path(d) / n


def _book_of(page: Path, root: Path) -> Path:
    """The folder a module page belongs to: the nearest with KNOWLEDGE-RULES.md, else its modules/ parent."""
    for a in page.parents:
        if a == root:
            break
        if (a / "KNOWLEDGE-RULES.md").exists():
            return a
    for a in page.parents:
        if a.name == "modules" and a.parent != root:
            return a.parent
    return page.parent


def scan(ctx: _ctx.Context) -> dict[str, list[dict[str, Any]]]:
    """Every kind of note this project already keeps, ones git ignores included."""
    root = ctx.root
    lessons_, plans, books, rules = [], {}, set(), []
    for p in _md_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = p.name.lower()
        n = len(_ENTRY.findall(text))
        if re.search(r"learn|lesson", name) and n >= 3:
            lessons_.append({"path": rel, "entries": n})
        elif "handover" in name or p.parent.name in ("plans", "handovers"):
            plans.setdefault(p.parent.relative_to(root).as_posix(), 0)
            plans[p.parent.relative_to(root).as_posix()] += 1
        elif text.startswith("---") and "\ntype: module" in text[:800]:
            books.add(_book_of(p, root).relative_to(root).as_posix())
        elif rel in ("CLAUDE.md", "AGENTS.md") and "run with Anthill" not in text[:600]:
            rules.append({"path": rel})
    found = {"lessons": lessons_,
             "handovers": [{"path": d + "/", "pages": n} for d, n in sorted(plans.items())],
             "pages": [{"path": b + "/"} for b in sorted(books)],
             "rules": rules}
    for kind in found.values():
        for x in kind:
            x["in_git"] = _in_git(root, x["path"])
    return found


def _in_git(root: Path, rel: str) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", rel.rstrip("/")], cwd=root, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return True
    return r.returncode != 0


def kind_of(ctx: _ctx.Context, rel: str) -> str:
    """lessons | handovers | pages, for a path the owner chose to use."""
    p = ctx.root / rel
    if p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
        return "lessons" if len(_ENTRY.findall(text)) >= 3 else "handovers"
    if p.is_dir() and ((p / "KNOWLEDGE-RULES.md").exists() or (p / "modules").is_dir()):
        return "pages"
    return "handovers"


def in_use(ctx: _ctx.Context) -> list[str]:
    return [str(p) for p in (ctx.config.get("knowledge") or {}).get("project_notes") or []]


# ------------------------------------------------------------------ reading them

def _refs(text: str, files: list[str]) -> set[str]:
    """The project files a piece of text names, in backticks: paths or module.function."""
    out: set[str] = set()
    for tok in _TICKED.findall(text):
        tok = tok.strip().rstrip("()")
        cands = []
        if Path(tok.split("::")[0]).suffix in CODE:
            cands.append(tok.split("::")[0])
        elif "." in tok and " " not in tok:
            mod = tok.rsplit(".", 1)[0]
            cands += [mod + ext for ext in (".py", ".ts", ".tsx", ".js")]
            if "." in mod:                                   # a.b.c -> a/b.py
                cands += [mod.replace(".", "/") + ext for ext in (".py", ".ts")]
        for c in cands:
            c = c.lstrip("./")
            out.update(f for f in files if f == c or f.endswith("/" + c))
    return out


def lessons(ctx: _ctx.Context, files: list[str] | None = None) -> list[dict[str, Any]]:
    files = files if files is not None else _git_files(ctx.root)
    out = []
    for src in in_use(ctx):
        p = ctx.root / src
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        heads = list(_ENTRY.finditer(text))
        for i, m in enumerate(heads):
            body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
            title = m.group(1)
            d = _DATE.search(title)
            out.append({"title": _DATE.sub("", title).strip(" —-(").strip(), "date": d.group(1) if d else "",
                        "source": src, "files": sorted(_refs(title + body, files)),
                        "text": body.strip()[:600]})
    return out


def handovers(ctx: _ctx.Context, files: list[str] | None = None) -> list[dict[str, Any]]:
    files = files if files is not None else _git_files(ctx.root)
    out = []
    for src in in_use(ctx):
        p = ctx.root / src
        pages = sorted(p.glob("*.md")) if p.is_dir() and "knowledge" not in p.parts else []
        for page in pages:
            text = page.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^#\s+(.+)$", text, re.M)
            out.append({"title": m.group(1).strip() if m else page.stem, "page": page.relative_to(ctx.root).as_posix(),
                        "files": sorted(_refs(text, files))})
    return out


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if w not in _STOP}


def relevant(ctx: _ctx.Context, files: list[str], task: str = "", k: int = 4) -> dict[str, list[dict[str, Any]]]:
    """Lessons and handover pages about these files (and this task's words)."""
    if not in_use(ctx):
        return {"lessons": [], "handovers": []}
    allf = _git_files(ctx.root)
    want, words = set(files), _words(task)

    def score(x: dict[str, Any]) -> float:
        return 3 * len(want & set(x["files"])) + 0.5 * len(words & _words(x["title"]))

    ls = sorted((x for x in lessons(ctx, allf) if score(x) > 0), key=lambda x: (score(x), x["date"]), reverse=True)
    hs = sorted((x for x in handovers(ctx, allf) if score(x) > 0), key=score, reverse=True)
    return {"lessons": [{"title": x["title"], "date": x["date"], "source": x["source"],
                         "files": x["files"][:4]} for x in ls[:k]],
            "handovers": [{"title": x["title"], "page": x["page"]} for x in hs[:2]]}


# ------------------------------------------------------------------ command

def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    verb = argv[0] if argv else "scan"
    if verb == "scan":
        found = scan(ctx)
        print(json.dumps({"found": found, "in_use": in_use(ctx),
                          "next": ("the owner chooses which to use: anthill config set knowledge.project_notes "
                                   "\"<path>,<path>\" --by <owner>, then anthill install --force to re-render the rules")},
                         indent=2))
        return 0
    if verb == "lessons":
        task = " ".join(a for a in argv[1:] if not a.startswith("--"))
        files = [a for a in argv[1:] if Path(a).suffix in CODE]
        print(json.dumps(relevant(ctx, files, task), indent=2))
        return 0
    print("usage: anthill notes scan | lessons \"<task or file>\"", file=sys.stderr)
    return 2
