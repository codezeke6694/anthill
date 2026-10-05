"""The anthill, drawn in Obsidian.

The owner opened Anthill's notes as an Obsidian vault and found loose dots:
the work pages, decisions and traps were there, but the map of the code --
the blueprint every agent navigates by -- lives in a data file Obsidian
cannot read, and nothing linked a piece of work to the code it is about.

This writes the map as linked notes into `<knowledge>/_map/`, inside the
vault the owner already has open:

  * one note per chamber, linked to the chambers it uses and the ones that use
    it -- Obsidian's graph then draws the anthill itself;
  * on each chamber, links to the work pages, rule pages and goals about it,
    which are the notes already in the vault;
  * a note per goal, and one note to start from.

It is a picture, regenerated after every map build: edit the work pages, not
these. `_map` is skipped by every check that reads the knowledge folder.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from anthill import context as _ctx

DIR = "_map"


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|#^\[\]]+', "-", name).strip() or "unnamed"


def _load_map(ctx: _ctx.Context) -> dict[str, Any]:
    p = ctx.gen_maps_dir / "codebase.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"nodes": []}


def _work_pages(ctx: _ctx.Context) -> list[dict[str, Any]]:
    from anthill.knowledge import work
    try:
        return work.load_work(ctx)
    except Exception:                       # noqa: BLE001 -- a picture must not fail a build
        return []


def _module_pages(ctx: _ctx.Context) -> list[tuple[Path, str]]:
    base = ctx.knowledge_dir / "modules"
    return [(p, p.read_text(encoding="utf-8", errors="replace")) for p in sorted(base.rglob("*.md"))] if base.exists() else []


def vault(ctx: _ctx.Context) -> Path:
    """The folder opened in Obsidian. On the new layout sprints sit beside the
    knowledge, not inside it, so the vault is the whole of `.anthill/`."""
    return ctx.state if ctx.v2 else ctx.knowledge_dir


def _link(ctx: _ctx.Context, p: Path, label: str = "") -> str:
    rel = p.relative_to(vault(ctx)).with_suffix("").as_posix()
    return f"[[{rel}|{label}]]" if label else f"[[{rel}]]"


def build(ctx: _ctx.Context) -> dict[str, Any]:
    from anthill.knowledge import work as work_mod
    m = _load_map(ctx)
    nodes = m.get("nodes") or []
    if not nodes:
        return {"written": 0, "why": "no map yet -- run anthill map build"}
    district_of = {n["node_id"]: n.get("district") or n["node_id"] for n in nodes}
    files = defaultdict(list)
    uses, used_by, tests = defaultdict(set), defaultdict(set), defaultdict(set)
    for n in nodes:
        d = district_of[n["node_id"]]
        files[d].append(n)
        for r in n.get("routes") or []:
            t = district_of.get(r.get("go_to", ""))
            if t and t != d:
                uses[d].add(t)
                used_by[t].add(d)
        for t in n.get("tests") or []:
            tests[d].add(str(t))

    def about(d: str) -> str:
        own = next((n for n in files[d] if n["node_id"] == d), None) or files[d][0]
        return (own.get("responsibility") or own.get("about") or "").strip()

    def files_of(d: str) -> set[str]:
        return {n.get("file", "") for n in files[d]}

    # which work pages, rule pages and goals are about each chamber
    work_for = defaultdict(list)
    for pg in _work_pages(ctx):
        scope = work_mod.page_scope(pg)
        for d in files:
            if any(f == s or f.startswith(s.rstrip("/") + "/") for f in files_of(d) for s in scope):
                work_for[d].append(pg)
    rules_for = defaultdict(list)
    for p, text in _module_pages(ctx):
        cited = set(re.findall(r"\((?:sg|cite|code):\s*([^):]+?)(?:::[^)]*)?\)", text))
        for d in files:
            if cited & files_of(d):
                rules_for[d].append(p)
    goals = []
    try:
        from anthill import goal as goal_mod
        # On the new layout a goal is a sprint, and its page already shows its
        # steps; drawing a second note for it would put every sprint in twice.
        goals = [] if ctx.v2 else goal_mod.all_goals(ctx)
    except Exception:                       # noqa: BLE001
        pass
    mp = (ctx.knowledge_dir / DIR).relative_to(vault(ctx)).as_posix()

    out = ctx.knowledge_dir / DIR
    tmp = ctx.knowledge_dir / (DIR + ".new")
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "chambers").mkdir(parents=True)
    (tmp / "goals").mkdir()

    def chamber_link(d: str) -> str:
        return f"[[{mp}/chambers/{_safe(d)}|{d}]]"

    written = 0
    for d in sorted(files):
        L = [f"# {d}", "", f"> {about(d)}" if about(d) else "", ""]
        if uses[d]:
            L += ["**Uses:** " + " · ".join(chamber_link(x) for x in sorted(uses[d])), ""]
        if used_by[d]:
            L += ["**Used by:** " + " · ".join(chamber_link(x) for x in sorted(used_by[d])), ""]
        if work_for[d]:
            L += ["## Work on it", *[f"- {_link(ctx, pg['path'], pg['frontmatter'].get('title') or pg['path'].stem)} "
                                     f"— {pg['frontmatter'].get('state', '')}" for pg in work_for[d]], ""]
        if rules_for[d]:
            L += ["## Rules written about it", *[f"- {_link(ctx, p)}" for p in rules_for[d]], ""]
        L += ["## Files", *[f"- `{n.get('file')}` — {(n.get('responsibility') or '').strip()}" for n in
                            sorted(files[d], key=lambda n: n.get("file", ""))], ""]
        if tests[d]:
            L += ["## Proved by", *[f"- `{t}`" for t in sorted(tests[d])[:12]], ""]
        L += ["#chamber"]
        (tmp / "chambers" / f"{_safe(d)}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        written += 1

    pages_by_branch = defaultdict(list)
    for pg in _work_pages(ctx):
        pages_by_branch[str(pg["frontmatter"].get("branch") or "")].append(pg)
    for g in goals:
        L = [f"# Goal: {g.get('title', '')}", "", f"**{g.get('status', '')}** · done when `{g.get('done_when', '')}`", ""]
        for pg in pages_by_branch.get(g.get("branch", ""), []):
            L.append(f"Part of: {_link(ctx, pg['path'], pg['frontmatter'].get('title') or pg['path'].stem)}")
        L += ["", "## Steps", *[f"- [{'x' if s.get('done') else ' '}] {s.get('text', '')}" for s in g.get("steps", [])], ""]
        if g.get("decided"):
            L += ["## Decided for the owner", *[f"- {d.get('what')} — *because* {d.get('because')}"
                                                 + (" — **overturned**" if d.get("overturned") else "") for d in g["decided"]], ""]
        open_q = [b for b in g.get("blockers", []) if not b.get("answer")]
        if open_q:
            L += ["## Waiting on the owner", *[f"- {b['question']}" for b in open_q], ""]
        L += ["#goal"]
        (tmp / "goals" / f"{_safe(g.get('id', 'goal'))}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        written += 1

    kd = ctx.knowledge_dir
    decisions = sorted((kd / "decisions").glob("*.md")) if (kd / "decisions").exists() else []
    home = [f"# {((ctx.config.get('project') or {}).get('name')) or ctx.root.name} — the anthill", "",
            "Drawn from Anthill's map after every commit. Open the graph (Cmd+G) to see the chambers and "
            "what connects them. These notes are redrawn; edit the work pages, not these.", "",
            "## Chambers", *[f"- {chamber_link(d)} — {about(d)[:90]}" for d in sorted(files)], "",
            "## Sprints" if ctx.v2 else "## Work",
            *[f"- {_link(ctx, pg['path'], pg['frontmatter'].get('title') or pg['path'].stem)}"
              + (f" — {pg['frontmatter'].get('kind', 'short')}, {pg['frontmatter'].get('state', '')}" if ctx.v2 else "")
              for pg in _work_pages(ctx)], "",
            *(["## Goals", *[f"- [[{mp}/goals/{_safe(g.get('id', ''))}|{g.get('title', '')}]] — {g.get('status')}"
                             for g in goals], ""] if goals else []),
            "## Your decisions", *[f"- {_link(ctx, p)}" for p in decisions], ""]
    if (kd / "TRAPS.md").exists():
        home += ["## Traps", f"- {_link(ctx, kd / 'TRAPS.md')}", ""]
    (tmp / "Start here.md").write_text("\n".join(home) + "\n", encoding="utf-8")
    written += 1

    if out.exists():
        shutil.rmtree(out)
    tmp.replace(out)
    _graph_colours(vault(ctx))
    return {"written": written, "chambers": len(files), "goals": len(goals), "where": str(out)}


def _graph_colours(vault: Path) -> None:
    """Colour the graph by kind, once, only if the vault has not been given colours already."""
    cfg = vault / ".obsidian" / "graph.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    except (OSError, ValueError):
        return
    if data.get("colorGroups"):
        return
    rgb = lambda h: int(h.lstrip("#"), 16)  # noqa: E731
    data["colorGroups"] = [
        {"query": "path:_map/chambers", "color": {"a": 1, "rgb": rgb("#7fc8a9")}},
        {"query": "path:work OR path:sprints", "color": {"a": 1, "rgb": rgb("#e0a15a")}},
        {"query": "path:_map/goals", "color": {"a": 1, "rgb": rgb("#8fb8ff")}},
        {"query": "path:decisions", "color": {"a": 1, "rgb": rgb("#e07a5f")}},
    ]
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2
    out = build(ctx)
    if not out.get("written"):
        print(f"anthill obsidian: {out.get('why')}", file=sys.stderr)
        return 1
    print(f"anthill obsidian: {out['chambers']} chambers and {out['goals']} goals drawn into {out['where']}\n"
          f"Open {vault(ctx)} as a vault in Obsidian; start from {(ctx.knowledge_dir / DIR).relative_to(vault(ctx)).as_posix()}/Start here.")
    return 0
