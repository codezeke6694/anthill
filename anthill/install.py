#!/usr/bin/env python3
"""Installation: the orchestrator takes control of a repository.

"Takes control" is a mechanical claim, not a tone. Three things happen:

  1. A constitution is written, owned by a human, that outranks every agent.
  2. Role definitions are written that bound what each agent may load and touch.
  3. The paths holding 1 and 2 are **denied to the coding agent** -- because an
     agent that can reach its own leash does not have one. This is the property
     that is easiest to get wrong and worst to get wrong.

Installation is transactional in the way that matters: it refuses to clobber an
existing install, and it names what it would have written instead of writing
half of it.

GREENFIELD vs BROWNFIELD
------------------------
The first move differs, so the installer decides rather than the operator:

  no source found   -> zone, then build. The blueprint has nothing to survey
                       yet, so the first sprint is authored cold.
  source found      -> survey first. `map build` is instant and free, and
                       `coverage` ranks the largest code with no intent
                       recorded -- that ranking IS the knowledge backlog.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from anthill import context as _ctx

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Paths that bind the agents. Rendered into the constitution, the deny rules,
# and the config -- and compared across all three, because a protected set that
# disagrees between surfaces protects nothing.
PROTECTED_PATHS = [
    "CONSTITUTION.md",
    ".anthill/roles/**",
    ".anthill/anthill.config.json",
    ".anthill/contracts/**",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    ".claude/**",
]

# The same locks for a v2 project: everything the owner alone changes is under
# `owner/`, and the board's contracts moved under `local/board/`.
PROTECTED_PATHS_V2 = [
    ".anthill/owner/**",
    ".anthill/local/board/contracts/**",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    ".claude/**",
]


def protected_paths(ctx: _ctx.Context) -> list[str]:
    return list(PROTECTED_PATHS_V2 if ctx.v2 else PROTECTED_PATHS)


# ---------------------------------------------------------------- local mode
#
# The owner, 30 Sep: Anthill should be something a person pulls into the
# project they are working on and uses, with none of it in that project's git
# -- their teammates are working on the project, not on Anthill. So when the
# tool itself sits inside the project (`git clone <anthill> anthill`), the
# install writes only files git never sees: the rules to CLAUDE.local.md, the
# guards and hooks to .claude/settings.local.json, and every Anthill path to
# the clone's private .git/info/exclude -- the project's own .gitignore is not
# touched. A tool installed from outside the project keeps the
# shared files, as before.

def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def is_local(ctx: _ctx.Context) -> bool:
    if (ctx.config.get("install") or {}).get("local") is not None:
        return bool(ctx.config["install"]["local"])
    try:
        tool_root().relative_to(ctx.root.resolve())
        return True
    except ValueError:
        return False


def rules_file(ctx: _ctx.Context) -> str:
    return "CLAUDE.local.md" if is_local(ctx) else "CLAUDE.md"


def _tracked(ctx: _ctx.Context, rel: str) -> bool:
    import subprocess
    r = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ctx.root,
                       capture_output=True, text=True)
    return r.returncode == 0


EXCLUDE_START, EXCLUDE_END = "# >>> anthill (local install) >>>", "# <<< anthill (local install) <<<"


def write_exclude(ctx: _ctx.Context, paths: list[str]) -> str | None:
    """Put Anthill's paths in this clone's own ignore list, and nowhere shared."""
    import subprocess
    r = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=ctx.root,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    p = Path(r.stdout.strip())
    if not p.is_absolute():
        p = ctx.root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if EXCLUDE_START in text:
        head, rest = text.split(EXCLUDE_START, 1)
        text = head.rstrip("\n") + ("\n" if head.strip() else "") + rest.split(EXCLUDE_END, 1)[-1].lstrip("\n")
    block = "\n".join([EXCLUDE_START, "# written by anthill install; teammates never see these", *paths, EXCLUDE_END])
    p.write_text((text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n", encoding="utf-8")
    return str(p)

STATE_SUBDIRS = ("contracts", "units", "audits", "sprints", "log",
                 "roles", "maps", "knowledge", "build")

# v2: four folders that travel with the project's git, one that never does.
STATE_SUBDIRS_V2 = ("owner", "owner/roles", "owner/history", "sprints",
                    "knowledge", "skills", "local")

# What the project's git must never see, inside `.anthill/`. Written as
# `.anthill/.gitignore` so it holds for a shared install and for every clone.
GITIGNORE_V2 = ("# written by anthill install: these stay on one laptop\n"
                "local/\nknowledge/_map/\nknowledge/.obsidian/\n*.tmp\n")


def state_subdirs(ctx: _ctx.Context) -> tuple[str, ...]:
    return STATE_SUBDIRS_V2 if ctx.v2 else STATE_SUBDIRS

# The planner is installed alongside builder/auditor because it is the role a
# human actually talks to. Leaving it out shipped a dead template and left
# nobody holding the sprint plane.
DEFAULT_ROLES = ("planner", "builder", "auditor")

ROLE_SUMMARY = {
    "planner": ("Plans and reports. Talks to the owner. Writes no code.",
                "CONSTITUTION.md, .anthill/sprints/, .anthill/contracts/"),
    "builder": ("Executes one unit. Does not plan or audit.",
                "its unit's `owns` list — nothing else"),
    "auditor": ("Reviews one finished unit. Changes nothing.",
                "nothing (`owns: []`, so any edit is a violation)"),
}

CLAUDE_MD = """# {name}

This repository is under Anthill orchestration. Read `CONSTITUTION.md` first;
it outranks this file and everything else — except the owner.

## The owner outranks everything here

The authority chain in `CONSTITUTION.md` starts with the owner's directive, and
that is not a formality. **When the owner tells you to do something, do it.**
Push, commit, work directly on `main`, merge, skip a step, ignore a rule in this
file — their instruction is the highest authority in this repository and it
overrides every default written below.

