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
    "pin", "verify", "pages", "index-pages", "eval-routing", "eval-map", "orient", "where", "coverage",
    "readiness", "board", "harvest", "kb", "work",
}

# Commands dispatched before argparse ever runs, each to its own module. They
# are listed here so `--help` can name them.
#
# It could not, and that was the bug: `anthill --help` advertised five commands
# while every command the agent instructions actually require -- `work`,
# `onboard`, `roles`, `map`, `blueprint` -- appeared in none of them, and an
# unsupported flag printed a third list again. An agent that has lost its
# instructions cannot recover them from `--help`; it has to read the Python.
DELEGATED = [
    ("trail", "What happened here: every command and commit, and any crash"),
    ("note", 'Leave a line for whoever picks this up: "doing X; ruled out Y; next Z"'),
    ("resume", "Pick up where this branch left off: work, next step, notes, commits"),
    ("correction", "Record that a page said something wrong: --page, --was, --now, --why"),
    ("score", "The scorecard: time to first change, messages per commit, what gets used"),
    ("work", "Claim, gate, close and escalate units (the execution loop)"),
    ("onboard", "Fill the charter by interview; the only writer of CONSTITUTION.md"),
    ("roles", "Who is planner, builder and auditor"),
    ("skill", "Reusable instruction, indexed and load-classed"),
    ("map", "Rebuild the structural blueprint (`map build`)"),
    ("blueprint", "Check the blueprint still matches the tree"),
    ("integrate", "Redraw the blueprint after a merge"),
    ("guard", "Pre-commit and pre-push checks (invoked by the hooks)"),
    ("control", "Has a control file drifted from what install wrote?"),
    ("config", "Read or change a setting; the only writer of anthill.config.json"),
    ("tidy", "Stray artefacts that belong to nobody"),
    ("upkeep", "What a change left undone: glossary, knowledge pages, tests"),
    ("survey", "Draw the map and report what Anthill knows (install runs it)"),
    ("ui", "The owner's view on a local page: start | stop | status"),
]

# The ported navigation and knowledge surface. Grouped rather than listed one by
# one: eighteen entries in the top-level help would bury the ten above, which
# are the ones an agent needs every session.
NAVIGATION = sorted(ROUTER_COMMANDS - {"work"})


def _out(data) -> None:
    print(json.dumps(data, indent=2))


def _ctx_or_die(args) -> _ctx.Context:
    ctx = _ctx.resolve(getattr(args, "project", "") or None)
    if not ctx.installed:
        raise SystemExit(
            f"anthill: not installed in {ctx.root} (found via {ctx.origin}).\n"
            f"  Run: anthill install --name \"<project>\"")
    return ctx


# What a newcomer needs before anything else, at the top of `--help`.
#
# Measured: an agent told nothing about Anthill found it through CLAUDE.md,
# then ran `--help` five times to work out which commands to use, never found
# `start`, and avoided others for fear they would change the board. So the
# first thing help says is where to begin and which commands only read.
START_HERE = """\
Starting cold? These only read -- none of them changes anything:

  anthill where                          what is being worked on, what waits on
                                         the owner, what they decided, the traps
  anthill orient                         the codebase on one page: chambers,
                                         how they connect, tests, rules, words
  anthill start "<task, in your words>"  where that task lives: the file, the
                                         line, what a change reaches, its tests
  anthill card <node> --goal "<task>"    the same card for another candidate
  anthill impact <node> --symbol <name>  what a change to one symbol reaches
  anthill work status --repo .           what is on the board, and whose
  anthill ui start --detach              all of the above on a local page

These change state: `work next|gate|done|escalate` (the board),
`map build` (redraws the map -- safe, the post-commit hook runs it anyway),
`install`, `config set`, `onboard` (the owner's).
"""


def main(argv: list[str] | None = None) -> int:
    """Run one command, and write what happened to the trail.

    Every command, the ones the git hooks run included, leaves one line: how
    long it took, its exit code, and whether it crashed. The hooks throw their
    output away so a failure can never cost a commit; before this, that also
    meant a crash was never seen by anyone.
    """
    import time
    import traceback
    from anthill import trail
    argv = list(sys.argv[1:] if argv is None else argv)
    verb = argv[0] if argv else ""
    # Hook calls and notes record their own, richer event; a second
    # "command" line for each owner message would only be noise.
    if verb in ("", "help", "start-here", "trail", "note", "prompt", "correction", "-h", "--help") or "--hook" in argv:
        return _dispatch(argv)
    t0 = time.monotonic()
    rc: int | None = None
    crash = ""
    try:
        rc = _dispatch(argv)
        return rc
    except SystemExit as exc:
        code = exc.code
        rc = code if isinstance(code, int) else (0 if code is None else 1)
        raise
    except KeyboardInterrupt:
        rc = 130                           # Ctrl-C is a stop, not a crash
        raise
    except Exception as exc:               # noqa: BLE001 -- recorded, then re-raised unchanged
        crash = "".join(traceback.format_exception_only(type(exc), exc)).strip()[-300:]
        raise
    finally:
        trail.record("command", verb=verb, args=trail.command_args(argv),
                     rc=rc, crashed=crash or None,
                     secs=round(time.monotonic() - t0, 2))


