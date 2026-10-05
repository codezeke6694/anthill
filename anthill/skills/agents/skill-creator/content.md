# skill-creator — Propose, then write, a project skill

## Purpose
A skill is a reusable instruction sheet that every chat on this project can load.
Use this sheet when you notice something worth turning into one, and again when
the owner says yes.

## When to propose a skill
Propose one when any of these is true:
- you have done the same procedure about three times (signing in to check a
  screen, re-running a scoring check, setting up test data);
- the owner has had to explain the same thing twice;
- a warning's fix is really a recipe ("do A, then B, never C").

Do **not** make the skill yet. Ask the owner first, in one line, with a draft:

> I've done X three times now. Should I make it a skill so the next chat just
> does it? Draft: <two or three lines of what it would say>.

- **Yes** → write it (below).
- **No** → note the refusal (`anthill note "owner declined a skill for X"`) and
  do not ask again for the same thing.

## Where it goes
- **Local skill** (this project only): `.anthill/skills/<category>/<name>/`.
  This is the default. It travels with the project's git.
- **Global skill** (shipped with Anthill to every project) lives in Anthill's own
  repo, under `anthill/skills/`. Only the owner promotes a local skill to global.

Categories: `agents` (how agents work), `development` (code), `design` (screens),
`testing`, `prompts` (instructions for an AI model), or a new one when none fits.

## Write it
1. **Name:** lowercase and hyphenated, saying what it does (`sign-in-headless`,
   not `helper`). Unique within the project.
2. **`skill.yaml`:**
   ```yaml
   name: sign-in-headless
   category: testing
   version: "1.0"
   description: One line: what it does and exactly when to load it
   load_class: reference      # bootstrap | phase-scoped | conditional | reference
   always_on: false
   proposed_by: <tool and chat that proposed it>
   approved_by: owner
   approved_on: <YYYY-MM-DD>
   ```
   Load classes:
   - `bootstrap`: loaded by every chat, every session. Use it rarely, because
     each one costs reading in every chat.
   - `phase-scoped`: only during one phase of work.
   - `conditional`: only when its trigger happens (an audit, a screen change).
   - `reference`: installed but never loaded on its own; a chat looks it up. This
     is the default.
3. **`content.md`:** `## Purpose` (the problem it solves, and when to load it),
   `## Steps` (directive, numbered, with exact commands), and optionally
   `## Don't` (what goes wrong, and why).
   - Write "Do X", not "X is recommended".
   - Cut every line that doesn't change what the agent does.
4. **Index it:** `anthill skill index`, then `anthill skill get <name>` to check
   it loads.

## Don't
- Don't make a skill without the owner's yes.
- Don't copy a general skill in from elsewhere. If Claude already has it built in
  (Word, PDF, slides), it does not belong here.
- Don't mark a skill `bootstrap` unless every chat genuinely needs it.
