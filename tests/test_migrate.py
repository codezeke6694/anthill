"""Moving a project from the old layout to the new one (owner, 5 Oct)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from anthill import migrate
from conftest import reload

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def to_v1(ctx):
    """Put a fresh install back the way installs used to lay it out."""
    s = ctx.state
    shutil.move(s / "owner/settings.json", s / "anthill.config.json")
    shutil.move(s / "owner/charter.md", ctx.root / "CONSTITUTION.md")
    shutil.move(s / "owner/roles", s / "roles")
    shutil.rmtree(s / "owner")
    # v2's sprint pages and v1's board plans share the name `sprints/`
    for empty in ("sprints", "skills"):
        shutil.rmtree(s / empty)
    (s / "build" / "maps").mkdir(parents=True)
    (s / "build" / "maps" / "codebase.json").write_text('{"nodes": []}')
    (s / "build" / "upkeep.json").write_text("{}")
    (s / "log" / "lessons").mkdir(parents=True)
    (s / "log" / "lessons" / "mapping.json").write_text('{"area": "mapping", "entries": []}')
    (s / "sprints").mkdir()
    (s / "contracts").mkdir()
    (s / "contracts" / "contract.json").write_text("{}")
    (s / "sprints" / "current.json").write_text(json.dumps(
        {"contract": str(s / "contracts" / "contract.json")}))
    (s / "idea.md").write_text("# the idea\n")
    (s / "trail.jsonl").write_text("")
    shutil.rmtree(s / "local")
    ctx = reload(ctx)
    assert ctx.layout == "v1"
    return ctx


def test_the_plan_moves_nothing_until_asked(project):
    ctx = to_v1(project)
    p = migrate.plan(ctx)
    froms = {m["from"] for m in p["moves"]}
    assert {".anthill/anthill.config.json", "CONSTITUTION.md", ".anthill/trail.jsonl",
            ".anthill/build/maps", ".anthill/log", ".anthill/idea.md"} <= froms
    assert (ctx.state / "anthill.config.json").exists()          # nothing moved
    assert any(".gitignore hides all of" in n for n in p["notes"])  # the fixture ignores .anthill/


def test_apply_moves_everything_and_rewrites_the_rules(project):
    ctx = to_v1(project)
    out = migrate.apply(ctx, now=True)
    assert out["migrated"] and out["reinstalled"], out
    assert not out["refused"]
    ctx = reload(ctx)
    s = ctx.state
    assert ctx.layout == "v2"
    for rel in ("owner/settings.json", "owner/charter.md", "owner/roles/builder.md",
                "local/map/codebase.json", "local/upkeep.json", "local/log.jsonl",
                "knowledge/log/lessons/mapping.json", "knowledge/plans/idea.md",
                "local/board/contracts/contract.json", "local/board/sprints/current.json"):
        assert (s / rel).exists(), rel
    assert not (ctx.root / "CONSTITUTION.md").exists()
    assert not (s / "build").exists() and not (s / "anthill.config.json").exists()
    # the board's own record of where its contract is points at the new place
    cur = json.loads((s / "local/board/sprints/current.json").read_text())
    assert cur["contract"] == str(s / "local/board/contracts/contract.json")
    # the rules name the new paths, and the locks cover owner/
    rules = (ctx.root / "CLAUDE.md").read_text()
    assert ".anthill/owner/charter.md" in rules and "CONSTITUTION.md" not in rules
    deny = json.loads((ctx.root / ".claude/settings.json").read_text())["permissions"]["deny"]
    assert "Edit(.anthill/owner/**)" in deny
    assert (s / ".gitignore").read_text().startswith("# written by anthill install")
    # and the next command logs to the moved trail
    r = subprocess.run([str(TOOL), "note", "after the move"], cwd=ctx.root,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "after the move" in (s / "local/log.jsonl").read_text()


def test_another_chat_at_work_stops_the_move(project, monkeypatch):
    ctx = to_v1(project)
    from datetime import datetime, timezone
    with (ctx.state / "trail.jsonl").open("a") as fh:
        fh.write(json.dumps({"t": datetime.now(timezone.utc).astimezone().isoformat(),
                             "kind": "command", "session": "someone-else", "tool": "claude-code",
                             "verb": "where"}) + "\n")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "me")
    out = migrate.apply(ctx)
    assert not out["migrated"] and "another chat" in out["why"]
    assert (ctx.state / "anthill.config.json").exists()


def test_a_migrated_project_says_so(project):
    assert migrate.apply(project)["why"] == "already on the new layout"


def test_a_project_not_yet_moved_keeps_working(project):
    ctx = to_v1(project)
    for args in (["map", "build"], ["note", "still on the old layout"], ["where"]):
        r = subprocess.run([str(TOOL), *args], cwd=ctx.root, capture_output=True, text=True)
        assert r.returncode == 0, (args, r.stderr)
    assert (ctx.state / "build/maps/codebase.json").read_text() != '{"nodes": []}'
    assert "still on the old layout" in (ctx.state / "trail.jsonl").read_text()
    assert not (ctx.state / "local").exists() and not (ctx.state / "owner").exists()


def test_work_pages_and_goals_become_sprints(project):
    ctx = to_v1(project)
    wk = ctx.knowledge_dir / "work"
    wk.mkdir(parents=True, exist_ok=True)
    (wk / "refunds.md").write_text("---\nid: refunds\ntitle: Refunds\nstate: in-progress\nnext: total it\n---\n\nbody\n")
    (wk / "old.md").write_text("---\nid: old\ntitle: Old\nstate: done\n---\n")
    (ctx.state / "goals").mkdir()
    (ctx.state / "goals" / "speed-up.json").write_text(json.dumps({
        "id": "speed-up", "title": "Speed up", "done_when": "true", "status": "blocked",
        "steps": [{"text": "profile", "done": True}], "session": "s1", "stalls": 1,
        "decided": [], "blockers": [{"question": "Cache it?", "answer": None}], "answers": []}))
    out = migrate.apply(ctx, now=True)
    assert out["migrated"], out
    ctx = reload(ctx)
    a, d = ctx.sprint_pages_dir / "active", ctx.sprint_pages_dir / "done"
    assert (a / "refunds.md").exists() and (d / "old.md").exists()
    assert "kind: short" in (a / "refunds.md").read_text()
    from anthill.sprint import page
    g = page.load(ctx, "speed-up")
    assert g["status"] == "blocked" and g["steps"][0]["done"] and g["session"] == "s1"
    assert "Cache it?" in (a / "speed-up.md").read_text()
    assert not (ctx.knowledge_dir / "work").exists()
    assert (ctx.local_dir / "goals-before-sprints" / "speed-up.json").exists()
