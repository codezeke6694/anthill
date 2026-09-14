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
    1   an audit REFUSES it -- a real finding, and the unit's problem
    2   usage error
    3   not reviewed yet: missing, stale, or unpinned

3 is separate from 1 on purpose. A refusal is the unit's fault and should cost
it an attempt. "Nobody has audited this at the current state" is a coordination
gap between builder and auditor, and charging the unit for it is how a unit
whose 13 tests all passed got escalated and abandoned -- observed, on the first
real sprint.
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

EXIT_REFUSED = 1
EXIT_NOT_REVIEWED = 3

VERDICTS = ("PASS", "FAIL", "PARTIAL", "DEVIATION", "ARCH NOTE")
REFUSING = ("FAIL",)                 # always refuses
CONDITIONAL = ("PARTIAL",)           # refuses when user_visible
RECORDING = ("DEVIATION", "ARCH NOTE", "PASS")   # never refuses


def _loc(f: dict) -> str:
    """`file:line`, or `file`, or nothing -- never `file:None`."""
    if not f.get("file"):
        return ""
    return f" {f['file']}:{f['line']}" if f.get("line") is not None else f" {f['file']}"


def _loc(f: dict) -> str:
    """`file:line`, or `file`, or nothing -- never `file:None`."""
    if not f.get("file"):
        return ""
    return f" {f['file']}:{f['line']}" if f.get("line") is not None else f" {f['file']}"


def work_fingerprint(cwd: Path, base: str = "") -> str:
    """A digest of the work as it stands, not just the commit it sits on.

    Pinning to HEAD alone proved insufficient, found by inspecting a real
    sprint: two audits were recorded against the current commit before any work
    existed, and neither verdict refused. A builder that leaves work
    uncommitted does not move HEAD, so such an audit stays "current" and
    satisfies the gate for code the auditor never saw.
    """
    import hashlib
    import subprocess as _sp

    def _git(args):
        try:
            r = _sp.run(["git", *args], cwd=cwd, capture_output=True,
                        text=True, timeout=30)
        except (OSError, _sp.SubprocessError):
            return ""
        return r.stdout if r.returncode == 0 else ""

    if not base:
        for cand in ("integration", "main", "master"):
            if _git(["rev-parse", "--verify", "--quiet", cand]).strip():
                base = cand
                break
    # The tool's own state is excluded, and this is load-bearing: writing the
    # audit record itself changes `.anthill/`, so including it made every audit
    # stale the instant it was written.
    ignore = [":(exclude).anthill", ":(exclude).claude"]
    parts = [_git(["rev-parse", "HEAD"]).strip()]
    if base:
        parts.append(_git(["diff", f"{base}...HEAD", "--", ".", *ignore]))
    status_out = _git(["status", "--porcelain", "-uall", "--", ".", *ignore])
    parts.append(status_out)
    parts.append(_git(["diff", "--", ".", *ignore]))
    parts.append(_git(["diff", "--cached", "--", ".", *ignore]))

    # `git status` names an untracked file but says nothing about its contents,
    # and `git diff` does not see it at all -- so on a new district, where every
    # file the builder wrote is untracked, editing the work changed nothing in
    # the fingerprint. Their contents are hashed in explicitly.
    for line in (status_out or "").splitlines():
        if not line.startswith("?? "):
            continue
        rel = line[3:].strip().strip('"')
        target = cwd / rel
        try:
            if target.is_dir():
                for f in sorted(target.rglob("*")):
                    if f.is_file():
                        parts.append(f"{f.relative_to(cwd)}:"
                                     + hashlib.sha256(f.read_bytes()).hexdigest())
            elif target.is_file():
                parts.append(f"{rel}:" + hashlib.sha256(target.read_bytes()).hexdigest())
        except OSError:
            parts.append(f"{rel}:<unreadable>")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def known_units(ctx: _ctx.Context) -> list[str]:
    """Unit ids the current contract declares, so a typo cannot be audited."""
    for name in ("contract.json",):
        p = ctx.contracts_dir / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return [str(u.get("id")) for u in (data.get("units") or [])]
    return []


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
           commit: str = "", cwd: Path | None = None,
           allow_unknown: bool = False) -> dict:
    """Write an auditor's findings. Called by the auditor, never by the builder.

    `commit` is captured here rather than trusted from the caller: an auditor
    that could name the commit it audited could name a different one.
    """
    # An audit for a unit no contract declares is an audit of nothing. Observed:
    # a real session recorded `platform.spec`, which was not on its board.
    known = known_units(ctx)
    if known and unit not in known and not allow_unknown:
        raise SystemExit(
            f"anthill: {unit!r} is not a unit on the current contract.\n"
            f"  Units: {', '.join(known)}\n"
            f"  If this is deliberate, pass --allow-unknown.")
    where = cwd or ctx.root
    commit = commit or head_commit(where)
    work = work_fingerprint(where)
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
        "work_fingerprint": work,
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
                EXIT_NOT_REVIEWED if required else 0)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ({"unit": unit, "verdict": "unreadable", "reason": str(exc)}, 1)

    where = cwd or ctx.root
    live = head_commit(where)
    recorded = str(rec.get("commit", ""))
    if live and recorded and live != recorded:
        return ({"unit": unit, "verdict": "stale",
                 "audited_commit": recorded, "head": live,
                 "reason": "the audit examined a different commit than the one "
                           "about to close",
                 "next": "re-audit at the current commit"},
                EXIT_NOT_REVIEWED if required else 0)

    # The commit can be identical while the work has changed -- uncommitted
    # edits do not move HEAD. The content pin is the one that actually binds.
    rec_work = str(rec.get("work_fingerprint", ""))
    live_work = work_fingerprint(where)
    if not rec_work:
        return ({"unit": unit, "verdict": "unpinned",
                 "reason": "this audit carries no work fingerprint, so there is "
                           "no way to tell what it examined",
                 "next": "re-audit; audits recorded before this check existed "
                         "cannot be trusted"},
                EXIT_NOT_REVIEWED if required else 0)
    if rec_work != live_work:
        return ({"unit": unit, "verdict": "stale",
                 "audited_work": rec_work, "live_work": live_work,
                 "reason": "the work has changed since it was audited (the commit "
                           "is the same, the content is not)",
                 "next": "re-audit the current state"},
                EXIT_NOT_REVIEWED if required else 0)

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
    return out, (EXIT_REFUSED if refuse else 0)


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
