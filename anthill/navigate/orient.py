"""`anthill orient`: what an agent is walking into, on one page.

An agent arriving cold had to assemble the picture itself: read the charter,
list the directories, open a few `__init__.py` files, guess the test command,
find the skills, and learn the git rules by being refused. Every piece existed;
nothing put them in one place, so every session paid for the assembly and most
paid for it badly.

This is that page, generated rather than written, so it cannot drift from the
code. It answers, in order: what is this product; what are its chambers and
what does each do; how do they connect; where is the knowledge; how do I prove
a change; which rules bind me; and how do I find where a task lives.

No model calls. Everything here is read from files the repository already has.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from anthill import context as _ctx


def _charter(ctx: _ctx.Context) -> dict[str, str]:
    from anthill import onboard
    sections = onboard.read_sections(ctx.constitution)
    text = ctx.constitution.read_text(encoding="utf-8") if ctx.constitution.exists() else ""
    # `[ \t]*`, not `\s*`: with re.M, `\s` crosses the newline, so a blank
    # Description read the next line -- measured, a fresh install printed its
    # stack twice.
    field = lambda k: (m.group(1).strip() if (m := re.search(rf"^\*\*{k}:\*\*[ \t]*(\S.*)$", text, re.M)) else "")
    # The charter's name first: the config's is whatever `install` was given,
    # and an install run without `--name` records the folder's name instead.
    name = field("Name") or ((ctx.config.get("project") or {}).get("name")) or ctx.root.name
    desc = field("Description")
    building = re.split(r"(?<=[.!?])\s", re.sub(r"\s+", " ", sections.get("building", "")).strip())
    return {"name": name, "description": desc,
            "building": " ".join(building[:2]).strip(),
            "stack": sections.get("stack", "").split(". ")[0].strip()}


def _package_doc(root: Path, district: str) -> str:
    """The one-line job a package states for itself in its `__init__.py`."""
    import ast
    init = root / district.replace(".", "/") / "__init__.py"
    if not init.exists():
        return ""
    try:
        doc = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8"))) or ""
    except (SyntaxError, UnicodeDecodeError):
        return ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _chamber_of(node: dict[str, Any]) -> str:
    """The district a node belongs to, at the grain a newcomer thinks in.

    Python keeps its package (`logiastro.sensing`). A frontend is flatter and
    deeper at once, so `web.components.risk.rank` groups under
    `web.components.risk` and `web.pages.Risk` under `web.pages`.
    """
    d = node.get("district") or node["node_id"]
    return d


def chambers(ctx: _ctx.Context, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        by[_chamber_of(n)].append(n)
    node_to_chamber = {n["node_id"]: _chamber_of(n) for n in nodes}
    out = []
    for ch, members in by.items():
        uses: Counter = Counter()
        used_by: Counter = Counter()
        tests: set[str] = set()
        for n in members:
            for r in n.get("routes") or []:
                t = node_to_chamber.get(r.get("go_to"))
                if t and t != ch:
                    uses[t] += 1
            for c in n.get("consumers") or []:
                t = node_to_chamber.get(c)
                if t and t != ch:
                    used_by[t] += 1
            tests.update(n.get("tests") or [])
        # The members most of the codebase leans on are the ones to read first.
        central = sorted(members, key=lambda n: (-len(n.get("consumers") or []), n["node_id"]))
        job = _package_doc(ctx.root, ch)
        if not job and len(members) == 1:
            job = members[0].get("responsibility", "")
        last = max((e.get("h", "") for n in members for e in (n.get("history") or [])[:1]), default="")
        out.append({
            "chamber": ch,
            "job": job,
            "files": len(members),
            "read_first": [{"node": n["node_id"], "file": n.get("file", ""),
                            "does": n.get("responsibility", "")} for n in central[:3]],
            "uses": [c for c, _ in uses.most_common(5)],
            "used_by": [c for c, _ in used_by.most_common(5)],
            "test_dirs": sorted({str(Path(t).parent) for t in tests})[:4],
            "recent": sum(len(n.get("history") or []) for n in members),
            "_last": last,
        })
    out.sort(key=lambda c: c["chamber"])
    return out


def _recent_work(ctx: _ctx.Context, nodes: list[dict[str, Any]], n: int = 8) -> list[dict[str, str]]:
    """The last few things people changed, and where. The fastest way to learn
    what a codebase is busy with is to see what it was busy with last week."""
    import subprocess
    file_to_chamber = {x.get("file"): _chamber_of(x) for x in nodes if x.get("file")}
    try:
        out = subprocess.run(["git", "log", "--no-merges", "-n", "40", "--format=@@%h|%ad|%s",
                              "--date=short", "--name-only"],
                             cwd=ctx.root, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[dict[str, Any]] = []
    for line in out.splitlines():
        if line.startswith("@@"):
            h, d, s = line[2:].split("|", 2)
            rows.append({"commit": h, "date": d, "subject": s, "where": Counter()})
        elif line.strip() and rows and line.strip() in file_to_chamber:
            rows[-1]["where"][file_to_chamber[line.strip()]] += 1
    rows = [r for r in rows if r["where"]][:n]
    return [{"date": r["date"], "subject": r["subject"],
             "where": ", ".join(c for c, _ in r["where"].most_common(2))} for r in rows]


def _knowledge(ctx: _ctx.Context) -> list[dict[str, Any]]:
    from anthill.knowledge import pages
    kd = ctx.knowledge_dir
    if not kd.exists():
        return []
    out = []
    for p in pages.load_pages(kd):
        fm = p["frontmatter"]
        out.append({"page": str(Path(p["abs_path"]).relative_to(ctx.root)),
                    "title": fm.get("title", ""), "covers": pages.footprint_of(p),
                    "rules": len(p["rules"]), "confirmed_by_owner": p["attested"]})
    return out


def _glossary(ctx: _ctx.Context) -> dict[str, Any]:
    """The owner's words for things, if anyone has written them down."""
    path = ctx.knowledge_dir / "GLOSSARY.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    lines = [ln.strip()[2:] for ln in text.splitlines()
             if ln.strip().startswith(("- **", "* **")) and ("→" in ln or "->" in ln)]
    attested = bool(re.search(r"^intent_attested_by:\s*\S", text, re.M))
    return {"page": str(path.relative_to(ctx.root)), "entries": lines,
            "confirmed_by_owner": attested}


