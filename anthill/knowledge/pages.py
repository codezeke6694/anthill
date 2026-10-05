#!/usr/bin/env python3
"""Knowledge pages as the addressable substrate.

Navigation over source symbols is language-bound: `build_map.py` parses Python
with `ast`, so it cannot see a TypeScript repository at all. Navigation over
knowledge pages is not, because a page is markdown in every project.

This module is the inversion. It reads Agent-Knowledge-Kit style pages, checks
the things about them that can be falsified, and converts them into the same
node shape `cli.py` already routes over -- so the router is reused rather than
rebuilt. Four of the five node fields come straight from the Kit's required
frontmatter (`id`, `area`, `aliases`, `related`, plus the title); only `anchors`
had no source, which is what `footprint` supplies.

Zero dependencies (principle P1). The frontmatter reader is a deliberate YAML
subset -- scalars, inline lists, block lists -- because that is all the Kit's
schema uses and a parser we own cannot drift from a parser we don't.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.knowledge import claims

from anthill import context as _ctx
REPO_ROOT = _ctx.current().root

# The Kit's FRAMEWORK-CONTRACT.md: every changed content page requires these.
REQUIRED_FIELDS = (
    "id", "type", "area", "owners", "criticality", "classification",
    "aliases", "related", "verified_against",
)
# Module and architecture pages additionally require a review date.
REVIEW_REQUIRED_TYPES = ("module", "architecture")

# `verified_against: <prefix>@<7-to-40-hex>` -- the same grammar claims.py pins on.
_PIN_GRAMMAR = re.compile(r"^[a-z0-9][a-z0-9._-]*@[0-9a-f]{7,40}$")
# The honest placeholder the Kit blesses while a page is still a draft.
_PLACEHOLDER = "REPLACE_ME"

_FM_BOUNDARY = re.compile(r"^---\s*$")


# --------------------------------------------------------------- frontmatter

def _scalar(raw: str) -> Any:
    """One frontmatter value. Inline lists become lists; everything else stays a
    string, because guessing types is how a config parser starts lying."""
    v = raw.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    if len(v) >= 2 and v[0] == v[-1] == '"':
        # Written by `json.dumps`, so it is read back the same way: a value with
        # a colon or a quote in it survives the round trip.
        try:
            return json.loads(v)
        except ValueError:
            pass
    return v.strip("'\"")


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Read the leading `---` block. Supports `k: v`, `k: [a, b]`, and

        k:
          - a
          - b

    An absent or unterminated block yields {} rather than raising: a malformed
    page is a validation finding, not a crash.
    """
    lines = text.splitlines()
    if not lines or not _FM_BOUNDARY.match(lines[0]):
        return {}
    body: list[str] = []
    for line in lines[1:]:
        if _FM_BOUNDARY.match(line):
            break
        body.append(line)
    else:
        return {}

    out: dict[str, Any] = {}
    key: str | None = None
    for line in body:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            # `key:` with nothing after it was recorded as "" a line ago; the
            # first block item is what reveals it was opening a list.
            if not isinstance(out.get(key), list):
                out[key] = [] if not str(out.get(key, "")).strip() else [out[key]]
            out[key].append(item.group(1).strip().strip("'\""))
            continue
        if key and line[:1] in (" ", "\t") and isinstance(out.get(key), str) and out[key]:
            # A value wrapped onto the next line. It was dropped, so a `next:`
            # that ran to two lines reached every chat cut off mid-sentence.
            out[key] = out[key] + " " + line.strip()
            continue
        kv = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
        if kv:
            key = kv.group(1)
            rest = kv.group(2).strip()
            # A key with nothing after it opens a block list, or is simply blank
            # (which `intent_attested_by` legitimately is).
            out[key] = _scalar(rest) if rest else ""
    return out


# ------------------------------------------------------------------- loading

def parse_page(path: Path, knowledge_dir: Path) -> dict[str, Any]:
    """One page: frontmatter, its rules, and where it came from."""
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    rules = [
        {"rule_id": rid, "text": _strip_cites(t), "cites": _cites(t)}
        for rid, t in claims._iter_rules(text)
    ]
    return {
        "path": str(path.relative_to(knowledge_dir)),
        "abs_path": str(path),
        "frontmatter": fm,
        "rules": rules,
        "attested": bool(str(fm.get("intent_attested_by") or "").strip()),
    }


def _cites(rule_text: str) -> list[str]:
    return claims._CITE_RE.findall(rule_text)


