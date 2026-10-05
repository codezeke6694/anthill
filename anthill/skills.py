#!/usr/bin/env python3
"""Skills: reusable instruction the roles can load on demand.

Dropped by accident, not by design. The mother product exposed skills through
its MCP server (`list_skills`, `get_skill`), and skipping MCP took the whole
library with it -- so 34 skills, 14 of them the orchestration doctrine this
system is built on, existed nowhere in the tool.

THE POINT IS `load_class`, NOT STORAGE
--------------------------------------
A skill library is easy; knowing when *not* to load something is the hard part,
and the library already answers it. Every skill declares one of four classes:

    bootstrap      always loaded
    phase-scoped   loaded only during its phase (idea / planning / execution)
    conditional    loaded only when triggered (an audit, an escalation)
    reference      installed, never auto-loaded -- looked up when needed

That is the same rule the role files state as "load only what your role
specifies", expressed per-skill instead of per-role. A tool that returns every
skill on every request would defeat it, so `list` filters by class and `get`
returns exactly one.

Skills live in `.anthill/skills/<category>/<name>/{skill.yaml,content.md}`, which
is the layout the existing library already uses -- so an import is a copy, and a
library maintained elsewhere stays usable as-is.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

LOAD_CLASSES = ("bootstrap", "phase-scoped", "conditional", "reference")
MANIFEST = "skill.yaml"
CONTENT = "content.md"


def skills_dir(ctx: _ctx.Context) -> Path:
    return ctx.state / "skills"


def _parse_manifest(text: str) -> dict:
    """A deliberate YAML subset: scalars, quoted scalars, and `- ` lists.

    Same reasoning as the knowledge-page frontmatter reader -- the manifests use
    only this much, and a parser we own cannot drift from a parser we don't.
    """
    out: dict = {}
    key = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(("  - ", "- ")):
            if key:
                out.setdefault(key, [])
                if isinstance(out[key], list):
                    out[key].append(raw.split("- ", 1)[1].strip().strip("'\""))
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", raw)
        if not m:
            # a wrapped description line continues the previous scalar
            if key and isinstance(out.get(key), str):
                out[key] = (out[key] + " " + raw.strip()).strip()
            continue
        key, value = m.group(1), m.group(2).strip()
        if value:
            v = value.strip("'\"")
            out[key] = {"true": True, "false": False}.get(v.lower(), v)
        else:
            out[key] = ""
    return out


def load_all(ctx: _ctx.Context) -> list[dict]:
    root = skills_dir(ctx)
    if not root.exists():
        return []
    found: list[dict] = []
    for manifest in sorted(root.rglob(MANIFEST)):
        # A retired or template skill is not installed. Only the index skipped
        # them, so `skill list --always-on` still told every chat to load 13
        # archived skills and the blank template.
        if manifest.relative_to(root).parts[0] in TEMPLATE_DIRS:
            continue
        try:
            meta = _parse_manifest(manifest.read_text(encoding="utf-8"))
        except OSError:
            continue
        d = manifest.parent
        meta["_path"] = str(d.relative_to(root))
        meta["_content"] = str(d / CONTENT)
        meta["_has_content"] = (d / CONTENT).exists()
        meta.setdefault("name", d.name)
        meta.setdefault("category", d.parent.name)
        meta.setdefault("load_class", "reference")
        found.append(meta)
    return found


def listing(ctx: _ctx.Context, category: str = "", load_class: str = "",
            always_on: bool = False, query: str = "") -> dict:
    rows = load_all(ctx)
    if category:
        rows = [r for r in rows if r.get("category") == category]
    if load_class:
        rows = [r for r in rows if r.get("load_class") == load_class]
    if always_on:
        rows = [r for r in rows if r.get("always_on") is True]
    if query:
        q = query.lower()
        rows = [r for r in rows
                if q in str(r.get("name", "")).lower()
                or q in str(r.get("description", "")).lower()
                or any(q in str(t).lower() for t in (r.get("tags") or []))]
    by_class: dict[str, int] = {}
    for r in load_all(ctx):
        by_class[str(r.get("load_class"))] = by_class.get(str(r.get("load_class")), 0) + 1
    return {
        "skills_dir": str(skills_dir(ctx)),
        "count": len(rows),
        "total_installed": len(load_all(ctx)),
        "by_load_class": by_class,
        "skills": [{"name": r.get("name"), "category": r.get("category"),
                    "load_class": r.get("load_class"),
                    "always_on": bool(r.get("always_on")),
                    "description": r.get("description", "")} for r in rows],
        "note": ("`bootstrap` and `always_on` skills are meant to be loaded every "
                 "session; `reference` skills are installed and looked up, never "
                 "auto-loaded."),
    }


def get(ctx: _ctx.Context, name: str, meta_only: bool = False) -> dict:
    matches = [r for r in load_all(ctx) if r.get("name") == name]
    if not matches:
        near = [r["name"] for r in load_all(ctx)
                if name.lower() in str(r.get("name", "")).lower()]
        raise SystemExit(f"anthill: no skill named {name!r}"
                         + (f". Did you mean: {', '.join(near[:5])}?" if near else ""))
    r = matches[0]
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    out["path"] = r["_path"]
    if not meta_only:
        p = Path(r["_content"])
        out["content"] = p.read_text(encoding="utf-8") if p.exists() else ""
        if not out["content"]:
            out["warning"] = f"{CONTENT} is missing or empty for this skill"
    return out


def install_library(ctx: _ctx.Context, source: Path, categories: list[str] | None = None,
                    force: bool = False) -> dict:
    """Copy a skills library in. Skips what is already there unless forced."""
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"anthill: no skills library at {source}")
    dest_root = skills_dir(ctx)
    dest_root.mkdir(parents=True, exist_ok=True)

    copied, skipped = [], []
    for manifest in sorted(source.rglob(MANIFEST)):
        d = manifest.parent
        rel = d.relative_to(source)
        if categories and (rel.parts[0] if rel.parts else "") not in categories:
            continue
        dest = dest_root / rel
        if dest.exists() and not force:
            skipped.append(str(rel))
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(d, dest)
        copied.append(str(rel))
    return {"source": str(source), "installed_into": str(dest_root),
            "copied": copied, "skipped_existing": skipped,
            "count": len(copied),
            "note": ("skipped entries already existed; pass --force to replace"
                     if skipped else "")}



# ---------------------------------------------------------------- indexing

# Directories that hold no loadable skill. `_template` is the authoring
# template; indexing it advertises `your-skill-name` as something an agent
# could load. `_archive` is where a retired instruction set goes instead of
# being deleted -- `.anthill/` has no other copy -- and an archived skill that
# still appears in INDEX.md is a retired rule an agent will follow anyway.
TEMPLATE_DIRS = {"_template", "_archive"}

# Peregrine kept its state in `.agent/`; this system keeps it in `.anthill/`,
# with a different shape. A skill that cites a path which does not exist sends an
# agent to a missing file and it has no way to tell that the instruction is
# stale rather than the repository broken -- so the citations are rewritten
# deliberately, and every rewrite is reported.
PATH_MAP = [
    (".agent/planner-brief.md", ".anthill/sprints/current.json"),
    (".agent/backlog.yaml", ".anthill/sprints/current.json"),
    (".agent/contracts/", ".anthill/contracts/"),
    (".agent/archive/", ".anthill/sprints/archive/"),
    (".agent/agent-log.md", ".anthill/log/"),
    (".agent/issues/index.md", ".anthill/log/lessons/"),
    (".agent/issues/", ".anthill/log/lessons/"),
    (".agent/logs/", ".anthill/log/"),
    (".agent/skills/", ".anthill/skills/"),
    (".agent/runtime/", ".anthill/"),
    (".agent/", ".anthill/"),          # last: catches anything unmapped above
]


def stale_paths(ctx: _ctx.Context) -> list[dict]:
    """Skills citing a path this install does not have."""
    out = []
    for r in load_all(ctx):
        p = Path(r["_content"])
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        hits = sorted({old for old, _ in PATH_MAP if old in text})
        if hits:
            out.append({"skill": r.get("name"), "category": r.get("category"),
                        "cites": hits})
    return out


def retarget(ctx: _ctx.Context, write: bool = True) -> dict:
    """Rewrite Peregrine-era path citations to this system's layout."""
    changed = []
    for r in load_all(ctx):
        p = Path(r["_content"])
        if not p.exists():
            continue
        try:
            text = original = p.read_text(encoding="utf-8")
        except OSError:
            continue
        replaced = {}
        for old, new in PATH_MAP:
            if old in text:
                replaced[old] = new
                text = text.replace(old, new)
        if text != original:
            if write:
                p.write_text(text, encoding="utf-8")
            changed.append({"skill": r.get("name"), "category": r.get("category"),
                            "replacements": replaced})
    return {"changed": changed, "count": len(changed), "written": write,
            "note": ("path citations only -- the instructions themselves are "
                     "unchanged, so a skill whose *procedure* assumed Peregrine "
                     "may still need editing by hand")}


