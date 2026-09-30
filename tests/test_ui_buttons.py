"""The owner's buttons: answer, sign, reopen -- and every way in that must stay shut."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from anthill import trail
from anthill.knowledge import work
from anthill.ui import actions, server

PAGE = """---
id: demo
type: work
title: Demo work
state: waiting-on-owner
branch: work/test
intent_attested_by:
---

## What

Something.

## Waiting on the owner

- Refunds: on the receipt, or a separate email?

## Traps

- None.
"""


@pytest.fixture
def page_server(project):
    (project.knowledge_dir / "work").mkdir(parents=True, exist_ok=True)
    (project.knowledge_dir / "work" / "demo.md").write_text(PAGE)
    port = server.free_port()
    server._Handler.ctx, server._Handler.key, server._Handler.port = project, "k3y", port
    httpd = server.ThreadingHTTPServer(("127.0.0.1", port), server._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield project, port
    httpd.shutdown()
    httpd.server_close()
    server._Handler.key = ""


def post(port, path, body, key="k3y", host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Anthill-Key": key,
                                          **({"Host": host} if host else {})})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_an_answer_lands_on_the_page_in_the_owners_words(page_server):
    project, port = page_server
    code, out = post(port, "/api/answer", {"work": "demo", "question": "Refunds?",
                                           "answer": "on the receipt"})
    assert code == 200, out
    text = (project.knowledge_dir / "work" / "demo.md").read_text()
    assert "## Owner's answers" in text and "**on the receipt**" in text
    assert text.index("## Owner's answers") < text.index("## Traps")
    row = [r for r in work.where(project)["work"] if r["id"] == "demo"][0]
    assert "on the receipt" in row["owner_answers"][0]
    assert trail.read(project)[-1]["kind"] == "answer"
    post(port, "/api/answer", {"work": "demo", "question": "again", "answer": "second"})
    assert len([r for r in work.where(project)["work"] if r["id"] == "demo"][0]["owner_answers"]) == 2


def test_signing_fills_the_line_no_agent_may(page_server):
    project, port = page_server
    code, out = post(port, "/api/sign", {"page": "work/demo.md"})
    assert code == 200, out
    text = (project.knowledge_dir / "work" / "demo.md").read_text()
    assert "intent_attested_by: owner" in text and "intent_attested_on:" in text
    assert text.count("intent_attested_by") == 1
    assert trail.read(project)[-1]["kind"] == "signed"


def test_no_key_wrong_key_or_wrong_host_is_refused(page_server):
    project, port = page_server
    before = (project.knowledge_dir / "work" / "demo.md").read_text()
    assert post(port, "/api/answer", {"work": "demo", "answer": "x"}, key="")[0] == 403
    assert post(port, "/api/answer", {"work": "demo", "answer": "x"}, key="guess")[0] == 403
    assert post(port, "/api/answer", {"work": "demo", "answer": "x"}, host="evil.example:80")[0] == 403
    assert (project.knowledge_dir / "work" / "demo.md").read_text() == before


def test_it_cannot_reach_outside_the_knowledge_folder(page_server):
    project, port = page_server
    code, out = post(port, "/api/sign", {"page": "../../CLAUDE.md"})
    assert code == 400 and "knowledge folder" in out["error"]
    assert post(port, "/api/answer", {"work": "../../CLAUDE", "answer": "x"})[0] == 400
    assert post(port, "/api/reopen", {"unit": "x; rm -rf /", "reason": "y"})[0] == 400
    assert post(port, "/api/nope", {})[0] == 404


def test_an_empty_answer_is_refused(page_server):
    project, port = page_server
    code, out = post(port, "/api/answer", {"work": "demo", "answer": "   "})
    assert code == 400 and "empty" in out["error"]
