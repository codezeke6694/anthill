"""The owner's to-do: what they are actually being asked, in a form they can answer.

The owner, 1 Oct, on the page: "I am lost in it -- what it shows me, what I
have to do." It listed eleven "questions" taken straight from work pages,
written by agents for agents: the same question three times, pointers to
another page, status updates, things already decided, 500 characters with
code names and commit hashes, and Yes / No buttons under "self-host it, or pay
a service?".

This turns those notes into to-do items: a one-line question, why it matters,
the agent's recommendation, and the real choices. Pointers and status lines
are dropped, repeats folded, and what holds up a running goal comes first. A
question written in the agreed form --

    **<the question>** Why: <…> Recommend: <…> Options: <A> / <B>

-- is read exactly; anything else is read as well as the words allow.
"""
from __future__ import annotations

import re
from typing import Any

_CITE = re.compile(r"\s*\((?:sg|cite|code):[^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_HASHES = re.compile(r"\s*\((?:[0-9a-f]{7,40}(?:,\s*)?)+\)")
_FIELD = re.compile(r"\b(Why|Recommend(?:ed|ation)?|Options?):\s*", re.I)


def clean(text: str) -> str:
    t = _CITE.sub("", str(text or ""))
    t = _LINK.sub(r"\1", t)
    t = _HASHES.sub("", t)
    t = t.replace("`", "").replace("**", "")
    return " ".join(t.split()).strip(" -—")


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+(?=[A-Z\"“(])", t) if s.strip()]


def is_noise(raw: str) -> bool:
    """A line that is not a question for the owner: a pointer, or a status."""
    t = clean(raw)
    low = t.lower()
    first = (_sentences(t) or [t])[0].lower()
    if low.startswith(("still open from before", "see ")):
        return True
    # a pointer: the question lives on another page ("the X answer on the Y page decides ...")
    if re.search(r"\banswer on the\b.*\bdecides\b|\bdecides how\b", low):
        return True
    # a status, not a question: judged on its opening sentence only, so a real
    # question with a status remark after it still counts
    if re.search(r"\bnow built\b|\balready (built|done|merged)\b|\bnot waiting on the owner\b", first):
        return True
    return False


def _options_from(question: str) -> list[str]:
    m = re.search(r"([^.?!]*?),?\s+or\s+([^.?!]+)\?", question)
    if not m:
        return []
    a, b = m.group(1).strip(), m.group(2).strip()
    a = re.split(r"[:—]\s*", a)[-1].strip()           # "Landmarks and roads: self-host it" -> "self-host it"
    if not a or not b or len(a) > 40 or len(b) > 40:
        return []
    cap = lambda s: s[:1].upper() + s[1:]                # noqa: E731
    return [cap(a), cap(b)]


def parse(raw: str) -> dict[str, Any]:
    """One note → {title, why, recommend, options}."""
    raw = str(raw or "")
    fields: dict[str, str] = {}
    parts = _FIELD.split(raw)
    head = parts[0]
    for i in range(1, len(parts) - 1, 2):
        key = parts[i].lower()
        key = "why" if key.startswith("why") else "recommend" if key.startswith("recommend") else "options"
        fields[key] = clean(parts[i + 1]).rstrip(".")
    bold = re.match(r"\s*\*\*(.+?)\*\*\s*(.*)", head, re.S)
    if bold:
        title, rest = clean(bold.group(1)).rstrip("."), clean(bold.group(2))
    else:
        sents = _sentences(clean(head))
        title, rest = (sents[0] if sents else clean(head)), " ".join(sents[1:])
    if not fields.get("recommend"):
        m = re.search(r"(?:I recommend|Recommendation(?: given to the owner)?|Recommended)[:,]?\s*(.+?)(?:\.(?:\s|$)|$)", rest + " ", re.I)
        if m:
            fields["recommend"] = m.group(1).strip()
            rest = (rest[:m.start()] + rest[m.end():]).strip()
    rest = re.sub(r"\bNot yet decided\.?", "", rest).strip()
    rest = re.sub(r"Not waiting on the owner.*$", "", rest).strip()
    if len(title) > 90:                                  # drop asides in a long title
        title = re.sub(r"\s*\([^)]*\)", "", title).strip()
    kind = ("question" if title.endswith("?") else
            "task" if re.match(r"(Spot-check|Check|Look at|Review|Read|Try|Approve|Sign|Test|Open)\b", title) else
            "decide")
    if kind == "decide":
        title = re.split(r"\s+(?:is|are)\s+the\s+|:\s", title)[0].strip().rstrip(".")
        if title.lower().startswith("whether "):
            title = title[8:]
            title = title[:1].upper() + title[1:] + "?"
            kind = "question"
    rec = fields.get("recommend", "")
    if rec:                                              # the recommendation, not what follows it
        rec = (_sentences(rec) or [rec])[0].rstrip(".")
        fields["recommend"] = rec
    why = fields.get("why") or rest
    if len(why) > 260:
        why = why[:259].rsplit(" ", 1)[0] + "…"
    if len(title) > 160:
        title = title[:159].rsplit(" ", 1)[0] + "…"
    options = [o.strip() for o in re.split(r"\s*(?:/|\|)\s*", fields.get("options", "")) if o.strip()]
    if not options:
        options = _options_from(title) or _options_from(clean(head))
    return {"title": title, "why": why, "recommend": fields.get("recommend", ""), "options": options[:4], "ask": kind}


def _key(title: str) -> str:
    words = [w for w in re.findall(r"[a-z]{4,}", title.lower())][:4]
    return " ".join(words)


def build(where: dict[str, Any], goals: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for g in goals:
        for i, b in enumerate(g.get("blockers") or []):
            if b.get("answer"):
                continue
            p = parse(b.get("question", ""))
            items.append({**p, "id": f"goal:{g['id']}:{i}", "kind": "goal", "ref": g["id"],
                          "from": g.get("title", ""), "holding_up": True,
                          "after": "the goal picks up again from where it stopped"})
            seen.add(_key(p["title"]))

    answered_work: list[dict[str, Any]] = []
    for r in where.get("work") or []:
        answers = [clean(a) for a in r.get("owner_answers") or []]
        for q in r.get("waiting_on_owner") or []:
            if is_noise(q):
                continue
            p = parse(q)
            k = _key(p["title"])
            if k and k in seen:
                continue
            seen.add(k)
            hit = next((a for a in answers if clean(q)[:60] in a or p["title"][:50] in a), None)
            item = {**p, "id": f"work:{r['id']}:{k}", "kind": "work", "ref": r["id"],
                    "question_raw": clean(q)[:240], "from": r.get("title", ""),
                    "holding_up": r.get("state") == "waiting-on-owner",
                    "after": "it goes on that piece of work; the next chat on it acts on your answer"}
            if hit:
                answered_work.append({**item, "answer": hit.split("”:")[-1].strip()})
            else:
                items.append(item)

    items.sort(key=lambda x: (x["kind"] != "goal", not x["holding_up"]))
    review = []
    for g in goals:
        for i, d in enumerate(g.get("decided") or []):
            if d.get("overturned") or d.get("acknowledged"):
                continue
            review.append({"goal": g["id"], "index": i, "what": clean(d.get("what", "")),
                           "because": clean(d.get("because", "")), "from": g.get("title", "")})
    return {"todo": items, "answered": answered_work, "review": review}
