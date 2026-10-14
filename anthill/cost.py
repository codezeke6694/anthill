"""What each sprint cost, and what Anthill itself cost (owner, 13 Oct 2026).

Read from the chat records Claude Code keeps on this laptop
(~/.claude/projects/<project>/), helpers included. Each reply carries its model,
its token counts, its chat and its time; it is charged to the sprint its chat
was acting on then, by Anthill's log.
The keeper's replies are shown apart: Anthill's background helper. What a chat
spends reading Anthill's rules and pages is inside the chat's own replies and
cannot be told apart here.

Money is the API-price equivalent: what the same tokens cost on the Claude API.
On a subscription nothing is billed per token, but the figure still compares one
sprint with another, and Anthill's share with the work it serves. Prices are per
million tokens, from Anthropic's price list (6 Oct 2026); a cache write costs
1.25x input for 5 minutes and 2x for an hour.

The result is cached in `local/cost.json` and redone only when a chat record
changed, because the owner's page asks for it every few seconds.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from anthill import context as _ctx

# model: (input, output, cache read) in dollars per million tokens
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
ANTHILL_AGENTS = {"anthill-keeper"}
NO_SPRINT = "(no sprint)"


def transcripts_dir(ctx: _ctx.Context) -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(ctx.root))


def _price(model: str) -> tuple[float, float, float] | None:
    model = re.sub(r"-\d{8}$", "", model or "")
    return PRICES.get(model)


def dollars(model: str, u: dict[str, Any]) -> float | None:
    p = _price(model)
    if p is None:
        return None
    inp, out, read = p
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens") or 0
    w5m = cc.get("ephemeral_5m_input_tokens")
    if w5m is None:
        w5m = (u.get("cache_creation_input_tokens") or 0) - w1h
    return ((u.get("input_tokens") or 0) * inp + (u.get("output_tokens") or 0) * out
            + w5m * inp * 1.25 + w1h * inp * 2 + (u.get("cache_read_input_tokens") or 0) * read) / 1e6


def _tokens(u: dict[str, Any]) -> int:
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                            "cache_creation_input_tokens", "cache_read_input_tokens"))


def replies(tdir: Path) -> list[dict[str, Any]]:
    """Every reply in the chat records, once each, with who made it."""
    seen: dict[str, dict[str, Any]] = {}
    for f in sorted(tdir.glob("*.jsonl")) + sorted(tdir.glob("*/subagents/*.jsonl")):
        agent = ""
        meta = f.with_suffix(".meta.json")
        if meta.exists():
            try:
                agent = json.loads(meta.read_text(encoding="utf-8")).get("agentType", "")
            except (OSError, ValueError):
                pass
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"usage"' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            m = j.get("message") or {}
            u = m.get("usage")
            if j.get("type") != "assistant" or not u or not m.get("id"):
                continue
            prev = seen.get(m["id"])
            # One reply is written once per content block, with the same usage;
            # the last copy has the final output count.
            if prev is None or (u.get("output_tokens") or 0) >= (prev["usage"].get("output_tokens") or 0):
                seen[m["id"]] = {"model": m.get("model", ""), "usage": u, "t": j.get("timestamp", ""),
                                 "branch": j.get("gitBranch", ""), "session": j.get("sessionId", ""),
                                 "agent": agent}
    return list(seen.values())


def _when(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()      # a date written without a zone is local


def _titles(ctx: _ctx.Context) -> dict[str, str]:
    from anthill.sprint import page
    return {g["id"]: g.get("title", "") for g in page.all_sprints(ctx)}


def _worked_on(ctx: _ctx.Context) -> dict[str, list[tuple[datetime, str]]]:
    """When each chat acted on which sprint, from the log."""
    from anthill import trail
    out: dict[str, list[tuple[datetime, str]]] = {}
    for e in trail.read(ctx):
        sid, t = e.get("sprint") or e.get("goal"), _when(e.get("t", ""))
        if sid and t and e.get("session"):
            out.setdefault(e["session"], []).append((t, sid))
    for v in out.values():
        v.sort()
    return out


def attribute(ctx: _ctx.Context, rs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each reply as (time, sprint, dollars, tokens, keeper?).

    A reply is charged to a sprint only when its own chat acted on that sprint
    (started it, ticked a step, decided, asked); helpers count with the chat that
    started them. The sprint is the one that chat touched last before the reply,
    or first after it. A branch is not enough: several chats share one, and a
    chat building Anthill on LogiAstro's branch was charged to LogiAstro's work.
    """
    worked = _worked_on(ctx)
    titles = _titles(ctx)
    rows = []
    for r in rs:
        t, acts = _when(r["t"]), worked.get(r["session"]) or []
        sid = NO_SPRINT
        if acts and t:
            before = [a for a in acts if a[0] <= t]
            sid = (before[-1] if before else acts[0])[1]
        d = dollars(r["model"], r["usage"])
        rows.append({"t": r["t"], "sprint": sid, "title": titles.get(sid, ""),
                     "usd": d, "tokens": _tokens(r["usage"]), "keeper": r["agent"] in ANTHILL_AGENTS})
    return rows


