"""A throwaway project with anthill installed, for every test.

The tool has had eleven fixes verified by hand in a temporary repository that
was then deleted. This fixture is that repository, kept.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from anthill import context as _ctx          # noqa: E402
from anthill import install as inst          # noqa: E402


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def commit_all(repo: Path, msg: str = "work") -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A git repo with one Python district, one test dir, and anthill installed."""
    repo = tmp_path / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "core.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "core").mkdir()
    (repo / "tests" / "core" / "test_add.py").write_text(
        "from pkg.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    (repo / "web").mkdir()
    (repo / "web" / "app.ts").write_text("export const x = 1;\n")
    (repo / ".gitignore").write_text(".anthill/\n")
    commit_all(repo, "initial")

    monkeypatch.chdir(repo)
    monkeypatch.delenv("ANTHILL_PROJECT", raising=False)
    monkeypatch.delenv("ANTHILL_OWNER", raising=False)
    _ctx.current.cache_clear()
    ctx = _ctx.resolve(repo)
    out = inst.install(ctx, project_name="Proj", stack="Python", write=True)
    assert out.get("created"), out
    # install put the real hooks in place, and they refuse commits on `main`;
    # every commit a test makes from here runs through them, on a work branch.
    git(repo, "switch", "-q", "-c", "work/test")
    _ctx.current.cache_clear()
    yield _ctx.resolve(repo)
    _ctx.current.cache_clear()


def reload(ctx: _ctx.Context) -> _ctx.Context:
    _ctx.current.cache_clear()
    return _ctx.resolve(ctx.root)


def read_config(ctx: _ctx.Context) -> dict:
    return json.loads(ctx.config_path.read_text())
