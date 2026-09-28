#!/usr/bin/env python3
"""`anthill upkeep`: what a change left undone, so the anthill stays mapped.

The map redraws itself after every commit, but nothing else did. A new screen
arrived with no name in the glossary; a function a knowledge rule cited was
reshaped and the rule went on saying the old thing; new code landed with no
test and nobody said so. Each of those is invisible the day it happens and
expensive the day an agent trusts it.

This is the list, computed from the commit and kept until it is empty:

  glossary   a line names code that no longer exists, or a screen has no line
  knowledge  a page's rule cites a symbol whose shape changed
  tests      product code changed that no test imports

Read-only apart from its own record, `.anthill/build/upkeep.json`. It never
blocks: it runs after the commit, and its job is to be handed to the
`anthill-keeper` helper so the agent doing the work does not stop to do it.
An item clears itself the next time its check passes.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

RECORD = "upkeep.json"
_GLOSS = re.compile(r"^\s*[-*]\s+(?P<terms>.+?)\s+(?:→|->)\s+(?P<code>.+?)\s*$")


def _git(args: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def changed_since(root: Path, since: str) -> set[str]:
    out = _git(["diff", "--name-only", f"{since}..HEAD"], root)
    return {f.strip() for f in out.splitlines() if f.strip()}


def _nodes(ctx: _ctx.Context) -> list[dict[str, Any]]:
    path = ctx.state / "build" / "maps" / "codebase.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("nodes") or []
    except (OSError, json.JSONDecodeError):
        return []


def _source_text(ctx: _ctx.Context, nodes: list[dict[str, Any]]) -> str:
    """Every mapped source file, lower-cased, for 'does this word still exist'."""
    parts = []
    for n in nodes:
        f = n.get("file")
        if not f:
            continue
        try:
            parts.append((ctx.root / f).read_text(encoding="utf-8").lower())
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def glossary_items(ctx: _ctx.Context, nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """A glossary line pointing at nothing, and a screen with no line."""
    path = ctx.knowledge_dir / "GLOSSARY.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    code = _source_text(ctx, nodes)
    items, named = [], set()
    for line in text.splitlines():
        m = _GLOSS.match(line)
        if not m:
            continue
        words = [w.strip() for w in re.split(r"[,;]", m.group("code")) if w.strip()]
        named.update(w.lower() for w in words)
        gone = [w for w in words if w.lower() not in code]
        if gone:
            term = (re.findall(r"\*\*(.+?)\*\*", m.group("terms")) or [m.group("terms")])[0]
            items.append({"kind": "glossary", "subject": f"line:{term}",
                          "detail": f"the line for \"{term}\" names {', '.join(gone)}, "
                                    f"which the code no longer contains"})
    for n in nodes:
        # A screen is a page the app routes to; its name is how the owner
        # refers to it, so it must be findable in the owner's words.
        if ".pages." not in n["node_id"]:
            continue
        name = n["node_id"].rsplit(".", 1)[-1]
        if name.lower() not in named:
            items.append({"kind": "glossary", "subject": f"screen:{n.get('file')}",
                          "detail": f"screen {name} ({n.get('file')}) has no glossary "
                                    f"line saying what the owner calls it"})
    return items


def knowledge_items(ctx: _ctx.Context, files: set[str]) -> list[dict[str, str]]:
    """Rules citing a symbol in these files whose structure has moved."""
    if not files or not ctx.knowledge_dir.exists():
        return []
    from anthill.knowledge import claims
    wanted = [c for c in claims.from_knowledge(ctx.knowledge_dir)
              if not c.get("uncited") and c["symbol_id"].split("::", 1)[0] in files]
    out = []
    for r in claims.verify(wanted):
        if r.get("severity", 0) >= 2:
            out.append({"kind": "knowledge", "subject": f"{r['source']}#{r['claim_id']}@{r['symbol_id']}",
                        "detail": f"{r['source']} rule {r['claim_id']} cites {r['symbol_id']}, "
                                  f"which was {r['drift']}: {r.get('detail', '')}"})
    return out


def test_items(nodes: list[dict[str, Any]], files: set[str]) -> list[dict[str, str]]:
    by_file = {n.get("file"): n for n in nodes if n.get("file")}
    out = []
    for f in sorted(files):
        n = by_file.get(f)
        if n is None or n.get("tests") or f.endswith(("__init__.py", "types.ts")):
            continue
        syms = n.get("symbols") or []
        if syms and all(x.get("type") for x in syms):
            # Only type declarations: nothing runs, so nothing can be tested.
            # Measured: nav.ts (two interfaces) was listed as untested code.
            continue
        out.append({"kind": "tests", "subject": f"file:{f}",
                    "detail": f"{f} changed and no test imports it"})
    return out


def check(ctx: _ctx.Context, files: set[str]) -> list[dict[str, str]]:
    nodes = _nodes(ctx)
    return (glossary_items(ctx, nodes) + knowledge_items(ctx, files)
            + test_items(nodes, files))


def _record_path(ctx: _ctx.Context) -> Path:
    return ctx.state / "build" / RECORD


def load(ctx: _ctx.Context) -> dict[str, Any]:
    try:
        return json.loads(_record_path(ctx).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"open": []}


def run(ctx: _ctx.Context, since: str = "HEAD~1", record: bool = False) -> dict[str, Any]:
    """Items this change left, plus any earlier ones that are still true."""
    prior = load(ctx).get("open") or []
    files = changed_since(ctx.root, since)
    # Re-check what was already open, on the files it was about, so an item
    # clears itself when the fix lands -- whoever makes it.
    for it in prior:
        subj = it.get("subject", "")
        if subj.startswith("file:"):
            files.add(subj[5:])
        elif "@" in subj and "::" in subj:
            files.add(subj.rsplit("@", 1)[1].split("::", 1)[0])
    now = check(ctx, files)
    head = _git(["rev-parse", "--short", "HEAD"], ctx.root).strip()
    first_seen = {it["subject"]: it.get("since", "") for it in prior}
    for it in now:
        it["since"] = first_seen.get(it["subject"]) or head
    cleared = sorted(set(first_seen) - {it["subject"] for it in now})
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "head": head,
           "open": now, "cleared": cleared}
    if record:
        p = _record_path(ctx)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


HANDOFF = ("Hand this to the anthill-keeper helper in the background and carry on "
           "with the work; do not stop to do it yourself.")


def render(out: dict[str, Any]) -> str:
    if not out["open"]:
        tail = f" ({len(out['cleared'])} cleared)" if out["cleared"] else ""
        return f"anthill upkeep: nothing left undone{tail}.\n"
    lines = [f"anthill upkeep: {len(out['open'])} thing(s) to bring up to date"]
    for it in out["open"]:
        lines.append(f"  - {it['kind']}: {it['detail']}")
    if out["cleared"]:
        lines.append(f"  ({len(out['cleared'])} cleared since last time)")
    lines.append(f"  {HANDOFF}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="anthill upkeep",
                                 description="What a change left undone: glossary, "
                                             "knowledge pages, tests. Read-only.")
    ap.add_argument("--since", default="HEAD~1", help="compare against this commit")
    ap.add_argument("--record", action="store_true",
                    help="save the open list (the post-commit hook does this)")
    ap.add_argument("--open", action="store_true", help="print the saved open list only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        return 0
    out = load(ctx) if args.open else run(ctx, args.since, args.record)
    out.setdefault("cleared", [])
    print(json.dumps(out, indent=2) if args.json else render(out), end="" if not args.json else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
