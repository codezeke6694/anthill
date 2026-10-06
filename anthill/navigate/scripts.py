"""The frontend half of the map: TypeScript and JavaScript, without a parser.

The map was Python-only because it read source with `ast`, and so a whole
frontend was invisible to it. Measured on a real project: 36 of 119 past tasks
touched only `web/src/`, and the router could not have sent an agent to any of
them, because no node existed there to send it to.

A real TS parser would mean a node toolchain at map-build time. What the map
needs is much less than a parse: a file's opening comment (what it is for), the
names it exports (its addresses), the doc comment above each export, and its
relative imports (its pathways). Those have a regular enough shape in any
codebase that follows its own formatter, and a miss costs one weaker node rather
than a wrong one.

Deliberately out of scope: bare-specifier imports (`react`, `lucide-react`) are
dependencies, not pathways; path aliases (`@/lib/x`) are not resolved.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs")
# Declarations, tests, and build config are not places an agent works in.
_SKIP = re.compile(r"(\.d\.ts$|\.test\.|\.spec\.|(^|/)vite-env\.|\.config\.)")
_NEVER = {"node_modules", "dist", "build", ".next", "coverage"}

_LEAD_BLOCK = re.compile(r"\A\s*/\*\*?(.*?)\*/", re.S)
_LEAD_LINES = re.compile(r"\A(?:\s*//[^\n]*\n)+")
_EXPORT = re.compile(
    r"(?:/\*\*(?P<doc>(?:(?!\*/).)*?)\*/\s*)?"
    r"^export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
    r"(?P<kind>function\*?|class|const|let|var|interface|type|enum)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)",
    re.M | re.S)
_IMPORT = re.compile(r"""(?:^|\n)\s*(?:import|export)\b[^'"]*?from\s*['"](\.[^'"]+)['"]"""
                     r"""|(?:^|\n)\s*import\s*['"](\.[^'"]+)['"]""")


_NOT_SOURCE = _NEVER | {".anthill", "anthill", ".git", "_archive", "archive", ".venv", "venv"}
# Top-level folders of a JavaScript project that hold no code an agent works in.
_NOT_CODE = {"public", "static", "assets", "docs", "logs", "test", "tests", "__tests__", "e2e",
             "dist-ssr", "out", "tmp"}


def discover(root: Path, configured: list[str] | None = None) -> list[str]:
    """Frontend source roots: a directory holding a `package.json` or
    `tsconfig.json`, at most two levels down, taken at its `src/` when it has one.

    Discovery rather than configuration because the Python half discovers too,
    and a map that needs a setting to see half the codebase is a map that does
    not see it. `source.script_dirs` overrides it when set.

    Not filtered by `source.exclude_parts`: that list keeps `web` out of the
    *Python* set, which is exactly the set this one exists to complement.
    """
    if configured:
        return [d for d in configured if (root / d).is_dir()]
    found: list[str] = []
    if (root / "package.json").exists() or (root / "tsconfig.json").exists():
        # The project itself is the JavaScript or TypeScript one, its folders
        # at the top: src/ for the screens, server/ for the API. Only folders
        # below the top were looked at, so such a project -- 160 files in its
        # src/ and server/ -- reached the map as nothing at all.
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            if d.name.startswith(".") or d.name in _NOT_SOURCE | _NOT_CODE:
                continue
            if any(f.suffix in SUFFIXES and not (_NEVER & set(f.relative_to(root).parts))
                   for f in d.rglob("*") if f.is_file()):
                found.append(d.name)
    for marker in ("package.json", "tsconfig.json"):
        for depth in ("*", "*/*"):
            for m in root.glob(f"{depth}/{marker}"):
                d = m.parent
                rel = d.relative_to(root)
                if _NOT_SOURCE & set(rel.parts):
                    continue
                pick = d / "src" if (d / "src").is_dir() else d
                r = str(pick.relative_to(root))
                if r not in found:
                    found.append(r)
    return sorted(found)


