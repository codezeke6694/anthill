# Anthill

A development agent system. It gives a coding agent a **blueprint** of the code,
a **record of intent** the code cannot carry, and a **foreman** that refuses work
which cannot prove itself.

Install it into a repository and it takes control of the agents working there.

---

## The model

> Code blocks are **chambers**. The functions calling them are **tunnels**. When
> you need to check something you consult the blueprint rather than crawling the
> tunnels, and send targeted work to the chamber.

That is what the tooling computes, not a metaphor over it:

| Ant hill | What it is |
|---|---|
| Chamber | a *node* — one responsibility per module |
| Tunnel | a *route* — the import graph, lifted to node level |
| Which tunnels land here | `consumers`, computed per node |
| The blueprint | `.anthill/build/maps/codebase.json` |
| Consult, don't crawl | `anthill start "<goal>"` → one card + one address |
| The navigator remembers | a **structural fingerprint**: signature + callees + callers, body excluded |

The fingerprint is the memory. Edit a formula *inside* a chamber and it holds.
Re-dig the chamber or re-route its tunnels and it breaks. Ordinary work
invalidates nothing; a change that could falsify a recorded statement is caught
mechanically.

## Three authorities an agent cannot forge

| Plane | Role | Authority |
|---|---|---|
| `navigate/` | the blueprint | a structural fingerprint — it cannot claim an address |
| `knowledge/` | the intent | a human attestation — it cannot claim intent |
| `orchestrate/` | the foreman | a gate's exit code — it cannot claim done |

**An agent never asserts completion.** `work done` is refused unless a gate passed.

## Two authority relationships

The system does not have one relationship with you. It has two, pointing
opposite ways — and the constitution states this on install:

- **Sprint / execution — you decide.** It discusses, proposes, executes what you
  approve, reports back. It does not choose what gets built, and it does not
  define "correct".
- **Knowledge / navigation — it decides.** It maintains its own blueprint and
  its own record as it works, without asking.

The cost of the second is stated rather than hidden: agent-written pages record
**what the agent did**, not what you wanted. `intent_attested_by` is the only
field that says a human agreed, no agent may fill it, and until one does the
area reports `intent_settled: false`. That is drift made visible, not prevented.

---

## Install

Pull it into the project you are working on, and install from there:

```bash
cd your-project
git clone <this repository> anthill
./anthill/bin/anthill install --name "Your Project" --stack "Python"
```

Nothing of it reaches your project's git. With the tool inside the project,
the install writes only files git never sees -- the agents' rules to
`CLAUDE.local.md`, the guards and hooks to `.claude/settings.local.json` --
and lists every Anthill path in this clone's own `.git/info/exclude`. Your
`.gitignore` is not touched and your teammates see no change. Every command it
writes is relative to the project, so the same setup works on any machine that
pulls it. A project that already tracks its own `AGENTS.md` keeps it.

Update later with one command; your charter, notes and settings are kept:

```bash
./anthill/bin/anthill update
```

Installed from a copy *outside* the project instead (`/path/to/anthill/bin/anthill
install`), it writes the shared `CLAUDE.md` and `.claude/settings.json`, for a
team that wants every agent on the project under the same rules.

Install writes a human-owned `CONSTITUTION.md`, role definitions under
`.anthill/roles/`, and — the part that matters — **deny rules in
`.claude/settings.json` for every path that binds the agents.** An agent that
can reach its own leash does not have one.

It never overwrites an existing `CONSTITUTION.md`, and it merges into an
existing `settings.json` rather than replacing it.

### It picks the first move for you

| Detected | First move |
|---|---|
| **greenfield** — no source | zone first: name the districts, author a cold contract. Nothing to survey yet. |
| **brownfield** — source found | survey first: `anthill integrate` draws the blueprint, then the intent gap ranks the largest code with no page. That ranking *is* your knowledge backlog. |

## Solo or pool

`execution.mode` decides how much of the machinery is in play.

| | `solo` (default) | `pool` |
|---|---|---|
| Who works | one interactive agent, in the repository itself | several headless agents, each in its own worktree |
| Escalation | by the agent's judgement; a failed gate is reported and the unit stays claimed | automatic after `escalate_after` failed gates |
| `work next --worker` | optional | required |
| `work done` | closes the unit; commits nothing, merges nothing | commits the unit's paths and merges into the integration branch |

Ownership, the gate, the spec/impl split and the compile-time gate check are
the same in both. Solo is the default because it is how the tool is actually
used: a person and one agent on one laptop. The pool exists to coordinate
agents that cannot talk to each other, and a single agent pays its whole cost
for nothing.

Change a setting through the one sanctioned writer, never by editing the JSON:

