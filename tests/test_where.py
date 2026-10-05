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
    # Pages about work are sprint pages on the new layout.
    if rel.startswith("work/"):
        rel = "../sprints/active/" + rel[len("work/"):]
    p = (repo / ".anthill" / "knowledge" / rel).resolve()
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
    assert "## Waiting on the owner\n\n- Is 2x fast enough?  _(adding)_" in out   # every question, in one place
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
    assert "anthill where" in text and text.index("anthill where") < text.index("anthill start")
    assert "carry on" in text
    keeper = (project.root / ".claude/agents/anthill-keeper.md").read_text()
    assert "a page is behind its branch" in keeper and "decisions/" in keeper


def test_the_board_and_the_pages_are_compared_where_they_disagree():
    from anthill.knowledge import work
    pages_ = [{"units": ["relevance.impl"], "state": "paused", "next": "Wait for the owner.",
               "title": "Reach"},
              {"units": ["risk-web.spec"], "state": "waiting-on-owner", "next": "",
               "title": "Two views"}]
    b = {"ready": [{"id": "relevance.impl", "title": ""}],
         "escalated": [{"id": "risk-web.spec", "since": "2026-09-22", "why": ""}]}
    said = work.disagreements(pages_, b)
    assert any("says `relevance.impl` is ready" in d and "Follow the page" in d for d in said)
    assert any("`risk-web.spec` has been escalated since 2026-09-22" in d for d in said)
    assert work.disagreements(pages_, {"ready": [], "escalated": []}) == []


def test_a_commit_outside_the_pages_code_is_not_drift(project):
    work_page(project.root, head(project.root))                     # cites pkg/core.py
    (project.root / "README.md").write_text("words\n")
    commit_all(project.root, "Edit the readme")
    assert "may be behind" not in anthill(project.root, "where")


def test_no_instruction_puts_anything_before_where(project):
    for doc in ("CLAUDE.md", "AGENTS.md"):
        text = (project.root / doc).read_text()
        assert "before anything else, find out whether a unit" not in text
        assert "after `anthill where`" in text
    status = json.loads(anthill(project.root, "work", "status", "--repo", ".")) \
        if project.work_root.exists() else None
    from anthill.navigate import router
    assert router.NEW_HERE["first"].startswith("anthill where")


def test_an_uncommitted_edit_is_shown_with_the_work_it_belongs_to(project):
    work_page(project.root, head(project.root))                     # cites pkg/core.py
    (project.root / "pkg/core.py").write_text("def add(a, b):\n    return a - -b\n")
    out = anthill(project.root, "where")
    assert "Being edited right now" in out
    assert "`pkg/core.py` — adding" in out


def test_a_fresh_install_shows_its_history_and_the_loop_starts_on_the_first_commit(project):
    out = anthill(project.root, "where")
    assert "No work page is open yet" in out
    assert "What has been happening" in out and "initial" in out
    git(project.root, "switch", "-q", "-c", "work/first-feature")
    (project.root / "pkg/new.py").write_text("def x():\n    return 1\n")
    commit_all(project.root, "Start the first feature")
    items = json.loads(anthill(project.root, "upkeep", "--json"))["open"]
    assert any(i["subject"] == "branch:work/first-feature" for i in items)


def test_orient_does_not_repeat_the_stack_when_the_description_is_blank(project):
    out = anthill(project.root, "orient")
    assert out.count("**Stack:**") <= 1


def test_untracked_work_is_found_in_a_repository_without_main(project):
    git(project.root, "branch", "-m", "main", "trunk")
    git(project.root, "switch", "-q", "-c", "work/on-trunk")
    (project.root / "pkg/new.py").write_text("def x():\n    return 1\n")
    commit_all(project.root, "Work on a trunk-based repo")
    assert "work/on-trunk" in anthill(project.root, "where")


def test_install_surveys_the_code_before_it_finishes(tmp_path, monkeypatch):
    from anthill import context as _ctx, install as inst
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "shop").mkdir()
    (repo / "shop" / "pricing.py").write_text('"""Prices."""\n\nTAX = 0.18\n\ndef total(x):\n    return x\n')
    commit_all(repo, "Start the shop")
    monkeypatch.chdir(repo)
    _ctx.current.cache_clear()
    out = inst.install(_ctx.resolve(repo), project_name="Shop", stack="Python", write=True)
    assert out["survey"]["map"]["nodes"] >= 1
    assert (repo / ".anthill/local/map/codebase.json").exists()
    assert "What Anthill knows already" in inst.render_survey(out["survey"])
    assert "places in the code" in anthill(repo, "survey")


def test_where_has_a_budget_and_all_shows_everything(project):
    for i in range(6):
        page(project.root, f"work/job{i}.md",
             f"---\nid: job{i}\ntitle: Job {i}\nstate: in-progress\n"
             f"updated: 2026-10-0{i + 1}\nnext: step {i}\n---\n\n## Traps\n\n- trap of job {i}\n")
    out = anthill(project.root, "where")
    assert "**Job 5** — in progress" in out and "**Job 4** — in progress" in out   # the latest two, in full
    assert "- **Job 0** — in progress — next: step 0" in out                     # the rest, one line
    assert "trap of job 5" in out and "trap of job 0" not in out
    assert "and 4 more on the other sprints" in out
    full = anthill(project.root, "where", "--all")
    assert "trap of job 0" in full and "Also open" not in full


def test_a_sprint_whose_branch_is_gone_shows_as_paused(project):
    page(project.root, "work/old.md", "---\nid: old\ntitle: Old work\nstate: in-progress\n"
         "branch: work/deleted-long-ago\nupdated: 2026-10-09\n---\n")
    row = [r for r in __import__("anthill.knowledge.work", fromlist=["x"]).where(project)["work"]
           if r["id"] == "old"][0]
    assert row["state"] == "paused" and row["branch_gone"]
    out = anthill(project.root, "where")
    assert "- **Old work** — paused (its branch is gone)" in out
    assert "state: in-progress" in (project.sprint_pages_dir / "active" / "old.md").read_text()  # not rewritten
