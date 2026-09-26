#!/usr/bin/env python3
"""Small deterministic Emergent Agent CLI for agent navigation.

This is intentionally a v0 helper:
- no model calls
- no embeddings
- no task memory persisted
- live symbol reads from the current working tree
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any


# Run either as a script (`anthill`) or as a module
# (`python -m anthill.cli`); the documented form is the script, which does not
# put the repo root on sys.path by itself.
import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.knowledge import claims
from anthill.navigate import structure

PKG_DIR = claims.PKG_DIR
MAPS_DIR = claims.MAPS_DIR
BUILD_DIR = claims.BUILD_DIR
GEN_MAPS_DIR = claims.GEN_MAPS_DIR
CATALOGUE_DIR = claims.CATALOGUE_DIR
WORK_ROOT = claims.WORK_ROOT

# The knowledge base lives inside the package, so every plane ships together and
# no command needs to be told where intent is kept. Defined in claims.py so the
# CLI, the ledger and the tests cannot disagree about the location.
KNOWLEDGE_DIR = claims.KNOWLEDGE_DIR
from anthill.knowledge import pages as pages_mod
from anthill.orchestrate import board as board_mod
from anthill.knowledge import harvest as harvest_mod
from anthill.knowledge import readiness as readiness_mod
from anthill.orchestrate import orchestrator as work_mod
from anthill.knowledge import scaffold as kb_mod
from anthill.orchestrate import pool as pool_mod
from anthill.knowledge import evaluate as eval_mod

from anthill import context as _ctx
REPO_ROOT = _ctx.current().root
# Layout comes from claims.py, the lowest-level module that needs it, so the CLI
# and the ledger cannot disagree about where anything lives.

# Restrict navigation to a single map file (basename without .json) when set;
# otherwise all maps in maps/ are merged. Set once per process from --map.
_MAP_FILTER: str | None = None
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "does", "for",
    "from", "has", "have", "how", "in", "into", "is", "it", "of", "on", "or",
    "que", "that", "the", "then", "this", "to", "was", "were", "what", "when",
    "where", "which", "why", "with",
}
# The words a person wraps around a request. Measured: "the weather along a
# road -- where do we go and fetch it?" went to the place-name lookup because
# "we" scored, and the weather collector came fourth. A query is asked in
# conversation and the map is written in docstrings; these carry meaning in
# neither.
STOPWORDS |= {
    "i", "me", "my", "we", "us", "our", "you", "your", "they", "them", "their",
    "he", "she", "him", "her", "its", "there", "here", "these", "those",
    "am", "been", "being", "do", "did", "doing", "done", "can", "could", "would",
    "should", "shall", "will", "may", "might", "must", "need", "want", "wants",
    "like", "just", "also", "too", "very", "so", "if", "than", "about",
    "again", "any", "some", "all", "each", "every", "more", "most", "much", "many",
    "other", "own", "such", "only", "not", "no", "yes", "up", "out",
    "get", "gets", "got", "go", "goes", "going", "make", "makes", "let", "put",
    "give", "see", "look", "say", "tell", "actually", "really", "thing", "things",
    "something", "someone", "somebody", "please", "ok", "now", "still", "who",
}
# Field weights: the curated lexical_signature is the intended match surface, so
# it counts more than descriptive prose in responsibility/arrive_when.
_W_SIGNATURE = 2
_W_RESPONSIBILITY = 1
_W_ARRIVE_WHEN = 1
# The opening paragraph says why the module exists, in prose.
_W_ABOUT = 1
# Past commit subjects are the only text phrased the way work is asked for.
_W_HISTORY = 1
# BM25 params. b<1 length-normalizes so a broad node (large signature) cannot win
# on surface area alone -- the v0 failure mode where `decomposition` buried the
# precise `chunk_combination`. k1 damps term-frequency saturation.
_BM25_K1 = 1.4
_BM25_B = 0.75

# Deterministic lightweight stemmer -- suffix stripping, longest match first.
# NOT full Porter: it deliberately nails the high-frequency inflections that
# broke v0 (plural s/es, -ing, -ed, -er) so "combined"/"combines"/"combiner"/
# "combining" all collapse to the same stem as "combine". No model, no deps
# (principle P1: zero query-time inference).
_SUFFIXES = (
    "izations", "ization", "isations", "isation", "ications", "ication",
    "ements", "ement", "ations", "ation", "ators", "ator", "ities", "ity",
    "ings", "ing", "edly", "ions", "ion", "ers", "er", "ies", "ied", "ical",
    "ally", "ness", "ments", "ment", "als", "es", "ed", "ly", "s",
)


def _stem(token: str) -> str:
    t = token
    if len(t) > 4:
        for suf in _SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]
                break
    # Collapse a trailing silent 'e' and a doubled final consonant so the bare
    # verb ("combine") aligns with its inflected forms ("combin-ed/-ing").
    if len(t) > 4 and t.endswith("e"):
        t = t[:-1]
    if len(t) > 4 and t[-1] == t[-2] and t[-1] not in "aeiou":
        t = t[:-1]
    return t


def _map_dirs() -> list[Path]:
    """Authored maps first, then generated -- `_nodes()` lets the first definition
    of a node_id win, so a curated map still beats a generated one."""
    return claims.map_dirs()


def _resolve_map(name: str) -> Path:
    for d in _map_dirs():
        p = d / f"{name}.json"
        if p.exists():
            return p
    raise SystemExit(f"Unknown map: {name} (looked in "
                     + ", ".join(str(d) for d in _map_dirs()) + ")")


def _map_files() -> list[Path]:
    if _MAP_FILTER:
        return [_resolve_map(_MAP_FILTER)]
    out: list[Path] = []
    for d in _map_dirs():
        out += sorted(d.glob("*.json"))
    return out


def _nodes() -> list[dict[str, Any]]:
    """Merge nodes from every selected map. Curated maps sort first, so on a
    node_id collision the curated node wins (auto ids are prefixed differently,
    so collisions are not expected in practice)."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mf in _map_files():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for node in data.get("nodes") or []:
            nid = node.get("node_id")
            if nid and nid not in seen:
                seen.add(nid)
                node = dict(node)
                node.setdefault("_map", mf.stem)
                merged.append(node)
    return merged


def _node_by_id(node_id: str) -> dict[str, Any]:
    for node in _nodes():
        if node.get("node_id") == node_id:
            return node
    raise SystemExit(f"Unknown node_id: {node_id}")


