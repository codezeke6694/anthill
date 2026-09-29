"""Picking work up again: after a chat's memory is compressed, in a new chat, or in another tool.

A chat that runs out of room has its memory compressed to a summary, and the
detail goes: which story it was testing, what it had just ruled out, what it
was about to try. A new chat, or Codex tomorrow, starts with none of it. The
work page says what the work is; it does not say where the last session was.

Three pieces, all written to the trail:

  * `anthill note "doing X; ruled out Y; next Z"` -- the agent's own line,
    left as it goes. Cheap, and the one thing only the agent knows.
  * a checkpoint, taken automatically just before Claude compresses a chat
    (the PreCompact hook): the owner's last message, what the agent last said,
    the files not yet committed, the last commit.
  * `anthill resume` -- the pick-up page: this branch's work and next step, the
    chat's own notes and checkpoint, other chats' notes on the same branch, and
    the commits since. Claude's SessionStart hook hands it over by itself on
    resume and after a compression; any other tool runs it.

The hooks also record when a chat started and when each owner message
arrived, which no agent could say for itself.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from anthill import context as _ctx
from anthill import trail

TEXT_MAX = 400


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _dirty(root: Path) -> list[str]:
    """Files with uncommitted changes. Not through _git: stripping the output
    ate the leading space of the first ` M path` line, and a column slice
    then cut the path's first letter off."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [l[3:] for l in r.stdout.splitlines() if len(l) > 3]


def _clip(s: str, n: int = TEXT_MAX) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _hook_input() -> dict[str, Any]:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


# ------------------------------------------------------------------ notes

def note(ctx: _ctx.Context, text: str, work: str = "") -> dict[str, Any]:
    text = _clip(text)
    trail.record("note", ctx, text=text, work=work or None)
    return {"noted": text}


# ------------------------------------------------------------ checkpoints

def _last_turns(transcript: Path) -> tuple[str, str]:
    """The owner's last message and the agent's last words, from a Claude transcript."""
    owner, agent = "", ""
    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return owner, agent
    for line in reversed(lines):
        if owner and agent:
            break
        try:
            d = json.loads(line)
        except ValueError:
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, list):
            text = " ".join(x.get("text", "") for x in content
                            if isinstance(x, dict) and x.get("type") == "text")
        else:
            text = content if isinstance(content, str) else ""
        if not text.strip() or text.lstrip().startswith("<"):
            continue                          # tool results, system notes, commands
        if d.get("type") == "user" and not owner and not d.get("isMeta"):
            owner = text
        elif d.get("type") == "assistant" and not agent:
            agent = text
    return _clip(owner), _clip(agent)


def checkpoint(ctx: _ctx.Context, hook: dict[str, Any]) -> dict[str, Any]:
    owner, agent = "", ""
    tp = hook.get("transcript_path")
    if tp:
        owner, agent = _last_turns(Path(tp))
    dirty = _dirty(ctx.root)
    ev = {"trigger": hook.get("trigger") or "manual", "owner_last": owner or None,
          "agent_last": agent or None, "uncommitted": dirty[:15],
          "head": _git(ctx.root, "log", "-1", "--format=%h %s")[:120]}
    trail.record("checkpoint", ctx, session=hook.get("session_id") or "", **ev)
    return ev


# ---------------------------------------------------------------- resume

def _work_for_branch(ctx: _ctx.Context, branch: str) -> list[dict[str, Any]]:
    try:
        from anthill.knowledge import work
        pages = work.where(ctx).get("work") or []
    except Exception:                          # noqa: BLE001 -- resume must still print the notes
        return []
    mine = [p for p in pages if p.get("branch") == branch]
    return mine or pages


