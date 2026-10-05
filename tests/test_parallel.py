"""Parallel pieces (owner, 5 Oct): one lead chat starts helpers for the
independent parts of a sprint; Anthill plans the waves and referees."""
from __future__ import annotations

import subprocess

import pytest

from anthill.sprint import page, parallel
from conftest import git


def sprint(project):
    page.new(project, "Screens and export", kind="planned", check="true")
    sid = "screens-and-export"
    parallel.add_piece(project, sid, "Home tests", ["tests/home/**"], "test -f tests/home/test_home.py")
    parallel.add_piece(project, sid, "Report tests", ["tests/report/**"], "test -f tests/report/test_report.py")
    parallel.add_piece(project, sid, "Export button", ["pkg/export.py"], "true", after=["report-tests"])
    return sid


def helper(project, branch, files, base="work/test"):
    """What a helper does in its own copy: branch, change, commit."""
    git(project.root, "switch", "-q", "-c", branch, base)
    for rel, text in files.items():
        p = project.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(project.root, "add", *files)
    git(project.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", f"piece {branch}")
    git(project.root, "switch", "-q", base)


def test_waves_run_the_independent_pieces_together(project):
    sid = sprint(project)
    ws = parallel.waves(project, page.load(project, sid))
    assert [[p["id"] for p in w] for w in ws] == [["home-tests", "report-tests"], ["export-button"]]
    plan = parallel.lead_plan(project, sid)
    assert "anthill sprint brief screens-and-export home-tests" in plan


def test_two_pieces_of_one_wave_may_not_share_a_file(project):
    sid = sprint(project)
    with pytest.raises(ValueError, match="both own"):
        parallel.add_piece(project, sid, "More home", ["tests/home/extra/**"], "true")


def test_a_brief_carries_the_piece_its_files_its_check(project):
    sid = sprint(project)
    b = parallel.brief(project, sid, "home-tests")
    assert "`tests/home/**`" in b and "test -f tests/home/test_home.py" in b
    assert "git switch -c piece/screens-and-export/home-tests" in b and "QUESTION:" in b


def test_the_referee_accepts_good_work_and_refuses_the_rest(project):
    sid = sprint(project)
    helper(project, "piece/a", {"tests/home/test_home.py": "def test_x():\n    assert True\n"})
    helper(project, "piece/b", {"tests/report/test_report.py": "x = 1\n", "pkg/core.py": "oops = 1\n"})
    helper(project, "piece/c", {"tests/report/notes.md": "no test file\n"})
    ok = parallel.referee(project, sid, "home-tests", "piece/a")
    assert ok["accepted"], ok
    out = parallel.referee(project, sid, "report-tests", "piece/b")
    assert not out["accepted"] and "does not own: pkg/core.py" in out["why"]
    out = parallel.referee(project, sid, "report-tests", "piece/c")
    assert not out["accepted"] and "check failed" in out["why"]
    # accepted work is on the holding branch, and nowhere else
    files = git(project.root, "ls-tree", "-r", "--name-only", "sprint/screens-and-export")
    assert "tests/home/test_home.py" in files and "pkg/core.py" in files and "oops" not in \
        git(project.root, "show", "sprint/screens-and-export:pkg/core.py")
    assert not (project.root / "tests/home/test_home.py").exists()     # the owner's folder untouched
    g = page.load(project, sid)
    st = {p["id"]: p["status"] for p in g["pieces"]}
    assert st == {"home-tests": "done", "report-tests": "refused", "export-button": "todo"}
    assert "**home-tests** [done]" in page.find(project, sid).read_text()


def test_a_helpers_question_reaches_the_owner(project):
    sid = sprint(project)
    parallel.ask(project, sid, "export-button", "CSV or Excel? I recommend CSV.")
    g = page.load(project, sid)
    assert g["status"] == "blocked"
    assert any("[piece export-button] CSV or Excel?" in b["question"] for b in g["blockers"])


def test_a_clash_on_the_holding_branch_is_stopped_and_shown(project):
    sid = sprint(project)
    helper(project, "piece/a", {"tests/home/test_home.py": "A = 1\n"})
    assert parallel.referee(project, sid, "home-tests", "piece/a")["accepted"]
    # a second attempt at the same piece, from the old base, writing the same file differently
    helper(project, "piece/a2", {"tests/home/test_home.py": "A = 2\n"})
    out = parallel.referee(project, sid, "home-tests", "piece/a2")
    assert not out["accepted"] and "clashes" in out["why"] and "tests/home/test_home.py" in out["why"]
    assert git(project.root, "show", "sprint/screens-and-export:tests/home/test_home.py") == "A = 1"
    assert "worktree" not in git(project.root, "worktree", "list").split("\n", 1)[-1] or \
        len(git(project.root, "worktree", "list").splitlines()) == 1       # no copies left behind