def _split_identifiers(text: str) -> str:
    """Break snake_case and camelCase so `resolve_metric`/`resolveMetric` also
    contribute their parts (`resolve`, `metric`) to matching."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return text.replace("_", " ")


def _tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", _split_identifiers(text).lower())
    return [_stem(tok) for tok in raw if tok not in STOPWORDS and len(tok) > 1]


def _node_doc(node: dict[str, Any], exclude: frozenset[str] = frozenset()) -> Counter:
    """Weighted bag-of-stems for one node.

    `exclude` drops the named commits from the node's history. It exists for
    measurement: asking the router about a past commit while that commit's own
    subject sits in the index is asking it to find the answer key.
    """
    doc: Counter = Counter()
    for tok in _tokens(node.get("about") or ""):
        doc[tok] += _W_ABOUT
    for entry in node.get("history") or []:
        if entry.get("h") in exclude:
            continue
        # Not divided by how many files the commit touched: tried, and it cost
        # seven points of top-1 on this repository's own history. A wide
        # commit's subject is still true of each file it names.
        for tok in _tokens(entry.get("s") or ""):
            doc[tok] += _W_HISTORY
    for phrase in node.get("lexical_signature") or []:
        for tok in _tokens(phrase):
            doc[tok] += _W_SIGNATURE
    for tok in _tokens(node.get("responsibility") or ""):
        doc[tok] += _W_RESPONSIBILITY
    for phrase in node.get("arrive_when") or []:
        for tok in _tokens(phrase):
            doc[tok] += _W_ARRIVE_WHEN
    return doc


@lru_cache(maxsize=1)
def _corpus() -> dict[str, Any]:
    """Deterministic corpus statistics for BM25: per-node weighted docs, document
    frequency per stem, and average document length. Computed once per process
    from the pinned map (no model, no embeddings)."""
    docs: dict[str, Counter] = {}
    df: Counter = Counter()
    for node in _nodes():
        doc = _node_doc(node)
        docs[node["node_id"]] = doc
        for tok in doc:
            df[tok] += 1
    n = max(1, len(docs))
    avgdl = sum(sum(d.values()) for d in docs.values()) / n
    return {"docs": docs, "df": df, "n": n, "avgdl": avgdl or 1.0}


def _idf(stem: str) -> float:
    c = _corpus()
    n, df = c["n"], c["df"].get(stem, 0)
    # BM25 idf with +1 floor so a term present in every node still scores > 0.
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


GLOSSARY_FILE = "GLOSSARY.md"
_GLOSS_LINE = re.compile(r"^\s*[-*]\s+(?P<terms>.+?)\s+(?:→|->)\s+(?P<code>.+?)\s*$")


@lru_cache(maxsize=1)
def _glossary() -> list[tuple[tuple[str, ...], list[str]]]:
    """The owner's words, and the code's words for the same thing.

    Measured: three of twelve cold-agent tasks could not be routed because the
    task and the code never share a word -- "how far from a supply chain can a
    news item be before it goes to the model" is, in the code, how close to a
    corridor a signal must be to be judged. No ranking closes that; only
    somebody writing down that the two mean the same thing does.

    One line per idea: `- **supply chain**, **chain** → corridor, lane, node`.
    """
    path = _ctx.current().knowledge_dir / GLOSSARY_FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _GLOSS_LINE.match(line)
        if not m:
            continue
        code = [w for w in re.split(r"[,;]", m.group("code")) if w.strip()]
        code_stems = [s for w in code for s in _tokens(w)]
        for term in re.findall(r"\*\*(.+?)\*\*", m.group("terms")):
            stems = tuple(_tokens(term))
            if stems and code_stems:
                out.append((stems, code_stems))
    return out


def _expansion(query: str) -> str:
    """The code's words for any owner's phrase in the query, and only those.

    Returned separately so they can count for less than the words actually
    asked: added at full weight, a glossary entry for a word in nearly every
    task ("chain") pulled every query toward the same chamber -- measured, it
    cost twelve points of top-1.
    """
    toks = _tokens(query)
    asked = set(toks)
    extra: list[str] = []
    for stems, code in _glossary():
        n = len(stems)
        if any(tuple(toks[i:i + n]) == stems for i in range(len(toks) - n + 1)):
            extra.extend(s for s in code if s not in asked)
    return " ".join(dict.fromkeys(extra))


# Measured on LogiAstro: 0 -> 53/71 (top-1/top-3), 0.2 -> 54/74, 0.3 -> 53/72,
# 0.5 -> 47/68, 1.0 -> 41/63. The glossary is a hint, never a vote.
_W_GLOSSARY = 0.2


def _score_node(query: str, node: dict[str, Any],
                exclude: frozenset[str] = frozenset()) -> tuple[float, list[str]]:
    query_stems = set(_tokens(query))
    if not query_stems:
        return 0.0, []
    c = _corpus()
    if exclude and any(e.get("h") in exclude for e in node.get("history") or []):
        doc: Counter = _node_doc(node, exclude)
    else:
        doc = c["docs"].get(node["node_id"]) or _node_doc(node)
    dl = sum(doc.values()) or 1
    score = 0.0
    matches: list[str] = []
    for stem in query_stems:
        f = doc.get(stem, 0)
        if not f:
            continue
        idf = _idf(stem)
        denom = f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / c["avgdl"])
        score += idf * (f * (_BM25_K1 + 1)) / denom
        matches.append(stem)
    # Verbatim multiword-phrase bonus: an exact signature phrase in the query is
    # a strong, low-ambiguity signal, scaled by its (idf-weighted) specificity.
    q_lower = str(query).lower()
    for phrase in node.get("lexical_signature") or []:
        phrase_l = str(phrase).lower()
        if " " in phrase_l and phrase_l in q_lower:
            # Half-weight: an exact phrase is a real signal but must not, on its
            # own, outrank a node that matches the query's actual intent tokens
            # (e.g. "metric phrase" appearing incidentally in the wording).
            bonus = 0.5 * (sum(_idf(t) for t in _tokens(phrase)) or 1.0)
            score += bonus
            matches.append(phrase_l)
    return score, sorted(set(matches))


# How much a node's best-matching symbol adds to the node's own score. Measured
# on LogiAstro's history: 0 -> 50/63 (top-1/top-3), 0.5 -> 55/70, 0.75 ->
# 53/71, 1.0 -> 50/71, 2.0 -> 47/63. Past about 1 the symbol outvotes the file.
_W_BEST_SYMBOL = 0.75


@lru_cache(maxsize=1)
def _symbol_corpus() -> dict[str, Any]:
    """BM25 statistics over every symbol in the map: name and docstring."""
    docs: dict[tuple[str, str], Counter] = {}
    df: Counter = Counter()
    for node in _nodes():
        for sym in node.get("symbols") or []:
            doc: Counter = Counter()
            for tok in _tokens(sym.get("name") or ""):
                doc[tok] += 2
            for tok in _tokens(sym.get("doc") or ""):
                doc[tok] += 1
            if not doc:
                continue
            docs[(node["node_id"], sym["name"])] = doc
            for tok in doc:
                df[tok] += 1
    n = max(1, len(docs))
    avgdl = sum(sum(d.values()) for d in docs.values()) / n
    return {"docs": docs, "df": df, "n": n, "avgdl": avgdl or 1.0}


def _best_symbol_scores(query: str) -> dict[str, tuple[float, str]]:
    """node -> (score, name) of its best-matching symbol for this query."""
    q = set(_tokens(query))
    c = _symbol_corpus()
    best: dict[str, tuple[float, str]] = {}
    for (nid, name), doc in c["docs"].items():
        dl = sum(doc.values()) or 1
        score = 0.0
        for stem in q:
            f = doc.get(stem, 0)
            if not f:
                continue
            idf = math.log(1 + (c["n"] - c["df"][stem] + 0.5) / (c["df"][stem] + 0.5))
            score += idf * (f * (_BM25_K1 + 1)) / (f + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / c["avgdl"]))
        if score > best.get(nid, (0.0, ""))[0]:
            best[nid] = (score, name)
    return best


def _rank_nodes(query: str, limit: int = 5,
                exclude: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    extra = _expansion(query) if _W_GLOSSARY else ""
    best = _best_symbol_scores(query) if _W_BEST_SYMBOL else {}
    best_x = _best_symbol_scores(extra) if extra and _W_BEST_SYMBOL else {}
    for node in _nodes():
        score, matches = _score_node(query, node, exclude)
        if extra:
            xs, xm = _score_node(extra, node, exclude)
            xs += _W_BEST_SYMBOL * best_x.get(node["node_id"], (0.0, ""))[0]
            score += _W_GLOSSARY * xs
            matches = matches + [f"~{m}" for m in xm[:3]]
        sym_score, sym_name = best.get(node["node_id"], (0.0, ""))
        if sym_score:
            score += _W_BEST_SYMBOL * sym_score
            matches = matches + [f"{sym_name}()"]
        if score <= 0:
            continue
        ranked.append({
            "node_id": node["node_id"],
            "responsibility": node["responsibility"],
            "score": round(score, 2),
            "matches": matches[:12],
        })
    ranked.sort(key=lambda item: (-item["score"], item["node_id"]))
    return ranked[:limit]


def _split_symbol_id(symbol_id: str) -> tuple[Path, str]:
    if "::" not in symbol_id:
        raise SystemExit(f"Symbol id must look like path/to/file.py::symbol_name: {symbol_id}")
    file_part, symbol_name = symbol_id.split("::", 1)
    return REPO_ROOT / file_part, symbol_name


def _find_symbol_span(symbol_id: str) -> dict[str, Any]:
    file_path, symbol_name = _split_symbol_id(symbol_id)
    if not file_path.exists():
        return {"exists": False, "reason": f"file not found: {file_path}"}
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"exists": False, "reason": f"could not parse {file_path}: {exc}"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol_name:
            end_lineno = getattr(node, "end_lineno", node.lineno)
            return {
                "exists": True,
                "file": str(file_path.relative_to(REPO_ROOT)),
                "symbol": symbol_name,
                "kind": node.__class__.__name__,
                "line_start": node.lineno,
                "line_end": end_lineno,
            }
    return {"exists": False, "reason": f"symbol not found: {symbol_id}"}


def _anchor_summary(anchor: dict[str, Any]) -> dict[str, Any]:
    """Verify one anchor against the live tree, attributing any drift.

    `address_verified` used to mean only "a symbol with this name still exists
    here", which passes an address whose signature has been rewritten out from
    under it. It now also compares the recorded structural fingerprint, so the
    card can say *how* the address drifted: reshaped, rewired, moved or gone.

    The caller set is skipped here (`with_callers=False`) because it costs a
    repo-wide pass and says nothing about this symbol's own contract; the
    `verify` command checks it.
    """
    symbol_id = anchor.get("symbol_id", "")
    try:
        live = structure.fingerprint(symbol_id, with_callers=False)
    except ValueError as exc:
        live = {"exists": False, "reason": str(exc)}
    recorded = anchor.get("struct")
    verdict = structure.compare(recorded, live)
    drift = verdict["drift"]
    out = {
        "symbol_id": symbol_id,
        "role": anchor.get("role", ""),
        "address_verified": bool(live.get("exists")) and verdict["severity"] < 3,
        "line_start": live.get("line_start"),
        "line_end": live.get("line_end"),
        "relocation_hint": None if live.get("exists") else verdict["detail"],
    }
    # Only speak up when there is something to say; an unchanged address stays
    # as quiet in the card as it was before.
    if drift not in (structure.DRIFT_NONE, "unpinned"):
        out["structural_drift"] = {"kind": drift, "detail": verdict["detail"]}
        if verdict.get("relocation"):
            out["structural_drift"]["now_at"] = verdict["relocation"]
    elif drift == "unpinned":
        out["structural_drift"] = {"kind": "unpinned",
                                   "detail": "map predates fingerprinting; rebuild to pin"}
    return out


def _anchor_files(node: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for anchor in node.get("anchors") or []:
        sid = anchor.get("symbol_id", "")
        if "::" in sid:
            f = sid.split("::", 1)[0]
            if f not in seen:
                seen.add(f)
                out.append(f)
    return out


def _node_scope(node: dict[str, Any]) -> list[str]:
    """Repo-relative paths that bound this node's territory: the directories that
    hold its anchor files. A grep scoped here can also surface sibling symbols the
    node never listed as anchors -- the fix for auto-generated nodes whose anchor
    is the right area but not the exact line."""
    dirs: list[str] = []
    seen: set[str] = set()
    # A knowledge page states its territory directly; prefer it over inference.
    for g in node.get("footprint") or []:
        d = str(g).replace("/**", "").rstrip("/*").rstrip("/")
        d = d if (REPO_ROOT / d).is_dir() else str(Path(d).parent)
        if d and d not in seen:
            seen.add(d)
            dirs.append(d)
    for f in _anchor_files(node):
        d = str(Path(f).parent)
        if d not in seen:
            seen.add(d)
            dirs.append(d)
    if dirs:
        return dirs
    guess = str(node.get("district", "")).replace(".", "/")
    return [guess] if guess and (REPO_ROOT / guess).exists() else ["."]


def _grep_pattern(node: dict[str, Any]) -> str:
    """Default directed query for a node: an alternation of its anchor symbol
    names, so a scoped grep relocates/confirms the exact definitions."""
    names = [
        re.escape(a.get("symbol_id", "").split("::", 1)[1])
        for a in node.get("anchors") or []
        if "::" in a.get("symbol_id", "")
    ]
    if names:
        return "|".join(names)
    return "|".join(re.escape(t) for t in (node.get("lexical_signature") or [])[:5])


def _local_search(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": f"anthill grep {node['node_id']} --pattern '<regex>'",
        "default_pattern": _grep_pattern(node),
        "scope": _node_scope(node),
        "purpose": (
            "Pinpoint the exact live symbol inside this node's territory -- use "
            "when the anchor is the right area but not the exact line."
        ),
        "expected_signal": "A def/class line at file:line to read-slice next.",
    }


def _default_next_action(node: dict[str, Any]) -> dict[str, Any]:
    anchors = node.get("anchors") or []
    if anchors:
        first = anchors[0].get("symbol_id", "")
        return {
            "type": "read_slice",
            "target": first,
            "purpose": "Inspect the live implementation at the primary anchor.",
            "expected_signal": "The function/class that owns this responsibility.",
        }
    return {
        "type": "grep",
        "query": "|".join((node.get("lexical_signature") or [])[:5]),
        "scope": [node.get("district") or "repository"],
        "purpose": "Find the live implementation for this responsibility.",
        "expected_signal": "A function, class, or test matching the responsibility.",
    }


def _symbols_in(file: str) -> list[dict[str, Any]]:
    """Every named thing in a file an agent might be sent to, with what it says.

    Top-level functions and classes, their methods, and module-level constants
    -- a constant is often the whole answer (`GATE_KM`, `INSTRUMENTS`), and in
    a well-kept codebase it carries its own docstring on the next line.
    """
    path = REPO_ROOT / file
    out: list[dict[str, Any]] = []
    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return out
        body = tree.body
        for i, node in enumerate(body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append({"symbol": node.name, "line": node.lineno,
                            "doc": ast.get_docstring(node) or ""})
                if isinstance(node, ast.ClassDef):
                    for m in node.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            out.append({"symbol": f"{node.name}.{m.name}", "line": m.lineno,
                                        "doc": ast.get_docstring(m) or ""})
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [x.id for x in targets if isinstance(x, ast.Name)]
                nxt = body[i + 1] if i + 1 < len(body) else None
                doc = (nxt.value.value if isinstance(nxt, ast.Expr) and isinstance(
                    getattr(nxt, "value", None), ast.Constant) and isinstance(nxt.value.value, str)
                    else "")
                values = sorted({c.value for c in ast.walk(node.value)
                                 if isinstance(c, ast.Constant) and isinstance(c.value, str)
                                 and 4 <= len(c.value) <= 60 and "\n" not in c.value})[:8] \
                    if node.value is not None else []
                for name in names:
                    out.append({"symbol": name, "line": node.lineno, "doc": doc,
                                **({"values": values} if values else {})})
    else:
        from anthill.navigate import scripts
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return out
        for sym in scripts.exports(text):
            hit = scripts.locate(path, sym["name"])
            out.append({"symbol": sym["name"], "line": hit["line_start"] if hit else None,
                        "doc": sym.get("doc", ""), "type": sym["kind"] == "type"})
    return out


def _look_here(node: dict[str, Any], goal: str, k: int = 3) -> list[dict[str, Any]]:
    """The lines in this node's file that best match the goal.

    Measured reason: cold agents reached the right file and then spent their
    steps searching inside it for the deciding line -- `GATE_KM`, `_cached`,
    `INSTRUMENTS` -- which the map knew nothing below file level about.
    """
    q = set(_tokens(goal))
    if not q:
        return []
    scored = []
    for s in _symbols_in(node.get("file") or ""):
        doc = s["doc"].strip()
        para = re.split(r"\n\s*\n", doc, maxsplit=1)[0] if doc else ""
        # The opening paragraph counts in full and the rest of the docstring at
        # half: `INSTRUMENTS` says "readings" up front and "merged" three
        # sentences later, but in a 1,700-line module the long docstrings would
        # otherwise out-talk the short one that is the answer.
        head = set(_tokens(s["symbol"])) | set(_tokens(para))
        rest = set(_tokens(doc[:1200])) - head
        hit = (q & head) | (q & rest)
        if not hit:
            continue
        score = sum(_idf(w) for w in q & head) + 0.5 * sum(_idf(w) for w in q & rest)
        if s.get("type"):
            score *= 0.5    # a type names the vocabulary; the function decides
        scored.append((score, s["line"] or 0, {
            "symbol": s["symbol"], "line": s["line"],
            "says": re.sub(r"\s+", " ", para)[:200],
            "matched": sorted(hit)}))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [x[2] for x in scored[:k]]


@lru_cache(maxsize=1)
def _searchable_files() -> tuple[str, ...]:
    """Every source and test file a symbol's users could be in."""
    from anthill.navigate import scripts
    files = {n.get("file") for n in _nodes() if n.get("file")}
    for base in ("tests", "test"):
        root = REPO_ROOT / base
        if root.is_dir():
            files.update(str(p.relative_to(REPO_ROOT)) for p in root.rglob("*")
                         if p.is_file() and (p.suffix == ".py" or p.suffix in scripts.SUFFIXES)
                         and "node_modules" not in p.parts)
    return tuple(sorted(f for f in files if f))


