"""The claim ledger — one verifier for every recorded statement about this code.

Three tools make three kinds of recorded statement, and all three rot the same
way when the tree moves:

    navigation   a map anchor says "this behaviour lives at this address"
    intent       a knowledge rule says "the system does X, verified at commit Y"
    execution    a work unit says "I own these paths, and this gate proves me done"

Each is a *claim*: a statement pinned to a tree that keeps moving. Today each
tool checks its own claims, or does not check them at all — the map re-checks
that a name still exists, a knowledge page waits for a human to notice, and a
unit gate is only ever run once. Nothing tells you which recorded statements
across the three no longer hold.

This module is that missing check. A claim is a symbol citation plus a recorded
fingerprint; verification is `structure.compare` against the live tree; and the
drift kind is attributed rather than reduced to pass/fail, because "its
signature changed" and "its callers changed" demand different responses.

Producers read formats that already exist. Nothing here writes to any of the
three tools, and no producer is required — a missing knowledge directory or
contract simply yields no claims of that kind.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from anthill import context as _ctx
from anthill.navigate import structure as s

REPO_ROOT = s.REPO_ROOT

# Package layout, defined once here because claims.py is the lowest-level module
# that needs it -- the CLI, the ledger and the tests must not disagree about where
# anything lives. Authored things are versioned; build/ holds everything this
# package generates and is gitignored.
# Every one of these used to hang off the tool's own directory, which meant an
# installation wrote its state into the installer. They now hang off the target
# project's state dir, so one project's maps, knowledge, and unit state cannot
# leak into another's -- and uninstalling is removing one directory.
PKG_DIR = Path(__file__).resolve().parents[1]   # the tool itself (templates only)
_C = _ctx.current()
STATE_DIR = _C.state                            # <project>/.anthill
KNOWLEDGE_DIR = _C.knowledge_dir                # authored intent
MAPS_DIR = _C.maps_dir                          # authored / curated maps
BUILD_DIR = _C.local_dir                        # everything generated
GEN_MAPS_DIR = _C.gen_maps_dir                  # generated maps
CATALOGUE_DIR = _C.catalogue_dir                # generated knowledge catalogue
WORK_ROOT = _C.work_root                        # orchestrator state, per target repo


def map_dirs() -> list[Path]:
    """Authored maps first, then generated ones."""
    return [MAPS_DIR, GEN_MAPS_DIR]

KIND_ANCHOR = "navigation"
KIND_RULE = "intent"
KIND_UNIT = "execution"

# A knowledge page pins itself to a source commit: `verified_against: hatu@a1b2c3d`
_PIN_RE = re.compile(r"^verified_against:\s*([A-Za-z0-9_.-]+)@([0-9a-fA-F]{7,40})\s*$", re.M)
# A business rule carries a stable identity that must never be reused. Only the
# rule's opening marker is matched here; the text runs to the next rule or
# heading, because a real rule wraps over several lines and its code citation is
# as likely to sit on the last line as the first.
_RULE_START_RE = re.compile(r"^[ \t]*[-*][ \t]*\*\*(BR-[A-Z0-9]+-[a-z0-9-]+):\*\*", re.M)
_RULE_END_RE = re.compile(r"^#{1,6}[ \t]", re.M)
# The extension that makes a prose rule falsifiable: an explicit symbol citation.
# `cite:` is canonical. `sg:` is accepted because it is what every page written
# before this change uses -- it was the district prefix of the project this tool
# was ported from and meant nothing here, but a grammar change that silently
# invalidated existing citations would be worse than an odd keyword. `code:`
# reads naturally and costs nothing to allow.
_CITE_PREFIXES = ("cite", "sg", "code")
_CITE_RE = re.compile(r"\((?:" + "|".join(_CITE_PREFIXES) + r"):\s*([^)]+?)\s*\)")
CANONICAL_CITE = "cite"


def _iter_rules(text: str) -> list[tuple[str, str]]:
    """Yield (rule_id, full rule text) for every business rule on a page.

    A rule's text runs from its marker to the next rule marker or the next
    heading, so a citation anywhere inside a wrapped bullet is found.
    """
    starts = list(_RULE_START_RE.finditer(text))
    out: list[tuple[str, str]] = []
    for i, match in enumerate(starts):
        body_start = match.end()
        body_end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        heading = _RULE_END_RE.search(text, body_start, body_end)
        if heading:
            body_end = heading.start()
        body = " ".join(text[body_start:body_end].split())
        out.append((match.group(1), body))
    return out


def head_commit(repo: Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo or REPO_ROOT), capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _claim(kind: str, claim_id: str, symbol_id: str, source: str,
           recorded: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "claim_id": claim_id, "symbol_id": symbol_id,
            "source": source, "recorded": recorded, **extra}


# --------------------------------------------------------------------- producers

def from_maps(maps_dir: Path | None = None) -> list[dict[str, Any]]:
    """Navigation claims: every anchor in every map is an address claim.

    Reads authored and generated map directories both. Walking only one is how a
    relocated generated map took the ledger from 902 claims to 214 without error.
    """
    out: list[dict[str, Any]] = []
    bases = [maps_dir] if maps_dir else map_dirs()
    paths = sorted(q for b in bases if b.exists() for q in b.glob("*.json"))
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for node in data.get("nodes") or []:
            node_id = node.get("node_id", "")
            for anchor in node.get("anchors") or []:
                symbol_id = anchor.get("symbol_id", "")
                if not symbol_id:
                    continue
                out.append(_claim(
                    KIND_ANCHOR, f"{node_id}#{symbol_id}", symbol_id, path.name,
                    recorded=anchor.get("struct"),
                    node_id=node_id, role=anchor.get("role", ""),
                ))
    return out


# Markdown in a knowledge repository that is not content. `_generated/` is
# derived, and `templates/` is worse: its example rules would enter the ledger as
# real claims citing `path/to/file.py::symbol`, which reports as missing code.
NON_CONTENT_DIRS = {"_generated", "_map", "templates", "node_modules", ".git", "archive"}
_FM_OPEN = re.compile(r"\A---\s*$", re.M)


def is_content_page(path: Path, root: Path) -> bool:
    """A content page, as opposed to a template, a catalogue, or a README.

    The discriminator is a leading frontmatter block: a file without one is
    prose, and a file someone meant as a page always has it.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if NON_CONTENT_DIRS & set(rel.parts) or path.name.startswith("."):
        return False
    try:
        return bool(_FM_OPEN.match(path.read_text(encoding="utf-8")[:64]))
    except (OSError, UnicodeDecodeError):
        return False


