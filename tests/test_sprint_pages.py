"""Sprints (owner, 5 Oct): every piece of work is one page any chat can pick up."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from anthill import goal
from anthill.knowledge import pages, work
from anthill.sprint import page

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def run(repo: Path, *args: str, chat: str = "chat-a", ok: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": chat, "CLAUDECODE": "1"}
    r = subprocess.run([str(TOOL), *args], cwd=repo, capture_output=True, text=True, env=env)
    if ok:
        assert r.returncode == 0, r.stderr + r.stdout
    return r


def test_a_short_sprint_is_a_page_with_its_steps_and_check(project):
    run(project.root, "sprint", "start", "Refunds on the receipt", "--kind", "short",
        "--check", "true", "--step", "Show the refund line", "--step", "Total it")
    p = project.sprint_pages_dir / "active" / "refunds-on-the-receipt.md"
    text = p.read_text()
    fm = pages.parse_frontmatter(text)
    assert fm["kind"] == "short" and fm["state"] == "in-progress" and fm["check"] == "true"
    assert fm["next"] == "Show the refund line"
    assert "- [ ] Show the refund line" in text and "## Learned" in text
    row = [r for r in work.where(project)["work"] if r["id"] == "refunds-on-the-receipt"][0]
    assert row["kind"] == "short" and row["steps"] == {"done": 0, "total": 2}
    assert "short sprint · in progress · 0/2 steps" in work.render(work.where(project))


def test_a_bug_sprint_starts_by_showing_the_break(project):
    run(project.root, "sprint", "start", "Totals off by one", "--kind", "bug", "--check", "true",
        "--step", "Fix the rounding")
    g = page.load(project, "totals-off-by-one")
    assert g["steps"][0]["text"].startswith("Write a test that shows the break")


def test_another_chat_continues_the_sprint(project):
    run(project.root, "sprint", "start", "Refunds", "--check", "true", "--step", "one", chat="chat-a")
    # a different chat, another day, with no name for the sprint
    run(project.root, "sprint", "step", "--done", "1", chat="chat-b")
    run(project.root, "sprint", "decided", "Round half up", "--because", "the owner's pricing note", chat="chat-b")
    g = page.load(project, "refunds")
    assert g["steps"][0]["done"] and g["decided"][0]["what"] == "Round half up"
    text = page.find(project, "refunds").read_text()
    assert "- [x] one" in text and "Round half up — because the owner's pricing note" in text


def test_only_a_passing_check_closes_it_and_lessons_reach_the_shelf(project):
    run(project.root, "sprint", "start", "Refunds", "--check", "test -f done.flag")
    assert run(project.root, "sprint", "done", ok=False).returncode == 1
    assert page.find(project, "refunds").parent.name == "active"
    p = page.find(project, "refunds")
    p.write_text(p.read_text().replace(
        "## History", "- Warning: restarting with auto-reload stops the background jobs\n"
        "- Decision: refunds show as a negative line\n- Rule: a refund never exceeds the charge\n\n## History"))
    (project.root / "done.flag").write_text("")
    out = run(project.root, "sprint", "done").stdout
    assert "filed on the shared shelf" in out
    assert page.find(project, "refunds").parent.name == "done"
    kd = project.knowledge_dir
    assert "auto-reload stops the background jobs (from sprint refunds" in (kd / "TRAPS.md").read_text()
    dec = kd / "decisions" / "refunds-show-as-a-negative-line.md"
    assert dec.exists() and "intent_attested_by:\n" in dec.read_text()       # unsigned until the owner signs
    assert "a refund never exceeds the charge" in (kd / "LEARNED.md").read_text()
    assert "refunds" in [f["id"] for f in work.where(project)["finished"]]


def test_a_question_and_its_answer_show_on_the_page(project):
    run(project.root, "sprint", "start", "Refunds", "--check", "true")
    run(project.root, "sprint", "block", "Show refunds on the receipt? I recommend yes.")
    row = [r for r in work.where(project)["work"] if r["id"] == "refunds"][0]
    assert row["state"] == "waiting-on-owner"
    assert any("Show refunds on the receipt" in q for q in row["waiting_on_owner"])
    goal.owner_answer(project, "refunds", "Yes")
    row = [r for r in work.where(project)["work"] if r["id"] == "refunds"][0]
    assert row["state"] == "in-progress" and not row["waiting_on_owner"]
    assert any("Yes" in a for a in row["owner_answers"])


def test_only_the_driving_chat_is_sent_back(project):
    run(project.root, "sprint", "start", "Refunds", "--check", "false", "--step", "one", chat="chat-a")
    run(project.root, "sprint", "go", "refunds", chat="chat-a")
    assert goal.stop_hook(project, {"session_id": "chat-a"})["decision"] == "block"
    assert goal.stop_hook(project, {"session_id": "chat-b"}) is None
    # who drives is this laptop's business, not the team's
    shared = json.loads((project.sprint_pages_dir / "active" / "refunds.json").read_text())
    assert "session" not in shared and "stalls" not in shared


def test_the_old_goal_command_starts_a_driven_sprint(project):
    run(project.root, "goal", "set", "Refunds", "--done-when", "true", "--step", "one")
    g = page.load(project, "refunds")
    assert g["driving"] and g["session"] == "chat-a" and g["done_when"] == "true"


def test_a_next_step_that_wraps_is_read_whole():
    fm = pages.parse_frontmatter("---\nid: x\nnext: Reply pending from the owner on three\n"
                                 "  fixes from the 30 Sep run\nstate: paused\n---\n")
    assert fm["next"] == "Reply pending from the owner on three fixes from the 30 Sep run"
    assert fm["state"] == "paused"


def test_where_says_where_an_answer_came_from(project):
    from anthill.ui import actions
    run(project.root, "sprint", "start", "Refunds", "--check", "true")
    p = page.find(project, "refunds")
    p.write_text(p.read_text().replace("## Owner's answers\n",
                 "## Owner's answers\n\n- 5 Oct — on “Show refunds?”: **No** (said in chat)\n"))
    actions.answer(project, "refunds", "Round half up?", "Yes, half up")
    out = work.render(work.where(project))
    assert "Recorded by an agent as the owner's answer (not from their page): 5 Oct" in out
    assert "The owner answered, on their page:" in out and "Yes, half up" in out


def test_a_sprint_closed_by_hand_shows_red(project):
    run(project.root, "sprint", "start", "Refunds", "--check", "false")
    g = page.load(project, "refunds")
    g["status"] = "done"                                  # no passing check: closed by hand
    page.save(project, g)
    w = work.where(project)
    assert [c["id"] for c in w["closed_without_check"]] == ["refunds"]
    assert "its check never passed" in work.render(w)


def test_a_locked_check_cannot_be_moved_by_the_agent(project):
    (project.root / "answers.txt").write_text("kerala -> india\n")
    run(project.root, "sprint", "start", "Placement", "--check", "grep -q india answers.txt")
    run(project.root, "sprint", "lock", "placement", "--file", "answers.txt", "--by", "owner")
    # the agent "fixes" the answer key instead of the code
    (project.root / "answers.txt").write_text("kerala -> finland, india\n")
    r = run(project.root, "sprint", "done", ok=False)
    assert r.returncode == 1 and "answers.txt" in r.stderr and "locked" in r.stderr
    assert page.find(project, "placement").parent.name == "active"
    # nor can it swap the check for an easier one
    assert run(project.root, "sprint", "go", "placement", "--check", "true", ok=False).returncode == 2
    # the owner looks, and locks again
    run(project.root, "sprint", "lock", "placement", "--file", "answers.txt", "--by", "owner")
    assert run(project.root, "sprint", "done").returncode == 0


def test_settled_notes_are_not_questions_and_the_owner_closes_finished_work(project):
    run(project.root, "sprint", "start", "Refunds")
    p = page.find(project, "refunds")
    p.write_text(p.read_text().replace("## Waiting on the owner\n", "## Waiting on the owner\n\n"
                 "- Settled 5 Oct: refunds show as a negative line.\n"
                 "- Nothing for the next step.\n"
                 "- Show refunds on the receipt? I recommend yes.\n"))
    row = [r for r in work.where(project)["work"] if r["id"] == "refunds"][0]
    assert row["waiting_on_owner"] == ["Show refunds on the receipt? I recommend yes."]
    assert run(project.root, "sprint", "close", "refunds", ok=False).returncode == 2   # owner's only
    run(project.root, "sprint", "close", "refunds", "--by", "owner", "--because", "merged")
    w = work.where(project)
    assert "refunds" in [f["id"] for f in w["finished"]] and not w["closed_without_check"]
    assert "closed by owner: merged" in page.find(project, "refunds").read_text()
