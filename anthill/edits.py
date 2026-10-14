"""Claude's check before every edit: one hook, two refusals (owner, 13 Oct 2026).

Both used to be caught only afterwards, when the work was already done:

  * a database change -- at the commit, after the dev server had already run
    it (`risky`);
  * a helper writing outside its piece's files -- at the referee, which then
    sends the whole branch back.

Refusing at the edit costs the chat one message instead of a wasted branch. The
checks after the fact stay: they catch what this cannot see (a shell command
writing a file, another tool, an edit made before the hook existed).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from anthill import context as _ctx
from anthill import risky

PIECE_PREFIX = "piece/"


def _git(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def piece_for(cwd: Path) -> tuple[str, dict[str, Any], Path] | None:
    """The piece a helper is building here, from its branch: piece/<sprint>/<piece>.

    The sprint page is read from the main checkout, where the lead planned it;
    a helper's own copy may have branched before the page was committed."""
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch.startswith(PIECE_PREFIX) or branch.count("/") != 2:
        return None
    _, sid, pid = branch.split("/")
    top = Path(_git(cwd, "rev-parse", "--show-toplevel") or cwd)
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    roots = [Path(common).parent] if common else []
    roots.append(top)
    from anthill.sprint import page as sp
    for root in roots:
        try:
            ctx = _ctx.resolve(root)
            g = sp.load(ctx, sid)
        except (SystemExit, Exception):            # noqa: BLE001 -- no sprint here: try the next
            continue
        piece = next((p for p in g.get("pieces") or [] if p.get("id") == pid), None)
        if piece:
            return sid, piece, top
    return None


def piece_hook(data: dict[str, Any]) -> dict[str, Any] | None:
    """Refuse an edit outside the files this helper's piece owns."""
    if data.get("tool_name") not in risky.EDIT_TOOLS:
        return None
    inp = data.get("tool_input") or {}
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    if not path:
        return None
    cwd = Path(data.get("cwd") or Path.cwd())
    found = piece_for(cwd)
    if not found:
        return None
    sid, piece, top = found
    p = Path(path)
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(top.resolve()).as_posix()
        except ValueError:
            return None                              # outside the repository: not the referee's concern
    else:
        rel = p.as_posix()
    from anthill.sprint import parallel
    if parallel.owns(piece, rel):
        return None
    reason = (f"Refused: {rel} is outside this piece. `{piece['id']}` owns "
              f"{', '.join(piece.get('owns') or [])}, and the referee sends back a branch that "
              f"changes anything else. If the piece really needs this file, stop and say so: "
              f"anthill sprint ask {sid} {piece['id']} \"<why it needs {rel}>\" -- the lead re-plans.")
    from anthill import trail
    trail.record("piece_refused", None, session=str(data.get("session_id") or ""),
                 sprint=sid, piece=piece["id"], file=rel)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def hook(ctx: _ctx.Context, data: dict[str, Any]) -> dict[str, Any] | None:
    return (risky.hook(ctx, data) if ctx.installed else None) or piece_hook(data)


def main(argv: list[str]) -> int:
    """`anthill edit --hook`: read Claude's tool call on stdin, print a refusal or nothing."""
    try:
        data = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
        cwd = Path(data.get("cwd") or Path.cwd())
        out = hook(_ctx.resolve(cwd), data)
    except Exception:                                # noqa: BLE001 -- a hook fault must never block work
        return 0
    if out:
        print(json.dumps(out))
    return 0
