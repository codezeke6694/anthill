"""Database changes wait for the owner: refused at the edit and at the commit."""
import json
import subprocess
import sys

from anthill import guard, install, risky
from anthill.knowledge import work
from anthill.ui import todo
from conftest import TOOL_ROOT, git, reload

MIG = "migrations/versions/0042_add_column.py"


def edit(path, tool="Edit"):
    return {"tool_name": tool, "tool_input": {"file_path": path}, "session_id": "s1"}


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "session_id": "s1"}


def test_migration_folders_are_risky_by_default(project):
    assert risky.is_risky(project, MIG)
    assert risky.is_risky(project, "app/db/migrate/2026_add.rb")
    assert risky.is_risky(project, str(project.root / MIG))       # absolute, as Claude sends it
    assert not risky.is_risky(project, "pkg/core.py")
    assert not risky.is_risky(project, "/elsewhere/migrations/x.py")


def test_the_project_names_its_own_paths_and_an_empty_list_turns_it_off(project):
    project.config["execution"]["risky_paths"] = ["schema/**"]
    project.save_config()
    ctx = reload(project)
    assert risky.is_risky(ctx, "schema/tables.sql") and not risky.is_risky(ctx, MIG)
    ctx.config["execution"]["risky_paths"] = []
    ctx.save_config()
    ctx = reload(ctx)
    assert risky.hook(ctx, edit(MIG)) is None


def test_an_edit_is_refused_until_the_owner_allows_it(project):
    out = risky.hook(project, edit(str(project.root / MIG), "Write"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "anthill risky ask" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert risky.hook(project, edit("pkg/core.py")) is None

    asked = risky.ask(project, [MIG], why="add the region column")
    assert asked["asked"] and risky.pending(project)
    assert risky.ask(project, [MIG], why="again")["already"]          # one question, not two
    assert risky.hook(project, edit(MIG)) is not None                  # asking is not allowing

    risky.decide(project, asked["id"], True, by="kamal", via="owner page")
    assert risky.hook(project, edit(MIG)) is None
    assert not risky.pending(project)
    assert risky.hook(project, edit("migrations/versions/0043_other.py")) is not None


def test_a_refused_request_stays_refused(project):
    rid = risky.ask(project, [MIG], why="drop a table")["id"]
    assert risky.decide(project, rid, False, by="kamal")["status"] == "refused"
    assert risky.hook(project, edit(MIG)) is not None
    assert not risky.decide(project, rid, True, by="kamal")["decided"]


def test_a_shell_command_that_writes_a_risky_file_is_refused(project):
    assert risky.hook(project, bash(f"cat > {MIG} <<'EOF'\nx\nEOF")) is not None
    assert risky.hook(project, bash(f"sed -i '' 's/a/b/' {MIG}")) is not None
    assert risky.hook(project, bash(f"cat {MIG}")) is None           # reading is fine
    assert risky.hook(project, bash("pytest -q")) is None


def test_the_commit_is_refused_too_and_the_owner_may_commit(project, monkeypatch):
    f = project.root / MIG
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n")
    git(project.root, "add", MIG)
    report, code = guard.check(project, project.root)
    assert code == guard.REFUSE and report["risky"] == [MIG]

    rid = risky.ask(project, [MIG], why="add the region column")["id"]
    risky.decide(project, rid, True, by="kamal")
    assert guard.check(project, project.root)[1] == guard.ALLOW

    rid2 = risky.ask(project, ["migrations/versions/0044.py"], why="x")["id"]
    g = project.root / "migrations/versions/0044.py"
    g.write_text("y = 2\n")
    git(project.root, "add", "-A")
    assert guard.check(project, project.root)[1] == guard.REFUSE
    monkeypatch.setenv("ANTHILL_OWNER", "1")
    assert guard.check(project, project.root)[1] == guard.ALLOW
    assert rid2


def test_only_the_owner_allows_from_the_terminal(project, monkeypatch):
    rid = risky.ask(project, [MIG], why="add the region column")["id"]
    cmd = [sys.executable, str(TOOL_ROOT / "anthill" / "cli.py"), "risky", "allow", rid, "--by", "agent"]
    r = subprocess.run(cmd, cwd=project.root, capture_output=True, text=True)
    assert r.returncode == 1 and "owner's decision" in r.stdout
    assert risky.pending(project)
    r = subprocess.run(cmd, cwd=project.root, capture_output=True, text=True,
                       env={**__import__("os").environ, "ANTHILL_OWNER": "1"})
    assert r.returncode == 0 and json.loads(r.stdout)["status"] == "allowed"


def test_the_hook_command_never_blocks_on_its_own_fault(project):
    cmd = [sys.executable, str(TOOL_ROOT / "anthill" / "cli.py"), "risky", "--hook"]
    r = subprocess.run(cmd, cwd=project.root, input="not json", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
    r = subprocess.run(cmd, cwd=project.root, input=json.dumps(edit(MIG)), capture_output=True, text=True)
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_owner_sees_it_on_their_page_and_in_where(project):
    risky.ask(project, [MIG], why="add the region column")
    w = work.where(project)
    assert w["risky_waiting"][0]["files"] == [MIG]
    item = todo.build(w, [])["todo"][0]
    assert item["kind"] == "risky" and item["options"] == ["Allow", "Refuse"]
    assert "Allow a database change" in work.render(w, {})


def test_install_adds_the_edit_hook_with_its_matcher(project):
    settings = {}
    install.merge_claude_hooks(settings, "anthill")
    pre = settings["hooks"]["PreToolUse"]
    assert pre[0]["matcher"].startswith("Edit|Write") and "edit --hook" in pre[0]["hooks"][0]["command"]
    assert install.merge_claude_hooks(settings, "anthill") == []      # twice changes nothing


def test_every_chat_is_told_how_to_ask(project):
    from anthill import rules
    assert "anthill risky ask" in rules._git_short(project)