def files(root: Path, dirs: list[str]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix not in SUFFIXES or not p.is_file():
                continue
            rel = p.relative_to(root)
            if _NEVER & set(rel.parts) or _SKIP.search(str(rel)):
                continue
            out.append(p)
    return sorted(out)


def _clean_comment(body: str) -> str:
    lines = [re.sub(r"^\s*\*? ?", "", ln) for ln in body.splitlines()]
    return "\n".join(lines).strip()


def lead_comment(text: str) -> str:
    """The comment a file opens with, before its first import or statement."""
    m = _LEAD_BLOCK.match(text)
    if m:
        return _clean_comment(m.group(1))
    m = _LEAD_LINES.match(text)
    if m:
        return "\n".join(re.sub(r"^\s*//\s?", "", ln) for ln in m.group(0).splitlines()).strip()
    return ""


def first_sentence(text: str, limit: int = 240) -> str:
    para = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    para = re.sub(r"\s+", " ", para).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", para)
    s = m.group(1) if m else para
    return s if len(s) <= limit else s[: limit - 3] + "..."


def exports(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _EXPORT.finditer(text):
        name = m.group("name")
        if name in seen:
            continue
        seen.add(name)
        kind = m.group("kind").rstrip("*")
        doc = _clean_comment(m.group("doc") or "")
        out.append({
            "name": name,
            # A PascalCase function in a .tsx is a component; that is the
            # behaviour boundary a frontend agent is looking for.
            "kind": "class" if kind == "class" else ("type" if kind in ("interface", "type", "enum")
                                                      else "function"),
            "public": True,
            "doc_first": doc.splitlines()[0] if doc else "",
            "doc": doc,
        })
    return out


def imports(text: str, path: Path, root: Path) -> set[str]:
    """Repo-relative files this one imports by relative path."""
    out: set[str] = set()
    for m in _IMPORT.finditer(text):
        spec = m.group(1) or m.group(2)
        target = resolve(path.parent / spec, root)
        if target:
            out.add(target)
    return out


def resolve(base: Path, root: Path) -> str | None:
    cands = [base] + [base.with_name(base.name + s) for s in SUFFIXES] \
        + [base / f"index{s}" for s in SUFFIXES]
    for c in cands:
        if c.is_file() and c.suffix in SUFFIXES:
            try:
                return str(c.resolve().relative_to(root.resolve()))
            except ValueError:
                return None
    return None


def extract(path: Path, root: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    rel = str(path.relative_to(root))
    syms = exports(text)
    doc = lead_comment(text)
    if not doc:
        # A component file often opens straight on imports and documents its
        # export instead; that comment is the file's description.
        doc = next((s["doc"] for s in syms if s["doc"] and s["kind"] != "type"), "")
    return {"rel": rel, "mod_doc": doc, "symbols": syms,
            "file_imports": imports(text, path, root), "script": True}


# ------------------------------------------------------------- fingerprinting

def locate(path: Path, name: str) -> dict[str, Any] | None:
    """Where a named top-level declaration sits, and a digest of its line.

    The Python fingerprint covers signature and callees; here the declaration
    line stands in for the signature. Enough to tell "still there" from "gone",
    and a renamed or re-typed export from an untouched one.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    rx = re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
        r"(?:function\*?|class|const|let|var|interface|type|enum)\s+" + re.escape(name) + r"\b[^\n]*",
        re.M)
    m = rx.search(text)
    if not m:
        return None
    line = text.count("\n", 0, m.start()) + 1
    decl = re.sub(r"\s+", " ", m.group(0)).strip()
    end = _body_end(text, m.start())
    body = text[m.start():end]
    out = {"line_start": line, "line_end": text.count("\n", 0, end) + 1,
           "sig": hashlib.sha256(decl.encode()).hexdigest()[:16]}
    calls = callees(body, name)
    if calls:
        # What it calls, as for Python (C7): a TypeScript function that starts
        # doing different work is now caught, not only one that disappears.
        out["callees"] = hashlib.sha256("|".join(calls).encode()).hexdigest()[:16]
    return out


_NOT_CALLS = {"if", "for", "while", "switch", "return", "function", "catch", "typeof", "new",
              "await", "super", "import", "require", "console", "log", "debug", "info", "warn", "error"}


def callees(body: str, own: str = "") -> list[str]:
    """Names a declaration calls, by a plain read of its text."""
    clean = re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.S)
    clean = re.sub(r"(['\"`])(?:\\.|(?!\1).)*\1", "''", clean, flags=re.S)
    names = set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", clean))
    names |= set(re.findall(r"\.([A-Za-z_$][\w$]*)\s*\(", clean))
    return sorted(n for n in names if n not in _NOT_CALLS and n != own)


def _body_end(text: str, start: int) -> int:
    """Where a declaration ends: its braces closed, or its statement over."""
    depth, opened, i, n = 0, False, start, len(text)
    in_str = ""
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = ""
        elif c in "'\"`":
            in_str = c
        elif c == "{":
            depth, opened = depth + 1, True
        elif c == "}":
            depth -= 1
            if opened and depth == 0:
                return i + 1
        elif c == ";" and depth == 0:
            return i + 1
        elif c == "\n" and depth == 0:
            # No semicolon: the statement ends where the next line starts a new
            # one -- a blank line, or anything at the left margin that does not
            # continue an expression.
            nxt = text[i + 1:i + 2]
            if nxt in ("", "\n") or (nxt not in (" ", "\t", ".", "?", ":", "|", "&", ")", "]", "}")
                                     and not text[start:i].rstrip().endswith(("=", "=>", "(", ",", "{"))):
                return i
        i += 1
    return n