def _strip_cites(rule_text: str) -> str:
    return claims._CITE_RE.sub("", rule_text).strip()


# The page/not-a-page discriminator lives in claims.py, which is lower level, so
# the ledger and the index cannot drift apart about what counts as content --
# they did, and the ledger indexed template example rules as real claims.
NON_CONTENT_DIRS = claims.NON_CONTENT_DIRS


def is_page(path: Path, knowledge_dir: Path) -> bool:
    """A content page, as opposed to a template, a catalogue, or a README."""
    return claims.is_content_page(path, knowledge_dir)


def load_pages(knowledge_dir: Path) -> list[dict[str, Any]]:
    """Every content page under a knowledge repository."""
    if not knowledge_dir.exists():
        return []
    out = []
    for p in sorted(knowledge_dir.rglob("*.md")):
        if not is_page(p, knowledge_dir):
            continue
        try:
            out.append(parse_page(p, knowledge_dir))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def skipped_files(knowledge_dir: Path) -> list[str]:
    """Markdown that was not indexed, so the exclusion is never silent."""
    if not knowledge_dir.exists():
        return []
    return [str(p.relative_to(knowledge_dir))
            for p in sorted(knowledge_dir.rglob("*.md"))
            if not is_page(p, knowledge_dir)]


# ---------------------------------------------------------------- footprint

def footprint_of(page: dict[str, Any]) -> list[str]:
    fp = page["frontmatter"].get("footprint")
    if isinstance(fp, list):
        return [str(x) for x in fp if str(x).strip()]
    if isinstance(fp, str) and fp.strip():
        return [fp.strip()]
    return []


def resolve_footprint(globs: list[str], source_root: Path) -> dict[str, list[str]]:
    """Which footprint entries actually match files, and which match nothing.

    Path existence is the language-neutral floor: it holds for TypeScript,
    Rust, or anything else. Symbol-level drift detection is a stronger check
    that only `structure.py` can do, and only for Python.
    """
    hit, miss = [], []
    for g in globs:
        g = g.strip()
        if not g:
            continue
        # A bare directory is treated as everything under it, which is how a
        # Peregrine `owns` glob reads too.
        if (source_root / g).is_dir():
            matched = any((source_root / g).rglob("*"))
        else:
            try:
                matched = any(source_root.glob(g))
            except (ValueError, OSError):
                matched = False
        (hit if matched else miss).append(g)
    return {"resolved": hit, "unresolved": miss}


def _overlaps(a: str, b: str) -> bool:
    """Conservative glob overlap: identical, or one is a prefix directory of the
    other. Full glob intersection is undecidable in general, so this catches the
    real-world case (`modules/billing/**` vs `modules/billing/schema.ts`) and
    stays quiet otherwise rather than guessing."""
    pa = a.rstrip("/").replace("/**", "").replace("**", "").rstrip("/*").rstrip("/")
    pb = b.rstrip("/").replace("/**", "").replace("**", "").rstrip("/*").rstrip("/")
    if not pa or not pb:
        return False
    if pa == pb:
        return True
    return pa.startswith(pb + "/") or pb.startswith(pa + "/")


# --------------------------------------------------------------- validation

def validate(pages: list[dict[str, Any]], source_root: Path | None = None) -> list[dict[str, Any]]:
    """Findings about a page set. `severity: error` bars a page from scoping work.

    An uncited rule is deliberately advisory, not an error: the Kit calls those
    the honest backlog of statements nothing can falsify, and refusing them
    would push authors toward inventing citations.
    """
    root = source_root or REPO_ROOT
    findings: list[dict[str, Any]] = []

    def add(page, severity, code, detail):
        findings.append({"page": page["path"], "page_id": page["frontmatter"].get("id", ""),
                         "severity": severity, "code": code, "detail": detail})

    for page in pages:
        fm = page["frontmatter"]
        for field in REQUIRED_FIELDS:
            if field not in fm or (fm[field] == "" and field not in ("aliases", "related")):
                add(page, "error", "missing_field", f"required frontmatter `{field}` is absent or blank")
        if str(fm.get("type", "")) in REVIEW_REQUIRED_TYPES and not str(fm.get("review_by", "")).strip():
            add(page, "error", "missing_review_by",
                f"a `{fm.get('type')}` page requires review_by")

        pin = str(fm.get("verified_against", "")).strip()
        if pin == _PLACEHOLDER:
            add(page, "warn", "draft_pin", "verified_against is still REPLACE_ME; page is a draft")
        elif pin and not _PIN_GRAMMAR.match(pin):
            add(page, "error", "bad_pin", f"verified_against `{pin}` is not <prefix>@<sha>")

        fp = footprint_of(page)
        if not fp:
            add(page, "warn", "no_footprint", "page declares no footprint, so it cannot scope work")
        else:
            r = resolve_footprint(fp, root)
            for g in r["unresolved"]:
                add(page, "error", "footprint_unresolved",
                    f"footprint `{g}` matches no file under {root}")

        for rule in page["rules"]:
            if not rule["cites"]:
                add(page, "info", "uncited_rule",
                    f"{rule['rule_id']} cites no symbol, so nothing can falsify it")

    # Overlap is cross-page, and only matters inside one area: two areas owning
    # neighbouring paths is normal, two pages in one area is a collision waiting
    # to happen when both become units in the same wave.
    by_area: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        by_area.setdefault(str(page["frontmatter"].get("area", "")), []).append(page)
    for area, group in by_area.items():
        for i, pa in enumerate(group):
            for pb in group[i + 1:]:
                for ga in footprint_of(pa):
                    for gb in footprint_of(pb):
                        if _overlaps(ga, gb):
                            add(pa, "error", "footprint_overlap",
                                f"`{ga}` overlaps `{gb}` in {pb['path']} (area {area})")
    return findings


