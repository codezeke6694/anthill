"""What each sprint cost, from the chat records, with the keeper shown apart."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from anthill import cost, trail
from anthill.sprint import page

NOW = datetime.now(timezone.utc)


def reply(mid, model, t, session, branch="work/test", **u):
    usage = {"input_tokens": u.get("i", 0), "output_tokens": u.get("o", 0),
             "cache_creation_input_tokens": u.get("w", 0), "cache_read_input_tokens": u.get("r", 0)}
    return json.dumps({"type": "assistant", "timestamp": t.isoformat(), "sessionId": session,
                       "gitBranch": branch, "message": {"id": mid, "model": model, "usage": usage}})


@pytest.fixture
def records(project, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    d = cost.transcripts_dir(project)
    d.mkdir(parents=True)
    return d


def test_dollars_follow_the_price_list():
    # Opus 5.5: $4 in, $20 out, $0.20 cache read, cache write 1.25x input
    u = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_creation_input_tokens": 1_000_000,
         "cache_read_input_tokens": 10_000_000}
    assert cost.dollars("claude-opus-5-5", u) == pytest.approx(4 + 2 + 5 + 2)
    one_hour = {**u, "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1_000_000}}
    assert cost.dollars("claude-opus-5-5", one_hour) == pytest.approx(4 + 2 + 8 + 2)
    assert cost.dollars("claude-haiku-4-5-20251001", {"output_tokens": 1_000_000}) == pytest.approx(5)
    assert cost.dollars("<synthetic>", u) is None


def test_a_reply_goes_to_the_sprint_its_chat_worked_on_and_the_keeper_apart(project, records):
    page.new(project, "Rounding", check="true")
    trail.record("sprint", project, session="chat-a", sprint="rounding", action="step")
    t = NOW - timedelta(hours=1)
    main = [reply("m1", "claude-opus-5-5", t, "chat-a", o=1_000_000),
            reply("m1", "claude-opus-5-5", t, "chat-a", o=1_000_000),          # same reply, written twice
            reply("m2", "claude-opus-5-5", t, "chat-b", o=500_000)]              # a chat on no sprint
    (records / "chat-a.jsonl").write_text("\n".join(main[:2]) + "\n")
    (records / "chat-b.jsonl").write_text(main[2] + "\n")
    sub = records / "chat-a" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-k.jsonl").write_text(reply("k1", "claude-sonnet-5-5", t, "chat-a", o=100_000) + "\n")
    (sub / "agent-k.meta.json").write_text(json.dumps({"agentType": "anthill-keeper"}))

    r = cost.report(project)
    assert r["by_sprint"]["rounding"]["usd"] == pytest.approx(20 + 1)
    assert r["by_sprint"]["rounding"]["keeper_usd"] == pytest.approx(1)
    assert r["by_sprint"][cost.NO_SPRINT]["usd"] == pytest.approx(10)
    assert r["total_usd"] == pytest.approx(31) and r["keeper_usd"] == pytest.approx(1)


def test_a_shared_branch_alone_charges_nothing_to_a_sprint(project, records):
    page.new(project, "Rounding", check="true")
    (records / "other.jsonl").write_text(reply("x", "claude-opus-5-5", NOW, "other-chat", o=1_000_000) + "\n")
    r = cost.report(project)
    assert "rounding" not in r["by_sprint"] and r["by_sprint"][cost.NO_SPRINT]["usd"] == pytest.approx(20)


def test_the_week_and_the_cache(project, records):
    old, new = NOW - timedelta(days=20), NOW - timedelta(days=1)
    f = records / "c.jsonl"
    f.write_text(reply("a", "claude-opus-5-5", old, "c", o=1_000_000) + "\n"
                 + reply("b", "claude-opus-5-5", new, "c", o=1_000_000) + "\n")
    assert cost.report(project)["total_usd"] == pytest.approx(40)
    assert cost.report(project, days=7)["total_usd"] == pytest.approx(20)
    assert (project.local_dir / "cost.json").exists()
    with f.open("a") as fh:                                   # a new reply: the cache is redone
        fh.write(reply("c", "claude-opus-5-5", NOW, "c", o=1_000_000) + "\n")
    assert cost.report(project, days=7)["total_usd"] == pytest.approx(40)


def test_the_owner_s_page_shows_the_week(project, records):
    from anthill.ui import status
    (records / "c.jsonl").write_text(reply("a", "claude-opus-5-5", NOW, "c", o=1_000_000) + "\n")
    assert status._cost(project)["usd"] == pytest.approx(20)
