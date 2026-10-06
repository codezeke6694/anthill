"""Make the owner's page start with the app (owner, 6 Oct 2026).

The page only runs if something starts it. LogiAstro's run.sh did, by hand;
a project installed afterwards had nothing, and the owner found no page at
all. So Anthill puts one guarded line into the project's own start command:

    run.sh / start.sh / dev.sh   a line after the shebang
    package.json  "dev"          a prefix to the script

`--with-parent $$` ties the page to the app: it comes up with it, goes down
with it, and each start prints a fresh key in the owner's terminal. The line
does nothing on a laptop without Anthill, so a teammate who never installed
it starts the app exactly as before.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from anthill import context as _ctx

MARK = "ui start --detach"
SHELL_SCRIPTS = ("run.sh", "start.sh", "dev.sh")
NPM_SCRIPTS = ("dev", "start")


def _cmd(ctx: _ctx.Context, shell: bool) -> str:
    """How the start command reaches Anthill: inside the project, by a path
    relative to it; installed from outside, by its full path."""
    from anthill import install as inst
    rel = inst.invocation(ctx)
    if not rel.startswith("./"):
        return rel
    return '"$(cd "$(dirname "$0")" && pwd)/' + rel[2:] + '"' if shell else rel


def detect(ctx: _ctx.Context) -> dict[str, Any]:
    for name in SHELL_SCRIPTS:
        p = ctx.root / name
        if p.is_file():
            return {"kind": "shell", "file": name, "wired": MARK in p.read_text(encoding="utf-8", errors="replace")}
    pj = ctx.root / "package.json"
    if pj.is_file():
        try:
            scripts = json.loads(pj.read_text(encoding="utf-8")).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        for name in NPM_SCRIPTS:
            if name in scripts:
                return {"kind": "npm", "file": "package.json", "script": name,
                        "wired": MARK in str(scripts[name])}
    return {"kind": None, "wired": False}


def wire(ctx: _ctx.Context, write: bool = True) -> dict[str, Any]:
    found = detect(ctx)
    if found["kind"] is None:
        return {**found, "why": "no start script (run.sh, start.sh, dev.sh, or a dev/start script "
                "in package.json); start the page from your terminal: anthill ui start --detach"}
    if found["wired"]:
        return {**found, "changed": False}
    if found["kind"] == "shell":
        p = ctx.root / found["file"]
        text = p.read_text(encoding="utf-8")
        cmd = _cmd(ctx, shell=True)
        block = ("# Anthill's owner page: up with the app, down with it, a fresh key each start.\n"
                 f"# Added by `anthill ui wire`; does nothing where Anthill is not installed.\n"
                 f"[ -x {cmd} ] && {cmd} ui start --detach --with-parent $$ || true\n")
        lines = text.splitlines(keepends=True)
        at = 1 if lines and lines[0].startswith("#!") else 0
        while at < len(lines) and re.match(r"\s*(set\s+-|#)", lines[at]):
            at += 1
        new = "".join(lines[:at]) + block + "".join(lines[at:])
        if write:
            p.write_text(new, encoding="utf-8")
        return {**found, "changed": True, "wired": True, "added": block.splitlines()[-1]}
    p = ctx.root / "package.json"
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    cmd = _cmd(ctx, shell=False)
    old = data["scripts"][found["script"]]
    data["scripts"][found["script"]] = f"(test -x {cmd} && {cmd} ui start --detach --with-parent $$ || true); {old}"
    m = re.search(r'\n(\s+)"', raw)
    indent = len(m.group(1)) if m else 2
    if write:
        p.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + ("\n" if raw.endswith("\n") else ""),
                     encoding="utf-8")
    return {**found, "changed": True, "wired": True, "added": data["scripts"][found["script"]]}
