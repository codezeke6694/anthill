"""The trail: every command and commit leaves a line, and a crash is never silent."""
import json
import subprocess
from pathlib import Path

import pytest

from anthill import cli, trail
from conftest import commit_all

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def events(ctx):
    return trail.read(ctx)


def test_a_command_records_who_ran_it(project, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "chat-1234")
    assert cli.main(["where"]) == 0
    ev = events(project)[-1]
    assert ev["kind"] == "command" and ev["verb"] == "where" and ev["rc"] == 0
    assert ev["tool"] == "claude-code" and ev["session"] == "chat-1234"
    assert ev["branch"] == "work/test"


def test_another_tool_is_named_too(project, monkeypatch):
    for k in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "AI_AGENT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CODEX_SESSION_ID", "cx-9")
    cli.main(["where"])
    ev = events(project)[-1]
    assert ev["tool"] == "codex" and ev["session"] == "cx-9"


def test_a_crash_is_recorded_and_still_raised(project, monkeypatch):
    def boom(argv):
        raise ValueError("symbol id must look like path/to/file.py::name: run.sh")
    monkeypatch.setattr(cli, "_dispatch", boom)
    with pytest.raises(ValueError):
        cli.main(["blueprint", "--all"])
    ev = events(project)[-1]
    assert ev["verb"] == "blueprint" and "run.sh" in ev["crashed"]
    h = trail.health(project)
    assert h["crashes"] and h["checks"][-1]["crashed"]


def test_every_commit_leaves_a_line(project):
    (project.root / "pkg" / "more.py").write_text("X = 1\n")
    commit_all(project.root, "add more")
    commits = [e for e in events(project) if e["kind"] == "commit"]
    assert commits and commits[-1]["subject"] == "add more"
    assert "pkg/more.py" in commits[-1]["paths"]


def test_a_torn_line_is_skipped(project):
    cli.main(["where"])
    with trail.path(project).open("a") as fh:
        fh.write('{"t": "2026-09-29T1')          # an interrupted write
    assert events(project)[-1]["verb"] == "where"


def test_the_page_shows_the_trail(project):
    from anthill.ui import server
    cli.main(["where"])
    s = server.state(project)
    assert s["trail"]["recent"][-1]["verb"] == "where"
    assert any(c["verb"] == "where" for c in s["trail"]["checks"])


def test_no_install_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from anthill import context as _ctx
    _ctx.current.cache_clear()
    trail.record("command", verb="where")
    assert not (tmp_path / ".anthill").exists()
