"""Changes that wait for the owner: the database first (owner, 13 Oct 2026).

On 8 Oct a LogiAstro chat saved a migration, the dev server reloaded, and the
change ran on the shared database before any test had. Nothing stopped it:
Anthill guarded pushes and commits on main, and a save is neither.

So a file under a risky path -- by default, the folders projects keep their
database changes in -- is refused at the moment of the edit until the owner
approves it, and again at commit, which also catches edits made by a shell
command or another tool. The project names its own paths in
`execution.risky_paths`; an empty list turns this off.

    anthill risky ask <path>... --why "<what the change does>"   a chat asks
    anthill risky allow <id> --by <owner>                         the owner says yes
    anthill risky list                                            what waits, what is allowed

The owner also answers from their page. An approval covers the files it names,
on this laptop, for APPROVAL_HOURS; the next change asks again, because an
approval from one context is not permission for the next.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from anthill import context as _ctx

DEFAULT_RISKY = ["**/migrations/**", "**/alembic/versions/**", "**/db/migrate/**"]
APPROVAL_HOURS = 12
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# A shell command that names a risky file and could change it.
_WRITES = re.compile(r"(>|\btee\b|\bsed\s+-i|\bmv\b|\bcp\b|\brm\b|\btouch\b|\bpatch\b|\bgit\s+(checkout|restore|apply)\b)")


def patterns(ctx: _ctx.Context) -> list[str]:
    ex = ctx.config.get("execution") or {}
    if "risky_paths" not in ex:
        return list(DEFAULT_RISKY)
    return [str(p) for p in ex.get("risky_paths") or []]


def _rel(ctx: _ctx.Context, path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(ctx.root.resolve())
        except ValueError:
            return ""                      # outside the project: not ours to guard
    rel = p.as_posix()
    while rel.startswith("./"):
        rel = rel[2:]
    return "" if rel in (".", "") else rel


# A new package is the owner's call too (AutoDev's DEP-001): checked at the
# commit, not the edit, because a manifest also holds scripts and settings.
DEP_FILES = re.compile(r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|"
                       r"composer\.(json|lock)|Gemfile(\.lock)?|go\.(mod|sum)|Cargo\.(toml|lock)|"
                       r"requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|uv\.lock|Pipfile(\.lock)?)$")
_DEP_KEYS = {"package.json": ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")}


def deps_need_owner(ctx: _ctx.Context) -> bool:
    return bool((ctx.config.get("execution") or {}).get("dependencies_need_owner", True))


def _deps_of(name: str, text: str) -> Any:
    """The dependency part of a manifest that also holds other things; None when unreadable."""
    try:
        if name == "package.json":
            data = json.loads(text or "{}")
            return {k: data.get(k) for k in _DEP_KEYS[name]}
        if name == "pyproject.toml":
            import tomllib
            data = tomllib.loads(text or "")
            proj, poetry = data.get("project") or {}, ((data.get("tool") or {}).get("poetry") or {})
            return [proj.get("dependencies"), proj.get("optional-dependencies"),
                    data.get("dependency-groups"), poetry.get("dependencies"), poetry.get("group")]
    except (ValueError, ImportError):
        return None
    return text


def dependency_changes(ctx: _ctx.Context, cwd: Path, files: list[str]) -> list[str]:
    """Staged manifests and lockfiles whose dependencies changed."""
    import subprocess
    if not deps_need_owner(ctx):
        return []

    def show(spec: str) -> str:
        r = subprocess.run(["git", "show", spec], cwd=cwd, capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    out = []
    for f in files:
        if not DEP_FILES.search(f):
            continue
        name = Path(f).name
        if name in ("package.json", "pyproject.toml"):
            before, after = _deps_of(name, show(f"HEAD:{f}")), _deps_of(name, show(f":{f}"))
            if before is not None and before == after:
                continue                    # scripts or settings changed, not what is installed
        out.append(f)
    return out


def is_risky(ctx: _ctx.Context, path: str) -> bool:
    from anthill.orchestrate.orchestrator import matches_any
    rel = _rel(ctx, path)
    return bool(rel) and matches_any(rel, patterns(ctx))


# ------------------------------------------------------------------ the record

def _store(ctx: _ctx.Context) -> Path:
    return ctx.local_dir / "approvals.json"


def _load(ctx: _ctx.Context) -> list[dict[str, Any]]:
    try:
        return json.loads(_store(ctx).read_text(encoding="utf-8")).get("requests") or []
    except (OSError, ValueError):
        return []


def _save(ctx: _ctx.Context, reqs: list[dict[str, Any]]) -> None:
    p = _store(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"requests": reqs}, indent=2), encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _live(r: dict[str, Any]) -> bool:
    try:
        return r.get("status") == "allowed" and datetime.fromisoformat(r["until"]) > _now()
    except (KeyError, ValueError):
        return False


def allowed(ctx: _ctx.Context, path: str) -> bool:
    rel = _rel(ctx, path)
    return any(_live(r) and rel in r.get("files", []) for r in _load(ctx))


def blocked(ctx: _ctx.Context, files: list[str]) -> list[str]:
    """The risky files in `files` the owner has not approved."""
    return [f for f in files if is_risky(ctx, f) and not allowed(ctx, f)]


def pending(ctx: _ctx.Context) -> list[dict[str, Any]]:
    return [r for r in _load(ctx) if r.get("status") == "asked"]


def ask(ctx: _ctx.Context, files: list[str], why: str, sprint: str = "") -> dict[str, Any]:
    rels = sorted({_rel(ctx, f) for f in files if is_risky(ctx, f) or DEP_FILES.search(_rel(ctx, f))})
    if not rels:
        return {"asked": False, "why": "none of these is a database change or a package list: "
                f"{', '.join(patterns(ctx)) or '(no risky paths set)'}"}
    kind = "package" if all(DEP_FILES.search(r) for r in rels) else "database"
    reqs = _load(ctx)
    for r in reqs:                       # the same files asked again: one question
        if r.get("status") == "asked" and r.get("files") == rels:
            return {"asked": True, "id": r["id"], "files": rels, "already": True}
    rid = f"r{len(reqs) + 1}"
    reqs.append({"id": rid, "kind": kind, "files": rels, "why": why.strip(), "sprint": sprint,
                 "status": "asked", "asked_at": _now().isoformat(timespec="seconds")})
    _save(ctx, reqs)
    from anthill import trail
    trail.record("risky_asked", ctx, id=rid, files=rels, why=why.strip())
    return {"asked": True, "id": rid, "files": rels,
            "next": "tell the owner it is on their page, and wait; do not edit these files until it is allowed"}


def decide(ctx: _ctx.Context, rid: str, yes: bool, by: str, via: str = "terminal") -> dict[str, Any]:
    reqs = _load(ctx)
    r = next((x for x in reqs if x.get("id") == rid), None)
    if r is None:
        return {"decided": False, "why": f"no request {rid}"}
    if r.get("status") != "asked":
        return {"decided": False, "why": f"{rid} is already {r.get('status')}"}
    r["status"] = "allowed" if yes else "refused"
    r["by"], r["via"], r["decided_at"] = by, via, _now().isoformat(timespec="seconds")
    if yes:
        r["until"] = (_now() + timedelta(hours=APPROVAL_HOURS)).isoformat(timespec="seconds")
    _save(ctx, reqs)
    from anthill import trail
    trail.record("risky_" + r["status"], ctx, id=rid, files=r["files"], by=by, via=via)
    return {"decided": True, "id": rid, "status": r["status"], "files": r["files"],
            "until": r.get("until")}


# ------------------------------------------------------------------ the hook

def _hook_paths(data: dict[str, Any]) -> tuple[list[str], str]:
    """The files a tool call would change, and the shell command if it is one."""
    tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return ([p] if p else []), ""
    if tool == "Bash":
        return [], str(inp.get("command") or "")
    return [], ""


def _refusal(files: list[str]) -> str:
    return (f"Refused: {', '.join(files)} is a database change, and these wait for the owner "
            f"(on 8 Oct a saved migration ran on the shared database before any test).\n"
            f"Ask first:  anthill risky ask {' '.join(files)} --why \"<what it changes and why>\"\n"
            f"then tell the owner it is on their page, and wait for the answer. "
            f"Do not work around this with another tool.")


def hook(ctx: _ctx.Context, data: dict[str, Any]) -> dict[str, Any] | None:
    """Claude's PreToolUse: a refusal for a risky edit the owner has not approved."""
    if not patterns(ctx):
        return None
    files, command = _hook_paths(data)
    if command:
        if not _WRITES.search(command):
            return None
        files = [tok for tok in re.split(r"[\s'\"<>|;&()]+", command) if tok and is_risky(ctx, tok)]
    hit = blocked(ctx, files)
    if not hit:
        return None
    rels = sorted({_rel(ctx, f) for f in hit})
    from anthill import trail
    trail.record("risky_refused", ctx, session=str(data.get("session_id") or ""),
                 files=rels, tool=data.get("tool_name", ""))
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": _refusal(rels)}}