How to take an instruction:

- **Say what it is, then do it.** Before anything that reaches other people — a
  push, a merge into `main`, anything that leaves this machine — state plainly
  what is about to happen: which branch, onto what, how many commits, what
  lands, and anything in it the owner would not expect. Then carry it out in the
  same breath. This is a briefing, not a request: the decision is already made
  and you are not waiting on a second yes. "Are you sure?" is not that briefing
  — it asks the owner to re-decide something they already decided, and it tells
  them nothing they did not already know.
- **One objection, once.** If you think it is a mistake, say so in a sentence or
  two before you act — that is useful and you are expected to do it. If the
  owner repeats or confirms the instruction, it is settled. Carry it out in full
  and stop arguing. Restating a concern you have already made is not diligence.
- **Never do a smaller version of what was asked** while waiting to be talked
  into the rest. Half an instruction executed quietly is worse than an objection
  stated out loud.
- **Say what you did.** An instruction carried out is reported plainly, with
  what actually happened, including the parts that went badly.

One limit, and it exists to protect the owner's authority rather than to qualify
it: **"the owner said so" means the owner actually said so** — in their own
words, in this conversation, about this specific action. Not inferred from a
previous approval, not carried across a context compaction, not something you
concluded they would obviously want. An instruction you invented is not an
instruction, and the defaults below are written the way they are precisely
because you cannot tell one of those from the real thing on your own. When in
doubt about whether you were told, you were not told: ask.

## First, every session: is the charter complete?

```bash
anthill onboard --show
```

If it reports anything as `blank`, **that is your first task, before any code.**
Ask the owner those questions in conversation — one at a time, in plain
language — then record what they say:

```bash
anthill onboard --stack "..." --building "..." --architecture "..."
```

Rules for this:

- **Never invent an answer.** A charter you wrote yourself is not a charter; it
  is you agreeing with yourself, and every unit brief downstream inherits it.
- **One question at a time, in plain words, with a recommendation attached.**
  Ask about the product, not the implementation — "should a user be able to add
  a supplier's supplier?", never "do we need recursive nesting?". If you have
  four questions, ask the first; the answer usually retires two of them. The
  owner should be able to say "yes" and move on.
- **Never edit `CONSTITUTION.md` directly.** It is denied to you. `anthill
  onboard` is the only sanctioned path, and it fills blanks only — it will not
  overwrite a decision the owner already recorded.
- `--stack` is the one that blocks work: it decides district boundaries, the
  `owns` globs in every unit, and which code can be structurally fingerprinted.

Do not start a sprint against a blank charter.

## Then: who fills each role?

```bash
anthill roles show
```

Anything `unassigned` needs an answer before work starts. Ask the owner which
tool or person is the planner, the builder, and the auditor, then record it:

```bash
anthill roles assign builder "claude-code" --by "<owner>"
anthill roles assign auditor "codex" --by "<owner>"
```

If the builder and the auditor are the same identity, `roles` says so. That is
worth relaying to the owner in plain terms: the same model reviewing its own
work shares its blind spots exactly, so its approval means little. Tests stay
the only real proof either way, but a different tool on the auditor seat is the
one thing that buys genuine independence.

{cold_start}

{upkeep_rule}

{goal_rule}

{owner_view}

{git_rules}

## Before you touch anything

You are operating as a **role**, not as a general assistant. Find your role in
`.anthill/roles/` and load only what it tells you to load. If you were not given
a unit, you have no boundary, and you should be planning rather than editing.

## What you may not do

These paths are denied to you and enforced outside your control. Do not attempt
to edit them, and do not propose edits to them as a workaround:

{protected}

## Skills

Reusable instruction lives in `.anthill/skills/`, indexed at
`.anthill/skills/INDEX.md`.

```bash
anthill skill list --always-on     # what to load every session
anthill skill list --query audit   # find one
anthill skill get token-discipline # read it
```

Load classes exist so you do **not** load everything:

| Class | When |
|---|---|
| `bootstrap` | every session |
| `phase-scoped` | only during its phase (idea / planning / execution) |
| `conditional` | only when triggered — an audit, an escalation |
| `reference` | installed, never auto-loaded; look it up when you need it |

Loading a `reference` skill you did not need is the same mistake as reading a
file outside your unit: context you did not need is context that made you worse.

## How work closes

You do not decide that work is complete. A gate does. An agent cannot assert
completion — that is the load-bearing rule of this system, and the sequence that
implements it is below.

## Doing a piece of work, start to finish

**Every session, after `anthill where`, find out whether a board unit is
already yours.** `where` comes first because it holds all the work, including
work the board never saw; the board holds only units loaded onto it. Context
gets compacted and sessions restart; neither forgets.

```bash
anthill work status --repo .
```

- It names a unit as `in_flight` → that is likely yours. Read
  `.anthill/build/work/*/briefs/<unit>.md` — your own instructions, written to a
  file for exactly this reason — before touching any code.
- It says `board_is_behind` → the sprint was changed since the board was seeded.
  Run `anthill work load --repo .` to pick up the new units. Without this,
  `work next` reports "drained" while the sprint sits there with work on it.
- Nothing ready and nothing behind → there is no work for you. Say so rather
  than inventing some.

Then:

```bash
anthill work next --repo .  --worker <you>   # claims one, prints the brief
#   build, inside the unit's `owns` paths and nowhere else
anthill work gate --repo .  --unit <id>      # ownership, tests, map, audit
anthill work done --repo .  --unit <id>      # refused unless the gate passed
```

### Read the gate's exit code; it tells you what to do next

