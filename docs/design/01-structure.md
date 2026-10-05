# Anthill structure

**Status:** locked by the owner, 5 Oct 2026.
**Covers:** how Anthill's files are organised inside a project, what is shared with the team and what stays on one laptop, sprints, shared knowledge, skills, and how Anthill itself is shipped.
**The last section** lists the open issues we still have to measure.

---

## 1. The idea in one line

**One project has one Anthill, and every file Anthill makes has a fixed home: it travels with the project's git to the whole team, or it stays on one laptop for that laptop's agent.**

The folder decides. Nobody decides file by file.

### What that means for a new teammate

Priya clones the project on her laptop for the first time and installs Anthill.

- ✅ She gets the owner's decisions, the warnings, every sprint and its next step, the project's own skills, and the Anthill version the team uses.
- ✅ She does **not** get the owner's chat log, their notes to themselves, their owner's page, or a copy of a code map her laptop can redraw in seconds.

---

## 2. The folders

```
your-project/
├── anthill/                  the tool, pulled from the Anthill repo (hidden from the project's git)
└── .anthill/
    ├── owner/                🚛 travels · locked from agents
    │   ├── charter.md          what is being built, the stack, the owner's authority
    │   ├── settings.json       every setting, including the Anthill version this project uses
    │   ├── roles.json          who plans, builds, audits
    │   └── history/            who changed a setting or the charter, when, and why
    ├── sprints/              🚛 travels
    │   ├── active/<name>.md    one page per sprint in progress
    │   └── done/<name>.md      closed sprints
    ├── knowledge/            🚛 travels · the shared shelf, outlives every sprint
    │   ├── decisions/          the owner's calls, in the owner's words
    │   ├── warnings.md         traps a chat fell into once
    │   ├── glossary.md         the owner's words → the code's words
    │   ├── code/<area>.md      what each part of the code is for, with its rules
    │   └── howto/              how to run, test, sign in, deploy
    ├── skills/               🚛 travels · this project's own skills
    └── local/                💻 stays on this laptop, never in git
        ├── log.jsonl           every command, chat start, owner message, save
        ├── notes/              breadcrumbs and the saves made before memory compression
        ├── map/                the map of the code, redrawn after every save
        ├── upkeep.json         what the last save left out of date
        ├── page/               the owner's page: its state and its log
        └── board/              claims and project copies, only if planned sprints use them
```

### Why each folder lives where it does

