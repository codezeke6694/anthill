"""The scorecard: is the work getting faster, and is Anthill why?

The owner's question, 29 Sep: "I am not sure whether Anthill is managing it
better or I am." Nothing could answer it. Every number here is read from the
trail -- when a chat started, when the owner spoke, when a commit landed,
which Anthill commands were used -- so none of it depends on an agent's
account of itself (three of three agents could not say when their own task
had started).

The trail only began on 29 Sep. Claude keeps every chat on disk with a time on
each line, so `import_claude` reads those once and writes the same events,
marked `imported`, and the scorecard starts with the project's real history
instead of an empty week.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from anthill import context as _ctx
from anthill import trail

# What counts as the owner speaking: not tool output, not the harness's own
# notes, not another agent's report relayed into the chat.
_NOT_OWNER = ("<", "[Request interrupted", "Another Claude session sent a message",
              "Caveat:", "This session is being continued")


def _when(ev: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(ev["t"])
    except (KeyError, ValueError, TypeError):
        return None


def _local(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


# ------------------------------------------------------------------ import

def claude_dir(root: Path) -> Path:
    """Where Claude keeps this project's chats: the path, every non-alphanumeric as '-'."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))


def _elsewhere(cmd: str, root: Path) -> bool:
    """A commit made after `cd` into another repository is not this project's."""
    for m in re.finditer(r'\bcd\s+("([^"]+)"|\'([^\']+)\'|(\S+))', cmd):
        target = m.group(2) or m.group(3) or m.group(4)
        p = Path(target).expanduser()
        if p.is_absolute() and root.resolve() not in (p.resolve(), *p.resolve().parents):
            return True
    return False


# Verbs that are Anthill commands. A chat's shell line mentions "anthill" for
# many reasons -- a path, a cd, a grep -- and counting the next word as a
# command filled the usage table with "tests", "python" and "is".
def _known_verbs() -> set[str]:
    from anthill import cli
    return (set(cli.ROUTER_COMMANDS) | {n for n, _ in cli.DELEGATED}
            | {"install", "status", "sprint", "audit", "lesson", "ui", "map", "guard", "control",
               "config", "survey", "upkeep", "tidy", "blueprint", "integrate", "skill", "roles",
               "onboard", "trail", "score", "note", "resume"})


def _chat_events(path: Path, root: Path, verbs: set[str]) -> tuple[list[dict[str, Any]], list[tuple]]:
    """A chat's owner messages and Anthill commands, and the time windows of its
    commit attempts. Commits themselves come from git, matched to these windows:
    a line that merely mentions committing -- a script, a grep -- is not one."""
    session = path.stem
    evs: list[dict[str, Any]] = []
    windows: list[tuple] = []
    pending: dict[str, tuple[str, str]] = {}          # tool_use id -> (time, branch)
    started = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain") or not d.get("timestamp"):
            continue                                   # a helper agent's own work
        if d.get("cwd") and Path(d["cwd"]).resolve() != root.resolve():
            continue
        t, branch = _local(d["timestamp"]), d.get("gitBranch") or ""
        base = {"t": t, "tool": "claude-code", "session": session, "branch": branch, "imported": True}
        content = (d.get("message") or {}).get("content")
        if d.get("type") == "user":
            if isinstance(content, list):
                for x in content:
                    if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("tool_use_id") in pending:
                        st, sb = pending.pop(x["tool_use_id"])
                        windows.append((st, t, sb, session))
            text = _text(content).strip()
            if text and not d.get("isMeta") and not text.startswith(_NOT_OWNER):
                if not started:
                    evs.append({**base, "kind": "session", "source": "startup"})
                    started = True
                evs.append({**base, "kind": "prompt", "chars": len(text), "text": " ".join(text.split())[:120]})
        elif d.get("type") == "assistant" and isinstance(content, list):
            for x in content:
                if not (isinstance(x, dict) and x.get("type") == "tool_use"):
                    continue
                cmd = str((x.get("input") or {}).get("command", ""))
                if re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd) and not _elsewhere(cmd, root):
                    pending[x.get("id")] = (t, branch)
                for m in re.finditer(r"(?:^|[\s;&|(])anthill\s+([a-z][a-z-]*)", cmd):
                    if m.group(1) in verbs:
                        evs.append({**base, "kind": "command", "verb": m.group(1),
                                    "args": m.group(1), "rc": None})
    return evs, windows


