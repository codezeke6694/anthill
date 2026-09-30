"""Picking work up again: after a compression, in a new chat, in another tool."""
import json
import subprocess
from pathlib import Path

from anthill import install as inst, resume, trail
from conftest import commit_all, reload

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def run(repo, *args, stdin=""):
    r = subprocess.run([str(TOOL), *args], cwd=repo, capture_output=True, text=True, input=stdin)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def as_chat(monkeypatch, sid):
    for k in ("ANTHILL_SESSION", "CODEX_SESSION_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


def transcript(tmp_path, owner, agent):
    p = tmp_path / "chat.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"type": "user", "message": {"content": "earlier"}},
        {"type": "user", "message": {"content": owner}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": agent}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
    ]) + "\n")
    return p


def test_a_note_comes_back_to_the_chat_that_left_it(project, monkeypatch):
    as_chat(monkeypatch, "chat-a")
    resume.note(project, "testing the refund total; ruled out rounding; next replay without the discount")
    page = resume.resume(project, "chat-a")
    assert "Your notes in this chat" in page and "ruled out rounding" in page


def test_a_compression_hands_back_what_was_in_flight(project, monkeypatch, tmp_path):
    as_chat(monkeypatch, "chat-b")
    (project.root / "pkg" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    tp = transcript(tmp_path, "try it with the discount off", "Replaying the order now.")
    resume.checkpoint(project, {"session_id": "chat-b", "transcript_path": str(tp), "trigger": "auto"})
    page = resume.session_start_hook(project, {"session_id": "chat-b", "source": "compact"})
    assert "try it with the discount off" in page
    assert "Replaying the order now." in page
    assert "pkg/core.py" in page
    assert trail.read(project)[-1]["kind"] == "session"


def test_a_new_chat_sees_what_another_chat_left(project, monkeypatch):
    as_chat(monkeypatch, "chat-old")
    resume.note(project, "refund fix done; five live orders still wrong, waiting on owner")
    as_chat(monkeypatch, "chat-new")
    page = resume.session_start_hook(project, {"session_id": "chat-new", "source": "startup"})
    assert "Left on this branch by other chats" in page and "five live orders" in page


def test_a_new_chat_on_a_quiet_branch_gets_nothing_extra(project, monkeypatch):
    as_chat(monkeypatch, "chat-c")
    assert resume.session_start_hook(project, {"session_id": "chat-c", "source": "startup"}) == ""


def test_the_hook_speaks_claudes_format(project):
    run(project.root, "note", "halfway through the backfill")
    out = run(project.root, "resume", "--hook",
              stdin=json.dumps({"session_id": "s1", "source": "resume"}))
    body = json.loads(out)["hookSpecificOutput"]
    assert body["hookEventName"] == "SessionStart"
    assert "halfway through the backfill" in body["additionalContext"]


def test_the_owner_speaking_is_timed(project):
    run(project.root, "prompt", "--hook", stdin=json.dumps({"session_id": "s2", "prompt": "carry on with refunds.."}))
    ev = trail.read(project)[-1]
    assert ev["kind"] == "prompt" and ev["session"] == "s2" and ev["chars"] == 23


def test_install_puts_the_hooks_in_the_per_person_file(project):
    local = project.root / ".claude" / "settings.local.json"
    shared = json.loads((project.root / ".claude" / "settings.json").read_text())
    assert "hooks" not in shared
    hooks = json.loads(local.read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreCompact", "Stop"}
    assert "resume --hook" in hooks["SessionStart"][0]["hooks"][0]["command"]


def test_reinstalling_keeps_the_developers_hooks_and_adds_none_twice(project):
    local = project.root / ".claude" / "settings.local.json"
    data = json.loads(local.read_text())
    data["hooks"]["SessionStart"].append({"hooks": [{"type": "command", "command": "echo mine"}]})
    local.write_text(json.dumps(data))
    inst.install(reload(project), project_name="Proj", stack="Python", write=True, force=True, run_survey=False)
    hooks = json.loads(local.read_text())["hooks"]["SessionStart"]
    cmds = [h["command"] for g in hooks for h in g["hooks"]]
    assert "echo mine" in cmds and sum("resume --hook" in c for c in cmds) == 1
