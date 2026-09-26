"""Structural fingerprinting — the mechanism that makes a claim falsifiable.

A *claim* is any recorded statement about a symbol: a map anchor's address, a
knowledge page's business rule, a work unit's owned surface. Every such claim
goes stale silently, because nothing re-checks it when the tree moves.

This module gives one deterministic answer to "has the thing I cited changed
shape?" It follows DESIGN.md section 6: the fingerprint covers the normalized
signature plus the sorted callee and caller sets, and **deliberately excludes
the body**.

    Edit a formula inside a function  -> body changes, fingerprint holds
                                      -> CONTENT change, no claim is stale
    Rename / re-sign / re-wire it     -> fingerprint breaks
                                      -> STRUCTURAL change, claims need review

That single distinction is the whole staleness policy: weeks of ordinary edits
touch nothing, while a change that could invalidate a recorded statement is
caught mechanically. No model calls, at build time or query time (P1).

The fingerprint is stored in three parts rather than one opaque digest, so
drift can be *attributed* — a changed signature and a changed caller set mean
very different things to the agent reading the result.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

from anthill import context as _ctx
REPO_ROOT = _ctx.current().root

# Kept in step with build_map.py: the fingerprint's caller index must scan the
# same active set the map was built from, or callers look spuriously deleted.
# The active source set comes from the installation's config (or first-run
# discovery), never from constants: hardcoding one project's directory names is
# exactly what made the ported version unusable in any other repository.
_conf = _ctx.current()
INCLUDE_DIRS, INCLUDE_TOPLEVEL, EXCLUDE_PARTS = _conf.source_roots()

_SYMBOL_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# Drift kinds, ordered most to least threatening to a recorded claim.
DRIFT_MISSING = "missing"            # symbol is gone entirely
DRIFT_MOVED = "moved"                # same name, different file
DRIFT_RESHAPED = "reshaped"          # signature changed — the contract moved
DRIFT_REWIRED = "rewired"            # callee set changed — it does other things now
DRIFT_RECONTEXTUALIZED = "recontextualized"  # caller set changed — impact moved
DRIFT_NONE = "verified"

_SEVERITY = {
    DRIFT_MISSING: 4,
    DRIFT_MOVED: 3,
    DRIFT_RESHAPED: 3,
    DRIFT_REWIRED: 2,
    DRIFT_RECONTEXTUALIZED: 1,
    DRIFT_NONE: 0,
}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def active_files() -> list[Path]:
    """Every source file the fingerprint is allowed to look at."""
    out: list[Path] = []
    for d in INCLUDE_DIRS:
        base = REPO_ROOT / d
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if EXCLUDE_PARTS & set(path.parts):
                continue
            out.append(path)
    for name in INCLUDE_TOPLEVEL:
        path = REPO_ROOT / name
        if path.exists():
            out.append(path)
    return sorted(out)


def split_symbol_id(symbol_id: str) -> tuple[str, str]:
    if "::" not in symbol_id:
        raise ValueError(f"symbol id must look like path/to/file.py::name: {symbol_id}")
    file_part, symbol_name = symbol_id.split("::", 1)
    return file_part, symbol_name


# --------------------------------------------------------------------------
# normalized signature — the contract, without the implementation
# --------------------------------------------------------------------------

def _annotation(node: ast.AST | None) -> str:
    # ast.unparse is what makes this *normalized*: dict[str,Any] and
    # dict[str, Any] collapse to one string, so reformatting is not drift.
    return "" if node is None else ast.unparse(node)


def _arg_spec(args: ast.arguments) -> str:
    parts: list[str] = []
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    n_defaults = len(args.defaults)
    first_defaulted = len(positional) - n_defaults
    for i, arg in enumerate(positional):
        has_default = i >= first_defaulted
        parts.append(f"{arg.arg}:{_annotation(arg.annotation)}{'=' if has_default else ''}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}:{_annotation(args.vararg.annotation)}")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(f"{arg.arg}:{_annotation(arg.annotation)}{'=' if default is not None else ''}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}:{_annotation(args.kwarg.annotation)}")
    return ",".join(parts)


def normalized_signature(node: ast.AST) -> str:
    """The symbol's public contract as a stable string. Body excluded."""
    decorators = sorted(ast.unparse(d) for d in getattr(node, "decorator_list", []))
    if isinstance(node, ast.ClassDef):
        bases = sorted(ast.unparse(b) for b in node.bases)
        # A class's contract is its method surface: names and arity, never bodies.
        methods = sorted(
            f"{m.name}/{len(getattr(m, 'args').args)}"
            for m in node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        return f"class {node.name}({','.join(bases)})[{','.join(decorators)}]{{{','.join(methods)}}}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = _annotation(getattr(node, "returns", None))
    return f"{prefix} {node.name}({_arg_spec(node.args)})->{returns}[{','.join(decorators)}]"


def callee_names(node: ast.AST) -> list[str]:
    """Sorted set of names this symbol calls. The *set*, never the body text."""
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return sorted(names)


# --------------------------------------------------------------------------
# caller index — who calls a given name, repo-wide
# --------------------------------------------------------------------------

_CALLER_INDEX: dict[str, list[str]] | None = None


def caller_index(refresh: bool = False) -> dict[str, list[str]]:
    """Map called-name -> sorted enclosing symbol ids, over the active set.

    Name-based and therefore an over-approximation: two functions sharing a
    name share callers here. That is a deliberate trade — it is deterministic,
    needs one pass over the tree, and over-approximation errs toward flagging a
    claim for review rather than passing a stale one.
    """
    global _CALLER_INDEX
    if _CALLER_INDEX is not None and not refresh:
        return _CALLER_INDEX
    index: dict[str, set[str]] = {}
    for path in active_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for top in tree.body:
            if not isinstance(top, _SYMBOL_NODES):
                continue
            holder = f"{rel}::{top.name}"
            for name in callee_names(top):
                index.setdefault(name, set()).add(holder)
    _CALLER_INDEX = {k: sorted(v) for k, v in index.items()}
    return _CALLER_INDEX


# --------------------------------------------------------------------------
# fingerprint
# --------------------------------------------------------------------------

def _locate(file_part: str, symbol_name: str) -> tuple[ast.AST | None, str]:
    path = REPO_ROOT / file_part
    if not path.exists():
        return None, f"file not found: {file_part}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return None, f"could not parse {file_part}: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, _SYMBOL_NODES) and node.name == symbol_name:
            return node, ""
    return None, f"symbol not found: {file_part}::{symbol_name}"


