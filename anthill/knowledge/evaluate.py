#!/usr/bin/env python3
"""Routing measured against questions the pages did not author.

The problem this solves is a conflict of interest. A routing score computed from
questions written by whoever wrote the pages measures phrasing agreement, not
retrieval: asked in page vocabulary the graph scored 19/19, and asked in a
developer's own words about a live bug it scored 1/4. The second number is the
real one, and nothing in the system was capable of producing it.

So the questions come from somewhere independent: a learning log. Each entry
already contains a *symptom* written by someone hitting the problem ("the answer
mentions a number that is not in the rows"), and separately names the *code* that
turned out to be responsible. That is a query and an expected answer, neither
authored for retrieval, both written before the pages existed.

Two outcomes are kept apart, because conflating them flatters the tool:
  - unreachable -- no page covers any file the entry blames. A miss here is a
    coverage gap, and reporting it as a routing failure would hide that.
  - routable    -- some page covers it, so routing had a fair chance. Only these
    are scored.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.knowledge import pages

_ENTRY = re.compile(r"^###\s+(.+?)\s*$", re.M)
_FIELD = re.compile(r"^\*\*(Problem|Cause|Fix)[^:]*:\*\*\s*(.+?)(?=^\*\*|\Z)", re.M | re.S)
# A repo-relative source path, as these entries habitually write it.
_PATH = re.compile(r"`([a-z_][A-Za-z0-9_/]*\.(?:py|ts|tsx|jsx|js))")


def parse_log(path: Path) -> list[dict[str, Any]]:
    """Entries with a symptom to ask and at least one file to expect."""
    text = path.read_text(encoding="utf-8")
    bounds = [(m.start(), m.group(1)) for m in _ENTRY.finditer(text)] + [(len(text), "")]
    out = []
    for (start, title), (end, _) in zip(bounds, bounds[1:]):
        body = text[start:end]
        fields = {k: v for k, v in _FIELD.findall(body)}
        problem = re.sub(r"\s+", " ", fields.get("Problem", "")).strip()
        blamed = {p for k in ("Cause", "Fix") for p in _PATH.findall(fields.get(k, ""))}
        if problem and blamed:
            out.append({"title": title, "question": problem, "expected_files": sorted(blamed)})
    return out


def _covered_files(knowledge_dir: Path, source_root: Path,
                   cited_only: bool = False) -> dict[str, set[str]]:
    """node_id -> the source files that page speaks for.

    `cited_only` is the strict reading, and it exists because the loose one makes a
    noisy label. A footprint can be one glob over a 3,000-line module, so every
    entry blaming any corner of that file "expects" the single page that owns it,
    whether or not the page says anything about that corner. A citation is a rule
    pointing at a named symbol, which is a much better claim that the page really
    discusses it.
    """
    out: dict[str, set[str]] = {}
    for page in pages.load_pages(knowledge_dir):
        pid = str(page["frontmatter"].get("id") or "")
        files: set[str] = set()
        if not cited_only:
            for glob in pages.footprint_of(page):
                try:
                    files.update(str(q.relative_to(source_root))
                                 for q in source_root.glob(glob) if q.is_file())
                except (ValueError, OSError):
                    continue
        for rule in page["rules"]:
            files.update(sid.split("::", 1)[0] for sid in rule["cites"] if "::" in sid)
        out[pid] = files
    return out


def routing(knowledge_dir: Path, source_root: Path, log: Path,
            rank: Callable[[str, int], list[dict[str, Any]]],
            top_k: int = 3, limit: int = 0, cited_only: bool = False) -> dict[str, Any]:
    """Score top-1 and top-k over entries a page could actually have answered.

    The question is truncated to its first sentence: a log entry's Problem line
    carries the measured figures that proved the bug, and feeding those in would
    let a number match a page by accident rather than by meaning.
    """
    covered = _covered_files(knowledge_dir, source_root.resolve(), cited_only)
    entries = parse_log(log)
    if limit:
        entries = entries[:limit]

    scored, unreachable = [], []
    for e in entries:
        answerable = sorted(n for n, files in covered.items()
                            if files & set(e["expected_files"]))
        question = re.split(r"(?<=[.;])\s", e["question"])[0][:300]
        if not answerable:
            unreachable.append({"title": e["title"], "expected_files": e["expected_files"]})
            continue
        ranked = [r["node_id"] for r in rank(question, top_k)]
        scored.append({
            "title": e["title"],
            "question": question,
            "answerable_by": answerable,
            "ranked": ranked,
            "top1": bool(ranked[:1]) and ranked[0] in answerable,
            "topk": any(n in answerable for n in ranked),
        })

    n = len(scored)
    hits1 = sum(1 for r in scored if r["top1"])
    hitsk = sum(1 for r in scored if r["topk"])
    return {
        "log": str(log),
        "entries_in_log": len(entries),
        "routable": n,
        "unreachable": len(unreachable),
        "top1": hits1,
        "top1_pct": round(100 * hits1 / max(1, n)),
        f"top{top_k}": hitsk,
        f"top{top_k}_pct": round(100 * hitsk / max(1, n)),
        "misses": [r for r in scored if not r["topk"]],
        "unreachable_entries": unreachable,
        "label_basis": "cited symbols only" if cited_only else "footprint or citation",
        "note": ("questions and expected answers both come from the log, so neither "
                 "was authored for retrieval; unreachable entries are a coverage "
                 "gap, not a routing failure"),
        "caveat": ("the expected answer is 'a page that speaks for the file the fix "
                   "touched', which is a proxy for 'the page that should answer this'. "
                   "A shared module or a large file makes that label wrong in both "
                   "directions, so top-1 here is a lower bound, not an accuracy."),
    }
