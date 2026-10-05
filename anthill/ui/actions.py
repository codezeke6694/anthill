"""What the owner's page may change, and only this.

Three buttons, each the owner's own act:

  * answer a question a work page says is waiting on them -- the answer is
    written onto that page, under "Owner's answers", so the next chat reads
    it in the owner's words;
  * sign a page -- `intent_attested_by`, the line no agent may ever fill;
  * reopen a unit the board escalated, with the reason.

Every one is also written to the trail as coming from the owner's page. The
server only calls these after the request carried the key printed in the
owner's terminal (see server.py); nothing here checks that itself.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from anthill import context as _ctx
from anthill import trail

ANSWERS = "## Owner's answers"
MAX = 2000


class Refused(Exception):
    """A request the page may not carry out; the message says why."""


def _work_page(ctx: _ctx.Context, work_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", work_id or ""):
        raise Refused("no such work page")
    from anthill.sprint import page as _sprint
    try:
        p = _sprint.find(ctx, work_id) or ctx.knowledge_dir / "work" / f"{work_id}.md"
    except ValueError:
        p = ctx.knowledge_dir / "work" / f"{work_id}.md"
    if not p.is_file():
        raise Refused(f"no work page called {work_id}")
    return p


def _knowledge_page(ctx: _ctx.Context, rel: str) -> Path:
    """A page the owner may sign: on the shared shelf, or a sprint page.

    `rel` is relative to `.anthill/` (`sprints/active/x.md`, `knowledge/...`),
    or, as the page used to send it, relative to the knowledge folder.
    """
    rel = rel or ""
    bases = [ctx.knowledge_dir.resolve(), ctx.sprint_pages_dir.resolve()]
    first = rel.split("/", 1)[0]
    p = ((ctx.state if first in ("knowledge", "sprints") else ctx.knowledge_dir) / rel).resolve()
    if not any(b in p.parents for b in bases) or p.suffix != ".md" or not p.is_file():
        raise Refused("that is not a page in the knowledge folder or a sprint")
    return p


def _one_line(s: str) -> str:
    return " ".join(str(s or "").split())[:MAX]


def answer(ctx: _ctx.Context, work_id: str, question: str, text: str) -> dict[str, Any]:
    text, question = _one_line(text), _one_line(question)
    if not text:
        raise Refused("the answer is empty")
    page = _work_page(ctx, work_id)
    body = page.read_text(encoding="utf-8")
    stamp = datetime.now().astimezone().strftime("%d %b %H:%M")
    q = question[:240] + ("…" if len(question) > 240 else "")
    line = f"- {stamp} — on “{q}”: **{text}**"
    if ANSWERS in body:
        head, rest = body.split(ANSWERS, 1)
        nxt = re.search(r"\n## ", rest)
        cut = nxt.start() if nxt else len(rest)
        section = rest[:cut].rstrip("\n")
        body = head + ANSWERS + section + "\n" + line + "\n" + rest[cut:]
    else:
        m = re.search(r"\n## (Traps|History)\b", body)
        block = f"\n{ANSWERS}\n\nIn the owner's words, from their page. Act on these; move a settled question out of Waiting on the owner.\n\n{line}\n"
        body = (body[:m.start()] + "\n" + block + body[m.start():]) if m else body.rstrip("\n") + "\n" + block
    page.write_text(body, encoding="utf-8")
    trail.record("answer", ctx, work=work_id, question=q, text=text[:400],
                 via="owner page")
    return {"answered": work_id, "line": line}


def sign(ctx: _ctx.Context, rel: str, by: str) -> dict[str, Any]:
    by = _one_line(by)[:80] or "owner"
    page = _knowledge_page(ctx, rel)
    text = page.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise Refused("that page has no header to sign")
    _, fm, rest = text.split("---", 2)
    today = datetime.now().astimezone().date().isoformat()
    lines = [l for l in fm.strip("\n").splitlines()
             if not re.match(r"^intent_attested_(by|on):", l)]
    lines += [f"intent_attested_by: {by}", f"intent_attested_on: {today}"]
    new = "---\n" + "\n".join(lines) + "\n---" + rest
    page.write_text(new, encoding="utf-8")
    digest = hashlib.sha256(new.encode("utf-8")).hexdigest()[:16]
    rel_out = str(page.relative_to(ctx.state.resolve()))
    trail.record("signed", ctx, page=rel_out, by=by, sha=digest, via="owner page")
    return {"signed": rel_out, "by": by}


def reopen(ctx: _ctx.Context, unit: str, reason: str, by: str, tool: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", unit or ""):
        raise Refused("no such unit")
    reason = _one_line(reason)
    if not reason:
        raise Refused("say why it can be reopened")
    r = subprocess.run([tool, "work", "reopen", "--repo", ".", "--unit", unit,
                        "--reason", reason, "--by", _one_line(by)[:80] or "owner"],
                       cwd=ctx.root, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise Refused((r.stderr or r.stdout).strip()[-300:] or f"reopen failed ({r.returncode})")
    trail.record("reopened", ctx, unit=unit, reason=reason[:300], via="owner page")
    return {"reopened": unit}
