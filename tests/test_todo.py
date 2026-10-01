"""The owner's to-do: real questions only, short, with choices that fit."""
from anthill.ui import todo


def test_a_pointer_a_status_and_a_repeat_never_reach_the_owner():
    where = {"work": [
        {"id": "pricing", "title": "Pricing", "state": "in-progress", "owner_answers": [], "waiting_on_owner": [
            "**Refund display.** Shown on the receipt or by email? Recommendation given to the owner: on the receipt. Not yet decided.",
            "**Three fixes from the audit** -- now built under the refunds goal, see [refunds](refunds.md) (25eafdf, 2e3d4a9).",
        ]},
        {"id": "receipts", "title": "Receipts", "state": "paused", "owner_answers": [], "waiting_on_owner": [
            "Still open from before: refund display (see [pricing](pricing.md)).",
            "The refund answer on the pricing page decides how receipts look.",
            "**Refund display.** Same question asked again here.",
        ]},
    ]}
    out = todo.build(where, [])
    assert [t["title"] for t in out["todo"]] == ["Refund display"]
    t = out["todo"][0]
    assert t["recommend"] == "on the receipt"
    assert "Not yet decided" not in t["why"] and "(" not in t["why"]


def test_choices_come_from_the_question_itself():
    p = todo.parse("**Landmarks and roads** (Hormuz): the free lookup forbids bulk use. Self-host it, or pay a service? Worth +2 points.")
    assert p["title"] == "Landmarks and roads" and p["options"] == ["Self-host it", "Pay a service"]


def test_the_agreed_form_is_read_exactly():
    p = todo.parse("**Show refunds where?** Why: customers ask support every week Recommend: on the receipt Options: Receipt / Email / Both")
    assert p == {"title": "Show refunds where?", "why": "customers ask support every week",
                 "recommend": "on the receipt", "options": ["Receipt", "Email", "Both"], "ask": "question"}


def test_code_names_and_hashes_are_cleaned_out():
    assert todo.clean("Defaults to `held` (sg: app/config.py::Settings), see [x](x.md) (25eafdf)") == "Defaults to held, see x"


def test_what_holds_up_a_goal_comes_first_and_an_answered_one_moves_aside():
    where = {"work": [{"id": "w", "title": "W", "state": "in-progress",
                       "owner_answers": ["01 Oct 10:00 — on “Spot-check the labels.”: **Done**"],
                       "waiting_on_owner": ["Spot-check the labels.", "**Pick a colour?** Why: brand"]}]}
    goals = [{"id": "g1", "title": "Goal", "blockers": [{"question": "Risk floor is the one stage left. Recommendation: group by what failed.", "answer": None}],
              "decided": [{"what": "Used one feed", "because": "never hardcode", "overturned": None}]}]
    out = todo.build(where, goals)
    assert out["todo"][0]["kind"] == "goal" and out["todo"][0]["holding_up"]
    assert out["todo"][0]["title"] == "Risk floor" and out["todo"][0]["recommend"] == "group by what failed"
    assert [a["title"] for a in out["answered"]] == ["Spot-check the labels."]
    assert out["review"] and out["review"][0]["what"] == "Used one feed"


def test_a_decision_marked_right_leaves_the_review(project, monkeypatch):
    from anthill import goal
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    g = goal.set_goal(project, "x", "true", ["one"])
    goal.decided(project, "picked A", "the rule")
    goal.acknowledge(project, g["id"], 0)
    assert todo.build({"work": []}, goal.all_goals(project))["review"] == []
