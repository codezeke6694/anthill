"""One Anthill per team (owner, 5 Oct): the project records which Anthill it
uses, and every laptop's `anthill update` lands on it."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", msg)
    return git(repo, "rev-parse", "--short=12", "HEAD")


def anthill(proj, *args):
    r = subprocess.run([str(proj / "anthill" / "bin" / "anthill"), *args], cwd=proj,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def laptop(tmp, name, origin, project_origin=None):
    proj = tmp / name
    if project_origin:
        git(tmp, "clone", "-q", str(project_origin), name)
    else:
        (proj / "shop").mkdir(parents=True)
        (proj / "shop" / "cart.py").write_text("def total(x):\n    return sum(x)\n")
        git(proj, "init", "-q", "-b", "main")
        commit(proj, "start")
    git(proj, "clone", "-q", str(origin), "anthill")
    return proj


def test_the_team_runs_the_anthill_the_project_records(tmp_path):
    origin = tmp_path / "anthill-origin"
    shutil.copytree(TOOL_ROOT, origin, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    git(origin, "init", "-q", "-b", "main")
    v1 = commit(origin, "v1")

    me = laptop(tmp_path, "mine", origin)
    anthill(me, "install", "--name", "Shop", "--stack", "Python")
    settings = me / ".anthill" / "owner" / "settings.json"
    assert json.loads(settings.read_text())["anthill"]["version"] == v1

    # Anthill moves on; nobody's copy moves until someone decides
    (origin / "NEWS.md").write_text("v2\n")
    v2 = commit(origin, "v2")
    assert "the team's version" in anthill(me, "update")
    assert git(me / "anthill", "rev-parse", "--short=12", "HEAD") == v1

    # an agent may not move the team; the owner can
    r = subprocess.run([str(me / "anthill" / "bin" / "anthill"), "update", "--latest"], cwd=me,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and "owner's decision" in r.stdout + r.stderr
    anthill(me, "update", "--latest", "--by", "owner")
    assert json.loads(settings.read_text())["anthill"]["version"] == v2
    assert git(me / "anthill", "rev-parse", "--short=12", "HEAD") == v2

    # the shared settings travel with the project; a teammate's copy is behind until updated
    git(me, "switch", "-q", "-c", "work/anthill")
    commit(me, "Share the notebook")
    mate = laptop(tmp_path, "theirs", origin, project_origin=me)
    git(mate, "switch", "-q", "work/anthill")
    git(mate / "anthill", "checkout", "-q", "--detach", v1)
    assert f"the team uses `{v2}`" in anthill(mate, "where")
    anthill(mate, "update")
    assert git(mate / "anthill", "rev-parse", "--short=12", "HEAD") == v2
    assert "the team uses" not in anthill(mate, "where")
