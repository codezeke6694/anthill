"""Claude's check before each edit: a helper stays inside its piece's files."""
import json
import subprocess
import sys

from anthill import edits
from anthill.sprint import page, parallel
from conftest import TOOL_ROOT, git


def plan(project):
    page.new(project, "Screens and export", kind="planned", check="true")
    sid = "screens-and-export"
    parallel.add_piece(project, sid, "Home tests", ["tests/home/**"], "true")
    parallel.add_piece(project, sid, "Export button", ["pkg/export.py"], "true")
    return sid


def edit(path, cwd, tool="Edit"):
    return {"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(cwd), "session_id": "h1"}


def test_a_helper_may_edit_its_own_files(project):
    sid = plan(project)
    git(project.root, "switch", "-q", "-c", f"piece/{sid}/home-tests")
    assert edits.piece_hook(edit(project.root / "tests/home/test_home.py", project.root)) is None
    assert edits.piece_hook(edit("tests/home/new_dir/test_more.py", project.root, "Write")) is None


def test_an_edit_outside_the_piece_is_refused_before_it_happens(project):
    sid = plan(project)
    git(project.root, "switch", "-q", "-c", f"piece/{sid}/export-button")
    out = edits.piece_hook(edit(project.root / "pkg/core.py", project.root))
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "pkg/core.py" in reason and "pkg/export.py" in reason
    assert f"anthill sprint ask {sid} export-button" in reason


def test_in_its_own_copy_the_helper_is_held_to_the_lead_s_plan(project, tmp_path):
    sid = plan(project)
    wt = tmp_path / "helper-copy"
    git(project.root, "worktree", "add", "-q", "-b", f"piece/{sid}/export-button", str(wt))
    assert edits.piece_hook(edit(wt / "pkg/export.py", wt)) is None
    assert edits.piece_hook(edit(wt / "pkg/core.py", wt)) is not None


def test_ordinary_branches_and_other_tools_are_left_alone(project):
    plan(project)
    assert edits.piece_hook(edit(project.root / "pkg/core.py", project.root)) is None        # work/test
    git(project.root, "switch", "-q", "-c", "piece/no-such-sprint/x")
    assert edits.piece_hook(edit(project.root / "pkg/core.py", project.root)) is None
    assert edits.piece_hook({"tool_name": "Read", "tool_input": {"file_path": "pkg/core.py"},
                             "cwd": str(project.root)}) is None


def test_the_one_hook_answers_both_questions(project):
    sid = plan(project)
    git(project.root, "switch", "-q", "-c", f"piece/{sid}/export-button")
    cmd = [sys.executable, str(TOOL_ROOT / "anthill" / "cli.py"), "edit", "--hook"]
    run = lambda d: subprocess.run(cmd, cwd=project.root, input=json.dumps(d), capture_output=True, text=True)
    db = run(edit(project.root / "migrations/versions/0001.py", project.root))
    assert "database change" in json.loads(db.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    outside = run(edit(project.root / "pkg/core.py", project.root))
    assert "outside this piece" in json.loads(outside.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert run(edit(project.root / "pkg/export.py", project.root)).stdout == ""
    bad = subprocess.run(cmd, cwd=project.root, input="{", capture_output=True, text=True)
    assert bad.returncode == 0 and bad.stdout == ""