def find_elsewhere(symbol_name: str, exclude_file: str = "") -> list[str]:
    """Scoped relocation search: where else does this symbol name now live?"""
    hits: list[str] = []
    for path in active_files():
        rel = str(path.relative_to(REPO_ROOT))
        if rel == exclude_file:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, _SYMBOL_NODES) and node.name == symbol_name:
                hits.append(f"{rel}::{symbol_name}")
                break
    return sorted(hits)


def _script_fingerprint(file_part: str, symbol_name: str) -> dict[str, Any]:
    """A frontend symbol: its declaration line stands in for a signature.

    There is no callee or caller set without a real parser, so a TS claim can
    go stale by vanishing or by being re-declared, never by being rewired.
    """
    from anthill.navigate import scripts
    path = REPO_ROOT / file_part
    if not path.exists():
        return {"exists": False, "reason": f"file not found: {file_part}"}
    hit = scripts.locate(path, symbol_name)
    if hit is None:
        return {"exists": False, "reason": f"symbol not found: {file_part}::{symbol_name}"}
    return {"exists": True, "file": file_part, "symbol": symbol_name, "kind": "script",
            **hit, "hash": hit["sig"]}


def is_script(file_part: str) -> bool:
    from anthill.navigate import scripts
    return Path(file_part).suffix in scripts.SUFFIXES