def from_knowledge(knowledge_dir: Path) -> list[dict[str, Any]]:
    """Intent claims: business rules from Agent-Knowledge-Kit style pages.

    A page pins itself with `verified_against: <prefix>@<sha>` and states rules
    as `- **BR-AREA-slug:** text`. A rule becomes machine-checkable only when it
    cites the code it is about, written inline as
    `(cite: path/to/file.py::symbol)`. `sg:` and `code:` are also accepted.
    Rules with no citation are still returned, marked uncited — they are the
    honest backlog of statements nothing can falsify.
    """
    out: list[dict[str, Any]] = []
    if not knowledge_dir.exists():
        return out
    for page in sorted(knowledge_dir.rglob("*.md")):
        if not is_content_page(page, knowledge_dir):
            continue
        try:
            text = page.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        pin = _PIN_RE.search(text)
        pinned = f"{pin.group(1)}@{pin.group(2)}" if pin else ""
        rel = str(page.relative_to(knowledge_dir))
        attested = bool(re.search(r"^intent_attested_by:\s*\S+", text, re.M))
        for rule_id, rule_text in _iter_rules(text):
            cites = _CITE_RE.findall(rule_text)
            if not cites:
                out.append(_claim(KIND_RULE, rule_id, "", rel, None,
                                  pinned_commit=pinned, attested=attested,
                                  text=_CITE_RE.sub("", rule_text).strip(), uncited=True))
                continue
            for symbol_id in cites:
                out.append(_claim(KIND_RULE, rule_id, symbol_id, rel, None,
                                  pinned_commit=pinned, attested=attested,
                                  text=_CITE_RE.sub("", rule_text).strip(), uncited=False))
    return out


def from_contract(contract_path: Path) -> list[dict[str, Any]]:
    """Execution claims: Peregrine units. A unit claims an owned surface.

    Ownership is a path claim rather than a symbol claim, so what can drift is
    whether the owned surface still exists. A unit owning globs that match
    nothing is a contract that has quietly stopped describing the repo.
    """
    out: list[dict[str, Any]] = []
    if not contract_path.exists():
        return out
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    repo = contract_path.resolve().parents[1]
    for unit in data.get("units") or []:
        unit_id = unit.get("id", "")
        for glob in unit.get("owns") or []:
            out.append(_claim(
                KIND_UNIT, f"{unit_id}#{glob}", "", contract_path.name, None,
                unit_id=unit_id, owns=glob, gate=unit.get("gate", ""),
                repo=str(repo),
            ))
    return out


# ------------------------------------------------------------------- verification

