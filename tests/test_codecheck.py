"""Coding standards: a skill to read, cheap checks after each commit, and a new
package that waits for the owner."""
import json

from anthill import codecheck, guard, risky, skills
from conftest import commit_all, git, reload


def write(project, rel, text):
    p = project.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def found(project):
    return {(f["check"], f["file"]) for f in codecheck.check(project)}


def test_a_personal_path_is_flagged(project):
    write(project, "pkg/paths.py", 'DATA = "/Users/kamal/data/cache.db"\n')
    commit_all(project.root, "paths")
    assert ("personal path", "pkg/paths.py") in found(project)


def test_one_long_new_block_is_flagged_and_a_short_one_is_not(project):
    write(project, "pkg/big.py", "def big():\n" + "".join(f"    x{i} = {i}\n" for i in range(70)))
    write(project, "pkg/small.py", "def small():\n    return 1\n")
    commit_all(project.root, "blocks")
    f = found(project)
    assert ("long block", "pkg/big.py") in f and ("long block", "pkg/small.py") not in f


def test_comment_heavy_code_is_flagged(project):
    body = "".join(f"# reason {i}\nx{i} = {i}\n" for i in range(20))
    write(project, "pkg/talky.py", body)
    write(project, "pkg/essay.py", "x = 1\n" + "".join(f"# line {i} of an essay\n" for i in range(10)) + "y = 2\n")
    write(project, "pkg/plain.py", "".join(f"x{i} = {i}\n" for i in range(30)) + "# one reason\n")
    commit_all(project.root, "comments")
    f = found(project)
    assert ("comment-heavy", "pkg/talky.py") in f and ("comment-heavy", "pkg/essay.py") in f
    assert ("comment-heavy", "pkg/plain.py") not in f


def test_documents_are_not_code_and_the_checks_can_be_turned_off(project):
    write(project, "notes.md", "# heading\n" * 40 + "/Users/kamal/x\n")
    write(project, "pkg/paths.py", 'P = "/home/kamal/x"\n')
    commit_all(project.root, "docs")
    assert not any(f["file"] == "notes.md" for f in codecheck.check(project))
    project.config["execution"]["code_checks"] = False
    project.save_config()
    assert codecheck.check(reload(project)) == []


def test_a_new_package_waits_for_the_owner(project, monkeypatch):
    write(project, "package.json", json.dumps({"scripts": {"dev": "vite"}, "dependencies": {"react": "18"}}))
    monkeypatch.setenv("ANTHILL_OWNER", "1")              # the owner set the project up
    commit_all(project.root, "manifest")
    monkeypatch.delenv("ANTHILL_OWNER")
    write(project, "package.json", json.dumps({"scripts": {"dev": "vite --host"}, "dependencies": {"react": "18"}}))
    git(project.root, "add", "package.json")
    assert guard.check(project, project.root)[1] == guard.ALLOW            # only a script changed
    write(project, "package.json", json.dumps({"scripts": {"dev": "vite"}, "dependencies": {"react": "18", "left-pad": "1"}}))
    write(project, "requirements.txt", "requests==2.32\n")
    git(project.root, "add", "package.json", "requirements.txt")
    report, code = guard.check(project, project.root)
    assert code == guard.REFUSE and set(report["risky"]) == {"package.json", "requirements.txt"}
    assert "supply-chain" in report["why"]

    asked = risky.ask(project, ["package.json", "requirements.txt"], why="add left-pad and requests")
    assert asked["asked"] and risky.pending(project)[0]["kind"] == "package"
    risky.decide(project, asked["id"], True, by="kamal", via="owner page")
    assert guard.check(project, project.root)[1] == guard.ALLOW


def test_the_owner_commits_packages_freely_and_can_turn_the_rule_off(project, monkeypatch):
    write(project, "requirements.txt", "requests==2.32\n")
    git(project.root, "add", "requirements.txt")
    assert guard.check(project, project.root)[1] == guard.REFUSE
    monkeypatch.setenv("ANTHILL_OWNER", "1")
    assert guard.check(project, project.root)[1] == guard.ALLOW
    monkeypatch.delenv("ANTHILL_OWNER")
    project.config["execution"]["dependencies_need_owner"] = False
    project.save_config()
    ctx = reload(project)
    assert guard.check(ctx, ctx.root)[1] == guard.ALLOW


def test_the_coding_standards_ship_with_anthill(project):
    s = {r["name"]: r for r in skills.load_all(project)}["coding-standards"]
    assert s.get("load_class") == "conditional"


def test_the_commit_hook_runs_the_checks(project):
    from anthill import install
    assert '"$ANTHILL" codecheck' in install.POST_HOOK