def _git_commits(root: Path, since: str) -> list[tuple[str, str, str]]:
    import subprocess
    r = subprocess.run(["git", "log", "--all", f"--since={since}", "--format=%h%x09%cI%x09%s"],
                       cwd=root, capture_output=True, text=True, timeout=30)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            out.append((parts[0], datetime.fromisoformat(parts[1]).astimezone().isoformat(timespec="seconds"), parts[2]))
    return out


def import_claude(ctx: _ctx.Context, redo: bool = False) -> dict[str, Any]:
    """Read Claude's saved chats and git's history into the trail, once.

    `redo` drops what an earlier import wrote and reads it all again; events
    recorded live are never touched."""
    d = claude_dir(ctx.root)
    if not d.exists():
        return {"imported": 0, "reason": f"no saved chats at {d}"}
    existing = trail.read(ctx)
    if redo:
        kept = [e for e in existing if not e.get("imported")]
        trail.path(ctx).write_text("".join(json.dumps(e) + "\n" for e in kept), encoding="utf-8")
        existing = kept
    elif any(e.get("imported") for e in existing):
        return {"imported": 0, "reason": "already imported; use --redo to read it again"}
    # A minute's margin: a chat running when the trail began has each command
    # both in its saved chat and on the trail, a second or two apart.
    first = min((e["t"] for e in existing), default="")
    first_live = ((datetime.fromisoformat(first) - timedelta(seconds=60)).isoformat(timespec="seconds")
                  if first else "9999")
    verbs = _known_verbs()
    evs: list[dict[str, Any]] = []
    windows: list[tuple] = []
    chats = 0
    for p in sorted(d.glob("*.jsonl")):
        e, w = _chat_events(p, ctx.root, verbs)
        if e or w:
            chats += 1
        evs += e
        windows += w
    earliest = min((e["t"] for e in evs), default=first_live)
    matched = unmatched = 0
    # A full timestamp, a day early: given a bare date, git fills in the time of
    # day it is now, and silently dropped every commit made earlier that day.
    since = (datetime.fromisoformat(earliest) - timedelta(days=1)).isoformat() if earliest != "9999" else "30.days"
    for sha, ct, subject in _git_commits(ctx.root, since):
        if ct >= first_live:
            continue                                   # the post-commit hook records these live
        c = datetime.fromisoformat(ct)
        best = None
        for st, et, branch, session in windows:
            a = datetime.fromisoformat(st) - timedelta(seconds=5)
            b = datetime.fromisoformat(et) + timedelta(seconds=5)
            if a <= c <= b and (best is None or b - a < best[0]):
                best = (b - a, branch, session)
        base = {"t": ct, "kind": "commit", "sha": sha, "subject": subject[:160], "imported": True}
        if best:
            evs.append({**base, "tool": "claude-code", "session": best[2], "branch": best[1]})
            matched += 1
        else:
            evs.append({**base, "tool": "unknown", "session": "", "branch": ""})
            unmatched += 1
    evs = [e for e in evs if e["t"] < first_live]
    with trail.path(ctx).open("a", encoding="utf-8") as fh:
        for e in sorted(evs, key=lambda e: e["t"]):
            fh.write(json.dumps(e) + "\n")
    return {"imported": len(evs), "chats": chats, "commits_matched_to_a_chat": matched,
            "commits_from_elsewhere": unmatched}


# --------------------------------------------------------------- the card

def _mins(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 60, 1)


