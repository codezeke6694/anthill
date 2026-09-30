#!/usr/bin/env python3
"""Make the board the only door into the source tree.

Anthill refuses to let a *unit* close without proof. It had no opinion about
code that was never a unit — and `git commit` always works. So one sprint ran
through the board and roughly four thousand lines across six districts went
around it: no owned boundary, no gate, no audit, no page. The instruction to use
the board was there; nothing required it.

This is the requirement. Staged product source must be owned by a unit that is
currently claimed. Everything else — documents, state, tests outside a district,
config — is untouched, because refusing those would just teach people the
`--no-verify` flag.

Deliberately narrow:
  * no install, or no contract  -> allow. A repo not using the board is not the
    board's business.
  * a merge commit             -> allow. `work done` merges, and blocking that
    would break the mechanism this exists to protect.
  * nothing staged in scope    -> allow.

`git commit --no-verify` still bypasses it, and that is fine: this is a door,
not a lock. The point is that walking around it becomes a visible choice rather
than the path of least resistance.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx
from anthill import hygiene as _hygiene

ALLOW, REFUSE, ERROR = 0, 1, 2


def _git(args: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


OWNER_ENV = "ANTHILL_OWNER"


def is_owner() -> bool:
    """Is this the owner acting, rather than an agent?

    A local hook runs the same binary for both, on the same machine, so it
    cannot actually tell. This is a convenience so the owner is not fighting
    their own tooling.

    Set it **per command** -- `ANTHILL_OWNER=1 git push` -- and never in a shell
    profile. An agent's shell is initialised from the same profile the owner's
    is, so a line in `.zshrc` hands the agent owner status permanently and this
    check never fires again. Measured: the PATH additions from a user's
    `.zshrc` were present in an agent's environment.

    A per-command prefix also matches the rule it enforces: pushing is asked for
    each time, and a persistent variable is standing permission -- which is
    exactly the failure this exists to catch, an approval from one context read
    as authorization for the next.

    So treat it as a turn signal, not a lock. The only control that genuinely
    distinguishes an owner from an agent lives off this machine: branch
    protection on the remote, where merging requires an identity the agent does
    not hold.
    """
    import os as _os
    return _os.environ.get(OWNER_ENV, "").strip().lower() in ("1", "true", "yes")


def current_branch(cwd: Path) -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


def protected(ctx: _ctx.Context) -> list[str]:
    ex = ctx.config.get("execution") or {}
    return [str(b) for b in (ex.get("protected_branches") or [])]


def check_branch(ctx: _ctx.Context, cwd: Path) -> tuple[dict, int] | None:
    """Is this a branch the owner keeps for themselves?

    Checked before ownership, because it is the more basic question: a change
    committed straight onto `main` has bypassed review entirely, whatever unit
    owned the files. The owner merges into a protected branch; nothing else does.
    """
    branch = current_branch(cwd)
    names = protected(ctx)
    if not names or branch not in names:
        return None
    if is_owner():
        return None
    return ({
        "verdict": "refused",
        "branch": branch,
        "protected": names,
        "why": (f"{branch!r} is the owner's branch. Work happens on a branch and "
                f"is merged in once the owner is satisfied with it."),
        "next": (f"git switch -c work/<what-you-are-doing>   # then commit\n"
                 f"  The owner merges it into {branch} once reviewed.\n"
                 f"  If you are the owner: {OWNER_ENV}=1 git push   "
                 f"(or `git opush`)"),
    }, REFUSE)


def hygiene_on(ctx: _ctx.Context) -> bool:
    """Off unless the owner turned it on (`execution.guard_hygiene`)."""
    ex = ctx.config.get("execution") or {}
    return bool(ex.get("guard_hygiene", False))


def check_hygiene(ctx: _ctx.Context, cwd: Path) -> tuple[dict, int] | None:
    """Secrets and junk in what is staged. No owner exception: a key committed
    by the owner is exactly as public as one committed by an agent."""
    if not hygiene_on(ctx):
        return None
    problems = _hygiene.scan_staged(cwd)
    if not problems:
        return None
    return ({
        "verdict": "refused",
        "hygiene": problems,
        "why": ("a secret in history is public from the first push, and removing "
                "it later does not take it back; junk files are noise in every "
                "diff and conflict on files nobody meant to share"),
        "next": ("git restore --staged <file>   # unstage it\n"
                 "  then add it to .gitignore so it cannot come back.\n"
                 "  A real key that was ever committed should be rotated."),
    }, REFUSE)


def check_force(ctx: _ctx.Context, cwd: Path,
                updates: list[tuple[str, str, str, str]]) -> tuple[dict, int] | None:
    """A push that rewrites a remote branch instead of adding to it.

    The owner may rewrite their own work branch -- they are the one who knows
    nobody else has it. Nobody rewrites a protected branch, because everybody
    has it.
    """
    if not hygiene_on(ctx):
        return None
    rewritten = _hygiene.forced_updates(updates, cwd)
    if not rewritten:
        return None
    names = protected(ctx)
    blocking = [b for b in rewritten if b in names or not is_owner()]
    if not blocking:
        return None
    return ({
        "verdict": "refused",
        "rewriting": blocking,
        "why": ("this push replaces commits the remote already has instead of "
                "adding to them; anyone who pulled them now holds a history that "
                "no longer exists"),
        "next": ("git fetch && git merge origin/<branch>   # then push normally\n"
                 "  If the branch is yours alone and you are the owner: "
                 f"{OWNER_ENV}=1 git push --force-with-lease\n"
                 "  A protected branch is never rewritten."),
    }, REFUSE)


def staged(cwd: Path) -> list[str]:
    out = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"], cwd)
    return [f for f in out.splitlines() if f.strip()]


def is_merging(cwd: Path) -> bool:
    """A merge in progress. `work done` makes one, so it must not be blocked."""
    gitdir = (_git(["rev-parse", "--git-dir"], cwd) or ".git").strip()
    base = (cwd / gitdir) if not Path(gitdir).is_absolute() else Path(gitdir)
    return (base / "MERGE_HEAD").exists()


def in_scope(rel: str, include: list[str], toplevel: list[str],
             exclude: set[str]) -> bool:
    """Is this a product source file the board should own?"""
    parts = Path(rel).parts
    if not parts or (exclude & set(parts)):
        return False
    return parts[0] in set(include) or rel in set(toplevel)


def active_units(ctx: _ctx.Context) -> tuple[list[dict], list[str]]:
    """Units currently claimed, and every unit id the contract declares."""
    contract_path = ctx.contracts_dir / "contract.json"
    work_root = ctx.state / "build" / "work"
    # The orchestrator keeps its own copy of the contract per run directory;
    # prefer that, since it is the one the board is actually executing.
    for cand in sorted(work_root.glob("*/contract.json")) + [contract_path]:
        if cand.exists():
            contract_path = cand
            break
    if not contract_path.exists():
        return [], []
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], []
    units = contract.get("units") or []
    state_dir = contract_path.parent / "state"
    live = []
    for u in units:
        sp = state_dir / f"{str(u.get('id','')).replace('/', '_')}.json"
        status = ""
        if sp.exists():
            try:
                status = json.loads(sp.read_text(encoding="utf-8")).get("status", "")
            except (OSError, json.JSONDecodeError):
                status = ""
        if status in ("claimed", "gated"):
            live.append(u)
    return live, [str(u.get("id")) for u in units]


def check(ctx: _ctx.Context, cwd: Path) -> tuple[dict, int]:
    from anthill.orchestrate.orchestrator import matches_any

    if not ctx.installed:
        return {"verdict": "allowed", "why": "anthill is not installed here"}, ALLOW
    if is_merging(cwd):
        return {"verdict": "allowed", "why": "merge in progress"}, ALLOW

    on_protected = check_branch(ctx, cwd)
    if on_protected is not None:
        return on_protected

    dirty = check_hygiene(ctx, cwd)
    if dirty is not None:
        return dirty

    ex = ctx.config.get("execution") or {}
    if not ex.get("guard_ownership", False):
        return ({"verdict": "allowed",
                 "why": "ownership guarding is off (execution.guard_ownership); "
                        "branch and push protection still apply"}, ALLOW)

    include, toplevel, exclude = ctx.source_roots()
    files = staged(cwd)
    scoped = [f for f in files if in_scope(f, include, toplevel, exclude)]
    if not scoped:
        return {"verdict": "allowed", "staged": len(files),
                "why": "nothing staged under the product source set"}, ALLOW

    live, all_ids = active_units(ctx)
    if not all_ids:
        return {"verdict": "allowed", "why": "no contract on this board"}, ALLOW

    owned: list[str] = []
    orphan: list[str] = []
    for f in scoped:
        holder = next((u["id"] for u in live if matches_any(f, u.get("owns") or [])), "")
        (owned if holder else orphan).append(f if holder else f)

    if not orphan:
        return {"verdict": "allowed", "owned_by_a_claimed_unit": len(owned)}, ALLOW

    return {
        "verdict": "refused",
        "unowned": orphan,
        "claimed_units": [{"id": u["id"], "owns": u.get("owns")} for u in live],
        "why": ("these files are product source that no currently claimed unit "
                "owns, so nothing will gate, audit or describe them"),
        "next": ("claim a unit that owns them (`anthill work next`), or add one "
                 "to the sprint and recompile. To commit anyway: "
                 "`git commit --no-verify` — a visible choice, not a blocked one"),
    }, REFUSE


def check_push(ctx: _ctx.Context, cwd: Path, refs: list[str]) -> tuple[dict, int]:
    """Refuse a push the owner has not asked for.

    Every push, not only one at a protected branch. A local commit stays on the
    machine and can be undone without anyone noticing; a push reaches the remote
    and everybody working from it, and cannot be taken back the same way. So
    pushing is the owner's act and needs their say-so each time -- an approval
    given once does not carry forward to the next one.

    git hands pre-push the refs being updated on stdin, so this reads what is
    actually being pushed rather than guessing from the current branch.
    """
    ex = ctx.config.get("execution") or {}
    if not ex.get("push_requires_owner", True):
        # Fall back to protecting just the named branches.
        names = protected(ctx)
        hit = [r for r in refs if r in names]
        if not hit or is_owner():
            return {"verdict": "allowed", "pushing": refs}, ALLOW
        return ({"verdict": "refused", "pushing_to": hit, "protected": names,
                 "why": "these branches belong to the owner",
                 "next": "push a work branch instead"}, REFUSE)
    if is_owner():
        return {"verdict": "allowed", "why": f"${OWNER_ENV} is set",
                "pushing": refs}, ALLOW
    return ({
        "verdict": "refused",
        "pushing": refs or ["(unknown ref)"],
        "why": ("pushing is the owner's act. A local commit stays here and can "
                "be undone quietly; a push reaches the remote and everyone "
                "working from it, and cannot be taken back the same way."),
        "next": ("ask the owner to push, and say what is ready and why.\n"
                 "  Commit as much as you like locally -- that costs nobody "
                 "anything.\n"
                 f"  If you are the owner: {OWNER_ENV}=1 git push   "
                 f"(or `git opush`)"),
    }, REFUSE)


def _pushed_updates(stdin_text: str) -> list[tuple[str, str, str, str]]:
    """Pre-push stdin as (local ref, local sha, remote ref, remote sha)."""
    out = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out.append((parts[0], parts[1], parts[2], parts[3]))
    return out


def _pushed_refs(stdin_text: str) -> list[str]:
    """Remote branch names from pre-push stdin: `<local ref> <sha> <remote ref> <sha>`."""
    out = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2].startswith("refs/heads/"):
            out.append(parts[2][len("refs/heads/"):])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a commit of product source that no claimed unit owns.")
    ap.add_argument("--project", default="")
    ap.add_argument("--push", action="store_true",
                    help="pre-push mode: read the refs being pushed on stdin")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cwd = Path.cwd()
    try:
        ctx = _ctx.resolve(args.project or None)
    except SystemExit:
        return ALLOW                      # never block a commit on our own fault

    if args.push:
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
        refs = _pushed_refs(stdin_text)
        forced = check_force(ctx, cwd, _pushed_updates(stdin_text))
        if forced is not None:
            report, code = forced
            if args.json:
                print(json.dumps(report, indent=2))
                return code
            print(f"\nanthill: push refused — it rewrites "
                  f"{', '.join(report['rewriting'])}.\n", file=sys.stderr)
            print(f"  {report['why']}\n", file=sys.stderr)
            print(f"  {report['next']}\n", file=sys.stderr)
            return REFUSE
        report, code = check_push(ctx, cwd, refs)
        if args.json:
            print(json.dumps(report, indent=2))
            return code
        if code == ALLOW:
            return ALLOW
        target = ", ".join(report.get("pushing_to") or report.get("pushing") or [])
        print(f"\nanthill: push refused — pushing is the owner's act "
              f"({target}).\n", file=sys.stderr)
        print(f"  {report['why']}\n", file=sys.stderr)
        print(f"  {report['next']}\n", file=sys.stderr)
        return REFUSE

    report, code = check(ctx, cwd)
    if args.json:
        print(json.dumps(report, indent=2))
        return code

    if code == ALLOW:
        return ALLOW
    if report.get("branch"):
        print(f"\nanthill: commit refused — {report['branch']} is the owner's "
              f"branch.\n", file=sys.stderr)
        print(f"  {report['why']}\n", file=sys.stderr)
        print(f"  {report['next']}\n", file=sys.stderr)
        return REFUSE
    if report.get("hygiene"):
        print("\nanthill: commit refused — this should not be shared.\n",
              file=sys.stderr)
        for p in report["hygiene"]:
            print(f"  {p['problem']:<6}  {p['file']}  — {p['why']}", file=sys.stderr)
        print(f"\n  {report['why']}\n", file=sys.stderr)
        print(f"  {report['next']}\n", file=sys.stderr)
        return REFUSE
    print("\nanthill: commit refused — the board is the way in.\n", file=sys.stderr)
    for f in report["unowned"]:
        print(f"  unowned  {f}", file=sys.stderr)
    print(f"\n  {report['why']}", file=sys.stderr)
    if report["claimed_units"]:
        print("\n  currently claimed:", file=sys.stderr)
        for u in report["claimed_units"]:
            print(f"    {u['id']}  owns {u['owns']}", file=sys.stderr)
    else:
        print("\n  no unit is claimed at all.", file=sys.stderr)
    print(f"\n  {report['next']}\n", file=sys.stderr)
    return REFUSE


if __name__ == "__main__":
    raise SystemExit(main())
