"""Tests judged by name (owner, 13 Oct 2026; the idea is AutoDev's).

A test already broken before a sprint failed its check, though the sprint broke
nothing -- so chats learned to ignore red. Now a sprint notes which tests its
check already fails when it starts, and at the end only a *new* name blocks.

Counting is not enough: fix one old failure and break one new test and the
count is unchanged. Names are compared instead. Output whose failures cannot be
named never passes on this rule; it fails as before.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from typing import Any

BASELINE_TIMEOUT = 300

_PATTERNS = [
    re.compile(r"^(?:FAILED|ERROR)\s+(\S+::\S+)", re.M),                 # pytest summary
    re.compile(r"^(?:FAIL|ERROR):\s+(\S+\s+\([\w.]+\))", re.M),          # unittest
    re.compile(r"^\s*(?:✕|×|✗)\s+(.+?)(?:\s+\(\d+\s*m?s\))?\s*$", re.M),  # jest, vitest
    re.compile(r"^\s*--- FAIL:\s+(\S+)", re.M),                          # go test
    re.compile(r"^not ok\s+\d+\s+-?\s*(.+?)\s*(?:#.*)?$", re.M),         # TAP
    re.compile(r"^\s{2}\d+\)\s+(.+?)\s*:?\s*$", re.M),                   # mocha "  1) suite name"
]
_FAILED_FILE = re.compile(r"^\s*FAIL\s+(\S+\.(?:[jt]sx?|mjs|cjs))\b", re.M)  # jest/vitest file line


def failing(output: str) -> set[str]:
    """The names of the failing tests in a run's output; empty when none can be named."""
    names: set[str] = set()
    for pat in _PATTERNS:
        names.update(m.strip() for m in pat.findall(output or "") if m.strip())
    if not names:                       # a test file that failed to load names no test
        names.update(f"{f} (file)" for f in _FAILED_FILE.findall(output or ""))
    return names


def run(cmd: str, cwd, timeout: int) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return False, ""


def baseline(ctx, cmd: str, timeout: int = BASELINE_TIMEOUT) -> dict[str, Any]:
    """Run the check before any change: what already fails, by name."""
    t = datetime.now().astimezone().isoformat(timespec="seconds")
    if not cmd.strip():
        return {}
    ok, out = run(cmd, ctx.root, timeout)
    if ok:
        return {"t": t, "check": cmd, "passed": True, "failing": []}
    names = sorted(failing(out))
    return {"t": t, "check": cmd, "passed": False, "failing": names,
            "named": bool(names), "timed_out": not out}


def judge(base: dict[str, Any] | None, cmd: str, ok: bool, output: str) -> dict[str, Any]:
    """Pass or fail on names: a failure already there at the start does not block."""
    old = set((base or {}).get("failing") or [])
    if (base or {}).get("check") not in (None, cmd):
        old = set()                     # the check changed since; its old names prove nothing
    now = set() if ok else failing(output)
    fixed = sorted(old - now) if (ok or now) else []
    if ok:
        return {"passed": True, "fixed": fixed, "still_failing": []}
    if now and now <= old:
        return {"passed": True, "fixed": fixed, "still_failing": sorted(now)}
    return {"passed": False, "fixed": fixed, "new_failures": sorted(now - old)}
