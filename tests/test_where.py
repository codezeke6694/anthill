"""A cold agent learns *what* to work on, and the page it learns from cannot
fall behind without saying so."""
import json
import subprocess
from pathlib import Path

from anthill import rules
from conftest import commit_all, git

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def anthill(repo: Path, *args: str) -> str:
    r = subprocess.run([str(TOOL), *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def page(repo: Path, rel: str, text: str) -> None:
    p = repo / ".anthill" / "knowledge" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def work_page(repo: Path, true_at: str, branch: str = "work/test", cite: str = "pkg/core.py::add") -> None:
    page(repo, "work/adding.md",
         f"---\nid: adding\ntype: work\ntitle: Make adding faster\nstate: waiting-on-owner\n"
         f"branch: {branch}\ntrue_at: {true_at}\nupdated: 2026-09-28\n"
         f"next: Measure it, then switch.\n---\n\n## Where\n\n- (sg: {cite})\n\n"
         "## Waiting on the owner\n\n- Is 2x fast enough?\n\n## Traps\n\n- Saving restarts the server.\n")


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD")


def test_where_names_the_work_its_next_step_and_what_waits_on_the_owner(project):
    work_page(project.root, head(project.root))
    page(project.root, "decisions/global.md",
         "---\nid: global\ntype: decision\ntitle: The market is global\ndecided: 2026-09-18\n---\nWhy.\n")
    out = anthill(project.root, "where")
    assert "**Make adding faster** — waiting on owner" in out
    assert "Next: Measure it, then switch." in out
    assert "Waiting on the owner: Is 2x fast enough?" in out
    assert "The market is global (2026-09-18)" in out
    assert "Saving restarts the server." in out
    assert "may be behind" not in out


def test_a_commit_on_the_branch_after_the_page_was_true_is_drift(project):
    work_page(project.root, head(project.root))
    (project.root / "pkg/core.py").write_text("def add(a, b):\n    return b + a\n")
    commit_all(project.root, "Switch the adder")
    out = anthill(project.root, "where")
    assert "This page may be behind: 1 commit(s)" in out and "Switch the adder" in out
    items = json.loads(anthill(project.root, "upkeep", "--json"))["open"]
    assert any(i["subject"] == "work:adding" for i in items)


def test_re_pinning_the_page_clears_the_drift(project):
    work_page(project.root, head(project.root))
    commit_all(project.root, "More work")
    work_page(project.root, head(project.root))
    assert "may be behind" not in anthill(project.root, "where")


def test_recent_work_no_page_describes_is_named(project):
    work_page(project.root, head(project.root))
    git(project.root, "switch", "-q", "-c", "work/secret-project")
    (project.root / "pkg/new.py").write_text("def x():\n    return 1\n")
    commit_all(project.root, "Start something nobody wrote down")
    out = anthill(project.root, "where")
    assert "Work no page describes" in out and "work/secret-project" in out
    items = json.loads(anthill(project.root, "upkeep", "--json"))["open"]
    assert any(i["subject"] == "branch:work/secret-project" for i in items)


def test_a_branch_inside_a_tracked_one_is_its_history_not_new_work(project):
    git(project.root, "branch", "work/older")                    # same commit, then left behind
    (project.root / "pkg/core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    commit_all(project.root, "Newer work on top")
    work_page(project.root, head(project.root))
    assert "work/older" not in anthill(project.root, "where")


def test_a_page_citing_code_that_is_gone_says_so(project):
    work_page(project.root, head(project.root), cite="pkg/core.py::vanished")
    assert "Cites code that is gone: pkg/core.py::vanished" in anthill(project.root, "where")


def test_the_rules_send_a_cold_agent_to_where_first(project):
    text = (project.root / "CLAUDE.md").read_text()
    assert "anthill where" in text and rules.cold_start_rule(project) in text
    assert "carry on" in text
    keeper = (project.root / ".claude/agents/anthill-keeper.md").read_text()
    assert "a page is behind its branch" in keeper and "decisions/" in keeper
