#!/usr/bin/env python3
"""Blueprint freshness as a gate condition.

`cli.py verify` already answers "which recorded statements about this code no
longer hold" -- but it prints JSON and exits 0, so nothing can act on it. The
orchestrator closes a unit on one fact only, its gate's exit code, which means a
digger can cut a new chamber, pass its tests, and never draw the tunnel. The
code grows; the blueprint rots; nothing objects.

This turns the report into a refusal. Composed into a gate:

    python3 -m pytest -q tests/foo.py && python3 scripts/blueprint_fresh.py

"you cannot close a chamber without drawing it" stops being an instruction in
the brief and becomes the same kind of fact as a failing test.

SCOPING -- why the default is not the whole ledger
--------------------------------------------------
The maps cover the entire tree, so an unscoped check fails unit A for drift that
unit B caused. The gate runs with cwd set to the unit's own worktree, and gets no
environment (only `setup_cmd` does), so `owns` cannot be read from the outside.
It does not need to be: the worktree's diff against the integration branch *is*
this unit's footprint. Scope to that and blame lands where it belongs.

This is safe against the "my change broke someone else's claim" case because of
how drift is grade: a change that alters a symbol's caller set elsewhere scores
`recontextualized` (severity 1), which sits below the refusal threshold by
design. What fails a unit is drift in a symbol it actually touched.

EXIT CODES
    0   blueprint holds for everything in scope
    1   stale claims in scope (or coverage below --min-coverage)
    2   usage / environment error
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from anthill import context as _ctx
REPO_ROOT = _ctx.current().root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from anthill.knowledge import claims, pages, readiness
    from anthill.orchestrate import orchestrator
except ImportError as exc:                                    # pragma: no cover
    print(f"blueprint: cannot import anthill from {REPO_ROOT}: {exc}",
          file=sys.stderr)
    raise SystemExit(2)

DEFAULT_THRESHOLD = 2   # matches claims.summarize()'s `needs_review`: >= 2
# What each drift kind means for the digger, in the terms of the thing to fix.
REMEDY = {
    "missing": "the symbol is gone -- correct the citation or delete the claim",
    "moved": "same name, new file -- re-point the citation at its new address",
    "reshaped": "the signature moved -- the recorded contract is now wrong",
    "rewired": "its callee set changed -- it does other things now; re-read the rule",
    "recontextualized": "its callers moved -- impact has shifted",
}


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=30)


def _is_repo(cwd: Path) -> bool:
    r = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    return r.returncode == 0 and r.stdout.strip() == "true"


def _detect_base(cwd: Path, given: str) -> str:
    """The ref to diff against. A named base that does not resolve is an error
    worth reporting rather than silently widening the check to everything."""
    if given:
        return given
    # Set by `work gate`: the commit the unit was claimed at. The only honest
    # scope for "what this unit changed", and the branch fallbacks below are
    # what blamed a unit for 404 files of drift it never touched.
    import os as _os
    unit_base = _os.environ.get("ANTHILL_UNIT_BASE", "").strip()
    if unit_base and _git(["rev-parse", "--verify", "--quiet", unit_base], cwd).returncode == 0:
        return unit_base
    for cand in ("integration", "main", "master"):
        if _git(["rev-parse", "--verify", "--quiet", cand], cwd).returncode == 0:
            return cand
    return ""


def in_scope(symbol_id: str, changed: set[str]) -> bool:
    """A claim is this unit's business when it cites a file the unit changed."""
    return symbol_id.split("::", 1)[0] in changed if "::" in symbol_id else False


def is_product_source(rel: str, include: list[str], toplevel: list[str],
                      exclude: set[str]) -> bool:
    """Is this a file the project's intent should describe?

    Three kinds of changed file are deliberately exempt, because demanding a
    page for them would make the check impossible to satisfy rather than useful:
    a test explains itself, the knowledge page cannot be its own subject, and
    anything outside the configured source set is not product code.
    """
    parts = set(Path(rel).parts)
    if exclude & parts:
        return False
    if Path(rel).suffix not in {".py"}:
        return False          # only Python is citable today; see README limits
    head = Path(rel).parts[0] if Path(rel).parts else ""
    return head in set(include) or rel in set(toplevel)