def _who_uses(file: str, symbol: str, limit: int = 12) -> dict[str, list[str]]:
    """Where a symbol's name appears outside its own file: code, then tests.

    Name-based, so an over-approximation: two things called `rank` look like
    one. That is the safe direction for "what could break" -- a false entry
    costs a glance, a missing one costs a regression.
    """
    name = symbol.split(".")[-1]
    if len(name) < 3:
        return {"code": [], "tests": []}
    rx = re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")
    code, tests = [], []
    for f in _searchable_files():
        if f == file:
            continue
        try:
            text = (REPO_ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not rx.search(text):
            continue
        is_test = f.startswith(("tests/", "test/")) or "/test" in f or ".test." in f
        (tests if is_test else code).append(f)
    return {"code": code[:limit], "tests": tests[:limit]}


def _same_values_elsewhere(file: str, values: list[str], limit: int = 10) -> list[dict[str, Any]]:
    """Other files that spell out one of these string values in quotes."""
    if not values:
        return []
    rx = re.compile(r"""(['"])(""" + "|".join(re.escape(v) for v in values) + r""")\1""")
    out = []
    for f in _searchable_files():
        if f == file:
            continue
        try:
            text = (REPO_ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = sorted({m.group(2) for m in rx.finditer(text)})
        if found:
            out.append({"file": f, "values": found})
    return out[:limit]


def _if_you_change(node: dict[str, Any], look: list[dict[str, Any]]) -> dict[str, Any]:
    """What a change here reaches: the one question search cannot answer.

    Measured: in four rounds of cold agents, the thing they reported saving
    them time was never the file -- search found that as fast -- but the list
    of tests and the rules. This puts the reach of the line itself first.
    """
    file = node.get("file") or ""
    out: dict[str, Any] = {}
    # Every pointed-at line, not only the first: the ranking is a guess at
    # which one decides, and the reach of the wrong one is no use.
    reach = []
    values = {s["symbol"]: s.get("values") or [] for s in _symbols_in(file)}
    for x in look[:3]:
        users = _who_uses(file, x["symbol"])
        row = {"symbol": x["symbol"], "used_in": users["code"],
               "tests_that_name_it": users["tests"]}
        # A constant of names -- which collectors are readings -- is often
        # half the rule; the other half is code elsewhere comparing to the
        # same strings, which no import graph shows. Measured: the related
        # bug beside a missing collector name was three `== "open-meteo"`
        # checks in other files, found only by grep.
        same = _same_values_elsewhere(file, values.get(x["symbol"]) or [])
        if same:
            row["same_values_elsewhere"] = same
        reach.append(row)
    if reach:
        out["by_line"] = reach
    out["files_that_import_this"] = [(_node_by_id(c).get("file") or c)
                                     for c in (node.get("consumers") or [])][:10]
    out["tests_that_import_this"] = node.get("tests") or []
    if not any(r["tests_that_name_it"] for r in reach) and not out["tests_that_import_this"]:
        out["warning"] = "no test covers this file -- a change here is unproven until one does"
    return out


@lru_cache(maxsize=1)
def _rules_by_file() -> dict[str, list[dict[str, str]]]:
    """file -> the knowledge-page rules that cite a symbol in it.

    A rule is the one thing on a card an agent cannot rediscover by reading the
    code: why it is shaped this way, and what must not be undone.
    """
    out: dict[str, list[dict[str, str]]] = {}
    kd = _ctx.current().knowledge_dir
    if not kd.exists():
        return out
    try:
        loaded = pages_mod.load_pages(kd)
    except Exception:          # a malformed page must not take navigation down
        return out
    for page in loaded:
        for rule in page["rules"]:
            text = re.sub(r"\s+", " ", rule["text"]).strip()
            first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
            for sid in rule["cites"]:
                f = sid.split("::", 1)[0]
                rows = out.setdefault(f, [])
                if not any(r["rule"] == rule["rule_id"] for r in rows):
                    rows.append({"rule": rule["rule_id"], "says": first[:300],
                                 "page": page["path"]})
    return out


def _card(node: dict[str, Any], goal: str = "", latest_finding: str = "") -> dict[str, Any]:
    anchors = [_anchor_summary(anchor) for anchor in node.get("anchors") or []]
    file = node.get("file") or (_anchor_files(node) or [""])[0]
    return {
        "you_are_here": {
            "node_id": node["node_id"],
            "file": file,
            "responsibility": node["responsibility"],
            "district": node.get("district", ""),
        },
        "look_here_first": (look := _look_here(node, goal) if goal else []),
        "if_you_change_this": _if_you_change(node, look),
        "rules_here": _rules_by_file().get(file, [])[:6],
        "recent_changes": [e.get("s", "") for e in (node.get("history") or [])[:4]],
        "current_goal": goal,
        "why_you_arrived": (node.get("arrive_when") or ["Best lexical match for the goal."])[0],
        "latest_finding": latest_finding,
        "live_address": anchors,
        "next_action": _default_next_action(node),
        "local_search": _local_search(node),
        "possible_routes": node.get("routes") or [],
        "validation_stops": node.get("tests") or [],
        "direct_consumers": node.get("consumers") or [],
        # Measured: a cold agent that trusted the top card stopped there and
        # named the right area but not the cause, while one reading without the
        # map followed the call chain and found it -- in twice the steps. The
        # card's job is the first step; this says the walk is not over.
        "how_to_use_this": (
            "This is where to start, not where it ends. Read the live code here, "
            "then follow possible_routes (what this calls) and direct_consumers "
            "(who calls it) until you reach the line that actually decides the "
            "behaviour. The top candidate is right about half the time; check the "
            "others before committing to one."),
        "done_when": [
            "The live code at the relevant anchor has been inspected.",
            "You followed the routes or consumers until the deciding line was found.",
            "The finding points to the edit site and the test that proves it.",
        ],
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=False))


DEFAULT_NODE = "assembly.pipeline_spine"


def _fallback_node() -> dict[str, Any]:
    """Where to land when nothing matched. The historic default is a foundary
    node, which does not exist in another repository, so fall back to the first
    node in the map rather than exiting."""
    nodes = _nodes()
    for node in nodes:
        if node.get("node_id") == DEFAULT_NODE:
            return node
    if not nodes:
        raise SystemExit(f"No nodes in any map under {MAPS_DIR}")
    return nodes[0]


def cmd_start(args: argparse.Namespace) -> None:
    ranked = _rank_nodes(args.goal, limit=args.top)
    node = _node_by_id(ranked[0]["node_id"]) if ranked else _fallback_node()
    card = _card(node, goal=args.goal)
    _print_json({
        "goal": args.goal,
        "candidates": ranked,
        "instruction": "Use the top card or choose a candidate with: anthill card <node_id>",
        "card": card,
    })


def cmd_observe(args: argparse.Namespace) -> None:
    # Fresh evidence drives rerouting. The goal is retained in the card, but it
    # should not overpower a clear finding such as "plan echo rejected".
    ranked = _rank_nodes(args.observation, limit=args.top)
    if not ranked:
        ranked = _rank_nodes(f"{args.goal} {args.observation}", limit=args.top)
    if ranked:
        node = _node_by_id(ranked[0]["node_id"])
    elif args.current_node:
        node = _node_by_id(args.current_node)
    else:
        node = _fallback_node()
    _print_json({
        "finding_recorded": args.observation,
        "resolution": "reroute_by_lexical_evidence",
        "candidates": ranked,
        "card": _card(node, goal=args.goal, latest_finding=args.observation),
    })


def cmd_card(args: argparse.Namespace) -> None:
    _print_json({"card": _card(_node_by_id(args.node_id), goal=args.goal or "")})


def cmd_nodes(args: argparse.Namespace) -> None:
    if args.query:
        _print_json({"query": args.query, "nodes": _rank_nodes(args.query, limit=args.top)})
    else:
        _print_json({
            "nodes": [
                {"node_id": node["node_id"], "responsibility": node["responsibility"]}
                for node in _nodes()
            ]
        })


def cmd_impact(args: argparse.Namespace) -> None:
    node = _node_by_id(args.node_id)
    look = [{"symbol": args.symbol}] if getattr(args, "symbol", "") else []
    _print_json({
        "node_id": node["node_id"],
        "if_you_change_this": _if_you_change(node, look),
        "validation_stops": node.get("tests") or [],
        "direct_consumers": node.get("consumers") or [],
        "possible_routes": node.get("routes") or [],
    })


def _search(pattern: str, scope_paths: list[str], max_results: int = 60) -> tuple[list[dict[str, Any]], bool]:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise SystemExit(f"invalid grep pattern: {exc}")
    results: list[dict[str, Any]] = []
    for base in scope_paths:
        p = REPO_ROOT / base
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = sorted(p.rglob("*.py"))
        else:
            continue
        for f in files:
            if {"__pycache__", "archive", "_archive", "venv", ".venv"} & set(f.relative_to(REPO_ROOT).parts):
                continue
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    results.append({
                        "file": str(f.relative_to(REPO_ROOT)),
                        "line": i,
                        "text": line.strip()[:200],
                    })
                    if len(results) >= max_results:
                        return results, True
    return results, False


def cmd_pin(args: argparse.Namespace) -> None:
    """Stamp structural fingerprints into a hand-authored map, in place.

    The generated map is fingerprinted by its builder, but a curated map has no
    builder — so without this its anchors can never report drift, only absence.
    Only the `struct` field is written; every hand-authored field is left alone.
    """
    path = Path(args.map_file).expanduser()
    if not path.is_absolute():
        path = _resolve_map(path.name.removesuffix(".json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    pinned = dead = 0
    dead_ids: list[str] = []
    for node in data.get("nodes") or []:
        for anchor in node.get("anchors") or []:
            symbol_id = anchor.get("symbol_id", "")
            if not symbol_id:
                continue
            try:
                fp = structure.fingerprint(symbol_id)
            except ValueError:
                fp = {"exists": False}
            if fp.get("exists"):
                anchor["struct"] = {k: fp[k] for k in
                                    ("file", "symbol", "sig", "callees", "callers", "hash") if k in fp}
                pinned += 1
            else:
                # Never fabricate a fingerprint for an address that is not there;
                # leave it unpinned so `verify` keeps reporting it as missing.
                anchor.pop("struct", None)
                dead += 1
                dead_ids.append(symbol_id)
    data["pinned_at_commit"] = claims.head_commit()
    if not args.dry_run:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _print_json({"map": path.name, "pinned": pinned, "unpinnable": dead,
                 "unpinnable_symbols": dead_ids,
                 "commit": data["pinned_at_commit"],
                 "written": not args.dry_run})


def cmd_verify(args: argparse.Namespace) -> None:
    """Check every recorded claim about this code against the live tree.

    Claims come from whichever of the three planes are present: map anchors
    always, knowledge-page rules when --knowledge points at a knowledge repo,
    and work-unit ownership when --contract points at a Peregrine contract.
    """
    ledger: list[dict[str, Any]] = []
    if not args.only or args.only == "navigation":
        ledger += claims.from_maps()
    # Intent is part of the ledger by default now that the package carries its own
    # knowledge base -- a spine that silently omits a plane is not a spine.
    kd = Path(args.knowledge).expanduser() if args.knowledge else KNOWLEDGE_DIR
    if (not args.only or args.only == "intent") and kd.exists():
        ledger += claims.from_knowledge(kd)
    if args.contract and (not args.only or args.only == "execution"):
        ledger += claims.from_contract(Path(args.contract).expanduser())
    results = claims.verify(ledger)
    summary = claims.summarize(results)
    if args.all:
        summary["claims"] = results
    _print_json(summary)


def cmd_grep(args: argparse.Namespace) -> None:
    """Run a directed, node-scoped grep. Returns match locations (addresses),
    never bodies -- read-slice the winner next. Scope is bounded to the node's
    own files/dirs so this can never become a whole-repo search."""
    node = _node_by_id(args.node_id)
    pattern = args.pattern or _grep_pattern(node)
    scope = _node_scope(node)
    results, truncated = _search(pattern, scope)
    _print_json({
        "node_id": node["node_id"],
        "pattern": pattern,
        "scope": scope,
        "match_count": len(results),
        "truncated": truncated,
        "matches": results,
        "next": "read-slice the file.py::symbol you want from these matches",
    })


def cmd_read_slice(args: argparse.Namespace) -> None:
    span = _find_symbol_span(args.symbol_id)
    if not span.get("exists"):
        _print_json({"symbol_id": args.symbol_id, "address_verified": False, "error": span.get("reason")})
        return
    file_path, _ = _split_symbol_id(args.symbol_id)
    lines = file_path.read_text(encoding="utf-8").splitlines()
    start = int(span["line_start"])
    end = int(span["line_end"])
    body = "\n".join(lines[start - 1:end])
    token_estimate = max(1, len(re.findall(r"\S+", body)))
    _print_json({
        "symbol_id": args.symbol_id,
        "address_verified": True,
        "file": span["file"],
        "line_start": start,
        "line_end": end,
        "token_estimate": token_estimate,
        "body": body,
    })


def _knowledge_args(args: argparse.Namespace) -> tuple[Path, Path]:
    """Knowledge repository and the source checkout its evidence points at.

    The Kit's own layout is two siblings, so the source root defaults to the
    repository this CLI lives in and is overridden with --source for the
    sibling case.
    """
    kd = Path(args.knowledge).expanduser().resolve() if args.knowledge else KNOWLEDGE_DIR
    sr = Path(getattr(args, "source", "") or REPO_ROOT).expanduser().resolve()
    return kd, sr


def _load_gates(path: str) -> dict[str, str]:
    """Read an area->gate map.

    Accepts a flat mapping, or a document with a `gates` key so the file can also
    carry why each gate is what it is and what it deliberately excludes. A gate
    file that cannot explain its own exclusions is how a silent coverage hole
    starts looking like a passing board.
    """
    if not path:
        return {}
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    inner = data.get("gates") if isinstance(data, dict) else None
    src = inner if isinstance(inner, dict) else data
    return {str(k): str(v) for k, v in src.items()
            if not str(k).startswith("_") and str(v).strip()}


def cmd_pages(args: argparse.Namespace) -> int:
    """Validate a page set: required frontmatter, pin grammar, footprint."""
    kd, sr = _knowledge_args(args)
    loaded = pages_mod.load_pages(kd)
    findings = pages_mod.validate(loaded, sr)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    blocked = sorted(pages_mod.blocking(findings))
    ruleless, uncited = [], []
    for page in loaded:
        if not page["rules"]:
            ruleless.append(page["path"])
        else:
            for r in page["rules"]:
                if not r["cites"]:
                    uncited.append(f"{page['path']}:{r['rule_id']}")
    out = {
        "knowledge_dir": str(kd),
        "source_root": str(sr),
        "page_count": len(loaded),
        "not_indexed": pages_mod.skipped_files(kd),
        "by_severity": counts,
        "blocked_pages": blocked,
        "pages_without_rules": ruleless,
        "rules_without_a_citation": uncited,
        "findings": findings if args.all else findings[:40],
        "truncated": (not args.all) and len(findings) > 40,
    }
    # It used to report `blocked_pages` and exit 0 regardless, which made every
    # knowledge gate vacuous -- the check ran, found the fault, and passed.
    code = 1 if blocked else 0
    if getattr(args, "require_rules", False) and (ruleless or uncited):
        out["refused"] = ("a page that states no rule, or a rule that cites no "
                          "symbol, records nothing that can later be proven wrong")
        code = 1
    _print_json(out)
    return code


def cmd_index_pages(args: argparse.Namespace) -> None:
    """Write the page map, so the existing router indexes knowledge."""
    kd, sr = _knowledge_args(args)
    gates = _load_gates(args.gates)
    m = pages_mod.build_map(kd, gates=gates, source_root=sr)
    GEN_MAPS_DIR.mkdir(parents=True, exist_ok=True)
    out = GEN_MAPS_DIR / f"{args.out}.json"
    if not args.dry_run:
        out.write_text(json.dumps(m, indent=2), encoding="utf-8")
    _print_json({
        "map": str(out), "written": not args.dry_run,
        "node_count": m["node_count"], "blocked_count": m["blocked_count"],
        "next": f"anthill start '<goal>' --map {args.out}",
    })


def cmd_readiness(args: argparse.Namespace) -> None:
    kd, sr = _knowledge_args(args)
    _print_json(readiness_mod.report(kd, sr, check_commits=not args.no_commit_check))


def cmd_coverage(args: argparse.Namespace) -> None:
    """Where the maps know code but no page explains it."""
    kd, sr = _knowledge_args(args)
    _print_json(readiness_mod.coverage(kd, sr, top=args.top))


def cmd_eval_routing(args: argparse.Namespace) -> None:
    """Score routing against questions the pages did not author."""
    kd, sr = _knowledge_args(args)
    res = eval_mod.routing(kd, sr, Path(args.log).expanduser(),
                           rank=lambda q, k: _rank_nodes(q, limit=k),
                           top_k=args.top_k, limit=args.limit,
                           cited_only=args.cited_only)
    if not args.all:
        res["misses"] = res["misses"][:10]
        res["unreachable_entries"] = res["unreachable_entries"][:5]
    _print_json(res)


def cmd_orient(args: argparse.Namespace) -> None:
    """What an agent is walking into, on one page."""
    from anthill.navigate import orient as orient_mod
    o = orient_mod.orient(_ctx.current(), _nodes())
    if args.json:
        _print_json(o)
    else:
        print(orient_mod.render(o), end="")


def cmd_eval_map(args: argparse.Namespace) -> None:
    """Score the map against the repository's own history."""
    res = eval_mod.routing_from_history(REPO_ROOT, _nodes(),
                                        rank=lambda q, k, exclude=frozenset(): _rank_nodes(q, k, exclude),
                                        top_k=args.top_k, limit=args.limit)
    if not args.all:
        res["misses"] = res["misses"][:10]
    _print_json(res)


def cmd_board(args: argparse.Namespace) -> None:
    """Generate a Peregrine contract from pages that verify."""
    kd, sr = _knowledge_args(args)
    gates = _load_gates(args.gates)
    result = board_mod.generate(
        kd, sr, project=args.project, base_branch=args.base_branch,
        gate_template=args.gate_template, gates=gates,
        areas=[a.strip() for a in args.areas.split(",") if a.strip()] if args.areas else None,
        check_commits=not args.no_commit_check,
    )
    if args.out and not args.dry_run:
        Path(args.out).expanduser().write_text(
            json.dumps(result["contract"], indent=2), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "contract"}
    summary["written_to"] = args.out if (args.out and not args.dry_run) else ""
    summary["contract"] = result["contract"] if args.all else "(use --all to print units)"
    _print_json(summary)


def cmd_harvest(args: argparse.Namespace) -> None:
    """Turn escalations into draft knowledge pages."""
    _print_json(harvest_mod.harvest(
        Path(args.escalations).expanduser().resolve(),
        Path(args.out_dir).expanduser().resolve(),
        contract_path=Path(args.contract).expanduser() if args.contract else None,
        evidence_prefix=args.evidence_prefix,
        write=not args.dry_run,
    ))


def _store(args: argparse.Namespace) -> "work_mod.Store":
    """State for the repo being worked, kept under this package's build/ dir.

    Nothing is written into the target repository except the worktrees git itself
    manages, so working a repo leaves no orchestrator litter in it.
    """
    repo = Path(args.repo).expanduser().resolve()
    override = getattr(args, "work_dir", "") or ""
    root = Path(override).expanduser().resolve() if override else \
        WORK_ROOT / re.sub(r"[^A-Za-z0-9._-]+", "-", repo.name)
    store = work_mod.Store(repo, root=root)
    store.init_dirs()
    return store


def cmd_kb_init(args: argparse.Namespace) -> None:
    _print_json(kb_mod.init(
        Path(args.knowledge).expanduser().resolve(),
        project=args.project,
        source=args.source or "../source",
        areas=[a.strip() for a in args.areas.split(",") if a.strip()],
        registries=[r.strip().upper() for r in args.registries.split(",") if r.strip()],
        prefix=args.prefix,
        write=not args.dry_run,
    ))


def cmd_kb_catalogue(args: argparse.Namespace) -> None:
    kd = (Path(args.knowledge).expanduser().resolve() if args.knowledge
          else KNOWLEDGE_DIR)
    _print_json(kb_mod.catalogue(kd, write=not args.dry_run, out_dir=CATALOGUE_DIR))


def cmd_work_plan(args: argparse.Namespace) -> int:
    st = _store(args)
    _print_json({**work_mod.plan(st), **_behind_note(st)})
    return 0


def _behind_note(store) -> dict:
    """A board seeded before the contract moved reports confidently wrong."""
    if not store.board_is_behind():
        return {}
    return {"board_is_behind": (
        "the approved contract is newer than this board. Run `work load` to "
        "pick up the change; until then this reflects the old plan.")}


# Said by the one command every session is told to run first. Measured: an
# agent that followed CLAUDE.md exactly -- onboard, roles, work status, skill
# list -- was never pointed at orient or start, concluded `start` did not
# exist, and navigated by grep alone.
NEW_HERE = {
    "orient": "anthill orient",
    "find_a_task": 'anthill start "<the task, in your own words>"',
    "why": ("orient is the codebase on one page; start names the file and line a task "
            "lives at, what a change there reaches, and the tests that prove it. Both "
            "only read."),
}


def cmd_work_status(args: argparse.Namespace) -> int:
    st = _store(args)
    _print_json({**work_mod.status(st), **_behind_note(st), "new_here": NEW_HERE})
    return 0


def cmd_work_next(args: argparse.Namespace) -> int:
    """Claim the next ready unit. The exit code is the worker protocol:
    0 = work claimed, 3 = wait, 4 = nothing left that can ever run."""
    import os as _os
    worker = args.worker or _os.environ.get("ANTHILL_WORKER", "") or "solo"
    payload, code = work_mod.claim(_store(args), worker=worker,
                                   unit_id=args.unit,
                                   isolate=False if args.no_isolate else None)
    _print_json(payload)
    return code


def cmd_work_gate(args: argparse.Namespace) -> int:
    payload, code = work_mod.gate(_store(args), args.unit)
    _print_json(payload)
    return code


def cmd_work_done(args: argparse.Namespace) -> int:
    payload, code = work_mod.done(_store(args), args.unit)
    _print_json(payload)
    return code


def cmd_work_release(args: argparse.Namespace) -> int:
    _print_json(work_mod.release(_store(args), args.unit))
    return 0


def cmd_work_load(args: argparse.Namespace) -> int:
    store = _store(args)
    src = Path(args.contract).expanduser() if args.contract else store.canonical_contract()
    _print_json(work_mod.load_board(store, src, write=not args.dry_run))
    return 0


def cmd_work_reopen(args: argparse.Namespace) -> int:
    out, code = work_mod.reopen(_store(args), args.unit, args.reason, args.by)
    _print_json(out)
    return code


def cmd_work_escalate(args: argparse.Namespace) -> int:
    _print_json(work_mod.escalate(_store(args), args.unit, args.reason))
    return 0


def cmd_work_reap(args: argparse.Namespace) -> int:
    store = _store(args)
    reaped = work_mod.reap_stale(store, store.load_contract())
    _print_json({"reaped": reaped, "count": len(reaped),
                 "note": f"a claim silent for more than "
                         f"{work_mod.STALE_LOCK_SECONDS}s is reclaimable"})
    return 0


def cmd_work_pool(args: argparse.Namespace) -> int:
    """Run the board to completion with N concurrent agents."""
    store = _store(args)
    prompt = (Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
              if args.prompt_file else pool_mod.DEFAULT_PROMPT)
    result = pool_mod.run(store, workers=args.workers, agent_cmd=args.agent,
                          isolate=False if args.no_isolate else None, prompt_template=prompt,
                          timeout=args.timeout, idle_sleep=args.idle_sleep)
    if not args.all:
        result["events"] = result["events"][-40:]
    _print_json(result)
    return 0 if result["final"]["complete"] else 1


def cmd_work_heartbeat(args: argparse.Namespace) -> int:
    """Keep a claim alive. Only the holder can beat it."""
    ok = _store(args).heartbeat(args.unit, args.worker)
    _print_json({"unit": args.unit, "worker": args.worker, "kept": ok})
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anthill",
        description="Anthill navigation and work CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def _with_map(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--map", default="", dest="map_name",
                       help="Restrict to one map (e.g. 'codebase' or an authored map name); default merges all")
        return p

    start = _with_map(sub.add_parser("start", help="Start navigation from a natural-language goal"))
    start.add_argument("goal")
    start.add_argument("--top", type=int, default=3)
    start.set_defaults(func=cmd_start)

    observe = _with_map(sub.add_parser("observe", help="Reroute from a compact observation"))
    observe.add_argument("--goal", required=True)
    observe.add_argument("--observation", required=True)
    observe.add_argument("--current-node", default="")
    observe.add_argument("--top", type=int, default=3)
    observe.set_defaults(func=cmd_observe)

    card = _with_map(sub.add_parser("card", help="Show a specific node card"))
    card.add_argument("node_id")
    card.add_argument("--goal", default="")
    card.set_defaults(func=cmd_card)

    nodes = _with_map(sub.add_parser("nodes", help="List or search nodes"))
    nodes.add_argument("--query", default="")
    nodes.add_argument("--top", type=int, default=10)
    nodes.set_defaults(func=cmd_nodes)

    impact = _with_map(sub.add_parser("impact", help="What a change here reaches: callers, "
                                      "importers, and the tests that prove it"))
    impact.add_argument("node_id")
    impact.add_argument("--symbol", default="", help="a function or constant in the node's file")
    impact.set_defaults(func=cmd_impact)

    grep = _with_map(sub.add_parser("grep", help="Run a directed grep scoped to one node's territory"))
    grep.add_argument("node_id")
    grep.add_argument("--pattern", default="", help="Regex to search (default: the node's anchor symbol names)")
    grep.set_defaults(func=cmd_grep)

    read_slice = sub.add_parser("read-slice", help="Read one live function/class body")
    read_slice.add_argument("symbol_id")
    read_slice.set_defaults(func=cmd_read_slice)

    pin = sub.add_parser("pin", help="Stamp structural fingerprints into a hand-authored map")
    pin.add_argument("map_file", help="Map filename or path (e.g. codebase.json)")
    pin.add_argument("--dry-run", action="store_true")
    pin.set_defaults(func=cmd_pin)

    verify = sub.add_parser("verify", help="Check recorded claims (addresses, rules, ownership) against the tree")
    verify.add_argument("--knowledge", default="", help="Path to a knowledge repository of BR-rule pages")
    verify.add_argument("--contract", default="", help="Path to a Peregrine contract.json")
    verify.add_argument("--only", default="", choices=["", "navigation", "intent", "execution"],
                        help="Restrict to one plane's claims")
    verify.add_argument("--all", action="store_true", help="Include every claim, not just the summary")
    verify.set_defaults(func=cmd_verify)

    def _kn(p: argparse.ArgumentParser, required: bool = False) -> argparse.ArgumentParser:
        p.add_argument("--knowledge", default="",
                       help=f"Knowledge repository (default: {KNOWLEDGE_DIR})")
        p.add_argument("--source", default="",
                       help="Path to the source checkout the evidence pins to (default: this repo)")
        return p

    pg = _kn(sub.add_parser("pages", help="Validate knowledge pages (frontmatter, pin, footprint)"))
    pg.add_argument("--all", action="store_true", help="Print every finding")
    pg.add_argument("--require-rules", action="store_true",
                    help="Also refuse a page with no rules, or a rule with no "
                         "citation — both validate clean and assert nothing")
    pg.set_defaults(func=cmd_pages)

    ip = _kn(sub.add_parser("index-pages", help="Build the page map the router navigates"))
    ip.add_argument("--out", default="knowledge", help="Map basename under maps/ (default: knowledge)")
    ip.add_argument("--gates", default="", help="JSON file of {area: gate command}")
    ip.add_argument("--dry-run", action="store_true")
    ip.set_defaults(func=cmd_index_pages)

    ev = _kn(sub.add_parser("eval-routing",
                            help="Score routing on questions the pages did not author"))
    ev.add_argument("--log", required=True, help="A learning log to draw questions from")
    ev.add_argument("--top-k", type=int, default=3)
    ev.add_argument("--limit", type=int, default=0)
    ev.add_argument("--cited-only", action="store_true",
                    help="Expect only pages that CITE the blamed file, not merely "
                         "own it by footprint — a tighter, less noisy label")
    ev.add_argument("--all", action="store_true")
    ev.add_argument("--map", default="knowledge", dest="map_name")
    ev.set_defaults(func=cmd_eval_routing)

    orp = sub.add_parser("orient", help="Start here: what this codebase is, its "
                         "chambers, how they connect, how to prove a change, the rules")
    orp.add_argument("--json", action="store_true")
    orp.set_defaults(func=cmd_orient)

    em = sub.add_parser("eval-map", help="Score routing against this repository's own "
                        "commit history: each past subject is a task, its files the answer")
    em.add_argument("--top-k", type=int, default=3)
    em.add_argument("--limit", type=int, default=0)
    em.add_argument("--all", action="store_true", help="list every miss")
    em.set_defaults(func=cmd_eval_map)

    cv = _kn(sub.add_parser("coverage", help="Code the maps know but no page explains"))
    cv.add_argument("--top", type=int, default=15, help="How many unexplained files to list")
    cv.set_defaults(func=cmd_coverage)

    rd = _kn(sub.add_parser("readiness", help="Per-area build/improve mode"))
    rd.add_argument("--no-commit-check", action="store_true",
                    help="Skip git reachability of pinned commits")
    rd.set_defaults(func=cmd_readiness)

    bd = _kn(sub.add_parser("board", help="Generate a work contract from pages that verify"))
    bd.add_argument("--project", default="", help="Project name recorded in the contract")
    bd.add_argument("--base-branch", default="main")
    bd.add_argument("--gate-template", default="", help="e.g. 'pnpm gate {area}' or 'pytest -k {area}'")
    bd.add_argument("--gates", default="", help="JSON file of {area: gate command}")
    bd.add_argument("--areas", default="", help="Comma-separated areas to include")
    bd.add_argument("--out", default="", help="Write the contract JSON here")
    bd.add_argument("--no-commit-check", action="store_true")
    bd.add_argument("--dry-run", action="store_true")
    bd.add_argument("--all", action="store_true", help="Print the full contract")
    bd.set_defaults(func=cmd_board)

    hv = sub.add_parser("harvest", help="Draft knowledge pages from Peregrine escalations")
    hv.add_argument("--escalations", required=True, help="Path to .peregrine/escalations/")
    hv.add_argument("--out-dir", required=True, help="Where draft pages are written")
    hv.add_argument("--contract", default="", help="Contract JSON, so drafts inherit owns as footprint")
    hv.add_argument("--evidence-prefix", default="src")
    hv.add_argument("--dry-run", action="store_true")
    hv.set_defaults(func=cmd_harvest)

    # ---- knowledge plane: create and maintain a knowledge base -------------
    kb = sub.add_parser("kb", help="Create and maintain a knowledge base")
    kbsub = kb.add_subparsers(dest="kb_command", required=True)

    kbi = kbsub.add_parser("init", help="Scaffold a new knowledge base")
    kbi.add_argument("--knowledge", required=True, help="Directory to create it in")
    kbi.add_argument("--project", required=True)
    kbi.add_argument("--source", default="", help="Path to the source checkout")
    kbi.add_argument("--areas", required=True, help="Comma-separated knowledge areas")
    kbi.add_argument("--registries", required=True,
                     help="Comma-separated rule registries, e.g. ORDER,BILLING")
    kbi.add_argument("--prefix", default="", help="Evidence prefix for verified_against")
    kbi.add_argument("--dry-run", action="store_true")
    kbi.set_defaults(func=cmd_kb_init)

    kbc = kbsub.add_parser("catalogue", help="Rebuild _generated/ rule catalogue and backlinks")
    kbc.add_argument("--knowledge", default="",
                     help=f"Knowledge repository (default: {KNOWLEDGE_DIR})")
    kbc.add_argument("--dry-run", action="store_true")
    kbc.set_defaults(func=cmd_kb_catalogue)

    # ---- execution plane: many agents, one repository ----------------------
    work = sub.add_parser("work", help="Run a work board: claim, gate, integrate")
    wsub = work.add_subparsers(dest="work_command", required=True)

    def _repo(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--repo", required=True, help="The source repository to work in")
        p.add_argument("--work-dir", default="",
                       help=f"Where run state is kept (default: {WORK_ROOT}/<repo>)")
        return p

    _repo(wsub.add_parser("plan", help="Waves and critical path")).set_defaults(func=cmd_work_plan)
    _repo(wsub.add_parser("status", help="Where every unit stands")).set_defaults(func=cmd_work_status)

    wn = _repo(wsub.add_parser("next", help="Claim the next ready unit (0=claimed, 3=wait, 4=drained)"))
    wn.add_argument("--worker", default="",
                    help="Worker identity holding the claim (default: the value of "
                         "$ANTHILL_WORKER, else 'solo')")
    wn.add_argument("--unit", default="", help="Claim only this unit")
    wn.add_argument("--no-isolate", action="store_true",
                    help="Work in the repo itself instead of a fresh worktree")
    wn.set_defaults(func=cmd_work_next)

    wg = _repo(wsub.add_parser("gate", help="Ownership check, then the unit's gate"))
    wg.add_argument("--unit", required=True)
    wg.set_defaults(func=cmd_work_gate)

    wd = _repo(wsub.add_parser("done", help="Close a unit — refused without a passing gate"))
    wd.add_argument("--unit", required=True)
    wd.set_defaults(func=cmd_work_done)

    wr = _repo(wsub.add_parser("release", help="Drop a claim without closing the unit"))
    wr.add_argument("--unit", required=True)
    wr.set_defaults(func=cmd_work_release)

    we = _repo(wsub.add_parser("escalate", help="Hand a unit to a human"))
    we.add_argument("--unit", required=True)
    we.add_argument("--reason", default="escalated by hand")
    we.set_defaults(func=cmd_work_escalate)

    wl = _repo(wsub.add_parser(
        "load", help="Seed or refresh the board from the compiled contract"))
    wl.add_argument("--contract", default="",
                    help="Contract to load (default: the one `sprint compile` wrote)")
    wl.add_argument("--dry-run", action="store_true")
    wl.set_defaults(func=cmd_work_load)

    wo = _repo(wsub.add_parser(
        "reopen", help="Return an escalated or blocked unit to the board"))
    wo.add_argument("--unit", required=True)
    wo.add_argument("--reason", default="", help="What was resolved")
    wo.add_argument("--by", default="", help="Who decided it was ready to retry")
    wo.set_defaults(func=cmd_work_reopen)

    _repo(wsub.add_parser("reap", help="Reclaim locks held by dead workers")).set_defaults(func=cmd_work_reap)

    wp = _repo(wsub.add_parser("pool", help="Run the board with N concurrent agents"))
    wp.add_argument("--workers", type=int, default=4)
    wp.add_argument("--agent", default="",
                    help="Command receiving the brief on stdin, run in the unit's "
                         "worktree. Empty = rehearsal: claim and gate, no agent.")
    wp.add_argument("--prompt-file", default="", help="Override the agent prompt")
    wp.add_argument("--timeout", type=int, default=3600, help="Per-unit agent timeout")
    wp.add_argument("--idle-sleep", type=float, default=pool_mod.IDLE_SLEEP,
                    help="Seconds a worker waits before polling the board again")
    wp.add_argument("--no-isolate", action="store_true")
    wp.add_argument("--all", action="store_true", help="Print every event")
    wp.set_defaults(func=cmd_work_pool)

    wh = _repo(wsub.add_parser("heartbeat", help="Keep a claim alive"))
    wh.add_argument("--unit", required=True)
    wh.add_argument("--worker", required=True)
    wh.set_defaults(func=cmd_work_heartbeat)

    return parser


def main(argv: list[str] | None = None) -> int:
    global _MAP_FILTER
    parser = build_parser()
    args = parser.parse_args(argv)
    _MAP_FILTER = getattr(args, "map_name", "") or None
    # Orchestrator commands return a meaningful exit code (3 = wait, 4 = drained,
    # 64 = ownership violation ...); navigation commands return None.
    try:
        return args.func(args) or 0
    except work_mod.OrchestratorError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
