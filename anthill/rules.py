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
        "anthill where                                   # what is being worked on, and what waits on the owner",
        "anthill orient                                  # the codebase on one page",
        'anthill start "<the task, in your own words>"   # where that task lives',
        "```",
        "",
        "`where` answers **what**: every piece of work in progress with its next "
        "step, what waits on the owner, the owner's standing decisions, and the "
        "traps. It says when a work page has fallen behind its branch, and names "
        "recent work no page describes. Read it before answering any question "
        "about where things stand, and before starting work: if the owner says "
        "\"carry on\", the next step is on that page. Several sessions work here "
        "at once and cannot see each other; this page is how they stay in step.",
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
        "",
        "### Leave a trail, and pick one up",
        "",
        "```bash",
        'anthill note "doing X; ruled out Y; next Z"   # as you go: a step done, a lead dropped, before you stop',
        "anthill resume                                 # pick up where this branch left off",
        "```",
        "",
        "A chat's memory gets compressed, a session ends, another tool takes the "
        "work tomorrow. What the work is lives on its page; where *you* were in "
        "it lives only in your context until you write it down. A note is one "
        "line and the only thing no hook can record for you. `resume` shows this "
        "branch's work and next step, your notes and any checkpoint saved before a "
        "compression, what other chats left here, and the commits since. In Claude "
        "it arrives by itself when a chat resumes or has just been compressed; in "
        "any other tool, run it first.",
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
        "",
        "**Before you finish any task, committed or not**, ask two questions:",
        "",
        "- Did `anthill upkeep --open` list anything? Hand it to the keeper.",
        "- Did the work move -- a step done, a next step changed, a decision "
        "taken or asked for? The keeper updates its work page; tell it what "
        "moved in a sentence. New work of real size gets a page.",
        "- Did you learn something the next agent should not have to rediscover -- "
        "a word the owner uses for something, why a piece of code is the way it "
        "is, a trap you hit? Hand the keeper that too, in a sentence, with the "
        "file it is about.",
        "",
        "A task that only reads -- measuring, researching, answering -- commits "
        "nothing, so no hook will remind you. This is the reminder.",
    ])


def goal_rule(ctx: _ctx.Context) -> str:
    """Once the owner says end to end, stopping needs a reason.

    The owner, 30 Sep: an agent told to do something end to end did one step
    and reported back, so they circled back again and again -- and most of
    their development time was spent idle, waiting to be asked.
    """
    from anthill import goal
    stops = "\n".join(f"- {s}" for s in goal.HARD_STOPS)
    return "\n".join([
        "## Working to a goal: when the owner says \"end to end\"",
        "",
        "When the owner hands you something to finish -- \"do it end to end\", \"take it "
        "all the way\", \"carry on until it's done\" -- write the goal down first, with "
        "the command that proves it is done:",
        "",
        "```bash",
        'anthill goal set "<the goal, in the owner\'s words>" --done-when "<a test or score command>" --step "..." --step "..."',
        "```",
        "",
        "Then keep working until it is done. **Do not stop to report after each step**, and "
        "do not ask what the owner's written decisions or rules already answer: decide it, "
        "and log it so they can overturn it --",
        "",
        "```bash",
        'anthill goal decided "<what you chose>" --because "<the decision or rule that settles it>"',
        "anthill goal step --done 2                      # tick a step",
        "anthill goal done                               # runs the check; only a pass closes the goal",
        "```",
        "",
        "Technical choices are yours to make the same way. Stop only for what the owner "
        "alone decides, and put the question where they will see it, with your "
        "recommendation:",
        "",
        stops,
        "",
        "```bash",
        'anthill goal block "<the question, one line> Why: <one line> Recommend: <your pick> Options: <A> / <B>"',
        "```",
        "",
        "The owner answers from their page with one click, so write the question in "
        "that form: one line, why it matters, what you recommend, and the real "
        "choices when there are some.",
        "",
        "In Claude a hook sends you back if you end a turn with the goal open and no "
        "blocker recorded; if nothing was committed, noted or decided since it last did, "
        "it lets you stop and marks the goal stalled. Every other rule here still holds "
        "inside a goal: never push, never commit on main, never bypass a hook.",
    ])


