#!/usr/bin/env python3
"""What no shared repository survives: secrets, junk, and rewritten history.

The other guards protect the board -- who may commit where, who may push. These
protect everyone who pulls. Each one refuses something that, once it reaches
the remote, costs somebody else:

  * a secret     -- a key or a `.env` in history is public from the first push,
                    and deleting it later does not un-publish it;
  * a junk file  -- `.DS_Store`, `__pycache__`, `node_modules`: noise in every
                    diff, and conflicts on files nobody meant to share;
  * a force push -- replaces commits other people already have, so their next
                    pull no longer matches anything.

Deliberately high-confidence. A scanner that cries wolf teaches `--no-verify`,
and then it protects nothing. So the secret patterns are the ones with a fixed,
recognisable shape (a provider's key prefix, a private key header), not a guess
at anything named `password`. Only *added* lines and *new* files are judged, so
a commit is never refused for something that was already in the tree.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

# name -> pattern. Each is a shape a real credential has and prose does not.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Stripe live key": re.compile(r"\b[rs]k_live_[0-9A-Za-z]{24,}"),
}

# A `.env` is where secrets live. Its documented twin is how you share the shape.
ENV_TEMPLATES = (".example", ".sample", ".template", ".dist")
KEY_FILES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}
KEY_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}

JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
JUNK_DIRS = {"__pycache__", "node_modules", ".venv", ".pytest_cache", ".mypy_cache",
             ".ruff_cache"}
JUNK_SUFFIXES = {".pyc", ".pyo", ".swp"}


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout


def secret_file(rel: str) -> str:
    """Why this path is a secret by its name alone, or ''."""
    p = PurePosixPath(rel)
    name = p.name
    if name == ".env" or (name.startswith(".env.") and not name.endswith(ENV_TEMPLATES)):
        return "an environment file (share a `.env.example` instead)"
    if name in KEY_FILES:
        return "a private SSH key"
    if p.suffix.lower() in KEY_SUFFIXES:
        return "a key or certificate file"
    return ""


def junk_file(rel: str) -> str:
    """Why this path is machine- or build-local noise, or ''."""
    p = PurePosixPath(rel)
    if p.name in JUNK_NAMES:
        return "an operating-system file"
    hit = JUNK_DIRS & set(p.parts[:-1])
    if hit:
        return f"inside {sorted(hit)[0]}/, which is generated locally"
    if p.suffix in JUNK_SUFFIXES:
        return "a compiled or editor-temporary file"
    return ""


def _mask(token: str) -> str:
    return token[:6] + "…" if len(token) > 6 else "…"


def secret_lines(diff_text: str) -> list[dict]:
    """Secrets on the added lines of a `git diff -U0`."""
    found: list[dict] = []
    path, line_no = "", 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = target[2:] if target.startswith("b/") else ""
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and path:
            text = raw[1:]
            for kind, pat in SECRET_PATTERNS.items():
                m = pat.search(text)
                if m:
                    found.append({"file": path, "line": line_no, "kind": kind,
                                  "starts": _mask(m.group(0))})
                    break
            line_no += 1
    return found


def scan_staged(cwd: Path) -> list[dict]:
    """Everything wrong with what is staged, one entry per problem."""
    problems: list[dict] = []
    _, added = _git(["diff", "--cached", "--name-only", "--diff-filter=ACR"], cwd)
    for rel in (f for f in added.splitlines() if f.strip()):
        why = secret_file(rel)
        if why:
            problems.append({"file": rel, "problem": "secret", "why": why})
            continue
        why = junk_file(rel)
        if why:
            problems.append({"file": rel, "problem": "junk", "why": why})
    _, diff = _git(["diff", "--cached", "-U0", "--no-color", "--no-ext-diff",
                    "--diff-filter=ACMR"], cwd)
    for s in secret_lines(diff):
        problems.append({"file": s["file"], "problem": "secret",
                         "why": f"line {s['line']} looks like a {s['kind']} "
                                f"({s['starts']})"})
    return problems


def _null(sha: str) -> bool:
    return not sha or set(sha) == {"0"}


def forced_updates(updates: list[tuple[str, str, str, str]], cwd: Path) -> list[str]:
    """Remote branches this push would rewrite rather than extend.

    `updates` is pre-push stdin: (local ref, local sha, remote ref, remote sha).
    A normal push only adds commits on top of what the remote has. Anything
    else -- the remote's tip is not an ancestor of what is being sent, or we do
    not even have the remote's tip -- throws away commits someone may hold.
    Creating a branch and deleting one are not rewrites.
    """
    rewritten = []
    for _local_ref, local_sha, remote_ref, remote_sha in updates:
        if _null(local_sha) or _null(remote_sha):
            continue
        code, _ = _git(["merge-base", "--is-ancestor", remote_sha, local_sha], cwd)
        if code != 0:
            name = remote_ref[len("refs/heads/"):] if remote_ref.startswith(
                "refs/heads/") else remote_ref
            rewritten.append(name)
    return rewritten
