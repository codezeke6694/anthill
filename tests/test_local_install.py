"""Anthill pulled into the project it serves.

The tool and everything that stays on one laptop are invisible to the
project's git; what the team shares -- owner/, sprints/, knowledge/, skills/
under .anthill/ -- is ordinary project files (owner, 5 Oct).
"""
import json
import shutil
import subprocess
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


SHARED = ("owner/", "sprints/", "knowledge/", "skills/", ".gitignore")


def shared_only(proj):
    """What git can see is .anthill's shared folders, and nothing else."""
    seen = [line[3:] for line in git(proj, "status", "--porcelain", "-uall").splitlines()]
    assert seen, "the shared folders should be visible to git"
    for path in seen:
        assert path.startswith(".anthill/"), path
        rest = path[len(".anthill/"):]
        assert rest.startswith(SHARED), path
        assert not rest.startswith(("knowledge/_map/", "knowledge/.obsidian/")), path
    return seen


def test_a_copy_inside_the_project_shares_only_what_the_team_shares(tmp_path):
    proj = tmp_path / "shop"
    (proj / "shop").mkdir(parents=True)
    (proj / "shop" / "__init__.py").write_text("")
    (proj / "shop" / "cart.py").write_text('"""The cart."""\ndef total(xs):\n    return sum(xs)\n')
    (proj / ".gitignore").write_text("*.pyc\n")
    git(proj, "init", "-q", "-b", "main")
    git(proj, "add", "-A")
    git(proj, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "start")
    # what a person does: clone Anthill into the project, install from it
    shutil.copytree(TOOL_ROOT, proj / "anthill",
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"))
    r = subprocess.run([str(proj / "anthill" / "bin" / "anthill"), "install", "--name", "Shop", "--stack", "Python"],
                       cwd=proj, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr + r.stdout

    seen = shared_only(proj)                                          # teammates see the notebook, not the tool
    assert ".anthill/owner/settings.json" in seen and ".anthill/owner/charter.md" in seen
    assert (proj / ".gitignore").read_text() == "*.pyc\n"             # the shared ignore file is untouched
    assert (proj / "CLAUDE.local.md").exists() and not (proj / "CLAUDE.md").exists()
    assert not (proj / ".claude" / "settings.json").exists()
    local = json.loads((proj / ".claude" / "settings.local.json").read_text())
    assert local["permissions"]["deny"] and "Stop" in local["hooks"]
    assert "$CLAUDE_PROJECT_DIR/anthill/bin/anthill" in local["hooks"]["Stop"][0]["hooks"][0]["command"]
    rules = (proj / "CLAUDE.local.md").read_text()
    assert "./anthill/bin/anthill" in rules and "$(git rev-parse --show-toplevel)/anthill/bin" in rules
    cfg = json.loads((proj / ".anthill" / "owner" / "settings.json").read_text())
    assert cfg["install"] == {"local": True, "tool": "anthill"}
    assert "anthill" in cfg["source"]["exclude_parts"]                # the map is of the shop, not the tool

    # the guards still work, from the relative path, on a branch
    git(proj, "switch", "-q", "-c", "work/x")
    (proj / "shop" / "cart.py").write_text('"""The cart."""\ndef total(xs):\n    return sum(xs) or 0\n')
    git(proj, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "tidy")
    trail = (proj / ".anthill" / "local" / "log.jsonl").read_text()
    assert '"kind": "commit"' in trail and "tidy" in trail
    shared_only(proj)                                                 # the log and the map stayed local

    # a second install replaces its ignore block rather than adding another
    subprocess.run([str(proj / "anthill" / "bin" / "anthill"), "install", "--force", "--name", "Shop"],
                   cwd=proj, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    exclude = (proj / ".git" / "info" / "exclude").read_text()
    assert exclude.count("anthill (local install) >>>") == 1


def test_a_project_that_tracks_its_own_agents_file_keeps_it(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "AGENTS.md").write_text("# Our own agent rules\n")
    (proj / "app.py").write_text("x = 1\n")
    git(proj, "init", "-q", "-b", "main")
    git(proj, "add", "-A")
    git(proj, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "start")
    shutil.copytree(TOOL_ROOT, proj / "anthill",
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"))
    r = subprocess.run([str(proj / "anthill" / "bin" / "anthill"), "install", "--name", "P"],
                       cwd=proj, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert (proj / "AGENTS.md").read_text() == "# Our own agent rules\n"
    shared_only(proj)
