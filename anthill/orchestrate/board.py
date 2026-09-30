#!/usr/bin/env python3
"""Pages become a work board.

Warm mode: the contract is generated from knowledge, not inferred from an import
graph. The page author already declared scope (`footprint`) and relations
(`related`), so nothing here has to guess dependency direction from imports --
which is the step that would otherwise need per-language type knowledge.

The gate in §7 of docs/plans/KNOWLEDGE_FIRST_AGENT_SYSTEM.md lives here: a page
whose evidence or footprint no longer verifies may not scope work. Once a board
is generated from knowledge, one stale page becomes a wrong board, so refusal is
the safe default and every refusal is reported rather than dropped.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.knowledge import claims, pages
from anthill.navigate import structure

# Peregrine escalates a unit after this many failed gate attempts; trap.fx
# recorded `attempts: 2`, which is the observed convention.
DEFAULT_ESCALATE_AFTER = 2


def _commit_exists(sha: str, repo: Path) -> bool:
    """Is the pinned commit real and reachable in the source repository?

    This is the language-neutral half of the staleness check and it is the one
    that matters most: a page pinned to a commit that no longer exists is a page
    whose evidence cannot be re-read by anyone.
    """
    if not sha:
        return False
    try:
        out = subprocess.run(["git", "cat-file", "-t", sha], cwd=repo,
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "commit"


def _citation_checkable(symbol_id: str) -> bool:
    """Only Python citations can be fingerprint-checked.

    `structure.py` parses with `ast` and `split_symbol_id` requires a `.py`
    file, so `claims.verify` reports a TypeScript citation as missing even when
    it is perfectly valid. Treating that as drift would refuse correct pages, so
    non-Python citations degrade to the footprint's path check instead.
    """
    return "::" in symbol_id and symbol_id.split("::", 1)[0].endswith(".py")


def gate_for(area: str, gates: dict[str, str], template: str) -> str:
    if area in gates:
        return gates[area]
    if template:
        return template.format(area=area)
    return ""


def assess(knowledge_dir: Path, source_root: Path,
           check_commits: bool = True) -> dict[str, Any]:
    """Per page: may it scope work, and if not, why not."""
    loaded = pages.load_pages(knowledge_dir)
    findings = pages.validate(loaded, source_root)
    blocked = pages.blocking(findings)

    # Fingerprint drift, but only when it can actually be computed. structure.py
    # resolves every symbol against the repository it lives in, so in the Kit's
    # normal sibling layout -- knowledge repo beside a separate source checkout --
    # a citation would be reported as missing merely because it is not in *this*
    # tree. Refusing a correct page is worse than checking it less deeply, so
    # verification degrades to the footprint's path check and says so.
    symbol_depth = source_root.resolve() == structure.REPO_ROOT.resolve()
    drifted: dict[str, list[str]] = {}
    ledger = [c for c in claims.from_knowledge(knowledge_dir)
              if not c.get("uncited") and _citation_checkable(c.get("symbol_id", ""))]
    if ledger and symbol_depth:
        for r in claims.verify(ledger):
            if r.get("severity", 0) >= 2:
                drifted.setdefault(r["source"], []).append(
                    f"{r['claim_id']} -> {r['symbol_id']}: {r.get('detail', r.get('drift'))}")

    out = []
    for page in loaded:
        fm = page["frontmatter"]
        reasons = [f["code"] + ": " + f["detail"]
                   for f in findings
                   if f["page"] == page["path"] and f["severity"] == "error"]
        pin = str(fm.get("verified_against", "")).strip()
        # An unverified pin bars scoping as firmly as a stale one -- more so. A page
        # still carrying the REPLACE_ME placeholder has never been read against real
        # code, so scoping work from it would hand a worker an unchecked instruction
        # and call it intent. Measured: two draft pages became units on this repo
        # before this check existed.
        if not pin or pin == pages._PLACEHOLDER:
            reasons.append("unverified_pin: verified_against is still a placeholder, "
                           "so nothing has been checked against real code")
        sha = pin.split("@", 1)[1] if "@" in pin else ""
        if check_commits and sha and not _commit_exists(sha, source_root):
            reasons.append(f"unreachable_commit: {pin} is not a commit in {source_root}")
        reasons += [f"symbol_drift: {d}" for d in drifted.get(page["path"], [])]
        if not pages.footprint_of(page):
            reasons.append("no_footprint: page declares no files, so it cannot scope work")
        out.append({
            "page": page["path"],
            "id": str(fm.get("id", "")),
            "area": str(fm.get("area", "")),
            "title": str(fm.get("title", "")),
            "attested": page["attested"],
            "footprint": pages.footprint_of(page),
            "scopes_work": not reasons and page["path"] not in blocked,
            "refused_because": reasons,
        })
    return {
        "pages": out,
        "findings": findings,
        "verification_depth": "symbol" if symbol_depth else "path",
        "depth_note": "" if symbol_depth else (
            f"citations are not fingerprint-checked: structure.py is bound to "
            f"{structure.REPO_ROOT}, not {source_root}"),
    }


def _brief(page_row: dict[str, Any], page: dict[str, Any]) -> str:
    """The unit's instruction, assembled from the page rather than invented.

    Rules are quoted with their stable IDs so a worker cannot silently reinterpret
    one, and the page path is named so the worker reads intent before editing.
    """
    rules = page["rules"]
    lines = [f"Intent source: {page['path']} (do not restate it, read it)."]
    if page_row["title"]:
        lines.append(f"Subject: {page_row['title']}.")
    if rules:
        lines.append("Rules this unit must keep true:")
        lines += [f"- {r['rule_id']}: {r['text']}" for r in rules[:12]]
    else:
        lines.append("This page states no BR- rules yet; establish them as part of the work.")
    lines.append("This unit owns its page as well as its code. When the change lands, "
                 "update the page: re-pin verified_against to the commit you produce, "
                 "correct any rule the change makes untrue, and add a History line. "
                 "Never fill intent_attested_by -- that is a human's signature.")
    return "\n".join(lines)


def generate(knowledge_dir: Path, source_root: Path, project: str,
             base_branch: str = "main", gate_template: str = "",
             gates: dict[str, str] | None = None,
             areas: list[str] | None = None,
             check_commits: bool = True) -> dict[str, Any]:
    """A Peregrine contract whose units come from pages that verify.

    `related` becomes `needs_data` -- the serialising constraint -- because the
    Kit's schema does not say which relations are interface-only, and assuming
    the parallel-friendly answer would let a worker build against an interface
    that is not frozen yet. An author who knows better says so with an explicit
    `needs_iface` list on the page.
    """
    gates = gates or {}
    loaded = {p["path"]: p for p in pages.load_pages(knowledge_dir)}
    a = assess(knowledge_dir, source_root, check_commits=check_commits)

    units, refused = [], []
    for row in a["pages"]:
        if areas and row["area"] not in areas:
            continue
        if not row["scopes_work"]:
            refused.append({"page": row["page"], "id": row["id"],
                            "because": row["refused_because"]})
            continue
        page = loaded[row["page"]]
        fm = page["frontmatter"]
        needs_iface = fm.get("needs_iface") or []
        if isinstance(needs_iface, str):
            needs_iface = [needs_iface] if needs_iface.strip() else []
        related = fm.get("related") or []
        if isinstance(related, str):
            related = [related] if related.strip() else []
        # A unit owns its own page as well as its code. The brief tells the agent to
        # re-pin the page to the commit it produces, and without the page in `owns`
        # doing so is an ownership violation -- the instruction and the boundary
        # contradicted each other. Owning it also means the page travels with the
        # change instead of drifting the moment the code lands.
        page_path = str((knowledge_dir / row["page"]).resolve())
        try:
            page_own = str((knowledge_dir / row["page"]).resolve().relative_to(
                source_root.resolve()))
        except ValueError:
            page_own = ""   # knowledge lives outside the worked repo; nothing to own
        units.append({
            "id": row["id"],
            "title": row["title"] or row["id"],
            "owns": row["footprint"] + ([page_own] if page_own else []),
            "gate": gate_for(row["area"], gates, gate_template),
            "brief": _brief(row, page),
            "needs_iface": [str(x) for x in needs_iface],
            "needs_data": [str(x) for x in related if str(x) not in set(map(str, needs_iface))],
            "escalate_after": DEFAULT_ESCALATE_AFTER,
        })

    # A dependency edge may point at a page that was refused, or at one filtered
    # out by --areas. Left in, the contract names a unit that does not exist and
    # the orchestrator refuses to load it at all -- measured: a tower board whose
    # only unit depended on the page refused beside it. Dropped edges are reported,
    # never silently removed: an edge that disappears means this board runs a unit
    # whose declared dependency is not being done.
    emitted = {u["id"] for u in units}
    dangling = []
    for u in units:
        for kind in ("needs_iface", "needs_data"):
            kept = []
            for dep in u[kind]:
                if dep in emitted:
                    kept.append(dep)
                else:
                    dangling.append({"unit": u["id"], "needs": dep, "kind": kind,
                                     "why": "refused or outside the selected areas"})
            u[kind] = kept

    ungated = [u["id"] for u in units if not u["gate"]]
    return {
        "dangling_edges": dangling,
        "verification_depth": a["verification_depth"],
        "depth_note": a["depth_note"],
        "contract": {
            "version": 1,
            "project": project,
            "base_branch": base_branch,
            "kernel_path": "",
            "units": units,
        },
        "generated_from": str(knowledge_dir),
        "unit_count": len(units),
        "refused_count": len(refused),
        "refused": refused,
        "ungated_units": ungated,
        "warning": " | ".join(w for w in [
            ("units without a gate cannot prove themselves; supply --gate-template "
             "or per-area gates") if ungated else "",
            (f"{len(dangling)} dependency edge(s) dropped because the unit they point "
             f"at is not on this board") if dangling else "",
        ] if w),
    }