def _proofs(ctx: _ctx.Context) -> list[dict[str, str]]:
    """How to prove a change, as commands that run here."""
    out: list[dict[str, str]] = []
    root = ctx.root
    venv = ((ctx.config.get("execution") or {}).get("venv")) or ""
    py = f"{venv.rstrip('/')}/bin/python" if venv else (
        ".venv/bin/python" if (root / ".venv/bin/python").exists() else "python3")
    pyproject = root / "pyproject.toml"
    if pyproject.exists() and "pytest" in pyproject.read_text(encoding="utf-8", errors="ignore"):
        tdir = "tests" if (root / "tests").is_dir() else ""
        out.append({"what": "Python tests", "run": f"{py} -m pytest {tdir} -q".replace("  ", " ")})
    from anthill.navigate import scripts
    for d in scripts.discover(root, (ctx.config.get("source") or {}).get("script_dirs")):
        pkg_dir = root / d
        while pkg_dir != root and not (pkg_dir / "package.json").exists():
            pkg_dir = pkg_dir.parent
        pkg = pkg_dir / "package.json"
        if not pkg.exists():
            continue
        try:
            scripts_ = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
        except (OSError, json.JSONDecodeError):
            continue
        rel = str(pkg_dir.relative_to(root))
        for key in ("test", "typecheck", "lint", "build"):
            if key in scripts_:
                run = f"npm --prefix {rel} test" if key == "test" else f"npm --prefix {rel} run {key}"
                out.append({"what": f"frontend {key}", "run": run})
    runner = root / "run.sh"
    if runner.exists():
        out.append({"what": "start the app", "run": "./run.sh"})
    return out


def _rules(ctx: _ctx.Context) -> dict[str, Any]:
    from anthill import skills
    try:
        always = [s["name"] for s in skills.listing(ctx, always_on=True)["skills"]]
    except Exception:           # skills are optional; orientation is not
        always = []
    ex = ctx.config.get("execution") or {}
    return {
        "load_every_session": always,
        "protected_branches": ex.get("protected_branches") or [],
        "push_needs_owner": bool(ex.get("push_requires_owner", True)),
        "hygiene_guard": bool(ex.get("guard_hygiene", False)),
        "never_edit": ctx.config.get("protected_paths") or [],
    }