| Code | Meaning | What you do |
|---|---|---|
| `0` | passed | `work done` |
| `1` | a test failed, or an audit refuses the work | fix the work |
| `3` | nobody has reviewed this state yet | **not your fault, and it costs you no attempt.** An auditor reviews it, then re-gate |
| `64` | you wrote outside `owns` — the file is named | revert that file; it belongs to another unit |
| `65` | you called `done` without a passing gate | run the gate |
| `66` | gated, but will not merge: two units claim one file | a contract bug. Escalate; do not resolve it yourself |

### When you are stuck

```bash
anthill work escalate --repo . --unit <id> --reason "<what stopped you>"
```

Then **stop**. Do not guess, do not widen your boundary to fix something
adjacent, and do not edit anything under `.anthill/build/work/` by hand — state
edited directly is indistinguishable from tampering and records nobody's
decision. If a unit was escalated and the cause is since fixed, the sanctioned
way back is `anthill work reopen --repo . --unit <id> --reason "..." --by "..."`.

If a command seems to be missing or a step does not exist, say so and ask. That
is a real answer and a useful one; inventing a workaround is neither.

## Keeping the blueprint current

{blueprint_rule}

Update your knowledge page as part of the same step: re-pin `verified_against`,
correct any rule your change made untrue, add a History line.

## Escalation

{escalation_rule}

## The audit

{audit_note}
"""


def update(ctx: _ctx.Context) -> dict[str, Any]:
    """Pull the newest Anthill into its folder, then re-render this project's rules.

    The install is re-run by the *new* code, in its own process: the running
    one has the old modules loaded. The owner's settings, charter and notes
    are kept -- a re-install carries them over.
    """
    import subprocess
    root = tool_root()
    r = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"], capture_output=True, text=True)
    if r.returncode != 0:
        return {"updated": False, "why": (r.stderr or r.stdout).strip()[-400:]}
    name = (ctx.config.get("project") or {}).get("name") or ctx.root.name
    re_run = subprocess.run([str(root / "bin" / "anthill"), "install", "--force", "--name", name],
                            cwd=ctx.root, capture_output=True, text=True)
    return {"updated": re_run.returncode == 0, "pulled": r.stdout.strip()[-400:],
            "install": (re_run.stdout + re_run.stderr).strip()[-600:]}


def hook_invocation(ctx: _ctx.Context) -> str:
    """The command Claude's hooks run. A hook's working directory follows the
    chat -- into a subfolder, into a worktree -- so a relative path breaks;
    $CLAUDE_PROJECT_DIR stays at the project root."""
    cmd = invocation(ctx)
    return "$CLAUDE_PROJECT_DIR/" + cmd[2:] if cmd.startswith("./") else cmd


def invocation(ctx: _ctx.Context) -> str:
    """How to run this tool from the project root.

    A fresh session reads CLAUDE.md and runs what it says. `anthill ...` only
    works if someone has already put `bin/` on PATH, which nobody has in a new
    shell -- so a vendored install must document its own relative path or every
    documented command fails with `command not found` on first contact.
    """
    # parents[1] is the directory holding `bin/` and the package.
    # parents[2] is the project, which is what this is being compared against.
    tool_root = Path(__file__).resolve().parents[1]
    try:
        rel = tool_root.relative_to(ctx.root.resolve())
    except ValueError:
        # Assuming `anthill` is on PATH is how a generated hook came out as
        # `exec anthill guard` and died "not found" -- while the commit
        # succeeded, so the guard looked installed and enforced nothing.
        return str(tool_root / "bin" / "anthill")
    return f"./{rel.as_posix()}/bin/anthill"


def render_values(ctx: _ctx.Context, name: str = "", description: str = "",
                  stack: str = "") -> dict[str, str]:
    """Every `{{PLACEHOLDER}}` the templates know, from one place.

    `install` and `control` each built this dict by hand and drifted; a value
    added to one and not the other made `control` report every role file as
    EDITED forever. The rule-shaped values come from `rules`, so the role files
    say what the config does.
    """
    from anthill import rules
    return {
        "PROJECT_NAME": name or (ctx.config.get("project") or {}).get("name") or ctx.root.name,
        "PROJECT_DESCRIPTION": description,
        "STACK": stack,
        "WHAT_WE_ARE_BUILDING": "",
        "ARCHITECTURE": "",
        "KEY_DECISIONS": "",
        "CODING_STANDARDS": "",
        "MAP_BUILD_RULE": rules.map_build_rule(ctx),
        "ESCALATION_RULE": rules.escalation_rule(ctx),
        "GIT_RULES": rules.git_rules(ctx),
        "COLD_START": rules.cold_start_rule(ctx),
        "UPKEEP_RULE": rules.upkeep_rule(ctx),
        "GOAL_RULE": rules.goal_rule(ctx),
        "OWNER_VIEW": rules.owner_view_rule(ctx),
        "AUDIT_NOTE": rules.audit_note(ctx),
        "MAX_FILES": "3",
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "project"


def _render(template: Path, values: dict[str, str], ctx: _ctx.Context | None = None) -> str:
    text = template.read_text(encoding="utf-8")
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    # Any placeholder left unfilled becomes an honest TODO rather than shipping
    # `{{STACK}}` into a document a human is expected to trust.
    text = re.sub(r"\{\{([A-Z_]+)\}\}",
                  lambda m: f"_TODO: {m.group(1).lower().replace('_', ' ')}_", text)
    # The templates name the old layout's paths; a v2 project reads its own.
    return _ctx.layout_text(ctx, text) if ctx is not None else text


def deny_rules(paths: list[str]) -> list[str]:
    """Claude Code deny entries for every protected path, both write verbs."""
    out: list[str] = []
    for p in paths:
        out.append(f"Edit({p})")
        out.append(f"Write({p})")
    return out


HOOK_MARKER = "anthill-pre-commit-guard"

HOOK = """#!/usr/bin/env bash
# anthill-pre-commit-guard — installed by `anthill install`. Refuses a commit of
# product source that no currently claimed unit owns, so the board is the way
# into the tree rather than one option among two.
ANTHILL="{cmd}"
if ! command -v "$ANTHILL" >/dev/null 2>&1 && [ ! -x "$ANTHILL" ]; then
  # Fail closed. A guard that cannot run must not pass silently -- that is the
  # state where it looks installed and enforces nothing.
  echo "anthill: pre-commit guard cannot run: $ANTHILL not found." >&2
  echo "  Re-run \\`anthill install --force\\` to repair the hook," >&2
  echo "  or \\`git commit --no-verify\\` to bypass it deliberately." >&2
  exit 1