def unexplained(changed: set[str], knowledge_dir: Path, source_root: Path,
                include: list[str], toplevel: list[str],
                exclude: set[str]) -> list[str]:
    """Changed product source that no page's footprint covers and no rule cites.

    This is the half `--require-claims` cannot reach. A stale claim means a
    recorded statement went wrong; a *missing* one means nothing was ever
    recorded, so there is nothing to go stale and the gate would pass an agent
    that added six files and explained none of them.
    """
    candidates = {c for c in changed
                  if is_product_source(c, include, toplevel, exclude)}
    if not candidates or not knowledge_dir.exists():
        return sorted(candidates)

    explained: set[str] = set()
    for page in pages.load_pages(knowledge_dir):
        for glob in pages.footprint_of(page):
            try:
                for q in source_root.glob(glob):
                    if q.is_file():
                        explained.add(str(q.relative_to(source_root)))
            except (ValueError, OSError):
                continue
        for rule in page["rules"]:
            for sid in rule["cites"]:
                if "::" in sid:
                    explained.add(sid.split("::", 1)[0])
    return sorted(candidates - explained)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse to close a unit whose blueprint no longer matches the code.")
    ap.add_argument("--knowledge", default="",
                    help="Knowledge dir (default: the install's knowledge dir)")
    ap.add_argument("--contract", default="",
                    help="Contract path; adds execution-plane ownership claims")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help=f"Minimum drift severity that refuses (default {DEFAULT_THRESHOLD}: "
                         "missing=4 moved=3 reshaped=3 rewired=2 recontextualized=1)")
    ap.add_argument("--all", action="store_true",
                    help="Check the whole ledger, not just what this worktree changed")
    ap.add_argument("--base", default="",
                    help="Ref to diff against for scoping (default: integration/main/master)")
    ap.add_argument("--min-coverage", type=int, default=-1,
                    help="Also refuse if the share of mapped files with a page is below this")
    ap.add_argument("--require-page", action="store_true",
                    help="Refuse when changed product source is covered by no "
                         "page -- catches MISSING intent, which a staleness "
                         "check cannot see")
    ap.add_argument("--require-claims", action="store_true",
                    help="Refuse when the ledger is empty -- an undrawn blueprint "
                         "is not a fresh one")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args(argv)

    cwd = Path.cwd()
    kd = Path(args.knowledge).expanduser() if args.knowledge else claims.KNOWLEDGE_DIR

    # ---------------------------------------------------------------- ledger
    ledger = list(claims.from_maps())
    if kd.exists():
        ledger += claims.from_knowledge(kd)
    if args.contract:
        cpath = Path(args.contract).expanduser()
        if not cpath.exists():
            print(f"blueprint: no contract at {cpath}", file=sys.stderr)
            return 2
        ledger += claims.from_contract(cpath)

    # ---------------------------------------------------------------- scope
    changed: set[str] = set()
    scope_note = "whole ledger (--all)"
    if not args.all:
        if not _is_repo(cwd):
            scope_note = "whole ledger (not a git repository, cannot scope to a diff)"
            args.all = True
        else:
            base = _detect_base(cwd, args.base)
            if not base:
                scope_note = "whole ledger (no integration/main/master to diff against)"
                args.all = True
            elif _git(["rev-parse", "--verify", "--quiet", base], cwd).returncode != 0:
                print(f"blueprint: base ref `{base}` does not resolve", file=sys.stderr)
                return 2
            else:
                changed = set(orchestrator.changed_files(cwd, base))
                scope_note = f"{len(changed)} file(s) changed vs {base}"

    # ---------------------------------------------------------------- verify
    results = claims.verify(ledger)
    stale = [r for r in results if r.get("severity", 0) >= args.threshold]
    if not args.all:
        stale = [r for r in stale if in_scope(r.get("symbol_id", ""), changed)]

    report: dict = {
        "verdict": "stale" if stale else "holds",
        "scope": scope_note,
        "threshold": args.threshold,
        "total_claims": len(results),
        "checked": len(results) if args.all else
                   sum(1 for r in results if in_scope(r.get("symbol_id", ""), changed)),
        "stale_count": len(stale),
        "stale": [{"kind": r.get("kind"), "claim": r.get("claim_id"),
                   "symbol": r.get("symbol_id"), "drift": r.get("drift"),
                   "severity": r.get("severity"),
                   "remedy": REMEDY.get(r.get("drift", ""), ""),
                   "detail": r.get("detail", ""),
                   "relocation": r.get("relocation") or []} for r in stale],
    }

    failed = bool(stale)

    # An empty ledger is the quiet failure this whole script exists to stop:
    # nothing recorded means nothing can be found stale.
    if not ledger:
        report["warning"] = ("the ledger is empty -- no map anchors and no page rules. "
                             "Nothing is being checked. Run build_map.py and author a page.")
        if args.require_claims:
            report["verdict"] = "no-blueprint"
            failed = True

    # ------------------------------------------------------------- coverage
    if args.min_coverage >= 0:
        if not kd.exists():
            print(f"blueprint: --min-coverage needs a knowledge dir; {kd} is absent",
                  file=sys.stderr)
            return 2
        cov = readiness.coverage(kd, REPO_ROOT)
        report["coverage"] = {
            "share_explained": cov["share_explained"],
            "floor": args.min_coverage,
            "files_with_no_page": cov["files_with_no_page"],
            "largest_unexplained": [r["file"] for r in cov["largest_unexplained"][:5]],
        }
        if cov["share_explained"] < args.min_coverage:
            report["verdict"] = "under-covered"
            failed = True

    # ------------------------------------------------------- missing intent
    if args.require_page:
        conf = _ctx.current()
        inc, top, exc = conf.source_roots()
        missing = unexplained(changed if not args.all else set(),
                              kd, conf.root, inc, top, exc)
        if args.all:
            report["undescribed"] = {
                "checked": 0,
                "note": "--require-page needs a diff to scope to; it is skipped "
                        "under --all because 'every unexplained file in the "
                        "repository' is a backlog, not a gate",
            }
        else:
            report["undescribed"] = {"files": missing, "count": len(missing)}
            if missing:
                report["verdict"] = "undescribed"
                failed = True

    # ---------------------------------------------------------------- output
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"blueprint: {report['verdict']}  "
              f"[{report['checked']}/{report['total_claims']} claims checked, "
              f"scope: {scope_note}]")
        if w := report.get("warning"):
            print(f"  warning: {w}")
        for s in report["stale"]:
            print(f"  STALE {s['drift']:18s} {s['symbol']}")
            print(f"        {s['remedy']}")
            if s["detail"]:
                print(f"        {s['detail']}")
            for alt in s["relocation"][:3]:
                print(f"        candidate: {alt}")
        if u := report.get("undescribed"):
            if u.get("note"):
                print(f"  {u['note']}")
            for f in u.get("files") or []:
                print(f"  UNDESCRIBED {f}")
            if u.get("files"):
                print("        no page's footprint covers this and no rule cites it")
        if c := report.get("coverage"):
            print(f"  coverage: {c['share_explained']}% explained "
                  f"(floor {c['floor']}%), {c['files_with_no_page']} file(s) with no page")
            for f in c["largest_unexplained"]:
                print(f"        unexplained: {f}")
        if failed:
            # The remedy differs by verdict, and printing all of them would send
            # someone re-pinning a page when what is missing is the page.
            remedy = {
                "undescribed": "Write a page whose footprint covers these files, "
                               "then re-run the gate.",
                "under-covered": "Raise coverage, or lower --min-coverage if the "
                                 "floor is wrong for this stage.",
                "no-blueprint": "Nothing is recorded yet. Draw the map with "
                                "`anthill integrate` and author a page.",
            }.get(report["verdict"],
                  "Re-pin the page, correct the rule, or redraw the map with "
                  "`anthill integrate` -- then re-run the gate.")
            print(f"\n  A unit does not close on a blueprint that no longer "
                  f"matches the code.\n  {remedy}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