def build_index(ctx: _ctx.Context, write: bool = True) -> dict:
    """Regenerate the skill index: one machine file, one readable page.

    Derived, never maintained by hand -- the same rule as the knowledge
    catalogue and the blueprint. A hand-edited index is an index that lies.
    """
    rows = [r for r in load_all(ctx)
            if r.get("category") not in TEMPLATE_DIRS
            and str(r.get("_path", "")).split("/")[0] not in TEMPLATE_DIRS]
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(str(r.get("category")), []).append(r)

    registry = {
        "meta": {"total_skills": len(rows),
                 "categories": sorted(by_cat),
                 "load_classes": {c: sum(1 for r in rows if r.get("load_class") == c)
                                  for c in LOAD_CLASSES},
                 "generated_by": "anthill skill index"},
        "skills": {cat: [{"name": r.get("name"), "path": r.get("_path"),
                          "version": str(r.get("version", "")),
                          "description": r.get("description", ""),
                          "tags": r.get("tags") or [],
                          "load_class": r.get("load_class"),
                          "always_on": bool(r.get("always_on"))}
                         for r in sorted(items, key=lambda x: str(x.get("name")))]
                   for cat, items in sorted(by_cat.items())},
    }

    lines = ["# Skill Index", "",
             f"{len(rows)} skills across {len(by_cat)} categories. "
             "Generated by `anthill skill index` — do not hand-edit.", "",
             "## When to load what", "",
             "| Load class | Meaning |", "|---|---|",
             "| `bootstrap` | load every session |",
             "| `phase-scoped` | load only during its phase (idea / planning / execution) |",
             "| `conditional` | load only when triggered (an audit, an escalation) |",
             "| `reference` | installed, never auto-loaded — look it up when needed |",
             "", "Read a skill with `anthill skill get <name>`.", ""]
    always = [r for r in rows if r.get("always_on") or r.get("load_class") == "bootstrap"]
    if always:
        lines += ["## Load every session", ""]
        lines += [f"- **{r.get('name')}** — {r.get('description','')}"
                  for r in sorted(always, key=lambda x: str(x.get("name")))]
        lines += [""]
    for cat, items in sorted(by_cat.items()):
        lines += [f"## {cat}", "", "| Skill | Load class | Description |", "|---|---|---|"]
        for r in sorted(items, key=lambda x: str(x.get("name"))):
            desc = str(r.get("description", "")).replace("|", "\\|")
            lines.append(f"| `{r.get('name')}` | {r.get('load_class')} | {desc} |")
        lines += [""]

    stale = stale_paths(ctx)
    if stale:
        lines += ["## Stale path citations", "",
                  "These skills cite paths this install does not use. Run "
                  "`anthill skill retarget` to rewrite them.", ""]
        lines += [f"- `{s['skill']}` → {', '.join(s['cites'])}" for s in stale]
        lines += [""]

    root = skills_dir(ctx)
    if write and rows:
        root.mkdir(parents=True, exist_ok=True)
        (root / "registry.json").write_text(json.dumps(registry, indent=2) + "\n",
                                            encoding="utf-8")
        (root / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    return {"skills_dir": str(root), "indexed": len(rows),
            "categories": sorted(by_cat),
            "load_classes": registry["meta"]["load_classes"],
            "excluded_templates": sorted(TEMPLATE_DIRS),
            "stale_path_citations": len(stale),
            "written": [str(root / "registry.json"), str(root / "INDEX.md")] if write else []}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Skills a role can load on demand.")
    ap.add_argument("--project", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("list", help="Installed skills, filtered")
    l.add_argument("--category", default="")
    l.add_argument("--load-class", default="", choices=("",) + LOAD_CLASSES)
    l.add_argument("--always-on", action="store_true",
                   help="Only skills meant to be loaded every session")
    l.add_argument("--query", default="", help="Match name, description, or tag")
    g = sub.add_parser("get", help="One skill's content")
    g.add_argument("name"); g.add_argument("--meta-only", action="store_true")
    i = sub.add_parser("install", help="Copy a skills library into this project")
    i.add_argument("source", help="Path to a skills-hub style directory")
    i.add_argument("--categories", default="", help="Comma-separated subset")
    i.add_argument("--force", action="store_true")
    x = sub.add_parser("index", help="Regenerate registry.json and INDEX.md")
    x.add_argument("--dry-run", action="store_true")
    rt = sub.add_parser("retarget", help="Rewrite stale path citations to this layout")
    rt.add_argument("--dry-run", action="store_true")
    sub.add_parser("stale", help="Skills citing paths this install does not have")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2

    if args.cmd == "get":
        out = get(ctx, args.name, args.meta_only)
        if not args.meta_only and out.get("content"):
            print(out["content"])
            return 0
    elif args.cmd == "install":
        out = install_library(
            ctx, Path(args.source),
            [c.strip() for c in args.categories.split(",") if c.strip()] or None,
            args.force)
    elif args.cmd == "index":
        out = build_index(ctx, write=not args.dry_run)
    elif args.cmd == "retarget":
        out = retarget(ctx, write=not args.dry_run)
    elif args.cmd == "stale":
        out = {"stale": stale_paths(ctx)}
    else:
        out = listing(ctx, args.category, args.load_class, args.always_on, args.query)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