| Folder | Lives | Why |
|---|---|---|
| `owner/` | travels | the whole team works to the same rules, settings and Anthill version |
| `sprints/` | travels | anyone can pick up anyone's sprint |
| `knowledge/` | travels | a lesson outlives the person who learned it |
| `skills/` | travels | made once, used by everyone on the project |
| `local/log` | stays | personal (it holds snippets of the owner's messages) and grows fast |
| `local/notes` | stays | scratch work; anything that matters goes onto the sprint page |
| `local/map` | stays | rebuilt from the code in seconds, and sharing it would cause merge clashes |
| `local/upkeep`, `local/page` | stays | worked out fresh each time; the page key must never leave the laptop |
| `local/board` | stays | claims and locks only mean something on one machine |

### Files outside `.anthill/`, made on each laptop

These are generated from `owner/settings.json` by `anthill install` and never shared. Because they are always rebuilt from the shared settings, every laptop ends up with the same rules and nobody hand-edits a shared copy.

- the rules file each AI reads first (`CLAUDE.local.md`, plus the matching rules for other tools);
- the locked-file list and automatic triggers (`.claude/settings.local.json`);
- the git save and push checks (`.git/hooks/`).

### How git sees it

`.anthill/local/` and `anthill/` are listed in the project's `.git/info/exclude`. `owner/`, `sprints/`, `knowledge/` and `skills/` are ordinary files in the project's git and travel with branches. A branch carries its own sprint page.

---

## 3. Sprints

All work is a sprint. A sprint comes in one of three kinds. All three share one page format, one set of commands and one finishing check.

| Kind | When | How it starts | Done when |
|---|---|---|---|
| **Planned** | big work you can lay out in advance, such as a new module | steps written up front; the test is written before the code | the finishing check passes |
| **Short** | the daily work: one feature, next step found by looking at the screen | one step; steps are added as you go | the finishing check passes |
| **Bug** | something is broken | the first step is a test that shows the break | that test passes; it stays in the test set for good |

### The sprint page

```
---
kind: short            # planned | short | bug
state: active          # active | waiting-on-owner | paused | done
branch: work/<name>
next: <the next step, one sentence>
check: <the command that proves it is done>
true_at: <commit the page was last true at>
---
## What            what this sprint is for, in the owner's words
## Steps           numbered; ticked as done
## Waiting on the owner
## Owner's answers written only from the owner's page
## Decisions taken for the owner   each one can be overturned by the owner
## Learned         handed to the shared shelf when the sprint closes
## History
```

### What it replaces

- **Work pages** become sprint pages.
- **Goals** become a sprint's steps and finishing check. A goal stops belonging to one chat: any chat, in any tool, can tick a step on any active sprint.
- **The old sprint, board and unit machinery** becomes the planned kind. It is optional, and only a planned sprint can opt in. Its one idea worth keeping everywhere is the **locked finishing check**: the agent building the work cannot edit the check it must pass.

### Closing a sprint

1. The finishing check runs. Only a pass closes the sprint.
2. Everything under **Learned** moves to the shared shelf: a warning to `warnings.md`, a decision to `decisions/`, a rule to a code page.
3. The page moves to `sprints/done/`.

---

## 4. Shared knowledge

The shelf holds what stays true after a sprint ends. A sprint page links to the decisions and warnings it used, and the shelf never links back to a single sprint.

**Why it is separate.** A chat in the placement sprint learns that restarting the server with auto-reload stops news collection. Next month, a bug sprint about missing news must still see that warning. If the warning were filed under the placement sprint, it would never see it.

Who writes what:

| Shelf | Written by | Owner's signature |
|---|---|---|
| decisions | the agent, in the owner's own words | the owner can sign from the owner's page |
| warnings, glossary, how-to | the keeper helper or the agent | none needed; corrections are logged |
| code pages and rules | the keeper helper or the agent; every rule points at the exact code | the owner signs to confirm the intent |

---

## 5. Skills

There are two sets.

- **Global skills** ship inside the Anthill repo. They are a small must-have set, such as finding your way around a project and the git ground rules. They are read in place from `anthill/` and updated by `anthill update`. They are never copied into a project.
- **Local skills** live in the project's `.anthill/skills/` and travel with its git. Each one says who proposed it, who approved it, and when.

### An agent proposes a skill, and the owner decides

An agent asks *"Should I make this a skill?"* and attaches a draft when it sees one of these:

- it has done the same procedure about three times;
- the owner has had to explain the same thing twice;
- a warning's fix is really a recipe.

The question appears in chat and on the owner's page. On a yes, `anthill skill new` writes the skill into `.anthill/skills/`. On a no, the agent records the refusal so it does not ask again.

**Promotion.** If a local skill is useful everywhere, the owner can promote it into the global set. That is a change to the Anthill repo, made like any other change to Anthill.

---

## 6. Shipping Anthill

1. **Anthill lives in its own repo** on GitHub.
2. **Anyone pulls it into their project.** It lands in `anthill/` inside the project and is hidden from the project's git. Then run `./anthill/bin/anthill install`.
3. **The team stays on the same version.** `owner/settings.json` records the Anthill version the project uses. `anthill update` brings the local `anthill/` to that version. Only the owner moves the version forward.
4. **A project has exactly one Anthill.** There is no separate knowledge repo per project, because the shared shelf travels in the project's own git.

---

## 7. The tool's own code, grouped by job

Today's layout follows where the code came from: 20 loose modules, plus folders named after the code they were ported from. The memory parts sit in five places, and one 1,600-line file serves four jobs. The new layout groups the code by what it does:

```
anthill/
  cli.py
  memory/     sprints, shared knowledge, where, resume, notes, the log, upkeep
  map/        reading the code, the map, start, orient, the map's own exam
  guards/     save and push checks, hygiene, locked files, tamper check
  proof/      finishing checks, planned-sprint board, audit
  owner/      the owner's page, the scorecard
  setup/      install, update, onboard, roles, settings, rule rendering, skills
  skills/     the global skills
  templates/
```

The behaviour stays the same while the code moves. The existing test suite proves it.

---

## 8. Cleaning out what exists now

What the first project's `.anthill/` holds today, and what happens to it:

| Today | Goes to |
|---|---|
| `anthill.config.json`, `roles/`, `config-history.json`, `charter-history.json` | `owner/` |
| `knowledge/work/*.md` + `goals/*.json` | `sprints/active` or `sprints/done` |
| `knowledge/decisions`, `TRAPS.md`, `GLOSSARY.md`, `howto/`, `modules/` | `knowledge/` (as decisions, warnings, glossary, howto, code) |
| `trail.jsonl` | `local/log.jsonl` |
| `build/maps`, `build/upkeep.json`, `build/ui.*` | `local/map`, `local/upkeep.json`, `local/page` |
| `build/work/*/wt/` (old project copies) | deleted; their work is already in git |
| `sprints/`, `contracts/`, `audits/`, `build/work/` state | `local/board`, kept only if planned sprints keep the board |
| `knowledge/_map`, `.obsidian`, stray vaults, `.DS_Store`, empty folders | deleted or regenerated on demand |
| `skills/` (39 copied-in sheets) | the few must-haves become global; the rest are removed |
| `prd/`, `plans/`, `idea.md` | the project's own planning documents; moved out of `.anthill/` |
| `maps/`, `log/`, `units/` (empty or leftover) | deleted |

Deleting needs the owner's yes at the time it happens.

---

## 9. Build order

1. **Clean out the dead weight**, so what is left is only what is in use.
2. **Make the new layout**, with the old paths still readable during the switch so no sprint breaks mid-way.
3. **Sprint pages**: three kinds, goals folded in, any chat can continue any sprint.
4. **Skills**: global and local, plus the agent's proposal question.
5. **Regroup the tool's code by job.**
6. **Ship it**: put the version pin in settings and have `anthill update` follow it.

---

## 10. Open issues to measure

Each issue is a question we can't yet answer with evidence. The current readings come from the first project, 29 Sep – 5 Oct 2026.

| # | Question | Why it matters | How to measure | Reading now |
|---|---|---|---|---|
| M1 | **Does Anthill make the owner faster?** | it is the whole point | give the same past tasks to fresh chats with Anthill hidden and visible; time from first message to first useful change; messages per change | fresh chats with a work page: 3½–7½ min to first change with no re-explaining. Weekly messages per save rose from 2.1 to 5.5, but harder work in those weeks muddies the comparison. Not yet proven either way |
| M2 | **How much of the AI's attention does it cost?** | every token Anthill uses is one the work can't | tokens loaded at chat start, plus `where` and `start`; set a budget | rules file ~4,600 tokens every chat; `where` ~5,400 and unbounded (44 warnings); `start` ~1,200; `orient` ~4,000 |
| M3 | **How often does the map point at the right file?** | a wrong card costs a detour | `eval-map` against past saves, after each change to the map | 58% top suggestion, 69% top three, 79% one step away |
| M4 | **How often is the notebook wrong?** | the next agent believes it | corrections logged per page per week; share of pages the owner signed; spot-checks of random claims | 3 corrections in 6 days; 1 page signed by the owner |
| M5 | **Does the upkeep actually happen?** | stale pages mislead | share of saves followed by a keeper run; open upkeep items over time | 25 open (19 are "no test", which never close) |
| M6 | **Does it work outside Claude Code?** | the team uses other tools | run M1 with Codex and Cursor | never tried; 0 non-Claude sessions in the log |
| M7 | **Do agents keep the rules nobody enforces?** | most rules are asked, not enforced | count hook skips, writes to owner files, forged answers or signatures, and self-closed work | not measured |
| M8 | **What actually gets used?** | unused features cost reading and upkeep | command counts per week from the log; anything idle for 4 weeks is a candidate to remove | board, sprints, audit and pool idle since 25 Sep; tidy, Obsidian and the checkpoint barely used |
| M9 | **Do teammates clash on shared pages?** | the shelf now travels through git | merge conflicts on `sprints/` and `knowledge/` per week, once two people use it | no team use yet |
| M10 | **Are skill proposals worth it?** | asks cost the owner's attention | proposals made vs accepted; how often accepted skills get loaded | feature not built yet |

---

## Decisions behind this document

- 5 Oct 2026, owner: all work is a sprint, of three kinds: planned, short and bug.
- 5 Oct 2026, owner: documentation is sprint pages plus a shared knowledge shelf.
- 5 Oct 2026, owner: skills are global (shipped) plus local (agent-proposed, owner-approved).
- 5 Oct 2026, owner: Anthill is its own repo, pulled into each project. One project has one Anthill.
- 5 Oct 2026, owner: the file structure is split into what travels and what stays local. Locked.