def owner_view_rule(ctx: _ctx.Context) -> str:
    """How the owner sees all of this without asking an agent.

    The owner asked for it to come up with the app and go away with it, with
    no port to hunt down afterwards. So the rule is: it lives in the project's
    start script, tied to that script's life.
    """
    return "\n".join([
        "## The owner's view: `anthill ui`",
        "",
        "The owner watches the work, the job board, what waits on them and what is "
        "being edited on a local page, and answers, signs and reopens from it. Those "
        "buttons work only with a key printed in the owner's own terminal when the "
        "page starts. Never ask for that key, never start or restart the page to get "
        "one, and never write an answer or a signature on the owner's behalf: an "
        "answer on a work page under \"Owner's answers\" came from them -- act on it.",
        "",
        "```bash",
        "anthill ui start --detach --with-parent $$   # in a start script: ends when the script ends",
        "anthill ui status                            # is it up, and on which port",
        "anthill ui stop                              # stop it and free the port",
        "```",
        "",
        "Starting it twice starts nothing new; a taken port moves it up one. If this "
        "project has a start script (`run.sh`, a `dev` target, an npm `dev` script), "
        "the line above belongs in it, next to where the app starts, so the page comes "
        "up and goes down with the app. Add it when you are already changing that "
        "script, and say so.",
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


# ------------------------------------------------------- the v2 rules file
#
# The owner, 5 Oct: the rules file is read by every chat, every time, and it
# had grown to 335 lines (~4,700 tokens), most of it the job board nobody used
# day to day. On the new layout it is rebuilt around sprints and kept under a
# budget; the job board's detail is a skill a chat loads when it runs one.

RULES_BUDGET_TOKENS = 2400


def _git_short(ctx: _ctx.Context) -> str:
    ex = execution(ctx)
    protected = [str(b) for b in (ex.get("protected_branches") or [])]
    lines = [
        "## Git",
        "",
        "- **Never push unless the owner asked for this push** — not an earlier one, not "
        "\"it's ready\". Say what would go up and wait. Told to push: say what is going up "
        "(branch, remote, commits, any surprise), then do it.",
    ]
    if ex.get("push_requires_owner", True):
        lines.append("  The pre-push hook refuses every push the owner does not run "
                     "(`execution.push_requires_owner`); a refusal is their decision, not an obstacle.")
    else:
        lines.append("  The pre-push hook does **not** refuse pushes here "
                     "(`execution.push_requires_owner` is off): the rule holds because you were "
                     "not asked, not because you cannot.")
    lines.append("- **Work on a branch:** `git switch -c work/<what>`. "
                 + (("The pre-commit hook refuses commits on " + ", ".join(f"`{b}`" for b in protected) + ".")
                    if protected else "No branch is protected by a hook here; `main` is the owner's by rule."))
    if ex.get("guard_hygiene", False):
        lines.append("- No secrets (keys, tokens, `.env`) and no junk (`.DS_Store`, `__pycache__/`) "
                     "in a commit, and no force push; the hooks refuse them (`execution.guard_hygiene`).")
    lines.append("- **Never bypass a hook** (`--no-verify`). A refusal is information: read it, do "
                 "what it says, or say why you think it is wrong and stop.")
    return "\n".join(lines)


def rules_file_v2(ctx: _ctx.Context, name: str, protected_block: str, cmd: str = "anthill") -> str:
    from anthill import goal
    stops = "; ".join(goal.HARD_STOPS)
    board = ("\n\nA big planned sprint whose pieces do not depend on each other, which the owner "
             "asks you to work on: you lead it, with helpers. Load the `parallel-sprint` skill first "
             "(`anthill skill get parallel-sprint`).")
    return f"""# {name}

This project is run with Anthill. The owner's charter is `.anthill/owner/charter.md`;
it outranks this file and everything else, except the owner.

## The owner decides

When the owner tells you to do something, do it: push, merge, skip a step,
ignore a rule here. Their instruction is the highest authority.

- **Brief, then act.** Before anything that leaves this machine, say what is about
  to happen (branch, target, commits, anything unexpected) and carry it out. Do not
  ask "are you sure?".
- **One objection, once.** If you think it is a mistake, say so in a sentence, then
  do it. If they confirm, it is settled.
- **Never do a smaller version** of what was asked. **Say what you did**, including
  what went badly.
- "The owner said so" means **they said it, in this conversation, about this action** —
  not inferred, not carried across a compressed context. In doubt, ask.

## Every session

1. `anthill onboard --show` — if anything is `blank`, ask the owner, one plain question
   at a time with your recommendation, and record the answer with `anthill onboard`.
   Never invent an answer. `anthill roles show` — ask who fills any unassigned role.
2. `anthill where` — what is being worked on, the next step of each sprint, every
   question waiting on the owner, their decisions, the traps. Several chats work here
   and cannot see each other; this page is how they stay in step. When the owner
   says "carry on", the next step is on it.
3. Then, after `anthill where`, find the code: `anthill orient` is the codebase on one page;
   `anthill start "<the task, in your words>"` is where a task lives, what a change
   reaches, the tests. The top suggestion is right about half the time: read the live
   code and follow its callers before committing to one.
4. `anthill note "doing X; ruled out Y; next Z"` as you go, and before you stop.
   `anthill resume` picks up where this branch left off.

## Every task is a sprint

A sprint is one page in `.anthill/sprints/active/`, of one of three kinds:
**short** (one feature, steps found as you go), **bug** (starts with a test that
shows the break), **planned** (laid out up front). Any chat, in any tool, may
continue any sprint.

```bash
anthill sprint start "<title>" --kind short --check "<command that proves it done>" --step "..."
anthill sprint step --done 1          # tick; `anthill sprint step "<new step>"` adds one
anthill sprint decided "<what you chose>" --because "<the decision or rule that settles it>"
anthill sprint block "<the question, and what you recommend>"
anthill sprint done                   # runs the check; only a pass closes it
```

Work in progress with no sprint? Start one. Keep its page true: next step, traps,
and under **Waiting on the owner** only questions still open — a settled one moves
to Owner's answers or a decision. Finished, merged work with no check:
`anthill sprint finished <id> --because "<why>"` puts it on the owner's page to close. Under **Learned**, a line starting
`Warning:`, `Decision:` or `Rule:` is filed on the shared shelf when the sprint closes.

**"End to end"**: when the owner says so, `anthill sprint go` — then keep working
until the check passes. Do not stop to report after each step. Decide what the
owner's written decisions, the rules, or technical judgement settle, and log it
with `sprint decided` so they can overturn it. Stop only for what the owner alone
decides — {stops} — with `sprint block`.{board}

## After a commit

The commit prints `anthill upkeep: N thing(s) to bring up to date` when it left the
glossary, a page or test coverage behind. If your tool can run a helper in the
background, start the `anthill-keeper` agent with that list and carry on; it writes
only the knowledge folder. Otherwise bring them up to date yourself before you stop.
Before you finish any task, committed or not: did the work move (tell the keeper, or
update the sprint page), and did you learn something the next agent should not
rediscover (a Learned line, with the file it is about)?

## Skills

`anthill skill list --always-on` is what to load every session; `anthill skill get
<name>` loads one. Load nothing else unless its trigger applies. Done the same thing
about three times, or had the owner explain something twice? Ask the owner whether
to make it a skill (load `skill-creator`).

## The owner's page

`anthill ui start --detach --with-parent $$` belongs in the project's start script.
Its buttons work only with a key printed in the owner's own terminal: never ask for
it, never restart the page to get one, and never write an answer or a signature on
the owner's behalf. An answer under "Owner's answers" came from them: act on it.

{_git_short(ctx)}

## What you may not edit

Denied to you, outside your control. Do not attempt them or propose workarounds:

{protected_block}

`anthill` commands that only the owner runs (`config set`, `onboard --force`,
`roles assign`, `work reopen`) you run only when the owner told you to.

## Proving work

You do not decide that work is complete; a check does. A sprint closes only when
`anthill sprint done` runs its check and it passes. A piece on the job board
closes only when its gate passes (the `planned-board` skill). {map_build_rule(ctx)}
"""


def agents_file_v2(ctx: _ctx.Context, name: str, protected_block: str, cmd: str = "anthill") -> str:
    """AGENTS.md: the same rules, for a tool that is not Claude Code.

    Claude gets the pick-up note, the save before compression and the push back
    from hooks; another tool gets none of them, so the file says what to run
    instead. The rules themselves are the same text, so they cannot disagree.
    """
    body = rules_file_v2(ctx, name, protected_block, cmd)
    head, rest = body.split("\n", 1)
    return (head + "\n\nEvery agent reads this file first, whatever tool it runs in. Claude Code "
            "reads the same rules from its own file and gets some steps done for it by hooks; "
            "here you do them yourself:\n\n"
            "- At the start of every session, and after your context is compressed: "
            f"`{cmd} resume`.\n"
            "- Driving a sprint end to end, nothing will send you back when you stop: "
            "check `anthill sprint show` yourself before you end a turn.\n"
            "- After a commit, bring the `anthill upkeep --open` list up to date yourself.\n"
            + rest)
