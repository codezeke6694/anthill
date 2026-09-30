#!/usr/bin/env python3
"""After a merge: the foreman redraws the blueprint and reports the intent gap.

This step exists because of an error found by running the loop. The builder's
role file originally told it to rebuild the map before calling its gate, which
cannot work and would have been wrong even if it could:

  - a builder works in an isolated worktree holding only its own change, so a
    map built there is missing every other unit's chambers;
  - the map is one shared file, so two concurrent builders would clobber each
    other's blueprint and the last writer would win.

The blueprint is a property of the *integrated* tree, so it is drawn once, on
the integration branch, after a unit merges -- by the foreman, not the digger.
Which is the right division anyway: "after each task the orchestrator fills the
knowledge and nav" is a foreman's job.

What a builder is still accountable for is the intent half: the page describing
what it built. The gate cannot fully enforce that yet (see `report_gap`), so
this step names the gap loudly rather than implying it is covered.
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


def integration_tree(ctx: _ctx.Context) -> Path | None:
    """Where the merged code actually is.

    The foreman merges into an integration branch held by its own worktree, so
    the integrated tree is *not* the main checkout -- main still holds whatever
    the operator last had. Scanning main is how the first version of this step
    reported a blueprint of 0 nodes while two units had already landed.
    """
    import subprocess
    try:
        r = subprocess.run(["git", "worktree", "list", "--porcelain"],
                           cwd=ctx.root, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    path = None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1])
        elif line.startswith("branch ") and path is not None:
            branch = line.split(" ", 1)[1].rsplit("/", 1)[-1]
            if branch == "integration":
                return path
    return None


def report_gap(ctx: _ctx.Context, tree: Path | None = None) -> dict:
    """Which integrated code has no page explaining it.

    Deliberately a report and not a refusal. A coverage floor applied from the
    first sprint would block all early work; applied never, the knowledge base
    quietly stops describing the code. Naming the largest unexplained file every
    time a unit lands is the honest middle, and `anthill blueprint
    --min-coverage` is there for when a project is ready to make it binding.
    """
    from anthill.knowledge import readiness
    if not ctx.knowledge_dir.exists():
        return {"knowledge_dir": str(ctx.knowledge_dir), "exists": False,
                "note": "no knowledge base yet; nothing can be explained by a page"}
    cov = readiness.coverage(ctx.knowledge_dir, tree or ctx.root)
    return {
        "share_explained": cov["share_explained"],
        "files_with_no_page": cov["files_with_no_page"],
        "largest_unexplained": [f"{r['file']} ({r['lines']} lines)"
                                for r in cov["largest_unexplained"][:5]],
        "note": cov["note"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Redraw the blueprint and report the intent gap. Run after a merge.")
    ap.add_argument("--project", default="")
    ap.add_argument("--skip-map", action="store_true")
    ap.add_argument("--tree", default="",
                    help="Tree to scan (default: the integration worktree, "
                         "falling back to the project root)")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2

    tree = (Path(args.tree).expanduser().resolve() if args.tree
            else integration_tree(ctx) or ctx.root)
    out: dict = {"root": str(ctx.root), "scanned_tree": str(tree)}

    if not args.skip_map:
        from anthill.navigate import build_map
        from anthill.navigate import structure
        # build_map and structure read their scan root as a module constant, set
        # from the ambient context at import. Pointing both at the integrated
        # tree here is deliberate and paired: structure's caller index must scan
        # the same set the map was built from, or callers look spuriously
        # deleted. The output path is left alone -- the map belongs to the
        # project's state, not to a transient worktree.
        build_map.REPO_ROOT = tree
        structure.REPO_ROOT = tree
        inc, top = _ctx.discover_sources(tree, set(build_map.EXCLUDE_PARTS))
        cfg_inc = (ctx.config.get("source") or {}).get("include_dirs") or []
        build_map.INCLUDE_DIRS = cfg_inc or inc
        build_map.INCLUDE_TOPLEVEL = (
            (ctx.config.get("source") or {}).get("include_toplevel") or top)
        structure.INCLUDE_DIRS = build_map.INCLUDE_DIRS
        structure.INCLUDE_TOPLEVEL = build_map.INCLUDE_TOPLEVEL
        out["scanned_dirs"] = build_map.INCLUDE_DIRS
        m = build_map.build()
        build_map.OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        build_map.OUT_PATH.write_text(json.dumps(m, indent=2), encoding="utf-8")
        out["blueprint"] = {"nodes": len(m["nodes"]),
                            "anchors": sum(len(n["anchors"]) for n in m["nodes"]),
                            "written": str(build_map.OUT_PATH)}
    out["intent_gap"] = report_gap(ctx, tree)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
