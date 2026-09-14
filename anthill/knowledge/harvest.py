#!/usr/bin/env python3
"""Escalations become knowledge.

An escalation is the rawest intent the system produces: the moment a contract or
a rule turned out to be wrong about the code. Today it dies in
`.peregrine/escalations/`, which is measurable -- `trap.fx.md` records
`attempts: 2` and `exit: 1` with an **empty** `## Failing output` block, and went
invisible to the board after a contract swap.

This turns each one into a draft page. The draft is deliberately incomplete: the
agent may write what happened, but `verified_against` stays the honest
REPLACE_ME placeholder until a human inspects code at a real commit, and
`intent_attested_by` is never written here at all.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_TITLE = re.compile(r"^#\s*ESCALATION\s*[—-]\s*(\S+)", re.M)
_FIELD = re.compile(r"^-\s*([a-z_]+):\s*(.*)$", re.M)
_OUTPUT = re.compile(r"##\s*Failing output\s*\n+```(.*?)```", re.S)


def parse_escalation(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    title = _TITLE.search(text)
    fields = {k: v.strip().strip("`") for k, v in _FIELD.findall(text)}
    out = _OUTPUT.search(text)
    failing = (out.group(1).strip() if out else "")
    return {
        "unit_id": title.group(1) if title else path.stem,
        "attempts": fields.get("attempts", ""),
        "gate": fields.get("gate", ""),
        "exit": fields.get("exit", ""),
        "at": fields.get("at", ""),
        "worktree": fields.get("worktree", ""),
        "failing_output": failing,
        "evidence_missing": not failing,
        "source_file": str(path),
    }


def _unit_index(contract_path: Path | None) -> dict[str, dict[str, Any]]:
    """Units by id, so a harvested page inherits the footprint for free: the
    unit's `owns` globs are exactly the files the page governs."""
    if not contract_path or not contract_path.exists():
        return {}
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {u["id"]: u for u in data.get("units", []) if u.get("id")}


def to_page(esc: dict[str, Any], unit: dict[str, Any] | None,
            area: str = "", evidence_prefix: str = "src") -> str:
    """One draft incident page.

    `type: incident` is chosen because the Kit requires `review_by` only on
    module and architecture pages -- inventing a review date for a page nobody
    has verified yet would be fabricating exactly the metadata the framework
    exists to keep honest.
    """
    unit = unit or {}
    uid = esc["unit_id"]
    area = area or (uid.split(".", 1)[0] if "." in uid else uid)
    owns = unit.get("owns") or []
    aliases = sorted({w for w in re.split(r"[^A-Za-z0-9]+", uid) if len(w) > 1})

    fm = [
        "---",
        f"id: escalation-{uid}",
        "type: incident",
        f"title: Escalation — {uid}",
        f"area: {area}",
        "owners: []",
        "classification: internal",
        "criticality: standard",
        f"aliases: [{', '.join(aliases)}]",
        "related: []",
        "verified_against: REPLACE_ME",
        "intent_attested_by:",
    ]
    if owns:
        fm.append("footprint:")
        fm += [f"  - {g}" for g in owns]
    fm.append("---")

    body = [
        "",
        f"# Escalation — {uid}",
        "",
        "## What happened",
        "",
        f"Unit `{uid}` stopped after {esc['attempts'] or 'an unrecorded number of'} "
        f"gate attempts with exit `{esc['exit'] or 'unknown'}`"
        + (f" at {esc['at']}." if esc["at"] else "."),
        "",
        f"Gate: `{esc['gate'] or 'not recorded'}`",
        "",
        "## Evidence",
        "",
    ]
    if esc["evidence_missing"]:
        body += [
            "**The failing output was not captured.** The escalation file records the",
            "exit code but its output block is empty, so the cause cannot be read from",
            "the artifact and must be reproduced by running the gate again.",
        ]
    else:
        body += ["```", esc["failing_output"][:4000], "```"]
    body += [
        "",
        "## Rules",
        "",
        "_No BR- rule yet. State one only once the cause is confirmed against code",
        f"at a real commit, then replace `REPLACE_ME` with `{evidence_prefix}@<sha>`._",
        "",
        "## History",
        "",
        f"- Drafted from `{Path(esc['source_file']).name}` by anthill/knowledge/harvest.py.",
        "",
    ]
    return "\n".join(fm + body)


def harvest(escalations_dir: Path, out_dir: Path, contract_path: Path | None = None,
            evidence_prefix: str = "src", write: bool = False) -> dict[str, Any]:
    """Draft one page per escalation. Never overwrites an existing page."""
    units = _unit_index(contract_path)
    if not escalations_dir.exists():
        return {"escalations": 0, "drafted": [], "skipped": [],
                "note": f"no escalations directory at {escalations_dir}"}
    drafted, skipped = [], []
    for path in sorted(escalations_dir.glob("*.md")):
        esc = parse_escalation(path)
        target = out_dir / f"escalation-{esc['unit_id']}.md"
        if target.exists():
            skipped.append({"page": str(target), "why": "already exists"})
            continue
        text = to_page(esc, units.get(esc["unit_id"]), evidence_prefix=evidence_prefix)
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        drafted.append({
            "page": str(target),
            "unit_id": esc["unit_id"],
            "footprint_inherited": bool((units.get(esc["unit_id"]) or {}).get("owns")),
            "evidence_missing": esc["evidence_missing"],
            "written": write,
        })
    return {"escalations": len(drafted) + len(skipped), "drafted": drafted,
            "skipped": skipped,
            "note": "drafts are unverified: REPLACE_ME must be replaced by a human"}
