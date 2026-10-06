"""The owner's page (6 Oct 2026): needs you, the sprint board, impact, what happened."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from anthill import trail
from anthill.knowledge import work
from anthill.sprint import page
from anthill.ui import actions, status


def state(project):
    from anthill import goal
    from anthill.ui import todo
    w = work.where(project)
    return status.build(project, w, todo.build(w, goal.all_goals(project)), trail.read(project))


def test_the_board_shows_what_is_moving_paused_and_finished(project):
    page.new(project, "Refunds on the receipt", check="true", steps=["one", "two"])
    page.new(project, "Old idea", check="")
    g = page.load(project, "old-idea"); g["status"] = "stopped"; page.save(project, g)
    page.new(project, "Done thing", check="true")
    page.close(project, "done-thing", by="owner", because="merged")
    b = state(project)["board"]
    assert [c["title"] for c in b["in_progress"]] == ["Refunds on the receipt"]
    assert b["in_progress"][0]["steps"] == {"done": 0, "total": 2}
    assert [c["title"] for c in b["paused"]] == ["Old idea"]
    assert [f["title"] for f in b["finished_week"]] == ["Done thing"]


def test_an_agent_proposes_finished_the_owner_closes_or_keeps_it(project):
    page.new(project, "Refunds", check="")
    page.propose_finished(project, "refunds", "merged; nothing left but the owner's push")
    s = state(project)
    assert s["needs"]["close"] == [{"id": "refunds", "title": "Refunds",
                                    "because": "merged; nothing left but the owner's push"}]
    assert s["board"]["in_progress"][0]["looks_finished"]
    actions.keep_open(project, "refunds", "owner")
    assert state(project)["needs"]["close"] == []
    page.propose_finished(project, "refunds", "really done now")
    actions.close_sprint(project, "refunds", "really done now", "owner")
    s = state(project)
    assert s["needs"]["close"] == [] and [f["id"] for f in s["board"]["finished_week"]] == ["refunds"]


def test_impact_counts_what_anthill_did_and_admits_thin_data(project):
    p = trail.path(project)
    now = datetime.now(timezone.utc)
    lines = [{"t": (now - timedelta(hours=3)).isoformat(), "kind": "command", "verb": "guard",
              "args": "guard --push", "rc": 1, "branch": "work/x"},
             {"t": (now - timedelta(hours=2)).isoformat(), "kind": "session", "source": "resume", "session": "s1"},
             {"t": (now - timedelta(hours=1)).isoformat(), "kind": "decided", "text": "picked A", "session": "s1"},
             {"t": (now - timedelta(minutes=50)).isoformat(), "kind": "commit", "subject": "Show refunds", "session": "s1"}]
    with p.open("a") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines))
    s = state(project)
    im = s["impact"]
    assert im["pushes_stopped"]["n"] == 1
    assert im["picked_up"] == {"n": 1, "resumed": 1, "compressed": 0, "chats": 1}
    assert im["decided_for_you"]["n"] == 1
    assert im["fresh_chat"]["median_min"] is None          # too few chats to say anything
    kinds = [(e["kind"], e["text"]) for e in s["happened"][:3]]
    assert ("saved", "Show refunds") in kinds
    assert ("stopped", "A push from work/x was refused: only you push") in kinds
