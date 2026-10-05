"""Which Anthill a project uses, so a whole team runs the same one.

The owner, 5 Oct: Anthill lives in its own repository; each project pulls a
copy into itself, and "for the team it stays in sync". The project's shared
settings (`owner/settings.json`, which travels with its git) record the commit
of Anthill the team uses. `anthill update` brings this laptop's copy to that
commit; `anthill update --latest`, which the owner runs, moves the team forward
by pulling the newest Anthill and recording it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from anthill import context as _ctx

TOOL_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(TOOL_ROOT), *args], capture_output=True,
                           text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return r.returncode, (r.stdout + r.stderr).strip()


def here() -> str:
    """The commit this copy of Anthill is at, or '' if it is not a git checkout."""
    rc, out = _git("rev-parse", "--short=12", "HEAD")
    return out if rc == 0 else ""


def pinned(ctx: _ctx.Context) -> str:
    return str((ctx.config.get("anthill") or {}).get("version") or "")


def status(ctx: _ctx.Context) -> dict:
    h, p = here(), pinned(ctx)
    return {"here": h, "team": p,
            "same": bool(h and p and (h.startswith(p) or p.startswith(h)))}


def go_to(ctx: _ctx.Context, latest: bool = False) -> dict:
    """Move this copy to the team's commit, or (`latest`) to the newest one."""
    rc, out = _git("fetch", "--quiet", "origin")
    if rc != 0:
        return {"moved": False, "why": f"could not reach Anthill's repository: {out[-300:]}"}
    if latest:
        rc, branch = _git("rev-parse", "--abbrev-ref", "origin/HEAD")
        target = branch if rc == 0 and branch != "origin/HEAD" else "origin/main"
    else:
        target = pinned(ctx)
        if not target:
            return {"moved": False, "why": "this project records no Anthill version yet; "
                    "the owner sets one with `anthill update --latest`"}
    rc, out = _git("checkout", "--quiet", "--detach", target)
    if rc != 0:
        return {"moved": False, "why": f"could not check out {target}: {out[-300:]}"}
    return {"moved": True, "now": here(), "target": target}