```bash
anthill config show
anthill config set execution.push_requires_owner false --by "<owner>"
anthill install --force        # re-render CLAUDE.md, AGENTS.md, roles from the config
```

The git rules, the map-build rule and the escalation rule in `CLAUDE.md`,
`AGENTS.md`, the role files and every compiled brief are rendered from the
config by `anthill/rules.py`. `anthill control` reports `stale` when a setting
has changed and the prose has not been re-rendered.

## The loop

```bash
anthill sprint new "S1" --goal "the greeting district"
anthill sprint add-unit greeting --title "Greeting" \
    --owns "greeting/**" --gate "pytest -q tests/greeting" --split
anthill sprint compile            # sprint (discussed) -> contract (enforced)

anthill work plan  --repo .       # waves and critical path
anthill work next  --repo . --worker builder-1     # atomic claim + own worktree
anthill work gate  --repo . --unit greeting.impl   # ownership, tests, blueprint, audit
anthill work done  --repo . --unit greeting.impl   # refused without a passing gate

anthill integrate                 # foreman redraws the blueprint, reports the gap
```

`--split` emits two units: `greeting.spec` owns `tests/**`, `greeting.impl` owns
the code and depends on it. **The builder cannot edit the tests it must pass** —
by ownership check, not by policy. On a cold start that is the only structural
defence against an agent authoring both the work and the definition of correct.

The two get different gates, which took a run to discover: `.spec` proves its
tests **exist and collect**; `.impl` proves they **pass**. Give them the same
gate and the spec unit has to make its own tests green, which is the opposite of
test-first, and the split deadlocks.

## Gates

A gate is a shell command. `compile` assembles three conditions, and a unit
cannot opt out of the last two:

```
<your tests>  &&  anthill blueprint  &&  anthill audit check <unit>
```

- **`anthill blueprint`** refuses a unit whose recorded claims no longer match
  the code. Scoped by default to the files *this* worktree changed, so blame
  lands on whoever caused the drift. It must not rebuild the map itself —
  rebuilding regenerates every fingerprint from the tree, so the check could
  never fail.
- **`anthill audit check`** refuses a unit whose audit refuses it.

## The audit, and what it is not

An auditor subagent is the same kind of thing as the builder — same model, same
blind spots. So the audit is deliberately asymmetric:

> **An audit may refuse a unit. It may never, by itself, pass one.**

Tests are the only positive proof. Five verdicts, because "wrong" and "not what
I would have written" deserve different consequences:

| Verdict | Consequence |
|---|---|
| `FAIL` | refuses the unit |
| `PARTIAL` | refuses **only if** `user_visible` |
| `DEVIATION` | recorded, does not refuse |
| `ARCH NOTE` | recorded and **escalated to a human** |
| `PASS` | recorded. Refuses nothing, passes nothing. |

Verdicts are **pinned to the commit audited**. A verdict from two commits ago
says nothing about the code about to close, so the gate refuses a stale audit —
the same rule as a page's `verified_against`, for the same reason.

The auditor's unit owns `[]`, so any file it touches is an ownership violation.
Read-only is enforced, not promised.

## Layout

```
anthill/
  bin/anthill              single entry point
  anthill/
    context.py             resolves the target project (installable, not vendored)
    install.py             constitution, roles, deny rules, state
    cli.py                 one CLI
    integrate.py           post-merge: redraw the blueprint, report the intent gap
    navigate/              structure, build_map, router
    knowledge/             pages, claims, readiness, harvest, evaluate, scaffold
    orchestrate/           orchestrator, pool, board
    gates/                 blueprint, audit
    sprint/                backlog — the human-facing plane
    templates/             constitution + role definitions
```

All state lives in `<project>/.anthill/`. Uninstalling is deleting one directory.

## Tests

```bash
python -m pytest tests -q
```

The suite installs the tool into a throwaway repository, with the real hooks,
and drives the modules through a claim, a gate and a close. Every fix in the
field report is covered here rather than verified by hand.

## Known limits

- **Structural fingerprinting is Python-only.** `structure.py` parses with `ast`.
  Non-Python citations degrade to a path-existence check. Pages, boards, gates
  and ownership are language-neutral; drift detection is not.
- **The blueprint is drawn on integration, not per unit.** A builder works in an
  isolated worktree holding only its own change, and the map is one shared file,
  so a per-unit rebuild would be both incomplete and a race.
- **`anthill blueprint` catches stale claims, not missing ones.** An agent that
  adds six files and writes no page has nothing to be stale about. `integrate`
  reports the gap; making it binding is `--min-coverage`, off by default.
- **Lessons are filed by area**, not chronologically, because a log written for
  completeness is never read. Anything not retrievable at a decision point is
  not logged.
