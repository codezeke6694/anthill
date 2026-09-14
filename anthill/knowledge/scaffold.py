#!/usr/bin/env python3
"""Create and maintain a knowledge base.

The knowledge plane needs three things the other two do not provide: somewhere
for pages to live, templates that make the required frontmatter unavoidable, and
a generated catalogue so a rule can be found by identity rather than by grep.

What is deliberately NOT here: CI workflows, auto-merge, and a review bot. Those
are policy for a particular host, and inventing them would mean shipping process
nobody asked for. The one policy this file does keep is the important one --
`intent_attested_by` is written into every template blank, and nothing in
anthill ever fills it.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.knowledge import pages

CONFIG_FILE = "knowledge.config.json"

_FRONTMATTER = """\
---
id: {id}
type: {type}
title: {title}
area: {area}
owners: []
classification: internal
criticality: standard
aliases: []
related: []
verified_against: REPLACE_ME
{review}intent_attested_by:
footprint:
  - REPLACE_ME
---
"""

_BODY = {
    "module": """
# {title}

## Purpose

_What this part of the system is for, in one paragraph. Not how it works -- the
code says that -- but what it is trying to achieve._

## Rules

_Each rule gets a stable identity that is never renamed or reused, and a
citation so it can be falsified:_

- **BR-{registry}-example:** Statement of the rule (sg: path/to/file.py::symbol).

## Non-obvious behaviour

_The things a reader would get wrong from the code alone._

## History

_A retired rule is recorded here with evidence, never deleted._
""",
    "architecture": """
# {title}

## Decision

_What was decided._

## Context

_What made the decision necessary, including the constraint that ruled out the
obvious alternative._

## Consequences

_What this makes easy, and what it makes hard._

## Rules

- **BR-{registry}-example:** Statement of the rule (sg: path/to/file.py::symbol).

## History
""",
    "decision": """
# {title}

## Question

## Options considered

## Decision and why

## Rules

- **BR-{registry}-example:** Statement of the rule (sg: path/to/file.py::symbol).

## History
""",
    "incident": """
# {title}

## What happened

## Evidence

_The log line, the failing output, or the row that proved it._

## Cause

_The mechanism, measured -- not the guess._

## Rules

- **BR-{registry}-example:** Statement of the rule (sg: path/to/file.py::symbol).

## History
""",
}

RULES_DOC = """\
# Knowledge rules

This repository records verified **intent**. The source repository stays
authoritative for **behaviour**.

## Non-negotiable

1. **Every claim is checked against code at a real commit.** `verified_against`
   is `{prefix}@<sha>` from the *source* repository. `REPLACE_ME` is the honest
   placeholder while a page is a draft; it is never left on a page that scopes
   work.
2. **A rule identity is permanent.** `BR-<REGISTRY>-<slug>` is never renamed or
   reused. A rule that stops applying is retired in History with evidence.
3. **A citation makes a rule falsifiable.** Write it inline as
   `(sg: path/to/file.py::symbol)`. A rule with no citation is allowed, and is
   tracked as the honest backlog of statements nothing can check.
4. **You never fill `intent_attested_by`.** That field is a human's signature on
   intent. An agent may draft, document, and cite; it may not attest.
5. **`footprint` is the page's scope.** It lists the files this page governs, and
   it is what lets the page become a unit of work. Two pages in one area may not
   own overlapping paths.
6. **Generated output is derived.** The catalogue, index and backlinks are
   rebuilt, never hand-edited, and are written outside the authored tree.

## The loop

```bash
anthill pages      --knowledge . --source {source}
anthill kb catalogue --knowledge .
anthill index-pages --knowledge . --source {source}
anthill readiness  --knowledge . --source {source}
```

An area with at least one page that can scope work is in `improve` mode; an area
with none is in `build` mode, and its next step is a sprint spec.
"""

AGENTS_DOC = """\
# Agent instructions — {project} knowledge