fi
"$ANTHILL" guard || exit 1
"""

PUSH_HOOK_MARKER = "anthill-pre-push-guard"

PUSH_HOOK = """#!/usr/bin/env bash
# anthill-pre-push-guard — installed by `anthill install`. Refuses a push to a
# branch the owner keeps. Reads the refs being pushed on stdin, so
# `git push origin HEAD:main` is caught too.
ANTHILL="{cmd}"
if ! command -v "$ANTHILL" >/dev/null 2>&1 && [ ! -x "$ANTHILL" ]; then
  echo "anthill: pre-push guard cannot run: $ANTHILL not found." >&2
  exit 1
fi
"$ANTHILL" guard --push || exit 1
"""

POST_HOOK_MARKER = "anthill-post-commit-blueprint"

POST_HOOK = """#!/usr/bin/env bash
# anthill-post-commit-blueprint — installed by `anthill install`.
# Redraws the blueprint after every commit. Hooked to the commit rather than to
# `work done` on purpose: that fires a handful of times per sprint and only if
# the board is used at all, and a blueprint that updates only when someone
# remembers the orchestrator is a blueprint that is usually wrong. ~0.25s.
# post-commit cannot abort anything, so failure here never costs a commit.
# Then says what the commit left undone -- glossary, knowledge pages, tests --
# and records it, so the list survives into the next session. It is printed to
# the terminal that committed, which is where the agent doing the work sees it.
# Every one of these writes its result to the trail (.anthill/trail.jsonl), so
# output thrown away here is still not a failure nobody sees; the full notes
# check runs in the background for the same reason, ~1.5s the commit never waits on.
ANTHILL="{cmd}"
if command -v "$ANTHILL" >/dev/null 2>&1 || [ -x "$ANTHILL" ]; then
  "$ANTHILL" trail commit >/dev/null 2>&1 || true
  "$ANTHILL" map build >/dev/null 2>&1 || true
  "$ANTHILL" upkeep --record 2>/dev/null | grep -v "nothing left undone" || true
  ( "$ANTHILL" blueprint --all >/dev/null 2>&1 & ) || true
fi
exit 0
"""


# Claude's own hooks, for what git cannot see: a chat starting, the owner
# speaking, and a chat's memory about to be compressed. Each calls anthill and
# anthill writes the trail; a hook that fails can never stop the chat.
CLAUDE_HOOKS = {
    "SessionStart": "resume --hook",
    "UserPromptSubmit": "prompt --hook",
    "PreCompact": "checkpoint --hook",
    "Stop": "goal --hook",
}


def merge_claude_hooks(settings: dict[str, Any], cmd: str) -> list[str]:
    """Add Anthill's hooks to Claude's settings, beside any the developer has."""
    hooks = settings.setdefault("hooks", {})
    added = []
    for event, verb in CLAUDE_HOOKS.items():
        groups = hooks.setdefault(event, [])
        line = f'"{cmd}" {verb}'
        if any(verb in h.get("command", "") and "anthill" in h.get("command", "")
               for g in groups for h in (g.get("hooks") or [])):
            continue
        groups.append({"hooks": [{"type": "command", "command": line, "timeout": 20}]})
        added.append(event)
    return added


def _write_hook(ctx: _ctx.Context, name: str, body: str, marker: str,
                advice: str) -> dict[str, Any]:
    """Write one git hook, never over something that is not ours."""
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ctx.root,
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {"installed": False, "reason": "git not available"}
    if r.returncode != 0:
        return {"installed": False, "reason": "not a git repository"}
    gitdir = Path(r.stdout.strip())
    if not gitdir.is_absolute():
        gitdir = ctx.root / gitdir
    hook = gitdir / "hooks" / name
    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="ignore")
        if marker not in existing:
            return {"installed": False, "path": str(hook),
                    "reason": f"a {name} hook already exists and was left alone",
                    "add_this_line": advice}
        if existing == body:
            return {"installed": True, "path": str(hook), "already": True}
        # Ours, but out of date. An earlier version pointed at a binary that did
        # not resolve and let every commit through; refusing to repair our own
        # hook left that in place.
        hook.write_text(body, encoding="utf-8")
        hook.chmod(0o755)
        return {"installed": True, "path": str(hook), "repaired": True}
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(body, encoding="utf-8")
    hook.chmod(0o755)
    return {"installed": True, "path": str(hook)}


KEEPER_AGENT = """---
name: anthill-keeper
description: Brings the anthill up to date after a commit -- the glossary, the knowledge pages, and a note of any code no test covers -- so the agent doing the work never stops for it. Use it in the background whenever `anthill upkeep` lists anything.
tools: Bash, Read, Grep, Glob, Edit, Write
model: sonnet
---

You keep the anthill's records true after someone else changed the code. You
do not change the code, and you do not commit.

## Where you may write

Only under `{knowledge}/`. Nothing else in the repository -- not source, not
tests, not CLAUDE.md, not `.claude/`. The agent that asked you is working in the
code right now; touching it would collide with them.

