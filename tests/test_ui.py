"""The owner's page: comes up once, says where, goes away with its parent,
never holds a port it no longer uses, and only reads."""
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from anthill import rules
from anthill.ui import server

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def ui(repo: Path, *args: str) -> str:
    return subprocess.run([str(TOOL), "ui", *args], cwd=repo, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout


def port_of(out: str) -> int:
    return int(out.strip().split()[-1].split("#")[0].rsplit(":", 1)[1].split("/")[0])


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
    assert not (project.page_dir / "ui.json").exists()


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
    rec = project.page_dir / "ui.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"pid": 999999, "port": 7098, "url": "x"}))
    assert server.running(project) is None and not rec.exists()


def test_a_page_started_by_an_agent_has_no_working_buttons(project):
    # Started through a pipe, as an agent's shell runs it: no terminal, no key.
    r = subprocess.run([str(TOOL), "ui", "start", "--detach"], cwd=project.root,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    out = r.stdout
    try:
        assert "view only" in r.stderr and "#key=" not in out
        req = urllib.request.Request(f"http://127.0.0.1:{port_of(out)}/api/answer", method="POST",
                                     data=b'{"work":"x","answer":"y"}',
                                     headers={"Content-Type": "application/json", "X-Anthill-Key": ""})
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("a keyless page accepted a button")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        ui(project.root, "stop")


def test_agents_are_told_how_to_run_it_with_the_app(project):
    for doc in ("CLAUDE.md", "AGENTS.md"):
        text = (project.root / doc).read_text()
        assert "anthill ui wire" in text and "never ask for" in text
    assert "--with-parent $$" in rules.owner_view_rule(project)


def test_a_page_started_from_a_terminal_prints_its_key_once(project):
    import os
    import pty
    import select
    pid, fd = pty.fork()
    if pid == 0:                                    # the child: a real terminal
        os.chdir(project.root)
        os.execv(str(TOOL), [str(TOOL), "ui", "start", "--detach"])
    out = b""
    while True:
        r, _, _ = select.select([fd], [], [], 10)
        if not r:
            break
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    os.waitpid(pid, 0)
    try:
        text = out.decode()
        assert "#key=" in text, text
        key = text.split("#key=", 1)[1].split()[0]
        assert key not in (project.page_dir / "ui.json").read_text()
    finally:
        ui(project.root, "stop")


def test_the_page_is_wired_into_the_apps_start_command(tmp_path, monkeypatch):
    import json as _json
    from anthill.ui import wire
    from conftest import git, commit_all
    from anthill import context as _c, install as inst
    repo = tmp_path / "app"
    repo.mkdir()
    (repo / "package.json").write_text(_json.dumps({"scripts": {"dev": "tsx watch server/index.ts"}}, indent=2) + "\n")
    (repo / "server").mkdir()
    (repo / "server" / "index.ts").write_text("export const x = 1;\n")
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo, "start")
    monkeypatch.chdir(repo)
    _c.current.cache_clear()
    ctx = _c.resolve(repo)
    out = inst.install(ctx, project_name="App", write=True, run_survey=False)
    assert out["owner_page"]["changed"]
    dev = _json.loads((repo / "package.json").read_text())["scripts"]["dev"]
    assert "ui start --detach --with-parent $$" in dev and dev.endswith("tsx watch server/index.ts")
    assert wire.wire(_c.resolve(repo))["changed"] is False          # once only
    _c.current.cache_clear()


def test_a_run_script_gets_the_line_after_its_header(tmp_path):
    from anthill.ui import wire
    from anthill import context as _c
    (tmp_path / "run.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\nnpm run dev\n")
    out = wire.wire(_c.Context(root=tmp_path, origin="test"))
    text = (tmp_path / "run.sh").read_text().splitlines()
    assert out["changed"] and text[0].startswith("#!") and text[1].startswith("set -")
    assert "ui start --detach --with-parent $$" in text[4] and text[-1] == "npm run dev"