# Peregrine's contract builders represent an already-merged unit with a
# placeholder that owns nothing and passes trivially, so its ownership claim is
# settled rather than broken. Recognised so the ledger does not report a
# deliberate convention as drift.
SETTLED_PREFIX = "__done__/"


def _verify_path_claim(claim: dict[str, Any]) -> dict[str, Any]:
    repo = Path(claim.get("repo") or REPO_ROOT)
    glob = claim.get("owns", "")
    if glob.startswith(SETTLED_PREFIX) and claim.get("gate", "").strip() == "true":
        return {"drift": "settled", "severity": 0,
                "detail": "unit already merged; placeholder owns nothing by design",
                "relocation": []}
    # Peregrine globs use `**` for a subtree; Path.glob understands that natively.
    try:
        matches = sum(1 for _ in repo.glob(glob))
    except (ValueError, OSError):
        matches = 0
    if matches:
        return {"drift": s.DRIFT_NONE, "severity": 0,
                "detail": f"{matches} path(s) match", "relocation": []}
    return {"drift": s.DRIFT_MISSING, "severity": s._SEVERITY[s.DRIFT_MISSING],
            "detail": f"owned glob matches nothing: {glob}", "relocation": []}


def _verify_file_citation(claim: dict[str, Any]) -> dict[str, Any]:
    rel = claim["symbol_id"].strip()
    if (Path(REPO_ROOT) / rel).is_file():
        return {"drift": "whole-file", "severity": 1,
                "detail": f"cites the whole file {rel}; only that it exists can be "
                          f"checked -- cite {rel}::<name> to make it checkable",
                "relocation": []}
    return {"drift": s.DRIFT_MISSING, "severity": s._SEVERITY[s.DRIFT_MISSING],
            "detail": f"cited file is gone: {rel}", "relocation": []}


def verify(claims: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check every claim against the live tree, attributing drift per claim."""
    results: list[dict[str, Any]] = []
    for claim in claims:
        if claim["kind"] == KIND_UNIT:
            verdict = _verify_path_claim(claim)
            live: dict[str, Any] = {}
        elif claim.get("uncited"):
            verdict = {"drift": "uncited", "severity": 1,
                       "detail": "rule cites no code; nothing can falsify it",
                       "relocation": []}
            live = {}
        elif "::" not in claim["symbol_id"]:
            # A citation of a whole file (`(sg: run.sh)`) has no shape to
            # fingerprint, only an existence to check. It used to reach
            # fingerprint_at_commit, which raised and took the whole check down
            # with it -- one careless citation silenced every other claim.
            verdict = _verify_file_citation(claim)
            live = {}
        else:
            try:
                live = s.fingerprint(claim["symbol_id"])
            except ValueError as exc:
                live = {"exists": False, "reason": str(exc)}
            recorded = claim.get("recorded")
            pin = (claim.get("pinned_commit") or "")
            if recorded is None and "@" in pin:
                # A knowledge rule records a commit rather than a fingerprint, so
                # derive the fingerprint from the cited code as it stood there.
                sha = pin.split("@", 1)[1]
                past = s.fingerprint_at_commit(claim["symbol_id"], sha)
                if past.get("exists"):
                    recorded = past
            if not live.get("exists") and not recorded:
                # No fingerprint was recorded, so treat the citation itself as
                # the claim: it must at least resolve to a real symbol.
                file_part = claim["symbol_id"].split("::", 1)[0] if "::" in claim["symbol_id"] else ""
                symbol = claim["symbol_id"].split("::", 1)[1] if "::" in claim["symbol_id"] else ""
                recorded = {"file": file_part, "symbol": symbol}
            verdict = s.compare(recorded, live)
        results.append({**claim, **verdict,
                        "live_line": live.get("line_start"),
                        "live_file": live.get("file")})
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by kind and drift, plus the claims that actually need a human."""
    by_kind: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = by_kind.setdefault(r["kind"], {})
        bucket[r["drift"]] = bucket.get(r["drift"], 0) + 1
    needs_review = sorted(
        (r for r in results if r["severity"] >= 2),
        key=lambda r: (-r["severity"], r["kind"], r["claim_id"]),
    )
    total = len(results)
    holding = sum(1 for r in results if r["severity"] == 0)
    return {
        "total_claims": total,
        "holding": holding,
        "needs_review": len(needs_review),
        "head_commit": head_commit(),
        "by_kind": by_kind,
        "top_review": [
            {k: r[k] for k in ("kind", "claim_id", "symbol_id", "drift", "detail", "relocation")
             if k in r}
            for r in needs_review[:25]
        ],
    }