## What to do

1. `{cmd} upkeep --open --json` -- the list you were sent to clear.
2. For each item:
   - **glossary, a line names code that is gone**: find what the code calls it
     now (`{cmd} start "<the owner's words on that line>"`, then read), and fix
     the words after the arrow. Never change the owner's words before it.
   - **glossary, a screen has no line**: add one under a heading
     `## Added by the keeper -- not yet confirmed`, in the form
     `- **<what a person would call it>** → <ComponentName>, <file stem>`.
   - **knowledge, a rule cites a symbol that moved**: read the rule, then the
     live code at the citation. If the rule is still true, fix only the
     citation. If the code now does something else, rewrite the rule to say
     what it does and add a History line saying what changed and when.
   - **tests, changed code no test imports**: do not write the test. Say in one
     line what a test for it would need to check.
   - **work, a page is behind its branch**: read `git log <true_at>..<branch>`
     and the diffs, then bring the page's What, Where, Next, Waiting on the
     owner and History up to date. Cite every file your statements depend on
     -- a claim about what `runner.py` does cites `runner.py`, not only the
     file the claim is about, or the page goes false the day runner changes.
     Set `true_at` to the branch's latest commit and `updated` to today.
     `state` says what the **next step** waits on: `waiting-on-owner` only
     when the next step cannot happen without the owner; `in-progress` when
     it can, even if later steps need the owner; `paused` when it waits on
     other work. A cold agent reads the state first.
   - **Waiting on the owner**, on any work page you write: one bullet per real
     question, in the form the owner's page turns into buttons --
     `- **<the question, one line>** Why: <one line> Recommend: <your pick> Options: <A> / <B>`.
     Never put there a pointer to another page, a status ("now built"), or a
     question the owner has already answered or decided: move those out.
   - **work, a branch no page describes**: write `{knowledge}/work/<id>.md`
     from its log, in the same shape as the others (What, Where, How,
     Waiting on the owner, Traps, History), `state: in-progress`.
   - **something the agent learned** (sent to you in words, not on the list):
     a word the owner uses goes in the glossary under the keeper heading; why
     a piece of code is the way it is goes on the knowledge page for that
     area as a rule citing the code (`(sg: path::name)`), under a heading
     `## Added by the keeper -- not yet confirmed`. If no page covers the
     area, say so in your report rather than creating one.
3. `{cmd} upkeep --record` -- items you fixed clear themselves.
   Every time you change a statement that was already on a page because it
   was wrong -- not because the work moved on -- record it:
   `{cmd} correction --page <page id> --was "<old>" --now "<new>" --why "<how you know>"`.
   The owner's page counts these; a page that keeps needing them is a page
   agents should not trust.
4. Report in at most five lines: what you fixed, what is still open, and the
   one-line test suggestions.

## Before you write a fact

A cold agent acts on what you write without checking it. Three wrong
statements on one page in one day each cost a chat time: a recommendation
the owner was never given, a cause the code did not show, a command missing
the step that made it run.

- **What code does**: read the code in this run, and cite the exact name,
  `(sg: path/to/file.py::name)`. Never a whole file -- `(sg: run.sh)` cannot
  be checked, and one such citation once stopped the check for every page.
- **What someone recommended, decided or asked**: quote their words from what
  you were handed, and say who. Never restate a recommendation in your own
  words; if you were not handed it, do not write it.
- **Why something happens**: only as a fact if the code, a test or a measured
  replay shows it. Otherwise write "suspected:" in front of it.
- **A command in How**: include every step it needs to run -- settings loaded,
  a file that must exist, the directory -- as the agent actually ran it. If
  you have not seen it run, add "(not run by the keeper)".

## Never

- Change a page under `{knowledge}/decisions/`. Those are the owner's words;
  if the code now contradicts one, say so in your report.
- Fill `intent_attested_by` or `intent_attested_on`. Those are the owner's
  signature; a page you edited stays unconfirmed until they look.
- Change the owner's words on the left of a glossary arrow.
- Edit, stage or commit anything outside `{knowledge}/`.
- Edit anything under `{knowledge}/_map/`. It is a picture of the map, redrawn
  after every commit; what you would change there belongs on a work page.
"""


def render_keeper(ctx: _ctx.Context) -> str:
    return KEEPER_AGENT.format(cmd=invocation(ctx),
                               knowledge=str(ctx.knowledge_dir.relative_to(ctx.root)))


def install_keeper(ctx: _ctx.Context) -> dict[str, Any]:
    """Write the upkeep helper's definition where Claude Code loads agents from."""
    path = ctx.root / ".claude" / "agents" / "anthill-keeper.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = render_keeper(ctx)
    already = path.exists() and path.read_text(encoding="utf-8") == body
    if not already:
        path.write_text(body, encoding="utf-8")
    return {"installed": True, "path": str(path), "already": already}


def install_hook(ctx: _ctx.Context) -> dict[str, Any]:
    cmd = invocation(ctx)
    return _write_hook(ctx, "pre-commit", HOOK.format(cmd=cmd), HOOK_MARKER,
                       f"{cmd} guard || exit 1")


def install_push_hook(ctx: _ctx.Context) -> dict[str, Any]:
    cmd = invocation(ctx)
    return _write_hook(ctx, "pre-push", PUSH_HOOK.format(cmd=cmd),
                       PUSH_HOOK_MARKER, f"{cmd} guard --push || exit 1")


def install_post_hook(ctx: _ctx.Context) -> dict[str, Any]:
    cmd = invocation(ctx)
    return _write_hook(ctx, "post-commit", POST_HOOK.format(cmd=cmd),
                       POST_HOOK_MARKER,
                       f"{cmd} map build >/dev/null 2>&1 || true")


