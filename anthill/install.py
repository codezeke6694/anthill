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
    "AGENTS.md",
    ".claude/**",
]

STATE_SUBDIRS = ("contracts", "units", "audits", "sprints", "log",
                 "roles", "maps", "knowledge", "build")

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

**Every session, before anything else, find out whether a unit is already
yours.** Context gets compacted and sessions restart; the board does not forget.

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
        "AUDIT_NOTE": rules.audit_note(ctx),
        "MAX_FILES": "3",
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "project"


def _render(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    # Any placeholder left unfilled becomes an honest TODO rather than shipping
    # `{{STACK}}` into a document a human is expected to trust.
    return re.sub(r"\{\{([A-Z_]+)\}\}",
                  lambda m: f"_TODO: {m.group(1).lower().replace('_', ' ')}_", text)


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
ANTHILL="{cmd}"
if command -v "$ANTHILL" >/dev/null 2>&1 || [ -x "$ANTHILL" ]; then
  "$ANTHILL" map build >/dev/null 2>&1 || true
fi
exit 0
"""


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
                            blueprint_rule=rules.map_build_rule(ctx),
                            escalation_rule=rules.escalation_rule(ctx),
                            audit_note=rules.audit_note(ctx))
    if cmd == "anthill":
        return text
    bindir = cmd.rsplit("/bin/", 1)[0] + "/bin"
    header = (f"## Run this first, every session\n\n"
              f"Anthill lives outside this repository. Put it on your PATH "
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
        "will_create": [str(ctx.state / d) for d in STATE_SUBDIRS],
        "will_write": [
            str(ctx.config_path),
            str(ctx.constitution),
            *[str(ctx.roles_dir / f"{r}.md") for r in ctx.config.get("roles", [])],
            str(ctx.root / "CLAUDE.md"),
            str(ctx.root / ".claude" / "settings.json"),
        ],
        "protected_paths": PROTECTED_PATHS,
        "first_move": (
            "survey first: run `anthill integrate` — it draws the blueprint "
            "and ranks the largest code with no page. That ranking is your "
            "knowledge backlog. Develop ahead only after the blueprint exists."
            if brownfield else
            "zone first: name the districts and their boundaries, then author a "
            "cold contract. There is nothing to survey yet."
        ),
    }


def install(ctx: _ctx.Context, project_name: str = "", stack: str = "",
            description: str = "", areas: list[str] | None = None,
            force: bool = False, write: bool = True,
            exclude: list[str] | None = None) -> dict[str, Any]:
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
    cfg["protected_paths"] = PROTECTED_PATHS
    cfg["installed_mode"] = result["mode"]

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

    for sub in STATE_SUBDIRS:
        (ctx.state / sub).mkdir(parents=True, exist_ok=True)

    ctx.config = cfg
    ctx.save_config()
    written.append(str(ctx.config_path))

    values = render_values(ctx, name, description, stack)

    # The constitution is human-owned, so an existing one is never overwritten
    # even under --force: that is exactly the file a human will have edited.
    if not ctx.constitution.exists():
        ctx.constitution.write_text(
            _render(TEMPLATE_DIR / "CONSTITUTION.md.tmpl", values), encoding="utf-8")
        written.append(str(ctx.constitution))
    else:
        result["kept_existing"] = [str(ctx.constitution)]

    for role in roles:
        tmpl = TEMPLATE_DIR / "roles" / f"{role}.md.tmpl"
        if not tmpl.exists():
            continue
        dest = ctx.roles_dir / f"{role}.md"
        dest.write_text(_render(tmpl, values), encoding="utf-8")
        written.append(str(dest))

    protected_block = "\n".join(f"- `{p}`" for p in PROTECTED_PATHS)
    cmd = invocation(ctx)

    # AGENTS.md was listed in PROTECTED_PATHS and rendered into the deny rules
    # from the start, but nothing created it -- so the file every non-Claude
    # agent reads first did not exist, and the deny rule guarded nothing.
    from anthill import roles as roles_mod
    agents_values = dict(values, ROLE_TABLE=roles_mod.table(ctx),
                         PROTECTED_BLOCK=protected_block, ANTHILL=cmd)
    (ctx.root / "AGENTS.md").write_text(
        _render(TEMPLATE_DIR / "AGENTS.md.tmpl", agents_values), encoding="utf-8")
    written.append(str(ctx.root / "AGENTS.md"))
    (ctx.root / "CLAUDE.md").write_text(
        render_claude_md(ctx, name, protected_block), encoding="utf-8")
    written.append(str(ctx.root / "CLAUDE.md"))

    # The deny rules. Merged into an existing settings.json rather than
    # replacing it -- clobbering a developer's own permissions to install a
    # guardrail would be its own kind of overreach.
    settings_path = ctx.root / ".claude" / "settings.json"
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
    added = [r for r in deny_rules(PROTECTED_PATHS) if r not in deny]
    deny.extend(added)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    written.append(str(settings_path))

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

    # Stamped after everything above is on disk, so the fingerprints cover what
    # is actually there. Without this, `control` compares against whatever was
    # recorded at some earlier install and calls every re-render pending.
    try:
        from anthill import control as control_mod
        result["control_fingerprints"] = control_mod.record(ctx)["recorded"]
    except Exception as exc:                          # pragma: no cover
        result["control_note"] = f"fingerprints not recorded: {exc}"

    gitignore = ctx.state / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("build/\nunits/\n", encoding="utf-8")
        written.append(str(gitignore))

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
