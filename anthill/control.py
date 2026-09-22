#!/usr/bin/env python3
"""Have the control files been changed since they were installed?

The deny rules in `.claude/settings.json` stop an agent editing the charter, the
roles, or its own instructions -- and they work: they blocked `cp`, `sed`, and a
whole compound command during development. But they intercept the *agent's* file
operations, not writes made by a program the agent runs. `anthill install`
rewrites `CLAUDE.md` quite happily, and `CLAUDE.md` is on the deny list.

Tightening the rules further is not the answer, because the installer has to be
able to write those files. So the answer is the one this system uses everywhere
else: if a thing cannot be prevented, make it *visible*. Same principle as the
blueprint gate -- a recorded fingerprint, re-checked against reality.

Three states are worth distinguishing, and collapsing them to "changed" would
hide the one that matters:

    unchanged        matches the fingerprint recorded at install
    render pending   differs from the fingerprint, but matches a fresh render
                     -- the templates moved on; re-run install
    EDITED           differs from both -- someone or something rewrote it
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

FINGERPRINT_FILE = "control-fingerprints.json"


def digest(text: str) -> str:
    """Newlines normalised, trailing whitespace stripped per line.

    An editor that re-saves a file with CRLF or trims a trailing space has not
    tampered with anything, and reporting that as an edit would train whoever
    reads this to ignore it.
    """
    norm = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(norm.strip().encode("utf-8")).hexdigest()[:16]


def controlled_files(ctx: _ctx.Context) -> list[Path]:
    out = [ctx.root / "CLAUDE.md", ctx.root / "AGENTS.md", ctx.constitution]
    for role in (ctx.config.get("roles") or []):
        out.append(ctx.roles_dir / f"{role}.md")
    out.append(ctx.root / ".claude" / "settings.json")
    return [p for p in out]


def fingerprint_path(ctx: _ctx.Context) -> Path:
    return ctx.state / FINGERPRINT_FILE


def record(ctx: _ctx.Context, note: str = "install") -> dict:
    """Stamp the current content of every control file."""
    prints = {}
    for p in controlled_files(ctx):
        if p.exists():
            try:
                prints[str(p.relative_to(ctx.root))] = digest(
                    p.read_text(encoding="utf-8"))
            except OSError:
                continue
    data = {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": note, "fingerprints": prints}
    fp = fingerprint_path(ctx)
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(fp)
    return {"recorded": len(prints), "path": str(fp)}


def _fresh_render(ctx: _ctx.Context) -> dict[str, str]:
    """What install would write right now, without writing it."""
    from anthill import install as inst, roles as roles_mod
    name = (ctx.config.get("project") or {}).get("name") or ctx.root.name
    values = inst.render_values(ctx, name)
    protected_block = "\n".join(f"- `{p}`" for p in inst.PROTECTED_PATHS)
    cmd = inst.invocation(ctx)
    out: dict[str, str] = {}

    out["CLAUDE.md"] = inst.render_claude_md(ctx, name, protected_block)

    try:
        agents_values = dict(values, ROLE_TABLE=roles_mod.table(ctx),
                             PROTECTED_BLOCK=protected_block, ANTHILL=cmd)
        out["AGENTS.md"] = inst._render(
            inst.TEMPLATE_DIR / "AGENTS.md.tmpl", agents_values)
    except OSError:
        pass
    for role in (ctx.config.get("roles") or []):
        tmpl = inst.TEMPLATE_DIR / "roles" / f"{role}.md.tmpl"
        if tmpl.exists():
            out[f".anthill/roles/{role}.md"] = inst._render(tmpl, values)
    return out


def check(ctx: _ctx.Context) -> dict:
    fp = fingerprint_path(ctx)
    recorded = {}
    recorded_at = ""
    if fp.exists():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            recorded = data.get("fingerprints") or {}
            recorded_at = data.get("recorded_at", "")
        except (OSError, json.JSONDecodeError):
            pass

    fresh = _fresh_render(ctx)
    rows = []
    for p in controlled_files(ctx):
        rel = str(p.relative_to(ctx.root))
        if not p.exists():
            rows.append({"file": rel, "state": "MISSING"})
            continue
        try:
            live = p.read_text(encoding="utf-8")
        except OSError:
            continue
        d = digest(live)
        was = recorded.get(rel)
        fresh_d = digest(fresh[rel]) if rel in fresh else None
        if was is None:
            state = "unrecorded"
        elif d == was and fresh_d is not None and fresh_d != d:
            # Nobody touched the file, but what install would write today is
            # different: a setting or a template moved on. The prose is now
            # describing a mechanism that no longer works that way -- the
            # exact drift that left an agent under a push rule the hook would
            # not let it obey. Reported separately from EDITED because the
            # remedy is the opposite: re-render, do not investigate.
            state = "stale"
        elif d == was:
            state = "unchanged"
        elif fresh_d == d:
            state = "render pending"
        else:
            state = "EDITED"
        # The constitution is meant to be filled in by a human, so an edit there
        # is expected rather than suspicious -- it is protected against agents,
        # not frozen against owners.
        if rel == "CONSTITUTION.md" and state == "EDITED":
            state = "edited (expected — human-owned)"
        rows.append({"file": rel, "state": state,
                     "recorded": was, "live": d})

    edited = [r for r in rows if r["state"] == "EDITED"]
    return {
        "fingerprints": str(fp),
        "recorded_at": recorded_at or "(never)",
        "files": rows,
        "edited_count": len(edited),
        "verdict": "control files edited" if edited else "control files intact",
        "note": ("Deny rules stop an agent editing these directly; they do not "
                 "stop a program the agent runs. This check is what makes such "
                 "a change visible."),
        "stale_count": len([r for r in rows if r["state"] == "stale"]),
        "next": ("`anthill install --force` to re-render, or `anthill control "
                 "--accept` if the change was intended"
                 ) if edited or any(r["state"] in ("render pending", "stale")
                                    for r in rows) else "",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check whether the control files still match what was installed.")
    ap.add_argument("--project", default="")
    ap.add_argument("--accept", action="store_true",
                    help="Re-record fingerprints, blessing the current content")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2

    if args.accept:
        print(json.dumps(record(ctx, note="accepted by operator"), indent=2))
        return 0

    out = check(ctx)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"control: {out['verdict']}  (recorded {out['recorded_at']})")
        for r in out["files"]:
            mark = "!!" if r["state"] == "EDITED" else (" !" if r["state"] == "stale" else "  ")
            print(f"  {mark} {r['state']:34s} {r['file']}")
        if out["next"]:
            print(f"\n  {out['next']}")
    return 1 if out["edited_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
