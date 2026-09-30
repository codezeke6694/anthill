#!/usr/bin/env python3
"""Who fills each role.

`install` writes role *definitions*. It never asked who performs them, which
left the most consequential fact about a run unrecorded: a role definition with
nobody assigned is a job description in an empty office.

WHY THE ASSIGNMENT IS NOT COSMETIC
----------------------------------
The audit's whole value depends on this answer. An auditor that is the same
model as the builder shares its blind spots exactly, so its approval carries
close to no information -- and the system already refuses to treat an approval
as proof for that reason. Assigning the auditor to a *different* tool or model
is the only lever that buys any real independence, so this module says so out
loud when it sees the same identity on both.

Assignments live under `.anthill/roles/`, which is a protected path. That is
deliberate: an agent must not be able to promote itself to auditor of its own
work. Reassignment is an owner action.

History is kept because "who audited this" stops being answerable the moment it
is overwritten, and that is exactly the question asked after something ships
broken.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

ASSIGNMENTS_FILE = "assignments.json"

# What each role is for, in one line, so `roles show` explains itself.
PURPOSE = {
    "planner": "plans and reports; talks to the owner; writes no code",
    "builder": "executes one unit inside its owned paths",
    "auditor": "reviews a finished unit; changes nothing; can refuse but not pass",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path_for(ctx: _ctx.Context) -> Path:
    return ctx.roles_dir / ASSIGNMENTS_FILE


def load(ctx: _ctx.Context) -> dict:
    p = path_for(ctx)
    if not p.exists():
        return {"assigned": {}, "history": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"assigned": {}, "history": []}
    data.setdefault("assigned", {})
    data.setdefault("history", [])
    return data


def save(ctx: _ctx.Context, data: dict) -> None:
    p = path_for(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def assign(ctx: _ctx.Context, role: str, who: str, by: str = "",
           note: str = "") -> dict:
    """Assign a role. Records what it replaced rather than discarding it."""
    known = list(ctx.config.get("roles") or [])
    if known and role not in known:
        raise SystemExit(f"anthill: {role!r} is not a role in this install "
                         f"({', '.join(known)})")
    data = load(ctx)
    previous = data["assigned"].get(role, "")
    data["assigned"][role] = who
    data["history"].append({"at": _now(), "role": role, "who": who,
                            "replaced": previous, "by": by, "note": note})
    save(ctx, data)
    return {"role": role, "assigned_to": who, "replaced": previous or None,
            **independence(ctx, data)}


def independence(ctx: _ctx.Context, data: dict | None = None) -> dict:
    """Is the auditor a different identity from the builder?

    Reported on every assignment and every `show`, because the answer silently
    decides how much an audit is worth and nothing else in the system surfaces
    it.
    """
    data = data or load(ctx)
    a = (data["assigned"].get("auditor") or "").strip().lower()
    b = (data["assigned"].get("builder") or "").strip().lower()
    if not a or not b:
        return {}
    if a == b:
        return {"independence": "none",
                "warning": (f"builder and auditor are both {data['assigned']['builder']!r}. "
                            "The same model auditing its own work shares its blind "
                            "spots exactly, so a PASS carries almost no "
                            "information. Tests remain the only real proof. "
                            "Assign the auditor to a different tool or model if "
                            "you can.")}
    return {"independence": "separate identities"}


def show(ctx: _ctx.Context) -> dict:
    data = load(ctx)
    roles = list(ctx.config.get("roles") or PURPOSE.keys())
    return {
        "roles": [{"role": r, "purpose": PURPOSE.get(r, ""),
                   "assigned_to": data["assigned"].get(r) or None,
                   "definition": f".anthill/roles/{r}.md"}
                  for r in roles],
        "unassigned": [r for r in roles if not data["assigned"].get(r)],
        **independence(ctx, data),
    }


def history(ctx: _ctx.Context, role: str = "") -> dict:
    data = load(ctx)
    rows = [h for h in data["history"] if not role or h["role"] == role]
    return {"role": role or "(all)", "entries": rows, "count": len(rows)}


def table(ctx: _ctx.Context) -> str:
    """The role table rendered into AGENTS.md, assignments included."""
    from anthill.install import ROLE_SUMMARY
    data = load(ctx)
    rows = ["| Role | Assigned to | What it does | What it owns |",
            "|---|---|---|---|"]
    for r in list(ctx.config.get("roles") or PURPOSE.keys()):
        what, owns_desc = ROLE_SUMMARY.get(r, ("see its role file", "see its unit brief"))
        who = data["assigned"].get(r) or "_unassigned_"
        rows.append(f"| **{r}** — `.anthill/roles/{r}.md` | {who} | {what} | {owns_desc} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Who fills each role.")
    ap.add_argument("--project", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="Current assignments and independence")
    a = sub.add_parser("assign", help="Assign a role to a tool or person")
    a.add_argument("role"); a.add_argument("who")
    a.add_argument("--by", default="", help="Who made this assignment")
    a.add_argument("--note", default="")
    h = sub.add_parser("history", help="Every assignment this role has had")
    h.add_argument("--role", default="")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2

    if args.cmd == "assign":
        out = assign(ctx, args.role, args.who, args.by, args.note)
    elif args.cmd == "history":
        out = history(ctx, args.role)
    else:
        out = show(ctx)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