def _chats(evs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chats: dict[str, dict[str, Any]] = {}
    for e in evs:
        sid = e.get("session") or ""
        if not sid:
            continue
        c = chats.setdefault(sid, {"session": sid, "tool": e.get("tool"), "branch": e.get("branch"),
                                   "start": None, "prompts": 0, "commits": 0, "first_commit": None,
                                   "prompts_before_first_commit": 0, "compressed": 0,
                                   "anthill": 0, "notes": 0, "waits": [], "_last": None})
        k = e.get("kind")
        if k == "prompt":
            c["start"] = c["start"] or e["t"]
            c["prompts"] += 1
            if not c["first_commit"]:
                c["prompts_before_first_commit"] += 1
            c["_last"] = c["_last"] or e["t"]         # the first message since the last commit
        elif k == "commit":
            c["commits"] += 1
            if c["start"] and not c["first_commit"]:
                c["first_commit"] = e["t"]
            if c["_last"]:
                c["waits"].append(_mins(datetime.fromisoformat(c["_last"]), datetime.fromisoformat(e["t"])))
                c["_last"] = None
        elif k == "session":
            c["compressed"] += e.get("source") == "compact"
        elif k == "command":
            c["anthill"] += 1
        elif k == "note":
            c["notes"] += 1
        if e.get("branch"):
            c["branch"] = e["branch"]
    rows = []
    for c in chats.values():
        c.pop("_last", None)
        if not c["start"]:
            continue
        c["to_first_change_min"] = (_mins(datetime.fromisoformat(c["start"]), datetime.fromisoformat(c["first_commit"]))
                                    if c["first_commit"] else None)
        rows.append(c)
    return sorted(rows, key=lambda c: c["start"], reverse=True)


def _stats(evs: list[dict[str, Any]]) -> dict[str, Any]:
    """The headline numbers for one slice of time.

    "Asked to saved" is the one that matters most: from the owner's first
    message after a commit to the next commit in that chat. It is measured per
    request rather than per chat, because one chat can run for days and hold a
    dozen tasks -- chat start to first commit said 17 minutes for one and 20
    hours for another, and meant nothing."""
    rows = _chats(evs)
    waits = [w for c in rows for w in c["waits"]]
    prompts = sum(c["prompts"] for c in rows)
    commits = sum(e.get("kind") == "commit" for e in evs)
    usage: dict[str, int] = {}
    for e in evs:
        if e.get("kind") == "command" and e.get("verb"):
            usage[e["verb"]] = usage.get(e["verb"], 0) + 1
    return {
        "chats": len(rows),
        "owner_messages": prompts,
        "commits": commits,
        "messages_per_commit": round(prompts / commits, 1) if commits else None,
        "asked_to_saved_median_min": round(statistics.median(waits), 1) if waits else None,
        "asked_to_saved_n": len(waits),
        "compressions": sum(c["compressed"] for c in rows),
        "notes": sum(e.get("kind") == "note" for e in evs),
        "crashes": sum(bool(e.get("crashed")) for e in evs),
        "anthill_uses": sum(usage.values()),
        "anthill_usage": dict(sorted(usage.items(), key=lambda kv: -kv[1])),
        "_rows": rows,
    }


def scorecard(events: list[dict[str, Any]], days: int = 7, weeks: int = 4,
              now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    evs = sorted((e for e in events if _when(e)), key=lambda e: e["t"])

    def between(a: datetime, b: datetime) -> list[dict[str, Any]]:
        return [e for e in evs if a <= _when(e) < b]

    head = _stats(between(now - timedelta(days=days), now + timedelta(seconds=1)))
    rows = head.pop("_rows")
    weekly = []
    for i in range(weeks - 1, -1, -1):
        b = now + timedelta(seconds=1) - timedelta(days=7 * i)
        a = b - timedelta(days=7)
        w = _stats(between(a, b))
        w.pop("_rows")
        w.pop("anthill_usage")
        weekly.append({"from": a.date().isoformat(), "to": (b - timedelta(seconds=1)).date().isoformat(), **w})
    return {
        "days": days, **head, "weekly": weekly,
        "chats_list": [{k: c[k] for k in ("session", "tool", "branch", "start", "prompts", "commits",
                                          "prompts_before_first_commit", "to_first_change_min",
                                          "anthill", "notes", "compressed")} for c in rows[:12]],
        "imported_share": round(sum(bool(e.get("imported")) for e in evs) / len(evs), 2) if evs else 0,
        "trail_since": evs[0]["t"] if evs else None,
    }


def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    if argv and argv[0] == "import":
        print(json.dumps(import_claude(ctx, redo="--redo" in argv)))
        return 0
    days = 7
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])
    print(json.dumps(scorecard(trail.read(ctx), days), indent=2))
    return 0
