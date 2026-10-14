"""Cheap checks on what a commit added (owner, 13 Oct 2026; AutoDev's checks).

Run by the post-commit hook and printed to the terminal that committed, where
the chat that wrote the code sees it and can fix it in the next commit. They
warn, never refuse: a line count cannot tell a long function from a long table,
and refusing would teach `--no-verify`. The rules behind them are in the
`coding-standards` skill.

  personal path   /Users/<name>/, /home/<name>/: code that runs only for its author
  long block      one run of new lines over `block_lines` (60): likely one
                  function doing several jobs
  comment-heavy   over `comment_pct` (35%) of a sizeable addition is commentary,
                  or one comment block runs over `comment_block` (8) lines

Limits are per project: `execution.code_checks` = {"block_lines": .., ...};
`false` turns the checks off. A new package is not here: it stops the commit
and asks the owner (`guard` and `risky`).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from anthill import context as _ctx

DEFAULTS = {"block_lines": 60, "comment_pct": 35, "comment_block": 8, "min_lines": 25}
CODE = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rb", ".php", ".java",
        ".kt", ".rs", ".swift", ".c", ".cc", ".cpp", ".h", ".cs", ".scala", ".sh", ".vue", ".svelte"}
PERSONAL = re.compile(r"(/Users/[A-Za-z][\w.-]*/|/home/[a-z][\w.-]*/|C:\\\\Users\\\\)")
COMMENT = re.compile(r"^\s*(#|//|/\*|\*|--|<!--|\"\"\"|''')")


def limits(ctx: _ctx.Context) -> dict[str, int] | None:
    cfg = (ctx.config.get("execution") or {}).get("code_checks", {})
    if cfg is False:
        return None
    return {**DEFAULTS, **(cfg if isinstance(cfg, dict) else {})}


def _diff(root: Path, rev: str) -> str:
    args = ["git", "show", "--format=", "--unified=0", "--no-color", rev]
    try:
        r = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _added(diff: str) -> dict[str, list[list[str]]]:
    """Added lines per code file, grouped by hunk."""
    out: dict[str, list[list[str]]] = {}
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].removeprefix("b/")
            path = p if p != "/dev/null" and Path(p).suffix in CODE else ""
        elif line.startswith("@@") and path:
            out.setdefault(path, []).append([])
        elif path and line.startswith("+") and out.get(path):
            out[path][-1].append(line[1:])
    return out


def _longest(lines: list[str], keep) -> int:
    best = run = 0
    for ln in lines:
        run = run + 1 if keep(ln) else 0
        best = max(best, run)
    return best


def check(ctx: _ctx.Context, rev: str = "HEAD") -> list[dict[str, str]]:
    lim = limits(ctx)
    if lim is None:
        return []
    found: list[dict[str, str]] = []
    for path, hunks in _added(_diff(ctx.root, rev)).items():
        lines = [ln for h in hunks for ln in h]
        hits = [ln.strip() for ln in lines if PERSONAL.search(ln)]
        if hits:
            found.append({"check": "personal path", "file": path,
                          "detail": f"names a personal path: {hits[0][:80]}"})
        block = max((_longest(h, lambda s: s.strip() != "") for h in hunks), default=0)
        if block > lim["block_lines"]:
            found.append({"check": "long block", "file": path,
                          "detail": f"one new block runs {block} lines (over {lim['block_lines']}): "
                                    "probably one function doing several jobs"})
        comments = sum(1 for ln in lines if COMMENT.match(ln))
        run = max((_longest(h, lambda s: bool(COMMENT.match(s))) for h in hunks), default=0)
        if len(lines) >= lim["min_lines"] and comments * 100 > lim["comment_pct"] * len(lines):
            found.append({"check": "comment-heavy", "file": path,
                          "detail": f"{comments} of {len(lines)} new lines are comments "
                                    f"(over {lim['comment_pct']}%)"})
        elif run > lim["comment_block"]:
            found.append({"check": "comment-heavy", "file": path,
                          "detail": f"one comment block runs {run} lines (over {lim['comment_block']})"})
    return found


def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        return 0
    rev = next((a for a in argv if not a.startswith("-")), "HEAD")
    found = check(ctx, rev)
    if found:
        from anthill import trail
        trail.record("codecheck", ctx, found=[f"{f['check']}: {f['file']}" for f in found])
        print(f"anthill codecheck: {len(found)} thing(s) to look at in this commit "
              "(the coding-standards skill says why):")
        for f in found:
            print(f"  - {f['check']}: {f['file']} -- {f['detail']}")
    return 0
