#!/usr/bin/env python3
"""The rules an agent reads, rendered from the configuration that enforces them.

Three files told the builder what to do -- CLAUDE.md, AGENTS.md, and the role
file -- plus the brief compiled into every unit. Each was written by hand, at a
different time, for a different version of the tool. By the time anyone looked,
they disagreed on whether to run `map build` before the gate, on the name of the
escalate flag, and on whether a push needs the owner's say-so -- while the hook
that actually decided the push read the config and ignored all three.

Prose that describes a mechanism has to be generated from the mechanism's
settings, or it drifts. Every function here returns text for exactly one such
rule, and every renderer imports it from here. One source, several renderings.
"""
from __future__ import annotations

from anthill import context as _ctx


def execution(ctx: _ctx.Context) -> dict:
    return ctx.config.get("execution") or {}


def mode(ctx: _ctx.Context) -> str:
    """`solo`: one interactive agent, working in place, escalating by judgement.
    `pool`: several headless agents, isolated worktrees, escalating by count.

    Solo is the default because it is how the tool is actually used: a person
    talking to one agent in the repository they are also editing. The pool
    machinery -- locks, heartbeats, attempt budgets, auto-escalation -- exists to
    coordinate agents that cannot talk to each other, and a single agent pays its
    whole cost for nothing.
    """
    m = str(execution(ctx).get("mode") or "solo").strip().lower()
    return m if m in ("solo", "pool") else "solo"


def isolated(ctx: _ctx.Context) -> bool:
    return bool(execution(ctx).get("isolate", False))


def map_build_rule(ctx: _ctx.Context) -> str:
    """Whether the builder rebuilds the blueprint before the gate.

    In an isolated worktree it must not: the map is one shared file and a
    rebuild from a worktree holding only one unit's change would erase every
    other unit. In place there is exactly one tree, so the builder is the only
    one who can rebuild it, and the gate refuses a stale blueprint.
    """
    if isolated(ctx):
        return ("Do **not** run `anthill map build`. You are in an isolated worktree "
                "holding only your own change, so a blueprint built here would be "
                "missing every other unit, and with several builders running the "
                "last writer would win. The foreman redraws it after your unit "
                "merges. The gate checks only the claims touching the files you "
                "changed.")
    return ("Run `anthill map build` before the gate. You are working in the "
            "repository itself, so yours is the only tree there is and nobody else "
            "will redraw the blueprint for you. The gate refuses a unit whose "
            "blueprint no longer matches the code.")


def escalation_rule(ctx: _ctx.Context) -> str:
    if mode(ctx) == "pool":
        return ("A unit escalates on its own after `escalate_after` failed gates "
                "(two, by default). An ownership failure or an unreviewed audit "
                "costs no attempt.")
    return ("Nothing escalates on its own. A failed gate is reported and the unit "
            "stays yours. Escalate when you have judged that you cannot finish "
            "it; a counter does not judge that for you.")


def cold_start_rule(ctx: _ctx.Context) -> str:
    """How an agent that knows nothing finds its way in.

    Two commands, and a warning measured rather than assumed: a cold agent that
    trusted the top card named the right area and missed the cause, where one
    reading without the map found it by following the calls -- in twice the
    steps. The map is fast because it points; the walk after it is still yours.
    """
    return "\n".join([
        "## Before any task: learn where you are",
        "",
        "```bash",
        "anthill orient                                  # the codebase on one page",
        'anthill start "<the task, in your own words>"   # where that task lives',
        "```",
        "",
        "`orient` says what this product is, its chambers and what each does, how "
        "they connect, what changed recently, how to prove a change, and the rules. "
        "`start` names the file a task most likely lives in, with what it calls, "
        "who calls it, the tests that cover it, and the rules written about it.",
        "",
        "The map says where to start, not where it ends. Read the live code, then "
        "follow the card's routes and consumers until you reach the line that "
        "actually decides the behaviour. The top suggestion is right about half "
        "the time (`anthill eval-map` measures it against this repository's own "
        "history), so look at the other candidates before committing to one.",
    ])


def upkeep_rule(ctx: _ctx.Context) -> str:
    """After a commit: hand the paperwork to a helper, and keep working.

    The owner's measured complaint: when the agent doing the work also does the
    admin -- glossary, knowledge pages, test notes -- development slows down.
    So the admin goes to a background helper that writes only the knowledge
    directory, and the agent in the code never waits for it.
    """
    return "\n".join([
        "## After you commit: hand off the upkeep, keep working",
        "",
        "The commit prints `anthill upkeep: N thing(s) to bring up to date` when a "
        "change left the glossary, a knowledge page, or test coverage behind. When "
        "it does:",
        "",
        "1. Start the `anthill-keeper` agent **in the background** with that list.",
        "2. Carry on with the work. Do not wait for it and do not do its job "
        "yourself; it writes only the knowledge directory, so it cannot collide "
        "with your code.",
        "3. When it reports, pass its test suggestions to the owner in one line.",
        "",
        "Anything left undone stays on the list: `anthill upkeep --open` shows it, "
        "and `anthill work status` repeats it to the next session.",
    ])


