#!/usr/bin/env python3
"""One entry point. `anthill <command>`.

The navigation and knowledge commands already had a working argparse surface, so
this delegates to it rather than reimplementing eighteen subcommands. What is
added here is the plane the ported code never had: install, sprint, audit, and
the gates.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

# Commands the ported router already implements, dispatched to it verbatim.
ROUTER_COMMANDS = {
    "start", "observe", "card", "nodes", "impact", "grep", "read-slice",
    "pin", "verify", "pages", "index-pages", "eval-routing", "coverage",
    "readiness", "board", "harvest", "kb", "work",
}


def _out(data) -> None:
    print(json.dumps(data, indent=2))


def _ctx_or_die(args) -> _ctx.Context:
    ctx = _ctx.resolve(getattr(args, "project", "") or None)
    if not ctx.installed:
        raise SystemExit(
            f"anthill: not installed in {ctx.root} (found via {ctx.origin}).\n"
            f"  Run: anthill install --name \"<project>\"")
    return ctx


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Delegate first, so the ported surface keeps its exact flags and output.
    if argv and argv[0] in ROUTER_COMMANDS:
        from anthill.navigate import router
        return router.main(argv) or 0
    if argv and argv[0] == "map" and len(argv) > 1 and argv[1] == "build":
        from anthill.navigate import build_map
        return build_map.main(argv[2:]) or 0
    if argv and argv[0] == "skill":
        from anthill import skills
        return skills.main(argv[1:])
    if argv and argv[0] == "roles":
        from anthill import roles
        return roles.main(argv[1:])
    if argv and argv[0] == "onboard":
        from anthill import onboard
        return onboard.main(argv[1:])
    if argv and argv[0] == "integrate":
        from anthill import integrate
        return integrate.main(argv[1:])
    if argv and argv[0] == "blueprint":
        from anthill.gates import blueprint
        return blueprint.main(argv[1:])

    ap = argparse.ArgumentParser(
        prog="anthill", description="A development agent system: blueprint, intent, foreman.")
    ap.add_argument("--project", default="", help="Target project root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # -------------------------------------------------------------- install
    ins = sub.add_parser("install", help="Take control of a repository")
    ins.add_argument("--name", default="")
    ins.add_argument("--stack", default="")
    ins.add_argument("--description", default="")
    ins.add_argument("--areas", default="", help="Comma-separated knowledge areas")
    ins.add_argument("--force", action="store_true",
                     help="Overwrite an existing install (never the constitution)")
    ins.add_argument("--exclude", default="",
                     help="Comma-separated directory names to keep out of the "
                          "source set (e.g. a vendored copy of this tool)")
    ins.add_argument("--dry-run", action="store_true")

    st = sub.add_parser("status", help="Where this installation stands")

    # --------------------------------------------------------------- sprint
    sp = sub.add_parser("sprint", help="Plan and report on work (human-facing)")
    sps = sp.add_subparsers(dest="sub", required=True)
    n = sps.add_parser("new"); n.add_argument("name"); n.add_argument("--goal", required=True)
    n.add_argument("--owner", default="")
    a = sps.add_parser("add-unit")
    a.add_argument("area"); a.add_argument("--title", required=True)
    a.add_argument("--owns", required=True, help="Comma-separated paths/globs")
    a.add_argument("--gate", default="", help="Test command that proves this unit")
    a.add_argument("--spec", default=""); a.add_argument("--context", default="")
    a.add_argument("--depends-on", default=""); a.add_argument("--contract", default="")
    a.add_argument("--role", default="builder")
    a.add_argument("--split", action="store_true",
                   help="Emit <area>.spec (owns tests) and <area>.impl (owns code)")
    a.add_argument("--test-owns", default="")
    a.add_argument("--spec-gate", default="",
                   help="Gate for the .spec unit. Defaults to inserting "
                        "--collect-only into a pytest command; supply this for "
                        "any other runner, since the tests must NOT pass yet.")
    c = sps.add_parser("compile", help="Turn the sprint into an enforced contract")
    c.add_argument("--out", default=""); c.add_argument("--base", default="")
    sps.add_parser("status")

    # ---------------------------------------------------------------- audit
    au = sub.add_parser("audit", help="Record and check audit findings")
    aus = au.add_subparsers(dest="sub", required=True)
    ar = aus.add_parser("record")
    ar.add_argument("unit"); ar.add_argument("--auditor", required=True)
    ar.add_argument("--finding", action="append", default=[],
                    help='JSON: {"verdict":"FAIL","detail":"...","file":"x.py","line":4}')
    ac = aus.add_parser("check"); ac.add_argument("unit")
    ac.add_argument("--optional", action="store_true")

    # -------------------------------------------------------------- lessons
    ls = sub.add_parser("lesson", help="Lessons, filed by area so they resurface")
    lss = ls.add_subparsers(dest="sub", required=True)
    lr = lss.add_parser("record"); lr.add_argument("area"); lr.add_argument("lesson")
    lr.add_argument("--unit", default=""); lr.add_argument("--kind", default="lesson")
    lg = lss.add_parser("for"); lg.add_argument("area")

    args = ap.parse_args(argv)

    if args.cmd == "install":
        from anthill import install as inst
        ctx = _ctx.resolve(args.project or None)
        areas = [x.strip() for x in args.areas.split(",") if x.strip()]
        _out(inst.install(ctx, project_name=args.name, stack=args.stack,
                          description=args.description, areas=areas,
                          force=args.force, write=not args.dry_run,
                          exclude=[x.strip() for x in args.exclude.split(",")
                                   if x.strip()]))
        return 0

    if args.cmd == "status":
        ctx = _ctx.resolve(args.project or None)
        from anthill import install as inst
        info = {"root": str(ctx.root), "found_via": ctx.origin,
                "installed": ctx.installed}
        if ctx.installed:
            info.update({
                "project": (ctx.config.get("project") or {}).get("name"),
                "mode": ctx.config.get("installed_mode"),
                "roles": ctx.config.get("roles"),
                "source_dirs": ctx.source_roots()[0],
                "areas": (ctx.config.get("knowledge") or {}).get("areas"),
                "state": str(ctx.state),
            })
        else:
            info["plan"] = inst.plan(ctx)
        _out(info)
        return 0

    if args.cmd == "sprint":
        from anthill.sprint import backlog
        ctx = _ctx_or_die(args)
        if args.sub == "new":
            _out(backlog.new(ctx, args.name, args.goal, args.owner))
        elif args.sub == "add-unit":
            _out(backlog.add_unit(
                ctx, args.area, args.title,
                [x.strip() for x in args.owns.split(",") if x.strip()],
                args.gate, args.spec, args.context,
                [x.strip() for x in args.depends_on.split(",") if x.strip()],
                args.contract, args.role, args.split,
                [x.strip() for x in args.test_owns.split(",") if x.strip()] or None,
                args.spec_gate))
        elif args.sub == "compile":
            _out(backlog.compile_contract(
                ctx, Path(args.out) if args.out else None, args.base))
        else:
            _out(backlog.status(ctx))
        return 0

    if args.cmd == "audit":
        from anthill.gates import audit
        ctx = _ctx_or_die(args)
        if args.sub == "record":
            findings = []
            for raw in args.finding:
                try:
                    findings.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"anthill: --finding is not valid JSON: {exc}")
            _out(audit.record(ctx, args.unit, args.auditor, findings, cwd=Path.cwd()))
            return 0
        return audit.main([args.unit] + (["--optional"] if args.optional else []))

    if args.cmd == "lesson":
        from anthill.sprint import backlog
        ctx = _ctx_or_die(args)
        _out(backlog.record_lesson(ctx, args.area, args.lesson, args.unit, args.kind)
             if args.sub == "record" else backlog.lessons_for(ctx, args.area))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