def _dispatch(argv: list[str]) -> int:
    if not argv or argv[0] in ("help", "start-here"):
        # `anthill help` is what a person types; it used to be an argparse
        # error, and an agent that got one concluded the command it was
        # looking for did not exist.
        print(START_HERE, end="")
        print("\nEvery command: anthill --help")
        return 0

    # Delegate first, so the ported surface keeps its exact flags and output.
    if argv and argv[0] in ROUTER_COMMANDS:
        from anthill.navigate import router
        return router.main(argv) or 0
    if argv and argv[0] == "map":
        # Dispatch on the verb, not the exact pair: `map --help` used to fall
        # through to a parser that had never heard of `map`.
        from anthill.navigate import build_map
        rest = argv[1:]
        if rest and rest[0] == "build":
            rest = rest[1:]
        elif rest and rest[0] not in ("-h", "--help", "--stats"):
            print(f"anthill: unknown map subcommand {rest[0]!r}; "
                  f"the only one is `map build`", file=sys.stderr)
            return 2
        return build_map.main(rest) or 0
    if argv and argv[0] == "guard":
        from anthill import guard
        return guard.main(argv[1:])
    if argv and argv[0] == "control":
        from anthill import control
        return control.main(argv[1:])
    if argv and argv[0] == "config":
        from anthill import configure
        return configure.main(argv[1:])
    if argv and argv[0] == "ui":
        from anthill.ui import server
        return server.main(argv[1:])
    if argv and argv[0] == "survey":
        from anthill import install as inst
        ctx = _ctx.resolve(None)
        if not ctx.installed:
            print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
            return 2
        sv = inst.survey(ctx)
        print(json.dumps(sv, indent=2) if "--json" in argv[1:] else inst.render_survey(sv))
        return 0
    if argv and argv[0] == "upkeep":
        from anthill import upkeep
        return upkeep.main(argv[1:])
    if argv and argv[0] == "tidy":
        from anthill import tidy
        return tidy.main(argv[1:])
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
    if argv and argv[0] == "score":
        from anthill import scorecard
        return scorecard.main(argv[1:])
    if argv and argv[0] in ("note", "resume", "checkpoint", "prompt", "correction"):
        from anthill import resume
        return resume.main(argv)
    if argv and argv[0] == "trail":
        from anthill import trail
        return trail.main(argv[1:])
    if argv and argv[0] == "blueprint":
        from anthill.gates import blueprint
        return blueprint.main(argv[1:])

    ap = argparse.ArgumentParser(
        prog="anthill",
        description="A development agent system: blueprint, intent, foreman.\n\n" + START_HERE,
        epilog="navigation and knowledge (`anthill <cmd> --help`):\n  "
               + "\n  ".join(", ".join(NAVIGATION[i:i + 6])
                             for i in range(0, len(NAVIGATION), 6)),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default="", help="Target project root")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # Registered so they appear in the command list and in `--help`. Dispatch
    # happened above, before parsing, so these parsers are never reached -- each
    # delegated command keeps its own flags and its own help.
    for name, blurb in DELEGATED:
        sub.add_parser(name, help=blurb, add_help=False)

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
    sg = sps.add_parser("set-gate", help="Change what proves a unit; recompile after")
    sg.add_argument("unit"); sg.add_argument("--gate", default="")
    sg.add_argument("--spec-gate", default="",
                    help="Verbatim gate for a .spec unit (must not require passing)")
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
        result = inst.install(ctx, project_name=args.name, stack=args.stack,
                              description=args.description, areas=areas,
                              force=args.force, write=not args.dry_run,
                              exclude=[x.strip() for x in args.exclude.split(",")
                                       if x.strip()])
        _out(result)
        if result.get("survey"):
            # For the person at the terminal; stdout stays valid JSON.
            print("\n" + inst.render_survey(result["survey"]), file=sys.stderr)
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
        elif args.sub == "set-gate":
            _out(backlog.set_gate(ctx, args.unit, args.gate, args.spec_gate))
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
