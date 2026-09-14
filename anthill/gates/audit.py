#!/usr/bin/env python3
"""An audit becomes a gate condition — without pretending to be proof.

The orchestrator closes a unit on one fact, its gate's exit code. An auditor
subagent produces prose. Bridging them naively -- "auditor says PASS, so exit 0"
-- would mint a fourth authority the model *can* forge, because it is model
output either way, and dress it in the costume of the three it cannot.

So this gate is deliberately asymmetric:

    an audit may REFUSE a unit.
    an audit may never, by itself, PASS one.

Tests remain the only positive proof. What this adds is a second filter that can
say "not yet", plus a record a human can check in ten seconds.

Verdict routing is the mother product's, which had five outcomes rather than a
boolean because "wrong" and "different from what I would have written" deserve
different consequences:

    FAIL        the work is wrong                   -> refuse, rework
    PARTIAL     incomplete                          -> refuse only if user-visible
    DEVIATION   defensible, not what was specified   -> record, do not refuse
    ARCH NOTE   raises a design question             -> record, escalate to a human
    PASS        nothing found                        -> does not refuse

STALENESS -- the reason a verdict is pinned
-------------------------------------------
An audit is a statement about a tree, and trees move. A verdict recorded two
commits ago says nothing about the code the gate is about to close, so the audit
carries the commit it examined and this gate refuses when that no longer matches
HEAD. Same rule as a knowledge page's `verified_against`, same reason.

EXIT CODES
    0   no audit refuses this unit
    1   an audit refuses it (or is missing / stale while required)
    2   usage error
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

VERDICTS = ("PASS", "FAIL", "PARTIAL", "DEVIATION", "ARCH NOTE")
REFUSING = ("FAIL",)                 # always refuses
CONDITIONAL = ("PARTIAL",)           # refuses when user_visible
RECORDING = ("DEVIATION", "ARCH NOTE", "PASS")   # never refuses


def _loc(f: dict) -> str:
    """`file:line`, or `file`, or nothing -- never `file:None`."""
    if not f.get("file"):
        return ""
    return f" {f['file']}:{f['line']}" if f.get("line") is not None else f" {f['file']}"


def head_commit(cwd: Path) -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def audit_path(ctx: _ctx.Context, unit: str) -> Path:
    return ctx.audits_dir / f"{unit.replace('/', '_')}.json"


def record(ctx: _ctx.Context, unit: str, auditor: str, findings: list[dict],
           commit: str = "", cwd: Path | None = None) -> dict:
    """Write an auditor's findings. Called by the auditor, never by the builder.

    `commit` is captured here rather than trusted from the caller: an auditor
    that could name the commit it audited could name a different one.
    """
    commit = commit or head_commit(cwd or ctx.root)
    clean: list[dict] = []
    for f in findings:
        v = str(f.get("verdict", "")).upper().strip()
        if v not in VERDICTS:
            raise ValueError(f"unknown verdict {v!r}; expected one of {VERDICTS}")
        clean.append({
            "verdict": v,
            "detail": str(f.get("detail", "")).strip(),
            "file": str(f.get("file", "")).strip(),
            "line": f.get("line"),
            "user_visible": bool(f.get("user_visible", False)),
        })
    rec = {
        "unit": unit,
        "auditor": auditor,
        "commit": commit,
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "findings": clean,
        "note": "An audit can refuse a unit. It cannot, alone, pass one.",
    }
    p = audit_path(ctx, unit)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return rec


def assess(ctx: _ctx.Context, unit: str, cwd: Path | None = None,
           required: bool | None = None) -> tuple[dict, int]:
    """Does any recorded finding refuse this unit?"""
    if required is None:
        required = bool((ctx.config.get("audit") or {}).get("required", True))
    p = audit_path(ctx, unit)
    if not p.exists():
        return ({"unit": unit, "verdict": "missing",
                 "reason": f"no audit at {p}",
                 "next": "an auditor must review this unit before it can close"},
                1 if required else 0)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ({"unit": unit, "verdict": "unreadable", "reason": str(exc)}, 1)

    live = head_commit(cwd or ctx.root)
    recorded = str(rec.get("commit", ""))
    if live and recorded and live != recorded:
        return ({"unit": unit, "verdict": "stale",
                 "audited_commit": recorded, "head": live,
                 "reason": "the audit examined a different commit than the one "
                           "about to close",
                 "next": "re-audit at the current commit"},
                1 if required else 0)

    findings = rec.get("findings") or []
    refuse = [f for f in findings if f.get("verdict") in REFUSING]
    refuse += [f for f in findings
               if f.get("verdict") in CONDITIONAL and f.get("user_visible")]
    refuse_ids = {id(f) for f in refuse}
    noted = [f for f in findings
             if f.get("verdict") != "PASS" and id(f) not in refuse_ids]
    escalate_kinds = tuple((ctx.config.get("audit") or {}).get(
        "escalate_verdicts") or ["ARCH NOTE"])
    escalate = [f for f in findings if f.get("verdict") in escalate_kinds]

    out = {
        "unit": unit,
        "verdict": "refused" if refuse else "not refused",
        "auditor": rec.get("auditor", ""),
        "commit": recorded,
        "counts": {v: sum(1 for f in findings if f.get("verdict") == v)
                   for v in VERDICTS if any(f.get("verdict") == v for f in findings)},
        "refusing": refuse,
        "recorded_only": noted,
        "escalate_to_human": escalate,
    }
    if escalate:
        out["human_action"] = (f"{len(escalate)} finding(s) need an owner's "
                               "decision; they do not block this unit")
    return out, (1 if refuse else 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a unit whose audit refuses it. Never passes one on its own.")
    ap.add_argument("unit", help="Unit id to check")
    ap.add_argument("--project", default="", help="Target project root")
    ap.add_argument("--optional", action="store_true",
                    help="A missing or stale audit does not refuse (overrides config)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root} (found via {ctx.origin})",
              file=sys.stderr)
        return 2

    report, code = assess(ctx, args.unit, cwd=Path.cwd(),
                          required=False if args.optional else None)
    if args.json:
        print(json.dumps(report, indent=2))
        return code

    print(f"audit: {report.get('verdict')}  [{args.unit}]")
    if r := report.get("reason"):
        print(f"  {r}")
    for f in report.get("refusing") or []:
        print(f"  REFUSED {f['verdict']}{_loc(f)}\n          {f['detail']}")
    for f in report.get("recorded_only") or []:
        print(f"  noted   {f['verdict']}{_loc(f)}\n          {f['detail']}")
    if ha := report.get("human_action"):
        print(f"  → {ha}")
    if n := report.get("next"):
        print(f"  next: {n}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