def resume(ctx: _ctx.Context, session: str = "") -> str:
    branch = _git(ctx.root, "branch", "--show-current")
    events = trail.read(ctx)
    here = [e for e in events if e.get("branch") == branch]
    mine = [e for e in here if session and e.get("session") == session]
    others = [e for e in here if e.get("session") != session]

    out = [f"# Picking up on {branch or 'this branch'}", ""]
    pages = _work_for_branch(ctx, branch)
    for p in pages[:3]:
        out.append(f"**{p.get('title', p.get('id'))}** ({p.get('state', '?')})")
        if p.get("next"):
            out.append(f"- Next: {_clip(p['next'], 500)}")
        for a in (p.get("owner_answers") or [])[-3:]:
            out.append(f"- The owner answered: {_clip(a, 300)}")
        for q in (p.get("waiting_on_owner") or [])[:2]:
            out.append(f"- Waiting on the owner: {_clip(q, 200)}")
    if pages:
        out.append("")

    def fmt(e: dict[str, Any]) -> str:
        return f"- {str(e.get('t', ''))[5:16].replace('T', ' ')}  {e.get('text', '')}"

    my_notes = [e for e in mine if e.get("kind") == "note"][-6:]
    if my_notes:
        out += ["Your notes in this chat:", *map(fmt, my_notes), ""]
    cps = [e for e in mine if e.get("kind") == "checkpoint"]
    if cps:
        cp = cps[-1]
        out.append(f"Saved just before this chat's memory was compressed ({str(cp.get('t', ''))[11:16]}):")
        if cp.get("owner_last"):
            out.append(f"- The owner's last message: \"{cp['owner_last']}\"")
        if cp.get("agent_last"):
            out.append(f"- What you last said: \"{cp['agent_last']}\"")
        if cp.get("uncommitted"):
            out.append(f"- Not yet committed: {', '.join(cp['uncommitted'])}")
        out.append("")
    their_notes = [e for e in others if e.get("kind") in ("note", "checkpoint")][-4:]
    if their_notes:
        out.append("Left on this branch by other chats:")
        for e in their_notes:
            who = e.get("tool", "?") + (" " + e["session"][:8] if e.get("session") else "")
            what = e.get("text") or (f"checkpoint; owner last said \"{_clip(e.get('owner_last'), 160)}\""
                                     if e.get("owner_last") else "checkpoint")
            out.append(f"- {str(e.get('t', ''))[5:16].replace('T', ' ')}  {who}: {what}")
        out.append("")
    since = [e for e in here if e.get("kind") == "commit"][-5:]
    if since:
        out += ["Latest commits here:", *[f"- {e.get('sha')}  {e.get('subject')}" for e in since], ""]
    dirty = _dirty(ctx.root)
    if dirty:
        out += [f"Uncommitted now: {', '.join(dirty[:10])}"
                + (f" and {len(dirty) - 10} more" if len(dirty) > 10 else ""), ""]
    out += ["Everything else: `anthill where`. Leave a line as you go: "
            "`anthill note \"doing X; ruled out Y; next Z\"`."]
    return "\n".join(out) + "\n"


def _has_pickup(ctx: _ctx.Context, session: str) -> bool:
    branch = _git(ctx.root, "branch", "--show-current")
    return any(e.get("kind") in ("note", "checkpoint") and e.get("branch") == branch
               for e in trail.read(ctx))


# ------------------------------------------------------------------ hooks

def session_start_hook(ctx: _ctx.Context, hook: dict[str, Any]) -> str:
    """Claude's SessionStart: record the start, and hand over the pick-up page when it helps.

    On `resume` and `compact` the chat is continuing, so it always gets the
    page. On `startup` it gets it only when this branch has notes or
    checkpoints from earlier -- otherwise the page repeats `where` for nothing.
    """
    source = hook.get("source") or "startup"
    session = hook.get("session_id") or ""
    trail.record("session", ctx, session=session, source=source)
    if source in ("resume", "compact") or _has_pickup(ctx, session):
        return resume(ctx, session)
    return ""


def prompt_hook(ctx: _ctx.Context, hook: dict[str, Any]) -> None:
    """Claude's UserPromptSubmit: when the owner spoke, and how much. Never blocks."""
    text = str(hook.get("prompt") or "")
    trail.record("prompt", ctx, session=hook.get("session_id") or "",
                 chars=len(text), text=_clip(text, 120))


def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        return 0 if "--hook" in argv else 2
    verb = argv[0] if argv else "resume"
    if verb == "note":
        text = " ".join(a for a in argv[1:] if not a.startswith("--"))
        if not text.strip():
            print('anthill note: say what you are doing, e.g. anthill note "ruled out X; next Y"',
                  file=sys.stderr)
            return 2
        print(f"noted: {note(ctx, text)['noted']}")
        return 0
    if verb == "correction":
        def opt(name: str) -> str:
            return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else ""
        page, was, now = opt("--page"), opt("--was"), opt("--now")
        if not (page and was and now):
            print('anthill correction --page <id> --was "<old>" --now "<new>" [--why "<how you know>"]',
                  file=sys.stderr)
            return 2
        trail.record("correction", ctx, page=page, was=_clip(was, 300), now=_clip(now, 300),
                     why=_clip(opt("--why"), 200) or None)
        print(f"recorded: {page} corrected")
        return 0
    if verb == "checkpoint":
        checkpoint(ctx, _hook_input() if "--hook" in argv else {})
        return 0
    if verb == "prompt":
        prompt_hook(ctx, _hook_input())
        return 0
    if verb == "resume":
        if "--hook" in argv:
            text = session_start_hook(ctx, _hook_input())
            if text:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                         "additionalContext": text}}))
            return 0
        print(resume(ctx, trail.who()["session"]), end="")
        return 0
    print(f"anthill: unknown {verb!r}", file=sys.stderr)
    return 2