def fingerprint(symbol_id: str, with_callers: bool = True) -> dict[str, Any]:
    """Structural fingerprint of one symbol, or an explanation of its absence.

    `with_callers=False` skips the repo-wide index. Use it on the card path,
    where only the symbol's own contract matters and latency does; `verify`
    uses the full three-part fingerprint.
    """
    file_part, symbol_name = split_symbol_id(symbol_id)
    if is_script(file_part):
        return _script_fingerprint(file_part, symbol_name)
    node, reason = _locate(file_part, symbol_name)
    if node is None:
        return {"exists": False, "reason": reason}
    sig = normalized_signature(node)
    callees = callee_names(node)
    out: dict[str, Any] = {
        "exists": True,
        "file": file_part,
        "symbol": symbol_name,
        "kind": node.__class__.__name__,
        "line_start": node.lineno,
        "line_end": getattr(node, "end_lineno", node.lineno),
        "sig": _digest(sig),
        "callees": _digest("|".join(callees)),
    }
    if with_callers:
        callers = caller_index().get(symbol_name, [])
        out["callers"] = _digest("|".join(callers))
        out["hash"] = _digest(out["sig"] + out["callees"] + out["callers"])
    return out


def compare(recorded: dict[str, Any] | None, live: dict[str, Any]) -> dict[str, Any]:
    """Attribute the drift between a recorded fingerprint and the live tree."""
    if not live.get("exists"):
        file_part = recorded.get("file", "") if recorded else ""
        symbol = recorded.get("symbol", "") if recorded else ""
        elsewhere = find_elsewhere(symbol, exclude_file=file_part) if symbol else []
        if elsewhere:
            return {
                "drift": DRIFT_MOVED,
                "severity": _SEVERITY[DRIFT_MOVED],
                "detail": f"no longer at {file_part}",
                "relocation": elsewhere,
            }
        return {
            "drift": DRIFT_MISSING,
            "severity": _SEVERITY[DRIFT_MISSING],
            "detail": live.get("reason", "not found"),
            "relocation": [],
        }
    if not recorded:
        # Nothing was recorded, so nothing can be contradicted. The live
        # fingerprint becomes the baseline rather than a pass or a failure.
        return {
            "drift": "unpinned",
            "severity": 0,
            "detail": "no recorded fingerprint; live shape captured as baseline",
            "relocation": [],
        }
    for key, kind, detail in (
        ("sig", DRIFT_RESHAPED, "signature changed — statements about its contract need review"),
        ("callees", DRIFT_REWIRED, "callee set changed — it now does different work"),
        ("callers", DRIFT_RECONTEXTUALIZED, "caller set changed — impact surface moved"),
    ):
        if key in recorded and key in live and recorded[key] != live[key]:
            return {"drift": kind, "severity": _SEVERITY[kind], "detail": detail, "relocation": []}
    return {"drift": DRIFT_NONE, "severity": 0, "detail": "structure unchanged", "relocation": []}

def fingerprint_at_commit(symbol_id: str, sha: str, repo: Path | None = None) -> dict[str, Any]:
    """Fingerprint a symbol as it was at a past commit.

    This is what turns a knowledge page's `verified_against: prefix@sha` from a
    note into a check: read the cited symbol at the commit a human verified it
    at, fingerprint that, and compare with the tree now. Only the signature and
    callee set are computed — the caller set would need the whole tree at that
    commit, and says nothing about the symbol's own contract anyway.
    """
    import subprocess

    file_part, symbol_name = split_symbol_id(symbol_id)
    if is_script(file_part):
        return {"exists": False, "reason": "frontend symbols are not fingerprinted at a past commit"}
    try:
        proc = subprocess.run(
            ["git", "show", f"{sha}:{file_part}"],
            cwd=str(repo or REPO_ROOT), capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"exists": False, "reason": f"could not read {file_part} at {sha}: {exc}"}
    if proc.returncode != 0:
        return {"exists": False, "reason": f"{file_part} not present at {sha}"}
    try:
        tree = ast.parse(proc.stdout)
    except SyntaxError as exc:
        return {"exists": False, "reason": f"could not parse {file_part} at {sha}: {exc}"}
    for node in ast.walk(tree):
        if isinstance(node, _SYMBOL_NODES) and node.name == symbol_name:
            return {
                "exists": True,
                "file": file_part,
                "symbol": symbol_name,
                "sig": _digest(normalized_signature(node)),
                "callees": _digest("|".join(callee_names(node))),
            }
    return {"exists": False, "reason": f"symbol not found at {sha}: {symbol_id}"}
