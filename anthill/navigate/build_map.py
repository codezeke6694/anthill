#!/usr/bin/env python3
"""Deterministic Emergent Agent map builder for the whole active codebase.

Implements the offline build pipeline (spec stages 1/2/4) with ZERO inference:
  1. Symbol extraction  -- ast over every active .py file.
  2. Edge extraction    -- within-repo import graph (module -> module).
  3. Node grouping      -- one responsibility node per module (behaviour boundary).
  4. Route derivation   -- lift import edges to node-level routes + consumers.
  5. Persist            -- emit maps/codebase.json in the same schema the CLI reads.

No models, no embeddings, no task memory (principles P1/P3). The map is a pure
function of the working tree, fully rebuildable: re-run this script.

Usage:  anthill map build           # writes maps/codebase.json
        anthill map build --stats   # also print a summary
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Run either as a script (`anthill`) or as a module
# (`python -m anthill.cli`); the documented form is the script, which does not
# put the repo root on sys.path by itself.
import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill import context as _ctx
from anthill.knowledge import claims
from anthill.navigate import structure

# The project the tool was pointed at -- not the directory the tool lives in.
_conf = _ctx.current()
REPO_ROOT = _conf.root
# Generated output belongs to the project's state dir, never inside the
# installed tool: two projects sharing one install must not share one map.
OUT_PATH = _conf.state / "build" / "maps" / "codebase.json"

# The active source set comes from the installation's config, or from first-run
# discovery when it is empty. Hardcoding one project's directory names is what
# made the ported version unusable in any repository but its own.
INCLUDE_DIRS, INCLUDE_TOPLEVEL, EXCLUDE_PARTS = _conf.source_roots()

# Short, readable node-id prefixes per top package. Unset means "use the
# directory name", which `_district()` already falls back to.
PREFIX: dict[str, str] = (_conf.config.get("source") or {}).get("district_prefix") or {}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "into", "is", "it", "its", "of", "on", "or", "que", "return", "returns",
    "self", "that", "the", "then", "this", "to", "was", "were", "when", "which",
    "with", "each", "one", "row", "rows", "use", "used", "using", "via", "not",
    "no", "if", "per", "any", "all", "e", "g", "i", "true", "false", "none",
}


def _active_files() -> list[Path]:
    files: list[Path] = []
    for d in INCLUDE_DIRS:
        base = REPO_ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if EXCLUDE_PARTS & set(p.relative_to(REPO_ROOT).parts):
                continue
            files.append(p)
    for name in INCLUDE_TOPLEVEL:
        p = REPO_ROOT / name
        if p.exists():
            files.append(p)
    return sorted(files)


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


def _dotted(rel: str) -> str:
    """Python import path for a file: a/b/c.py -> a.b.c ; a/b/__init__.py -> a.b"""
    d = rel[:-3] if rel.endswith(".py") else rel
    d = d.replace("/", ".")
    return d[:-9] if d.endswith(".__init__") else d


def _node_id(rel: str) -> str:
    dotted = _dotted(rel)
    top = dotted.split(".", 1)[0]
    rest = dotted[len(top):]
    return PREFIX.get(top, top) + rest


def _split_words(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return [w for w in re.findall(r"[a-z0-9]+", text.replace("_", " ").lower())
            if w not in STOPWORDS and len(w) > 1]


def _extract(path: Path) -> dict[str, Any] | None:
    rel = _rel(path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None
    mod_doc = (ast.get_docstring(tree) or "").strip()
    symbols: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = (ast.get_docstring(node) or "").strip()
            symbols.append({
                "name": node.name,
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "public": not node.name.startswith("_"),
                "doc_first": doc.splitlines()[0] if doc else "",
            })
    imports = _imports(tree)
    return {"rel": rel, "dotted": _dotted(rel), "mod_doc": mod_doc,
            "symbols": symbols, "imports": imports}


def _imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.add(node.module)
                for a in node.names:
                    out.add(f"{node.module}.{a.name}")
    return out


def _responsibility(mod: dict[str, Any]) -> str:
    if mod["mod_doc"]:
        first = mod["mod_doc"].splitlines()[0].strip()
        if first:
            return first if len(first) <= 240 else first[:237] + "..."
    pubs = [s for s in mod["symbols"] if s["public"]]
    nfun = sum(1 for s in pubs if s["kind"] == "function")
    ncls = sum(1 for s in pubs if s["kind"] == "class")
    name = mod["dotted"].split(".")[-1]
    return f"{name} module -- {nfun} function(s), {ncls} class(es)."


def _lexical_signature(mod: dict[str, Any]) -> list[str]:
    counter: Counter = Counter()
    # Path segments and symbol names are the strongest, always-included signal.
    strong: list[str] = []
    for seg in mod["dotted"].split("."):
        strong.extend(_split_words(seg))
    for s in mod["symbols"]:
        if s["public"]:
            strong.extend(_split_words(s["name"]))
    # Docstring words are supporting signal, ranked by frequency.
    for w in _split_words(mod["mod_doc"]):
        counter[w] += 1
    for s in mod["symbols"]:
        for w in _split_words(s["doc_first"]):
            counter[w] += 1
    sig: list[str] = []
    seen: set[str] = set()
    for w in strong + [w for w, _ in counter.most_common(40)]:
        if w not in seen:
            seen.add(w)
            sig.append(w)
    return sig[:28]


def _anchors(mod: dict[str, Any]) -> list[dict[str, Any]]:
    pubs = [s for s in mod["symbols"] if s["public"]]
    chosen = pubs or mod["symbols"]
    # Classes first (usually the behaviour boundary), then functions; cap for card size.
    chosen = sorted(chosen, key=lambda s: (s["kind"] != "class",))
    out: list[dict[str, Any]] = []
    for sym in chosen[:10]:
        symbol_id = f"{mod['rel']}::{sym['name']}"
        anchor: dict[str, Any] = {"symbol_id": symbol_id, "role": sym["kind"]}
        # The recorded fingerprint is what lets a later run tell a harmless body
        # edit from a change that invalidates anything citing this address.
        fp = structure.fingerprint(symbol_id)
        if fp.get("exists"):
            anchor["struct"] = {k: fp[k] for k in ("file", "symbol", "sig", "callees", "callers", "hash")
                                if k in fp}
        out.append(anchor)
    return out


def build() -> dict[str, Any]:
    mods = [m for m in (_extract(p) for p in _active_files()) if m]
    # Modules with no defined symbols (e.g. empty __init__) are containers, not
    # navigation locations -- skip them (spec: functions are addresses).
    mods = [m for m in mods if m["symbols"]]

    dotted_to_node = {m["dotted"]: _node_id(m["rel"]) for m in mods}
    node_ids = set(dotted_to_node.values())

    def resolve(imp: str) -> str | None:
        # Longest-prefix match: "al.validation.pii.foo" -> node for al.validation.pii
        parts = imp.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in dotted_to_node:
                return dotted_to_node[cand]
        return None

    downstream: dict[str, set[str]] = defaultdict(set)  # node -> nodes it imports
    upstream: dict[str, set[str]] = defaultdict(set)     # node -> nodes importing it
    resp_by_node: dict[str, str] = {}
    for m in mods:
        nid = _node_id(m["rel"])
        resp_by_node[nid] = _responsibility(m)
    for m in mods:
        nid = _node_id(m["rel"])
        for imp in m["imports"]:
            tgt = resolve(imp)
            if tgt and tgt != nid:
                downstream[nid].add(tgt)
                upstream[tgt].add(nid)

    nodes: list[dict[str, Any]] = []
    for m in sorted(mods, key=lambda x: x["rel"]):
        nid = _node_id(m["rel"])
        dotted = m["dotted"]
        district = ".".join(nid.split(".")[:-1]) or nid
        routes = [
            {"when": f"Depends on {tid.split('.')[-1]}: {resp_by_node.get(tid, '')[:80]}",
             "go_to": tid}
            for tid in sorted(downstream[nid])[:6]
        ]
        nodes.append({
            "node_id": nid,
            "responsibility": _responsibility(m),
            "district": district,
            "lexical_signature": _lexical_signature(m),
            "anchors": _anchors(m),
            "arrive_when": [
                f"Locating or fixing behaviour owned by {dotted.split('.')[-1]} ({m['rel']}).",
                f"A symbol defined in {m['rel']} is wrong or is being traced.",
            ],
            "routes": routes,
            "tests": [],
            "consumers": sorted(upstream[nid])[:10],
        })

    return {
        "map_id": "codebase_v1",
        "name": "Whole active codebase (auto-generated, deterministic)",
        "scope": " + ".join(INCLUDE_DIRS + INCLUDE_TOPLEVEL) or "(no source discovered)",
        "generated_by": "anthill/navigate/build_map.py",
        "built_at_commit": claims.head_commit(),
        "principles": [
            "Return one navigation card at a time.",
            "Use the map for addresses and routes only.",
            "Read live source before editing.",
            "Auto-generated: module-granularity nodes, import-derived routes.",
        ],
        "nodes": sorted(nodes, key=lambda n: n["node_id"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the whole-codebase blueprint")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args(argv)
    m = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(m, indent=2), encoding="utf-8")
    nodes = m["nodes"]
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} -- {len(nodes)} nodes")
    if args.stats:
        anchors = sum(len(n["anchors"]) for n in nodes)
        routes = sum(len(n["routes"]) for n in nodes)
        by_district: Counter = Counter(n["district"].split(".")[0] for n in nodes)
        print(f"  anchors: {anchors}   routes: {routes}")
        print("  nodes by top package:", dict(sorted(by_district.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
