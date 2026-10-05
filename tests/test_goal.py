"""Goal mode: an agent told to finish something keeps going until it is done,
a real question stops it, or it stops making progress."""
import json
import subprocess
from pathlib import Path

from anthill import goal, resume, trail

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def as_chat(monkeypatch, sid):
    monkeypatch.delenv("ANTHILL_SESSION", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


def hook(project, sid):
    return goal.stop_hook(project, {"session_id": sid, "stop_hook_active": False})


def test_an_unfinished_goal_sends_the_agent_back_with_the_next_step(project, monkeypatch):
    as_chat(monkeypatch, "c1")
    goal.set_goal(project, "price carts in the buyer's currency", "true",
                  ["add exchange rates", "use them at checkout"])
    out = hook(project, "c1")
    assert out["decision"] == "block"
    assert "Next: step 1: add exchange rates" in out["reason"]
    assert "goal block" in out["reason"] and "pushing, or merging into main" in out["reason"]


def test_no_goal_or_a_blocked_goal_lets_the_turn_end(project, monkeypatch):
    as_chat(monkeypatch, "c2")
    assert hook(project, "c2") is None
    goal.set_goal(project, "do a thing", "true", ["one"])
    goal.block(project, "Show refunds on the receipt? I recommend yes.")
    assert hook(project, "c2") is None
    assert goal.current(project)["status"] == "blocked"


def test_a_chat_that_makes_no_progress_is_let_go_and_marked_stalled(project, monkeypatch):
    as_chat(monkeypatch, "c3")
    goal.set_goal(project, "spin", "true", ["one"])
    assert hook(project, "c3")                                     # first push back
    assert hook(project, "c3") and hook(project, "c3")             # no progress: stall 1, 2
    assert hook(project, "c3") is None                             # stall 3: let go
    assert goal.all_goals(project)[0]["status"] == "stalled"
    assert any(e.get("action") == "stalled" for e in trail.read(project))


def test_progress_keeps_the_brake_off(project, monkeypatch):
    as_chat(monkeypatch, "c4")
    goal.set_goal(project, "real work", "true", ["one", "two"])
    for i in range(5):
        assert hook(project, "c4")
        resume.note(project, f"did part {i}")                     # progress each time
    assert goal.current(project)["stalls"] == 0


def test_only_a_passing_check_closes_a_goal(project, monkeypatch):
    as_chat(monkeypatch, "c5")
    goal.set_goal(project, "fails first", "false", [])
    g = goal.finish(project)
    assert g["status"] == "active" and not g["result"]["passed"]
    goal.all_goals(project)[0]  # still open
    g = goal.load(project, g["id"]); g["done_when"] = "true"; goal.save(project, g)
    assert goal.finish(project)["status"] == "done"
    assert hook(project, "c5") is None                             # done: free to stop


def test_a_decision_for_the_owner_is_logged_and_can_be_overturned(project, monkeypatch):
    as_chat(monkeypatch, "c6")
    g = goal.set_goal(project, "currency", "true", ["one"])
    goal.decided(project, "rates from one daily feed, no hand-typed table",
                 "owner decision: never hardcode")
    assert trail.read(project)[-1]["kind"] == "decided"
    goal.overturn(project, g["id"], 0, "use the bank's rate instead")
    page = resume.resume(project, "c6")
    assert "OVERTURNED" in page and "bank's rate" in page


def test_the_owners_answer_reopens_the_goal_and_reaches_the_agent(project, monkeypatch):
    as_chat(monkeypatch, "c7")
    g = goal.set_goal(project, "refunds", "true", ["decide display"])
    goal.block(project, "On the receipt, or a separate email?")
    goal.owner_answer(project, g["id"], "on the receipt")
    assert goal.current(project)["status"] == "active"
    assert "on the receipt" in hook(project, "c7")["reason"]


def test_the_hook_speaks_claudes_format(project):
    subprocess.run([str(TOOL), "goal", "set", "hooked goal", "--done-when", "true", "--step", "one"],
                   cwd=project.root, capture_output=True, text=True,
                   env={**__import__("os").environ, "ANTHILL_SESSION": "c8"})
    r = subprocess.run([str(TOOL), "goal", "--hook"], cwd=project.root, capture_output=True, text=True,
                       input=json.dumps({"session_id": "c8", "stop_hook_active": False}))
    assert json.loads(r.stdout)["decision"] == "block"


def test_install_adds_the_stop_hook_and_the_rule(project):
    hooks = json.loads((project.root / ".claude" / "settings.local.json").read_text())["hooks"]
    assert "goal --hook" in hooks["Stop"][0]["hooks"][0]["command"]
    for doc in ("CLAUDE.md", "AGENTS.md"):
        text = (project.root / doc).read_text()
        assert "End to end" in text and "anthill sprint go" in text and "sprint decided" in text