This repository is the intent layer for `{source}`. Read it before changing
behaviour there, and write to it when you learn something durable that the code
cannot explain by itself.

## Looking something up

```bash
anthill start "<what you are trying to do>" --map knowledge
anthill card <page-id> --map knowledge
```

The card names the page, its rules, and the live code addresses those rules cite.

## Writing a page

Copy the closest template from `templates/`, fill every required field, and cite
real code at a real commit. Then:

```bash
anthill pages --knowledge . --source {source}
```

Fix every `error` before proposing the change. A `warn` is a judgement call; an
`info` is a note.

## What you must not do

- Fill `intent_attested_by`. Ever.
- Rename or reuse a `BR-` identity.
- Hand-edit generated output. Rebuild it instead.
- Invent a `verified_against` sha. Use `REPLACE_ME` until you have read code.
"""


def default_config(project: str, source: str, areas: list[str],
                   registries: list[str], prefix: str = "") -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-") or "project"
    return {
        "project": {"name": project, "slug": slug},
        "source": {"checkout": source, "evidence_prefix": prefix or slug,
                   "integration_branch": "main"},
        "knowledge": {"areas": areas, "registries": registries},
        "advisory": {"review_by_days": {"critical": 180, "standard": 365,
                                        "architecture": 180},
                     "page_length_warning": 400},
        "attestation": {"owners": [], "note":
                        "only a human listed here may fill intent_attested_by"},
    }


def init(knowledge_dir: Path, project: str, source: str, areas: list[str],
         registries: list[str], prefix: str = "", write: bool = True) -> dict[str, Any]:
    """Create a knowledge base. Refuses to clobber an existing one."""
    knowledge_dir = Path(knowledge_dir)
    cfg_path = knowledge_dir / CONFIG_FILE
    if cfg_path.exists():
        return {"created": False,
                "reason": f"{cfg_path} already exists; nothing was written"}

    cfg = default_config(project, source, areas, registries, prefix)
    created: list[str] = []

    def put(rel: str, text: str) -> None:
        p = knowledge_dir / rel
        if write:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        created.append(rel)

    if write:
        knowledge_dir.mkdir(parents=True, exist_ok=True)
    put(CONFIG_FILE, json.dumps(cfg, indent=2) + "\n")
    put("KNOWLEDGE-RULES.md", RULES_DOC.format(
        prefix=cfg["source"]["evidence_prefix"], source=source))
    put("AGENTS.md", AGENTS_DOC.format(project=project, source=source))

    horizon = cfg["advisory"]["review_by_days"]
    for kind in ("module", "architecture", "decision", "incident"):
        days = horizon.get("architecture" if kind == "architecture" else "standard", 365)
        review = (f"review_by: {(date.today() + timedelta(days=days)).isoformat()}\n"
                  if kind in pages.REVIEW_REQUIRED_TYPES else "")
        put(f"templates/{kind}.md",
            _FRONTMATTER.format(id="REPLACE_ME", type=kind, title="REPLACE_ME",
                                area=areas[0] if areas else "REPLACE_ME",
                                review=review)
            + _BODY[kind].format(title="REPLACE_ME",
                                 registry=registries[0] if registries else "AREA"))

    for area in areas:
        put(f"modules/{area}/.gitkeep", "")
    put("incidents/.gitkeep", "")
    put(".gitignore", "*.tmp.*\n")

    return {"created": bool(write), "knowledge_dir": str(knowledge_dir),
            "files": created, "areas": areas, "registries": registries,
            "next": "copy a template into modules/<area>/ and fill it in"}


def catalogue(knowledge_dir: Path, write: bool = True,
              out_dir: Path | None = None) -> dict[str, Any]:
    """Rebuild `_generated/`: the rule catalogue, backlinks, and an area index.

    A rule must be findable by its identity -- that is the point of a stable ID --
    and a page must be reachable from the pages that relate to it. Both are
    derived, so both are regenerated rather than maintained.
    """
    knowledge_dir = Path(knowledge_dir)
    loaded = pages.load_pages(knowledge_dir)

    rules: list[dict[str, Any]] = []
    duplicates: dict[str, list[str]] = {}
    by_area: dict[str, list[dict[str, Any]]] = {}
    backlinks: dict[str, list[str]] = {}

    seen_rule: dict[str, str] = {}
    for page in loaded:
        fm = page["frontmatter"]
        pid = str(fm.get("id") or Path(page["path"]).stem)
        area = str(fm.get("area", "") or "(unset)")
        by_area.setdefault(area, []).append({
            "id": pid, "title": str(fm.get("title", "")), "page": page["path"],
            "attested": page["attested"], "rules": len(page["rules"]),
            "footprint": pages.footprint_of(page),
        })
        related = fm.get("related") or []
        if isinstance(related, str):
            related = [related] if related.strip() else []
        for target in related:
            backlinks.setdefault(str(target), []).append(pid)
        for rule in page["rules"]:
            rid = rule["rule_id"]
            if rid in seen_rule and seen_rule[rid] != page["path"]:
                # A reused identity is the one thing the scheme cannot tolerate:
                # two different statements would answer to the same name.
                duplicates.setdefault(rid, [seen_rule[rid]]).append(page["path"])
            seen_rule[rid] = page["path"]
            rules.append({"rule_id": rid, "page": page["path"], "page_id": pid,
                          "area": area, "cites": rule["cites"],
                          "falsifiable": bool(rule["cites"]),
                          "text": rule["text"][:300]})

    rules.sort(key=lambda r: r["rule_id"])
    lines = ["# Rule catalogue", "",
             f"_Generated by anthill/knowledge/scaffold.py. {len(rules)} rules across "
             f"{len(loaded)} pages. Do not hand-edit._", ""]
    for area in sorted(by_area):
        lines += [f"## {area}", ""]
        for r in [r for r in rules if r["area"] == area]:
            mark = "" if r["falsifiable"] else "  _(uncited)_"
            lines.append(f"- **{r['rule_id']}** — {r['text']}{mark}  \n"
                         f"  `{r['page']}`")
        lines.append("")

    index = ["# Page index", "",
             f"_Generated by anthill/knowledge/scaffold.py. {len(loaded)} pages._", ""]
    for area in sorted(by_area):
        index += [f"## {area}", ""]
        for p in sorted(by_area[area], key=lambda x: x["id"]):
            att = "attested" if p["attested"] else "unattested"
            index.append(f"- `{p['id']}` — {p['title'] or '(untitled)'} "
                         f"({p['rules']} rules, {att}) — `{p['page']}`")
        index.append("")

    back = ["# Backlinks", "",
            "_Which pages declare a relation to each page._", ""]
    for target in sorted(backlinks):
        back.append(f"- `{target}` ← " + ", ".join(f"`{s}`" for s in sorted(set(backlinks[target]))))

    # Derived output defaults beside the base for a standalone knowledge repo, but
    # this package points it at build/ so generated files never sit among authored ones.
    out_dir = Path(out_dir) if out_dir else knowledge_dir / "_generated"
    written = []
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in (("RULES.md", "\n".join(lines)),
                           ("INDEX.md", "\n".join(index)),
                           ("BACKLINKS.md", "\n".join(back)),
                           ("rules.json", json.dumps(rules, indent=2))):
            (out_dir / name).write_text(text + "\n", encoding="utf-8")
            written.append(str(out_dir / name))

    return {
        "pages": len(loaded), "rules": len(rules),
        "falsifiable": sum(1 for r in rules if r["falsifiable"]),
        "uncited": sum(1 for r in rules if not r["falsifiable"]),
        "areas": sorted(by_area),
        "duplicate_rule_ids": duplicates,
        "written": written,
        "warning": ("a rule identity is reused across pages; identities must be "
                    "unique" if duplicates else ""),
    }