def render_claude_md(ctx: _ctx.Context, name: str, protected_block: str) -> str:
    """The exact text install writes. Shared with `control` on purpose.

    These were two copies of the same construction and drifted the moment the
    vendored-invocation footer was added here and not there -- so `control`
    reported CLAUDE.md as EDITED on every vendored install, permanently.

    The path is stated once, at the top, rather than substituted into every
    example. Substituting turned every command in the work sequence into a
    60-character absolute path and made the section unreadable; one export the
    agent runs first is both shorter and how a person would actually work.
    """
    from anthill import rules
    cmd = invocation(ctx)
    text = CLAUDE_MD.format(name=name, protected=protected_block,
                            git_rules=rules.git_rules(ctx),
                            cold_start=rules.cold_start_rule(ctx),
                            upkeep_rule=rules.upkeep_rule(ctx),
                            goal_rule=rules.goal_rule(ctx),
                            owner_view=rules.owner_view_rule(ctx),
                            blueprint_rule=rules.map_build_rule(ctx),
                            escalation_rule=rules.escalation_rule(ctx),
                            audit_note=rules.audit_note(ctx))
    text = _ctx.layout_text(ctx, text)
    if cmd == "anthill":
        return text
    bindir = cmd.rsplit("/bin/", 1)[0] + "/bin"
    if bindir.startswith("./"):
        # Inside the project: from the project root, wherever the shell is --
        # a relative PATH entry breaks the moment an agent cds into a subfolder.
        where = (f"Anthill is in `{bindir[2:-4]}/` inside this project, kept out of git "
                 f"(`{cmd}` from the project root).")
        bindir = '$(git rev-parse --show-toplevel)/' + bindir[2:]
    else:
        where = "Anthill lives outside this repository."
    header = (f"## Run this first, every session\n\n"
              f"{where} Put it on your PATH "
              f"before anything else, or every command below fails with "
              f"`command not found`:\n\n"
              f"```bash\nexport PATH=\"{bindir}:$PATH\"\n```\n\n"
              f"Every `anthill ...` in this file assumes you have done that.\n\n")
    # after the H1 and its opening lines, before the first section
    marker = "## First, every session: is the charter complete?"
    return text.replace(marker, header + marker, 1) if marker in text else header + text


def plan(ctx: _ctx.Context, project_name: str = "",
         exclude: list[str] | None = None) -> dict[str, Any]:
    """What an install would do, without doing it."""
    try:
        inside = tool_root().relative_to(ctx.root.resolve()).parts[0]
        exclude = sorted(set(exclude or []) | {inside})
    except (ValueError, IndexError):
        pass
    if exclude:
        # Applied before discovery, not after: a vendored copy of this tool sits
        # in the project it manages, and left in the source set the blueprint
        # ends up navigating the navigator instead of the product.
        base = ctx.config.setdefault("source", {})
        base["exclude_parts"] = sorted(set(base.get("exclude_parts") or []) | set(exclude))
        base["include_dirs"] = []
        base["include_toplevel"] = []
    include, toplevel, _ = ctx.source_roots()
    brownfield = bool(include or toplevel)
    name = project_name or ctx.root.name
    return {
        "project": name,
        "root": str(ctx.root),
        "root_found_via": ctx.origin,
        "already_installed": ctx.installed,
        "mode": "brownfield" if brownfield else "greenfield",
        "discovered_source_dirs": include,
        "discovered_toplevel": toplevel,
        "will_create": [str(ctx.state / d) for d in state_subdirs(ctx)],
        "will_write": [
            str(ctx.config_path),
            str(ctx.constitution),
            *[str(ctx.roles_dir / f"{r}.md") for r in ctx.config.get("roles", [])],
            str(ctx.root / rules_file(ctx)),
            str(ctx.root / ".claude" / ("settings.local.json" if is_local(ctx) else "settings.json")),
        ],
        "local": is_local(ctx),
        "protected_paths": protected_paths(ctx),
        "first_move": (
            "the install has already surveyed the code (see `survey`): the map "
            "is drawn, and the largest code no page explains is the keeper's "
            "first list. `anthill survey` redraws and re-reports at any time."
            if brownfield else
            "zone first: name the districts and their boundaries, then author a "
            "cold contract. There is nothing to survey yet."
        ),
    }


def brownfield_now(ctx: _ctx.Context) -> bool:
    """Is there code to survey? A new, empty project has nothing to map."""
    include, toplevel, _ = ctx.source_roots()
    return bool(include or toplevel)


