"""The owner's page: comes up once, says where, goes away with its parent,
never holds a port it no longer uses, and only reads."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from anthill import rules
from anthill.ui import server

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def ui(repo: Path, *args: str) -> str:
    return subprocess.run([str(TOOL), "ui", *args], cwd=repo, capture_output=True, text=True).stdout


def port_of(out: str) -> int:
    return int(out.rsplit(":", 1)[1].split("/")[0])


def test_start_twice_starts_once_and_stop_frees_the_port(project):
    first = ui(project.root, "start", "--detach")
    try:
        assert "anthill ui: http://127.0.0.1:" in first
        assert "already up at" in ui(project.root, "start", "--detach")
        body = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port_of(first)}/api/state", timeout=5).read())
        assert body["project"] == "Proj" and "where" in body and "upkeep" in body
        page = urllib.request.urlopen(f"http://127.0.0.1:{port_of(first)}/", timeout=5).read().decode()
        assert "/api/state" in page and "textContent" in page
    finally:
        out = ui(project.root, "stop")
    assert "is free" in out
    assert "not running" in ui(project.root, "status")
    assert not (project.state / "build" / "ui.json").exists()


def test_it_ends_when_its_parent_ends(project):
    parent = subprocess.Popen(["sleep", "30"])
    try:
        out = ui(project.root, "start", "--detach", "--with-parent", str(parent.pid))
        assert "http://127.0.0.1:" in out
    finally:
        parent.kill()
        parent.wait()
    for _ in range(40):
        if "not running" in ui(project.root, "status"):
            break
        time.sleep(0.2)
    assert "not running" in ui(project.root, "status")


def test_a_stale_record_cleans_itself_up(project):
    rec = project.state / "build" / "ui.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"pid": 999999, "port": 7098, "url": "x"}))
    assert server.running(project) is None and not rec.exists()


def test_the_page_only_reads(project):
    handler = server._Handler
    assert not hasattr(handler, "do_POST") and not hasattr(handler, "do_PUT")


def test_agents_are_told_how_to_run_it_with_the_app(project):
    for doc in ("CLAUDE.md", "AGENTS.md"):
        assert rules.owner_view_rule(project) in (project.root / doc).read_text()
    assert "--with-parent $$" in rules.owner_view_rule(project)