def summarize(rows: list[dict[str, Any]], days: int | None = None) -> dict[str, Any]:
    from datetime import timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    by: dict[str, dict[str, Any]] = {}
    unpriced = 0
    for r in rows:
        t = _when(r["t"])
        if since and (t is None or t < since):
            continue
        if r["usd"] is None:
            unpriced += 1
        row = by.setdefault(r["sprint"], {"usd": 0.0, "keeper_usd": 0.0, "tokens": 0, "replies": 0,
                                          "title": r.get("title", "")})
        row["usd"] += r["usd"] or 0.0
        row["tokens"] += r["tokens"]
        row["replies"] += 1
        if r["keeper"]:
            row["keeper_usd"] += r["usd"] or 0.0
    for row in by.values():
        row["usd"], row["keeper_usd"] = round(row["usd"], 2), round(row["keeper_usd"], 2)
    total = round(sum(r["usd"] for r in by.values()), 2)
    keeper = round(sum(r["keeper_usd"] for r in by.values()), 2)
    return {"days": days, "total_usd": total, "keeper_usd": keeper,
            "keeper_share_pct": round(100 * keeper / total, 1) if total else 0.0,
            "by_sprint": dict(sorted(by.items(), key=lambda kv: -kv[1]["usd"])),
            "unpriced_replies": unpriced, "basis": "API-price equivalent"}


def _rows(ctx: _ctx.Context, fresh: bool = False) -> list[dict[str, Any]]:
    tdir = transcripts_dir(ctx)
    cache = ctx.local_dir / "cost.json"
    files = (list(tdir.glob("*.jsonl")) + list(tdir.glob("*/subagents/*.jsonl"))) if tdir.exists() else []
    newest = max((f.stat().st_mtime for f in files), default=0.0)
    stamp = {"newest_record": newest, "chats": len(files)}
    if not fresh and cache.exists():
        try:
            old = json.loads(cache.read_text(encoding="utf-8"))
            if old.get("stamp") == stamp:
                return old["rows"]
        except (OSError, ValueError, KeyError):
            pass
    rows = attribute(ctx, replies(tdir)) if files else []
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"stamp": stamp, "rows": rows}), encoding="utf-8")
    except OSError:
        pass
    return rows


def report(ctx: _ctx.Context, days: int | None = None, fresh: bool = False) -> dict[str, Any]:
    out = summarize(_rows(ctx, fresh), days)
    out["records"] = str(transcripts_dir(ctx))
    return out


def main(argv: list[str]) -> int:
    ctx = _ctx.resolve(None)
    if not ctx.installed:
        print("anthill cost: not installed here")
        return 2
    days = None
    if "--days" in argv:
        try:
            days = int(argv[argv.index("--days") + 1])
        except (IndexError, ValueError):
            print("anthill cost: --days takes a number")
            return 2
    out = report(ctx, days=days, fresh="--fresh" in argv)
    if "--json" in argv:
        print(json.dumps(out, indent=2))
        return 0
    span = f"the last {days} days" if days else "all time"
    print(f"Spent on chats here, {span}: ${out['total_usd']:,.2f} ({out['basis']}); "
          f"the keeper (Anthill's background helper) ${out['keeper_usd']:,.2f} ({out['keeper_share_pct']}%)")
    for sid, r in list(out["by_sprint"].items())[:15]:
        own = f"  (keeper ${r['keeper_usd']:,.2f})" if r["keeper_usd"] else ""
        print(f"  ${r['usd']:>9,.2f}  {sid}{own}")
    if out.get("unpriced_replies"):
        print(f"  {out['unpriced_replies']} replies from models with no listed price are not counted")
    return 0
