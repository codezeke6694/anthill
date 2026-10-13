# 03 · What to take from AutoDev

13 Oct 2026. Read from AutoDev 0.8.10's code (marko-hq/autodev; a local copy
with no GitHub link sits at `~/autodev-copy`), not only its readme. Status:
**proposed, waiting on the owner** — build 1–3 together as one sprint with 4
after, or the database guard alone first. Item 5 added 13 Oct.

Take the idea, not the code: AutoDev is shell scripts, and its versions are
tied to one Laravel project. Each one is rebuilt in Anthill's way and set per
project.

## 1. Stop a database change before it happens

**What went wrong.** 8 Oct: a LogiAstro chat saved a file, the dev server
reloaded, and a database change ran on the shared database before any test.
Anthill stops pushes and commits on main; nothing else.

**AutoDev.** A job whose plan touches migrations, queues or permissions waits
at READY until a person runs `autodev approve` (`lib/engine.sh`
`eng_critical_scope`). Its list is hard-coded Laravel paths and words, and a
trivial job skips the check entirely.

**For Anthill.** A per-project list of risky paths and words in the owner's
settings (LogiAstro: `migrations/versions/`, anything the dev server reloads).
A chat about to change one stops and asks on the owner's page; the answer is
the approval. No size of task skips it.

## 2. Refuse edits outside the sprint's files, as they happen

**What goes wrong.** Writing outside a unit's files is caught only at the
gate (exit 64), after the work is done; it must then be undone. With
parallel helpers, that is how two pieces collide.

**AutoDev.** A Claude PreToolUse hook refuses Edit/Write on any file not named
in the plan's Scope and tells the coder to stop and explain
(`lib/scope-guard.py`). Test files and new files in a named folder pass.
Gaps: edits made through a shell command are not covered; Codex has no hook;
a Scope naming no files allows everything.

**For Anthill.** The same hook against the sprint's or piece's files, when it
has any. Keep the gate check: it catches what the hook cannot (shell edits,
other tools).

## 3. Judge tests by name

**What goes wrong.** A test already broken before the sprint fails its check,
though the sprint broke nothing; chats learn to ignore red.

**AutoDev.** Records the names of failing tests when the job starts and fails
only on new names; a fix of one old failure plus one new failure still fails;
unnamed failures fail (`lib/gate.sh`). It used to compare counts and moved
away from that.

**For Anthill.** At `sprint start`, record failing test names; `sprint done`
and the gate block only on names not in that list, and say which old ones
the sprint fixed.

## 4. Show what each sprint cost

**What is missing.** Anthill cannot say what a piece of work cost, or what
Anthill itself costs.

**AutoDev.** Reads usage from the chat transcripts, de-duplicated by message
id, weighted cache-write ×1.25, cache-read ×0.1 (`lib/state.sh`). Budgets per
stage and per job escalate when exceeded.

**For Anthill.** The same reading, attributed to the sprint each chat worked
on: a cost line on the sprint page and a total on the owner's page, with
Anthill's own share (keeper, `where`) shown apart. Budgets later, if at all.

## 5. Coding standards, and cheap checks at save time

**What is missing.** Anthill says how to work (sprints, git, the owner) but
nothing about how code should be written. Each chat brings its own taste.

**AutoDev.** 28 rules in `policy/`: a fixed floor of 9 (`pack/rules`: git,
secrets, evidence) and a starter set of 19 coding standards a team edits
(`starter-pack/rules`). Each rule names how it is checked: a registered script
in `lib/checks/`, the reviewer, or both. A project may tighten a rule, never
loosen it.

**Already in Anthill:** the owner pushes (GIT-001/002), no secrets (SEC-001),
agent and settings files off-limits (GIT-005), nothing done without a passing
check (EVID-001).

**Take, as standards a chat follows:** simplest solution, no speculative
layers (CODE-SIMPLE, CODE-DUP, CODE-TERSE); small functions and files, split by
job (CODE-SIZE); no magic literals, name them once (CODE-CONST — our 650 km
problem); comments only for a non-obvious reason (CODE-COMMENT); surface the
tool's own error (CODE-ERR); no personal paths, accounts or hosts (CODE-PORT —
Anthill's own B8); behaviour changes come with tests (TEST-001); a changed data
or API shape bumps its version (ARCH-COMPAT); follow the project's own
conventions (ARCH-CONV).

**Take, as checks at save time** (scripts, no tokens): a dependency manifest
or lockfile changed → ask the owner (`lockfile-diff`, DEP-001; sits with item 1);
personal path or hostname added (`portability-grep`); one added block over 60
lines (`size-ceiling`); comment density (`comment-density`).

**Leave out:** ARCH-OOP-001 (tuned to one Laravel codebase), REV-001 (Anthill
has no separate reviewer), GIT-002's `autodev/**` branch namespace.

**For Anthill.** Not in the rules file every chat reads (19 rules would about
double it): a global skill, `coding-standards`, loaded when a chat writes code,
merged with LogiAstro's local Ponytail skill, which covers the "simplest" side.
A project adds stricter rules locally; it cannot loosen the shipped ones. The
four checks run in the post-commit hook and land on the upkeep list; the
dependency check stops and asks, like item 1. Credit AutoDev and tell its
developer.

## Left out, and why

- Running unattended: waiting out usage limits, restarting after sleep. The
  owner positions Anthill for working with them, not overnight.
- Sorting tickets by size with keywords: the three sprint kinds cover it.
- Task memory: weaker than Anthill's notebook (word matching, planning step
  only).

## Also noted in AutoDev's code

To ask its developer, not to copy:

- The readme says a standard ticket costs 80–150K tokens; code comments record
  plans alone at 118K–494K, and job budgets go up to 6M.
- No eval results are recorded; the 80% DONE target is unmeasured.
- The reviewer defaults to Haiku; its help text says Sonnet.
- "DONE means proven by a test" does not hold for trivial jobs.
- Questions wait forever, except in background mode (5 minutes).
