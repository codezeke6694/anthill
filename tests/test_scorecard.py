"""The scorecard: numbers read from the trail, and history read from saved chats and git."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthill import scorecard, trail
from conftest import commit_all


def at(base, minutes):
    return (base + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_asked_to_saved_is_measured_per_request_not_per_chat():
    now = datetime.now().astimezone()
    t0 = now - timedelta(days=1)
    evs = [
        {"t": at(t0, 0), "kind": "prompt", "session": "a"},
        {"t": at(t0, 1), "kind": "prompt", "session": "a"},
        {"t": at(t0, 5), "kind": "commit", "session": "a"},
        {"t": at(t0, 300), "kind": "prompt", "session": "a"},      # hours later, same chat
        {"t": at(t0, 303), "kind": "commit", "session": "a"},
    ]
    sc = scorecard.scorecard(evs, now=now)
    assert sc["asked_to_saved_median_min"] == 4.0                   # 5 and 3 minutes
    assert sc["messages_per_commit"] == 1.5
    assert sc["chats_list"][0]["to_first_change_min"] == 5.0
    assert len(sc["weekly"]) == 4 and sc["weekly"][-1]["commits"] == 2


def z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_import_takes_commits_from_git_not_from_mentions(project, monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    before = datetime.now().astimezone() - timedelta(seconds=30)
    (project.root / "pkg" / "x.py").write_text("X = 1\n")
    commit_all(project.root, "real change")
    after = datetime.now().astimezone() + timedelta(seconds=30)
    # the live trail from the commit hook would hide an import of the same moment
    trail.path(project).unlink()
    d = scorecard.claude_dir(project.root)
    d.mkdir(parents=True)
    root = str(project.root)
    lines = [
        {"type": "user", "timestamp": z(before - timedelta(minutes=3)), "cwd": root, "gitBranch": "work/test",
         "message": {"content": "carry on with placement"}},
        {"type": "assistant", "timestamp": z(before - timedelta(minutes=2)), "cwd": root, "gitBranch": "work/test",
         "message": {"content": [{"type": "tool_use", "id": "g1", "input": {"command": "grep -n 'git commit' notes.md"}}]}},
        {"type": "user", "timestamp": z(before - timedelta(minutes=2)), "cwd": root,
         "message": {"content": [{"type": "tool_result", "tool_use_id": "g1", "content": ""}]}},
        {"type": "assistant", "timestamp": z(before), "cwd": root, "gitBranch": "work/test",
         "message": {"content": [{"type": "tool_use", "id": "c1", "input": {"command": "git add -A && git commit -m 'real change' && anthill where"}}]}},
        {"type": "user", "timestamp": z(after), "cwd": root,
         "message": {"content": [{"type": "tool_result", "tool_use_id": "c1", "content": "ok"}]}},
    ]
    (d / "chat-1.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    out = scorecard.import_claude(project)
    evs = trail.read(project)
    commits = [e for e in evs if e["kind"] == "commit" and e["session"] == "chat-1"]
    assert "real change" in [c["subject"] for c in commits], out
    # the grep that only mentions committing made no commit of its own
    grep_t = (before - timedelta(minutes=2)).isoformat(timespec="seconds")
    assert not [c for c in commits if abs((datetime.fromisoformat(c["t"]) - datetime.fromisoformat(grep_t)).total_seconds()) < 20]
    assert [e["verb"] for e in evs if e["kind"] == "command"] == ["where"]
    assert sum(e["kind"] == "prompt" for e in evs) == 1
    assert scorecard.import_claude(project)["imported"] == 0      # once only
    assert scorecard.import_claude(project, redo=True)["imported"] == out["imported"]


def test_the_page_carries_the_numbers(project):
    from anthill import cli
    from anthill.ui import server
    cli.main(["where"])
    s = server.state(project)
    assert "weekly" in s["score"] and s["score"]["anthill_usage"].get("where") == 1


def test_a_correction_is_recorded_and_counted(project):
    import subprocess
    tool = Path(__file__).resolve().parents[1] / "bin" / "anthill"
    r = subprocess.run([str(tool), "correction", "--page", "placement",
                        "--was", "Pachpedwa crosses because of NEAR_KM",
                        "--now", "Pachpedwa crosses because the town list has no country",
                        "--why", "replayed the story"], cwd=project.root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    sc = scorecard.scorecard(trail.read(project))
    assert sc["corrections"] == 1 and sc["corrected"][0]["page"] == "placement"
    r = subprocess.run([str(tool), "correction", "--page", "placement"], cwd=project.root,
                       capture_output=True, text=True)
    assert r.returncode == 2