# ------------------------------------------------------------------ command

def main(argv: list[str]) -> int:
    import argparse
    if "--hook" in argv:
        try:
            ctx = _ctx.resolve(None)
            data = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
            out = hook(ctx, data) if ctx.installed else None
        except Exception:                  # noqa: BLE001 -- a hook fault must never block work
            return 0
        if out:
            print(json.dumps(out))
        return 0

    ap = argparse.ArgumentParser(prog="anthill risky",
                                 description="Changes that wait for the owner (database changes first).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="Ask the owner to allow a change to risky files")
    a.add_argument("files", nargs="+"); a.add_argument("--why", required=True)
    a.add_argument("--sprint", default="")
    for name, text in (("allow", "Allow a request (owner)"), ("refuse", "Refuse a request (owner)")):
        d = sub.add_parser(name, help=text)
        d.add_argument("id"); d.add_argument("--by", required=True)
    sub.add_parser("list", help="What waits for the owner, and what is allowed now")
    args = ap.parse_args(argv)
    ctx = _ctx.resolve(None)

    if args.cmd == "ask":
        out = ask(ctx, args.files, args.why, args.sprint)
    elif args.cmd in ("allow", "refuse"):
        from anthill import guard
        if not guard.is_owner():
            print(json.dumps({"decided": False, "why": (
                "allowing a risky change is the owner's decision: they answer on their "
                "page, or run this with ANTHILL_OWNER=1 in their own terminal")}, indent=2))
            return 1
        out = decide(ctx, args.id, args.cmd == "allow", args.by)
    else:
        reqs = _load(ctx)
        out = {"paths": patterns(ctx), "waiting": pending(ctx),
               "allowed_now": [r for r in reqs if _live(r)]}
    print(json.dumps(out, indent=2))
    return 0 if out.get("asked", out.get("decided", True)) else 1