def survey(ctx: _ctx.Context, exam_limit: int = 150) -> dict[str, Any]:
    """What Anthill knows about the project the moment it is installed.

    An install used to end by *suggesting* a survey. Until somebody ran it, or
    until the first commit fired the hook, there was no map: an agent arriving
    in between got a blank orient and a start that found nothing. Measured on a
    fresh install, where the map had to be built by hand before anything else
    worked. So the install does it, and says what it found:

      map        every chamber, pathway and test
      exam       how often a past task is sent to the right file, from day one
      backlog    the largest code no page explains -- the keeper's first list
      work       branches with recent work no page describes yet

    Each step runs as its own process, because the map modules bind the
    project root when they are imported.
    """
    import subprocess
    tool = str(Path(__file__).resolve().parents[1] / "bin" / "anthill")

    def run(*args: str, timeout: int = 180) -> tuple[int, str]:
        try:
            r = subprocess.run([tool, *args], cwd=ctx.root, capture_output=True,
                               text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, str(exc)
        return r.returncode, r.stdout

    out: dict[str, Any] = {}
    code, text = run("map", "build")
    m = re.search(r"--\s*(\d+) nodes", text)
    out["map"] = {"nodes": int(m.group(1)) if m else 0} if code == 0 else {"error": text[-300:]}
    code, text = run("eval-map", "--limit", str(exam_limit))
    try:
        exam = json.loads(text) if code == 0 else {}
        out["exam"] = {k: exam[k] for k in ("questions", "top1_pct", "top3_pct", "one_step_pct")}
    except (ValueError, KeyError):
        out["exam"] = {"note": "no history to score against yet"}
    try:
        from anthill import integrate
        gap = integrate.report_gap(ctx)
        out["backlog"] = gap.get("largest_unexplained") or []
    except Exception:
        out["backlog"] = []
    code, text = run("where", "--json")
    try:
        w = json.loads(text)
        out["work"] = [u["branch"] for u in w.get("untracked") or []]
    except ValueError:
        out["work"] = []
    return out


def render_survey(sv: dict[str, Any]) -> str:
    L = ["What Anthill knows already:"]
    mp = sv.get("map") or {}
    L.append(f"  map      {mp.get('nodes', 0)} places in the code, with their pathways and tests"
             if "nodes" in mp else f"  map      not built: {mp.get('error', '')}")
    ex = sv.get("exam") or {}
    if "top1_pct" in ex:
        L.append(f"  finding  a past task goes to the right file first time {ex['top1_pct']}%, "
                 f"top three {ex['top3_pct']}% ({ex['questions']} past commits)")
    else:
        L.append("  finding  no history yet to measure against")
    if sv.get("backlog"):
        L.append("  explain  the largest code no page explains yet: " + "; ".join(sv["backlog"][:3]))
    if sv.get("work"):
        L.append("  work     recent work with no page yet: " + ", ".join(sv["work"]))
    L.append("Next: `anthill onboard` for the charter, then hand the lists above to the "
             "anthill-keeper in the first chat.")
    L.append("Watch it on a page: `anthill ui start --detach` (add it to your start script "
             "with `--with-parent $$` so it stops with the app).")
    return "\n".join(L)


def install(ctx: _ctx.Context, project_name: str = "", stack: str = "",
            description: str = "", areas: list[str] | None = None,
            force: bool = False, write: bool = True,
            exclude: list[str] | None = None, run_survey: bool = True) -> dict[str, Any]:
    """Scaffold control. Refuses to clobber unless forced."""
    result = plan(ctx, project_name, exclude)
    if ctx.installed and not force:
        result["created"] = False
        result["refused"] = (f"{ctx.config_path} already exists. Re-running would "
                             "overwrite a constitution and role set a human may "
                             "have edited. Pass --force only if that is intended.")
        return result

    name = project_name or ctx.root.name
    include, toplevel, exclude_parts = ctx.source_roots()
    roles = list(ctx.config.get("roles") or DEFAULT_ROLES)

    cfg = json.loads(json.dumps(_ctx.DEFAULT_CONFIG))   # deep copy
    cfg["project"] = {"name": name, "slug": _slug(name)}
    cfg["source"]["include_dirs"] = include
    cfg["source"]["include_toplevel"] = toplevel
    cfg["source"]["exclude_parts"] = sorted(exclude_parts)
    cfg["knowledge"]["areas"] = list(areas or [])
    cfg["roles"] = roles
    cfg["protected_paths"] = protected_paths(ctx)
    cfg["installed_mode"] = result["mode"]
    local = is_local(ctx)
    cfg["install"] = {"local": local,
                      "tool": (str(tool_root().relative_to(ctx.root.resolve())) if local else str(tool_root()))}

    # Settings the owner chose, carried across a re-install. `--force` is the
    # sanctioned way to re-render CLAUDE.md and AGENTS.md after this tool
    # changes, and it started from DEFAULT_CONFIG -- so re-rendering a doc also
    # silently reset every execution decision the owner had made: which branches
    # are protected, whether a push needs them, where the venv is, whether units
    # run isolated. The one command an owner is told to run to stay current was
    # the command that undid their configuration.
    for block in ("execution", "audit", "blueprint", "gates"):
        existing = ctx.config.get(block)
        if isinstance(existing, dict) and existing:
            cfg[block] = {**cfg.get(block, {}), **existing}

    written: list[str] = []
    if not write:
        result["created"] = False
        result["dry_run"] = True
        return result

    for sub in state_subdirs(ctx):
        (ctx.state / sub).mkdir(parents=True, exist_ok=True)

    ctx.config = cfg
    ctx.save_config()
    written.append(str(ctx.config_path))

    values = render_values(ctx, name, description, stack)

    # The constitution is human-owned, so an existing one is never overwritten
    # even under --force: that is exactly the file a human will have edited.
    if not ctx.constitution.exists():
        ctx.constitution.write_text(
            _render(TEMPLATE_DIR / "CONSTITUTION.md.tmpl", values, ctx), encoding="utf-8")
        written.append(str(ctx.constitution))
    else:
        result["kept_existing"] = [str(ctx.constitution)]

    for role in roles:
        tmpl = TEMPLATE_DIR / "roles" / f"{role}.md.tmpl"
        if not tmpl.exists():
            continue
        dest = ctx.roles_dir / f"{role}.md"
        dest.write_text(_render(tmpl, values, ctx), encoding="utf-8")
        written.append(str(dest))

    protected_block = "\n".join(f"- `{p}`" for p in protected_paths(ctx))
    cmd = invocation(ctx)

    # AGENTS.md was listed in PROTECTED_PATHS and rendered into the deny rules
    # from the start, but nothing created it -- so the file every non-Claude
    # agent reads first did not exist, and the deny rule guarded nothing.
    from anthill import roles as roles_mod
    agents_values = dict(values, ROLE_TABLE=roles_mod.table(ctx),
                         PROTECTED_BLOCK=protected_block, ANTHILL=cmd)
    # In local mode a project's own AGENTS.md -- one git already tracks -- is
    # theirs, and left alone; Codex then reads theirs, and the install says so.
    if local and _tracked(ctx, "AGENTS.md"):
        result["agents_md_kept"] = ("AGENTS.md belongs to the project, so Anthill left it alone; "
                                    "tools that read only AGENTS.md will not see Anthill's rules")
    else:
        (ctx.root / "AGENTS.md").write_text(
            _render(TEMPLATE_DIR / "AGENTS.md.tmpl", agents_values, ctx), encoding="utf-8")
        written.append(str(ctx.root / "AGENTS.md"))
    rules = ctx.root / rules_file(ctx)
    rules.write_text(render_claude_md(ctx, name, protected_block), encoding="utf-8")
    written.append(str(rules))

    # The deny rules. Merged into an existing settings.json rather than
    # replacing it -- clobbering a developer's own permissions to install a
    # guardrail would be its own kind of overreach. In local mode they go in
    # the per-person file with the hooks, so nothing shared changes.
    settings_path = ctx.root / ".claude" / ("settings.local.json" if local else "settings.json")
    settings: dict[str, Any] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            backup = settings_path.with_suffix(".json.anthill-backup")
            shutil.copy2(settings_path, backup)
            result["backed_up"] = str(backup)
            settings = {}
    perms = settings.setdefault("permissions", {})
    deny = perms.setdefault("deny", [])
    added = [r for r in deny_rules(protected_paths(ctx)) if r not in deny]
    deny.extend(added)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    written.append(str(settings_path))

    # The hooks go in the per-person file, not the shared one: they name where
    # Anthill lives on this laptop, and settings.json is committed -- a
    # teammate who cloned it would get a hook pointing at nothing.
    local_path = ctx.root / ".claude" / "settings.local.json"
    personal: dict[str, Any] = {}
    if local_path.exists():
        try:
            personal = json.loads(local_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            shutil.copy2(local_path, local_path.with_suffix(".json.anthill-backup"))
            personal = {}
    result["claude_hooks"] = merge_claude_hooks(personal, hook_invocation(ctx))
    local_path.write_text(json.dumps(personal, indent=2) + "\n", encoding="utf-8")
    written.append(str(local_path))

    # A knowledge dir with no config is a knowledge base you cannot author into,
    # so `kb init` is part of installation rather than a step to remember.
    try:
        from anthill.knowledge import scaffold
        kb = scaffold.init(
            ctx.knowledge_dir,
            project=name,
            source=".",
            areas=list(areas or []) or ["general"],
            registries=[(_slug(name).upper().replace("-", "_")[:12] or "PROJ")],
            prefix=_slug(name))
        result["knowledge_base"] = kb.get("created", False)
        if kb.get("reason"):
            result["knowledge_note"] = kb["reason"]
    except Exception as exc:                          # pragma: no cover
        result["knowledge_note"] = f"knowledge scaffold skipped: {exc}"

    # If a skills library is already installed, keep its index current: a stale
    # index is worse than none, because an agent trusts it.
    try:
        from anthill import skills as skills_mod
        if skills_mod.load_all(ctx):
            idx = skills_mod.build_index(ctx)
            result["skills_indexed"] = idx["indexed"]
    except Exception as exc:                          # pragma: no cover
        result["skills_note"] = f"skill index skipped: {exc}"

    result["pre_commit_hook"] = install_hook(ctx)
    result["pre_push_hook"] = install_push_hook(ctx)
    result["post_commit_hook"] = install_post_hook(ctx)
    result["keeper_agent"] = install_keeper(ctx)

    # Stamped after everything above is on disk, so the fingerprints cover what
    # is actually there. Without this, `control` compares against whatever was
    # recorded at some earlier install and calls every re-render pending.
    try:
        from anthill import control as control_mod
        result["control_fingerprints"] = control_mod.record(ctx)["recorded"]
    except Exception as exc:                          # pragma: no cover
        result["control_note"] = f"fingerprints not recorded: {exc}"

    gitignore = ctx.state / ".gitignore"
    if ctx.v2:
        if not gitignore.exists() or gitignore.read_text(encoding="utf-8") != GITIGNORE_V2:
            gitignore.write_text(GITIGNORE_V2, encoding="utf-8")
            written.append(str(gitignore))
    elif not gitignore.exists():
        gitignore.write_text("build/\nunits/\n", encoding="utf-8")
        written.append(str(gitignore))

    if local:
        tool = cfg["install"]["tool"]
        # v2: the shared folders -- owner/, sprints/, knowledge/, skills/ --
        # are the project's to commit, so only what stays on this laptop is
        # hidden here. v1 hid the whole state directory.
        state_paths = ["/.anthill/local/", "/.anthill/knowledge/_map/",
                       "/.anthill/knowledge/.obsidian/"] if ctx.v2 else ["/.anthill/"]
        paths = [f"/{tool}/", *state_paths, "/CLAUDE.local.md", "/.claude/settings.local.json",
                 "/.claude/agents/anthill-keeper.md"]
        if not _tracked(ctx, "AGENTS.md"):
            paths.append("/AGENTS.md")
        if not ctx.v2 and not _tracked(ctx, "CONSTITUTION.md"):
            paths.append("/CONSTITUTION.md")
        result["excluded_in"] = write_exclude(ctx, paths)
        result["local"] = True

    if run_survey and write and brownfield_now(ctx):
        result["survey"] = survey(ctx)
    result.update({
        "created": True,
        "written": written,
        "deny_rules_added": added,
        # The charter is scaffolded blank, and a blank charter is a form. The
        # interview is the next step, not an optional extra.
        "next": "run `anthill onboard` — it asks the questions CONSTITUTION.md "
                "needs and fills them in. Then: " + result["first_move"],
    })
    return result