def orient(ctx: _ctx.Context, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "project": _charter(ctx),
        "chambers": chambers(ctx, nodes),
        "recent_work": _recent_work(ctx, nodes),
        "knowledge": _knowledge(ctx),
        "glossary": _glossary(ctx),
        "prove_a_change": _proofs(ctx),
        "rules": _rules(ctx),
        "find_your_task": 'anthill start "<the task, in your own words>"',
    }


def render(o: dict[str, Any]) -> str:
    p = o["project"]
    L: list[str] = [f"# You are in {p['name']}", ""]
    if p["description"]:
        L.append(p["description"])
    if p["building"]:
        L += ["", p["building"]]
    if p["stack"]:
        L += ["", f"**Stack:** {p['stack']}"]

    L += ["", "## The chambers", "",
          "Each chamber is one area of the code with one job. `uses` is what it",
          "depends on; `used by` is who breaks if you change it.", ""]
    for c in o["chambers"]:
        job = f" — {c['job']}" if c["job"] else ""
        L.append(f"**{c['chamber']}**{job}  ({c['files']} file{'s' if c['files'] != 1 else ''})")
        for r in c["read_first"][:2 if c["files"] > 1 else 1]:
            if c["files"] > 1 or not c["job"]:
                L.append(f"  - `{r['file']}` — {r['does']}")
        if c["uses"]:
            L.append(f"  - uses: {', '.join(c['uses'])}")
        if c["used_by"]:
            L.append(f"  - used by: {', '.join(c['used_by'])}")
        if c["test_dirs"]:
            L.append(f"  - tests: {', '.join(c['test_dirs'])}")
    if o["recent_work"]:
        L += ["", "## What people changed recently", ""]
        for r in o["recent_work"]:
            L.append(f"- {r['date']} — {r['subject']}  _({r['where']})_")
    L += ["", "## Where the knowledge is", ""]
    if o["knowledge"]:
        for k in o["knowledge"]:
            mark = "" if k["confirmed_by_owner"] else " — written by an agent, not yet confirmed by the owner"
            L.append(f"- `{k['page']}` — {k['title']} ({k['rules']} rules){mark}")
    else:
        L.append("- No knowledge pages yet. The docstrings are the knowledge.")
    g = o.get("glossary") or {}
    if g.get("entries"):
        mark = "" if g["confirmed_by_owner"] else " (drafted by an agent, not yet confirmed by the owner)"
        L += ["", "## Words the owner uses", "",
              f"From `{g['page']}`{mark}. The owner's words, then the code's:", ""]
        L += [f"- {e}" for e in g["entries"][:12]]
        if len(g["entries"]) > 12:
            L.append(f"- … {len(g['entries']) - 12} more in the page")
    L += ["", "## How to prove a change", ""]
    for pr in o["prove_a_change"]:
        L.append(f"- {pr['what']}: `{pr['run']}`")
    r = o["rules"]
    L += ["", "## Rules you live by", ""]
    if r["load_every_session"]:
        L.append(f"- Load every session: {', '.join(r['load_every_session'])} "
                 "(`anthill skill get <name>`)")
    if r["protected_branches"]:
        L.append(f"- Never commit on {', '.join(r['protected_branches'])}; work on a branch.")
    L.append("- Never push unless the owner asked for this push."
             + (" The hook enforces it." if r["push_needs_owner"] else ""))
    if r["hygiene_guard"]:
        L.append("- Commits with secrets or junk files, and force pushes, are refused.")
    if r["never_edit"]:
        L.append(f"- Never edit: {', '.join(f'`{x}`' for x in r['never_edit'])}")
    L += ["", "## Find where your task lives", "",
          f"    {o['find_your_task']}", "",
          "It names the chamber and the file, why it matched, what that file",
          "connects to, and which tests prove a change there. Read the live code",
          "before editing: the map says where, never what."]
    return "\n".join(L) + "\n"
