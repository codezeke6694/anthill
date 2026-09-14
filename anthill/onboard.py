#!/usr/bin/env python3
"""The interview that fills the constitution.

`install` scaffolds the *structure* of a charter and leaves its content blank,
which is only half a job: a constitution with an empty "What we're building" is
a form, and nobody fills in a form. The planner's role is to discuss, fill, and
report -- so the questions get asked.

WHY THIS IS A COMMAND AND NOT AN AGENT EDIT
-------------------------------------------
`CONSTITUTION.md` is a protected path: it is denied to every agent, because an
agent that can edit the document binding it is not bound. That rule must survive
onboarding, so this command is the one sanctioned path into the file, and it is
deliberately narrow:

    it fills sections that are EMPTY.
    it never overwrites a section a human has already written.

An agent may therefore help set the charter up, and can never quietly rewrite a
decision once recorded. `--force` exists for a human correcting their own
answer, and says so when used.

Interactive in a terminal; flag-driven when a planner agent runs the interview
conversationally and then applies what it heard.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

# (config key, heading in CONSTITUTION.md, question, help shown before asking)
QUESTIONS: list[tuple[str, str, str, str]] = [
    ("stack", "**Stack:**", "What is the stack?",
     "Languages, frameworks, database. This decides district boundaries and "
     "which code can be structurally fingerprinted (Python only, today)."),
    ("building", "## What we're building",
     "What are we building, for whom, and what problem does it solve?",
     "Two or three sentences. Every unit brief inherits this framing."),
    ("architecture", "## Architecture",
     "How is the system laid out — the main components and how they connect?",
     "High level. This becomes the district map, so name the parts you expect "
     "to own separate directories."),
    ("decisions", "## Key decisions",
     "Which technical decisions are already made, and why?",
     "One per line. Recording the 'why' is the point — an agent that cannot see "
     "the reason will relitigate it."),
    ("standards", "## Coding standards",
     "Any coding standards agents must follow?",
     "Naming, error handling, test style. Leave empty if you have none yet."),
]


def _section_bounds(text: str, heading: str) -> tuple[int, int] | None:
    """Character span of a section's body, exclusive of its heading."""
    if heading.startswith("**"):                       # inline field
        m = re.search(re.escape(heading) + r"([^\n]*)", text)
        return (m.start(1), m.end(1)) if m else None
    # `[ \t]*$` rather than `\s*$`: with re.M, `\s` matches newlines too, so the
    # heading match ran past the section's blank body and the answer was appended
    # after it instead of replacing it -- leaving a growing stack of blank lines.
    m = re.search(r"^" + re.escape(heading) + r"[ \t]*$", text, re.M)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r"^(?:## |---\s*$)", text[start:], re.M)
    end = start + (nxt.start() if nxt else len(text) - start)
    return (start, end)


def read_sections(path: Path) -> dict[str, str]:
    """What each section currently holds, so 'empty' is a fact not a guess."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for key, heading, _, _ in QUESTIONS:
        span = _section_bounds(text, heading)
        out[key] = text[span[0]:span[1]].strip() if span else ""
    return out


def _is_blank(value: str) -> bool:
    """A rendered TODO placeholder counts as blank -- it is a prompt, not content."""
    v = value.strip()
    return not v or bool(re.fullmatch(r"_TODO:[^_]*_", v))


def apply(path: Path, answers: dict[str, str], force: bool = False
          ) -> tuple[list[str], list[str]]:
    """Write answers into blank sections. Returns (filled, kept)."""
    text = path.read_text(encoding="utf-8")
    current = read_sections(path)
    filled, kept = [], []
    # Reverse order so earlier spans stay valid as later ones are rewritten.
    for key, heading, _, _ in reversed(QUESTIONS):
        answer = (answers.get(key) or "").strip()
        if not answer:
            continue
        if not _is_blank(current.get(key, "")) and not force:
            kept.append(key)
            continue
        span = _section_bounds(text, heading)
        if not span:
            continue
        body = f" {answer}" if heading.startswith("**") else f"\n\n{answer}\n\n"
        text = text[:span[0]] + body + text[span[1]:]
        filled.append(key)
    path.write_text(text, encoding="utf-8")
    return list(reversed(filled)), kept


def interview(current: dict[str, str]) -> dict[str, str]:
    """Ask, in a terminal. Blank input leaves a section alone."""
    print("\nFilling CONSTITUTION.md. Press Enter to skip a question.")
    print("Answers become the charter every agent reads first.\n")
    answers: dict[str, str] = {}
    for key, heading, question, helptext in QUESTIONS:
        if not _is_blank(current.get(key, "")):
            print(f"— {question}\n  already answered, skipping "
                  f"(use --force to change it)\n")
            continue
        print(f"— {question}")
        print(f"  {helptext}")
        try:
            value = input("  > ").strip()
        except EOFError:
            print()
            break
        if value:
            answers[key] = value
        print()
    return answers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Interview the owner and fill CONSTITUTION.md. Fills blanks "
                    "only; never overwrites a recorded decision.")
    ap.add_argument("--project", default="")
    for key, _, question, _ in QUESTIONS:
        ap.add_argument(f"--{key}", default="", help=question)
    ap.add_argument("--force", action="store_true",
                    help="Overwrite sections that already have content. For a "
                         "human correcting their own answer.")
    ap.add_argument("--show", action="store_true",
                    help="Report what is answered and what is still blank")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2
    if not ctx.constitution.exists():
        print(f"anthill: no constitution at {ctx.constitution}", file=sys.stderr)
        return 2

    current = read_sections(ctx.constitution)
    blank = [k for k, _, _, _ in QUESTIONS if _is_blank(current.get(k, ""))]

    if args.show:
        out = {"constitution": str(ctx.constitution),
               "answered": [k for k, _, _, _ in QUESTIONS if k not in blank],
               "blank": blank,
               "questions": {k: q for k, _, q, _ in QUESTIONS if k in blank}}
        print(json.dumps(out, indent=2) if args.json else
              "answered: " + (", ".join(out["answered"]) or "(none)") +
              "\nblank   : " + (", ".join(blank) or "(none)"))
        return 0

    supplied = {k: getattr(args, k) for k, _, _, _ in QUESTIONS
                if getattr(args, k, "")}
    if not supplied:
        if not sys.stdin.isatty():
            print("anthill: nothing supplied and stdin is not a terminal.\n"
                  "  Either run this interactively, or pass answers as flags "
                  "(see --help), or use --show to list what is still blank.",
                  file=sys.stderr)
            return 2
        supplied = interview(current)

    if not supplied:
        print("nothing to write.")
        return 0

    filled, kept = apply(ctx.constitution, supplied, force=args.force)
    result = {"constitution": str(ctx.constitution), "filled": filled,
              "kept_existing": kept,
              "still_blank": [k for k, _, _, _ in QUESTIONS
                              if _is_blank(read_sections(ctx.constitution).get(k, ""))]}
    if kept:
        result["note"] = ("these sections already had content and were left "
                          "alone; pass --force to change them")
    print(json.dumps(result, indent=2) if args.json else
          f"filled: {', '.join(filled) or '(none)'}"
          + (f"\nkept  : {', '.join(kept)} (already answered; --force to change)"
             if kept else "")
          + (f"\nblank : {', '.join(result['still_blank'])}"
             if result["still_blank"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