def git_rules(ctx: _ctx.Context) -> str:
    """The two git rules, as they actually stand in this installation.

    `push_requires_owner` and `protected_branches` are what the hooks read. The
    prose has to say the same thing, or the agent is under a written instruction
    the hook will not let it obey -- observed: CLAUDE.md said "told to push, you
    push" for an hour while the hook refused every push regardless.
    """
    ex = execution(ctx)
    protected = [str(b) for b in (ex.get("protected_branches") or [])]
    push_owner = bool(ex.get("push_requires_owner", True))

    parts = ["## Two rules about git", ""]
    parts.append("Both of these are what you do **absent an instruction**. The owner "
                 "can override either one at any time, and when they do, the section "
                 "at the top of this file governs: brief them on what is about to "
                 "happen, then do it.")
    parts.append("")
    parts.append("**1. Never push on your own initiative. Ask.**")
    parts.append("")
    parts.append("Pushing is the owner's act, every time, on every branch. An approval "
                 "given once does not carry forward: not to the next push, not across "
                 "a context compaction, not because the last one was fine. If "
                 "something is ready to go up, say what it is and why, and let the "
                 "owner decide.")
    parts.append("")
    parts.append("Told to push, you push. Say first what is going up (branch, remote, "
                 "how many commits, anything that will surprise them) and then do it, "
                 "without asking again.")
    parts.append("")
    if push_owner:
        parts.append("The pre-push hook refuses every push unless the owner runs it "
                     "themselves. That is the configured setting "
                     "(`execution.push_requires_owner`), and it is why a refused push "
                     "is not something to route around: it is the owner's decision, "
                     "written into the hook.")
    else:
        parts.append("The pre-push hook does **not** refuse pushes here "
                     "(`execution.push_requires_owner` is off). Nothing mechanical "
                     "stops you. The rule holds because you were not asked, not "
                     "because you cannot.")
    parts.append("")
    parts.append("Commit locally as much as you like. A local commit stays on this "
                 "machine and can be undone without anyone noticing. A push reaches "
                 "the remote and everyone working from it, and cannot be taken back "
                 "the same way.")
    parts.append("")
    parts.append("**2. Work on a branch, not on `main`.**")
    parts.append("")
    parts.append("```bash\ngit switch -c work/<what-you-are-doing>\n```")
    parts.append("")
    parts.append("Not only because `main` is the owner's. Other people work on this "
                 "codebase from the same remote. `main` is the thing everybody "
                 "branches from and merges into, so a change sitting directly on it "
                 "is a change nobody agreed to and everybody inherits. Your branch "
                 "is yours to be wrong on.")
    parts.append("")
    if protected:
        parts.append("The pre-commit hook refuses a commit on " +
                     ", ".join(f"`{b}`" for b in protected) +
                     " (`execution.protected_branches`).")
    else:
        parts.append("No branch is protected by a hook here "
                     "(`execution.protected_branches` is empty). `main` is the "
                     "owner's by rule, not by mechanism.")
    parts.append("")
    if ex.get("guard_hygiene", False):
        parts.append("The hooks also refuse what no shared repository survives "
                     "(`execution.guard_hygiene`): a commit that adds a secret — a "
                     "key, a token, a `.env` — or a junk file like `.DS_Store` or "
                     "`__pycache__/`, and a push that rewrites a remote branch "
                     "instead of adding to it. Unstage the file and `.gitignore` "
                     "it; catch up with a merge, not a force push.")
        parts.append("")
    parts.append("**And never bypass the hooks.** No `--no-verify`, on commit or on "
                 "push. A refusal is information: read it and do what it says. If you "
                 "think a hook is wrong, say so and stop.")
    parts.append("")
    parts.append("Know why these are asked rather than enforced: a local hook runs the "
                 "same git binary for you and for the owner, on the same machine, so "
                 "it cannot tell you apart. What holds is that you choose to let it "
                 "hold. Bypassing it once teaches the next session that bypassing is "
                 "normal.")
    parts.append("")
    parts.append("So the rule is short, and it is the whole of it: **you do not push "
                 "unless the owner asked for this push.** An approval from earlier in "
                 "the session is not this push. A branch that is ready is not a "
                 "request. If you think something should go up, say so and wait.")
    return "\n".join(parts)


def audit_note(ctx: _ctx.Context) -> str:
    """What an audit is worth here, from the role assignments."""
    from anthill import roles as roles_mod
    try:
        ind = roles_mod.independence(ctx).get("independence", "")
    except Exception:                                   # pragma: no cover
        ind = ""
    if ind == "none":
        return ("The builder and the auditor are the same identity, so a missing "
                "audit does not block a unit here: the gate runs `audit check "
                "--optional`, which still refuses on a recorded FAIL but does not "
                "wait for a review that would carry no information.")
    return ("An audit is required before a unit closes. A missing or stale audit "
            "exits 3: not your fault, and it costs no attempt.")