def blocking(findings: list[dict[str, Any]]) -> set[str]:
    """Page paths that may not scope work."""
    return {f["page"] for f in findings if f["severity"] == "error"}


# ------------------------------------------------------------- node conversion

def to_node(page: dict[str, Any], gate: str = "") -> dict[str, Any]:
    """A page in the node shape `cli.py` already routes over.

    `anchors` carries only rule citations, because those are real
    `file::symbol` addresses the existing helpers can split. Footprint globs go
    in their own field -- they are territory, not addresses.
    """
    fm = page["frontmatter"]
    pid = str(fm.get("id") or Path(page["path"]).stem)
    aliases = fm.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases] if aliases.strip() else []
    related = fm.get("related") or []
    if isinstance(related, str):
        related = [related] if related.strip() else []

    signature = list(dict.fromkeys(
        [str(a) for a in aliases]
        + [w for w in re.split(r"[^A-Za-z0-9]+", pid) if len(w) > 1]
        + [str(fm.get("area", ""))]
    ))
    # One anchor per symbol, not per citation: several rules commonly cite the
    # same function, and a card that lists it three times reads as three addresses.
    cited: dict[str, list[str]] = {}
    for rule in page["rules"]:
        for sid in rule["cites"]:
            cited.setdefault(sid, []).append(rule["rule_id"])
    anchors = [{"symbol_id": sid, "role": "cited_by:" + ",".join(rids)}
               for sid, rids in cited.items()]
    return {
        "node_id": pid,
        "responsibility": str(fm.get("title") or fm.get("id") or pid),
        "district": str(fm.get("area", "")),
        "lexical_signature": [s for s in signature if s],
        "anchors": anchors,
        "footprint": footprint_of(page),
        "consumers": [str(r) for r in related],
        "tests": [gate] if gate else [],
        "arrive_when": [r["text"][:160] for r in page["rules"][:6]],
        "page": page["path"],
        "verified_against": str(fm.get("verified_against", "")),
        "attested": page["attested"],
        "rule_ids": [r["rule_id"] for r in page["rules"]],
    }


def build_map(knowledge_dir: Path, gates: dict[str, str] | None = None,
              source_root: Path | None = None) -> dict[str, Any]:
    """The page map, in the same envelope build_map.py writes."""
    gates = gates or {}
    pages = load_pages(knowledge_dir)
    findings = validate(pages, source_root)
    blocked = blocking(findings)
    nodes = []
    for page in pages:
        node = to_node(page, gate=gates.get(str(page["frontmatter"].get("area", "")), ""))
        node["scopes_work"] = page["path"] not in blocked
        nodes.append(node)
    return {
        "map_id": "knowledge_v1",
        "name": "Knowledge pages",
        "scope": str(knowledge_dir),
        "generated_by": "anthill/knowledge/pages.py",
        "built_at_commit": claims.head_commit(),
        "principles": [
            "A node is a knowledge page, so the index is language-neutral.",
            "A page scopes work only while its evidence and footprint verify.",
            "Intent is attested by a human; the map never sets that field.",
        ],
        "node_count": len(nodes),
        "blocked_count": sum(1 for n in nodes if not n["scopes_work"]),
        "nodes": nodes,
    }
