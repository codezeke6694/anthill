#!/usr/bin/env python3
"""Which areas can be improved, and which must still be built.

The Kit's `doctor.py` answers this once for a whole installation: READY or NOT
READY, where readiness requires at least one verified page. That is the right
question at the wrong grain. A real repository sits at partial coverage -- pages
for three areas out of twenty -- so mode is a property of the area being worked.

An area with at least one page that can scope work is in `improve` mode. An area
with none is in `build` mode, and its next step is a sprint spec rather than a
navigation query.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.knowledge import claims, pages
from anthill.orchestrate import board


def declared_areas(knowledge_dir: Path) -> list[str]:
    """Areas the knowledge base says it has, whether or not any page exists yet."""
    cfg = knowledge_dir / "knowledge.config.json"
    if not cfg.exists():
        return []
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [str(a) for a in (data.get("knowledge", {}).get("areas") or [])]


def report(knowledge_dir: Path, source_root: Path,
           check_commits: bool = True) -> dict[str, Any]:
    a = board.assess(knowledge_dir, source_root, check_commits=check_commits)
    # Seed every declared area, or an area with no pages is invisible -- and
    # "which areas still need building" is the question this report exists for.
    areas: dict[str, dict[str, Any]] = {
        name: {"pages": 0, "scoping": 0, "attested": 0, "blocked": []}
        for name in declared_areas(knowledge_dir)
    }
    for row in a["pages"]:
        bucket = areas.setdefault(row["area"] or "(unset)", {
            "pages": 0, "scoping": 0, "attested": 0, "blocked": [],
        })
        bucket["pages"] += 1
        bucket["scoping"] += 1 if row["scopes_work"] else 0
        bucket["attested"] += 1 if row["attested"] else 0
        if not row["scopes_work"]:
            bucket["blocked"].append({"page": row["page"], "because": row["refused_because"]})

    out = {}
    for name, b in sorted(areas.items()):
        out[name] = {
            **b,
            "mode": "improve" if b["scoping"] else "build",
            # Attestation is the human's signature on intent. An area can be
            # improved without it, but nothing there should be called settled.
            "intent_settled": b["attested"] > 0,
        }
    return {
        "knowledge_dir": str(knowledge_dir),
        "verification_depth": a["verification_depth"],
        "depth_note": a["depth_note"],
        "source_root": str(source_root),
        "area_count": len(out),
        "improve_areas": sorted(k for k, v in out.items() if v["mode"] == "improve"),
        "build_areas": sorted(k for k, v in out.items() if v["mode"] == "build"),
        "areas": out,
        "install_ready": any(v["mode"] == "improve" for v in out.values()),
        "note": ("no page can scope work yet, so every area starts in build mode"
                 if not any(v["mode"] == "improve" for v in out.values()) else ""),
    }


def coverage(knowledge_dir: Path, source_root: Path | None = None,
             top: int = 15) -> dict[str, Any]:
    """Which code the navigation plane knows about but no page explains.

    Readiness answers "can this area be worked". This answers the question that
    preceded it and had no command: *where is there no intent at all*. It exists
    because a real bug was traced to `conversationalist.py` -- 813 lines, two map
    anchors, and zero knowledge rules -- and nothing in the system said so. A
    blind spot that has to be discovered by hitting it is not a blind spot the
    tool is helping with.

    A file counts as explained when a page's footprint resolves to it or a rule
    cites a symbol in it. Size is the proxy for risk: the largest unexplained
    file is where the next surprise is cheapest to prevent.
    """
    root = (source_root or claims.REPO_ROOT).resolve()

    # The package's own code and the test suite are not product intent: this
    # package's rules live in its TECHNICAL.md, and a test explains itself. Counting
    # them would put a permanent, unclosable gap in every report.
    def is_product(rel: str) -> bool:
        head = rel.split("/", 1)[0]
        return head not in {"anthill", "tests", "scripts", ".anthill"}

    known: set[str] = set()
    for c in claims.from_maps():
        sid = c.get("symbol_id", "")
        if "::" in sid and is_product(sid.split("::", 1)[0]):
            known.add(sid.split("::", 1)[0])

    explained: dict[str, set[str]] = {}
    for page in pages.load_pages(knowledge_dir):
        pid = str(page["frontmatter"].get("id") or "")
        for glob in pages.footprint_of(page):
            try:
                for q in root.glob(glob):
                    if q.is_file():
                        explained.setdefault(str(q.relative_to(root)), set()).add(pid)
            except (ValueError, OSError):
                continue
        for rule in page["rules"]:
            for sid in rule["cites"]:
                if "::" in sid:
                    explained.setdefault(sid.split("::", 1)[0], set()).add(pid)

    def lines(rel: str) -> int:
        try:
            return len((root / rel).read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            return 0

    rows = []
    for rel in sorted(known):
        rows.append({"file": rel, "lines": lines(rel),
                     "pages": sorted(explained.get(rel, ()))})
    uncovered = [r for r in rows if not r["pages"]]

    by_dir: dict[str, dict[str, int]] = {}
    for r in rows:
        d = r["file"].split("/", 1)[0]
        b = by_dir.setdefault(d, {"files": 0, "explained": 0, "lines": 0,
                                  "unexplained_lines": 0})
        b["files"] += 1
        b["lines"] += r["lines"]
        if r["pages"]:
            b["explained"] += 1
        else:
            b["unexplained_lines"] += r["lines"]

    return {
        "files_known_to_the_maps": len(rows),
        "files_with_a_page": len(rows) - len(uncovered),
        "files_with_no_page": len(uncovered),
        "share_explained": round(100 * (len(rows) - len(uncovered)) / max(1, len(rows))),
        "by_directory": {d: {**b,
                             "share_explained": round(100 * b["explained"] / max(1, b["files"]))}
                         for d, b in sorted(by_dir.items())},
        "largest_unexplained": sorted(uncovered, key=lambda r: -r["lines"])[:top],
        "note": ("size is the proxy for risk: the largest unexplained file is where "
                 "the next surprise is cheapest to prevent"),
    }
