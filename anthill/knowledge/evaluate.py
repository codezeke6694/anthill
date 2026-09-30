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


# ------------------------------------------------------------------ from history

def history_questions(repo: Path, node_files: dict[str, str],
                      max_files: int = 4) -> list[dict[str, Any]]:
    """Past commits as exam questions: the subject is the task, the files are the answer.

    The learning log above needs a log, and most repositories never keep one.
    Every repository keeps this. A commit subject is written by whoever did the
    work, in the words they would have used to ask for it, before any map
    existed -- so it is independent of the map in the way that matters.

    Only commits touching 1..`max_files` files the map knows are used: a subject
    spread over twenty files names none of them. Files that no longer exist are
    dropped from the answer, and a commit left with no answer is skipped.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "log", "--no-merges", "--format=@@%h|%s", "--name-only"],
                             cwd=repo, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    known = set(node_files.values())
    qs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in out.splitlines():
        if line.startswith("@@"):
            h, _, subj = line[2:].partition("|")
            cur = {"commit": h, "question": subj, "files": []}
            qs.append(cur)
        elif line.strip() and cur is not None:
            cur["files"].append(line.strip())
    usable = []
    for q in qs:
        hit = sorted(set(q.pop("files")) & known)
        if 1 <= len(hit) <= max_files:
            q["expected_files"] = hit
            usable.append(q)
    return usable


def routing_from_history(repo: Path, nodes: list[dict[str, Any]],
                         rank: Callable[..., list[dict[str, Any]]],
                         top_k: int = 3, limit: int = 0) -> dict[str, Any]:
    """How often the router sends a past task to the files that task changed.

    Each question is asked with its own commit hidden from the index
    (`exclude`), because a node that carries the question's subject as history
    would otherwise find the answer by reading the answer key.

    `one_step` also counts a question as found when an expected file is a
    direct route or consumer of a top-k node: the card lists both, so an agent
    standing there is one read away.
    """
    node_files = {n["node_id"]: n["file"] for n in nodes if n.get("file")}
    by_id = {n["node_id"]: n for n in nodes}
    qs = history_questions(repo, node_files)
    if limit:
        qs = qs[:limit]
    rows = []
    for q in qs:
        want = set(q["expected_files"])
        ranked = [r["node_id"] for r in rank(q["question"], top_k,
                                             exclude=frozenset([q["commit"]]))]
        files = [node_files.get(n) for n in ranked]
        near = set()
        for n in ranked:
            node = by_id.get(n) or {}
            near.update(r.get("go_to") for r in node.get("routes") or [])
            near.update(node.get("consumers") or [])
        near_files = {node_files.get(n) for n in near}
        rows.append({
            "commit": q["commit"], "question": q["question"],
            "expected_files": q["expected_files"], "ranked_files": files,
            "top1": bool(files) and files[0] in want,
            "topk": any(f in want for f in files),
            "one_step": any(f in want for f in files) or bool(near_files & want),
        })
    n = max(1, len(rows))
    pct = lambda k: round(100 * sum(1 for r in rows if r[k]) / n)
    return {
        "questions": len(rows),
        "top1_pct": pct("top1"),
        f"top{top_k}_pct": pct("topk"),
        "one_step_pct": pct("one_step"),
        "misses": [r for r in rows if not r["topk"]],
        "note": ("each question is a past commit subject, asked with that commit "
                 "hidden; the answer is the files it changed"),
    }
