# Closing the known gaps

**Status:** proposed, 5 Oct 2026. Goes with `01-structure.md`.
**Source:** every gap listed in the plain explainer of Anthill (5 Oct). Each one is checked against the code at commit a9788ba.

Every gap falls into one of five groups:

| Group | What it means | Count |
|---|---|---|
| **A · Solved by the new structure** | building `01-structure.md` closes it | 5 |
| **B · Bugs** | small, clear fixes | 8 |
| **C · Improvements** | real work, but clear what to build | 10 |
| **D · Can't be fully stopped, so make it visible** | on one machine, an agent and the owner run the same programs | 6 |
| **E · Remove, or rebuild to be real** | unused or broken today | 4 |

**The rule for group D:** *if Anthill can't stop it, it has to show it.* Every write that didn't come through the sanctioned path shows up red on the owner's page and in `where`. A determined agent can still do it, but it can't do it quietly.

---

## A · Solved by the new structure

| # | Gap | How the structure closes it |
|---|---|---|
| A1 | Memory doesn't travel between laptops | `owner/`, `sprints/`, `knowledge/` and `skills/` travel in the project's git |
| A2 | A goal belongs to the chat that set it | goals become sprint steps and a finishing check; any chat, in any tool, continues any sprint |
| A3 | Notes mixed together when everything is on main | notes belong to a sprint, not a branch |
| A4 | Old project copies (160+ MB), stray vaults, empty folders | the clean-out step |
| A5 | 39 copied-in skills, most unrelated | global and local skills |

## B · Bugs

| # | Gap | Fix |
|---|---|---|
| B1 | A "next step" longer than one line is cut at the first line | read continuation lines in page headers |
| B2 | Anthill's own rule files show as "another session may be editing these" | leave Anthill's generated files out of the "being edited" check |
| B3 | `where` and `resume` disagree about uncommitted files | one shared function, so both count the same files |
| B4 | Notes from a tool with no session id show up nowhere | fall back to tool + start time as the id; never drop a note |
| B5 | 22 of 24 pages fail a format check written for code pages | one format per page type (sprint, decision, warning, code, how-to) |
| B6 | Pages for deleted branches stay "active" | mark them paused, with "branch gone", on the next `where` |
| B7 | Coverage counts a folder glob as every file explained | count only files a rule or page actually names |
| B8 | Hooks contain one laptop's full path to Anthill | hooks call `./anthill/bin/anthill` relative to the project |

## C · Improvements

| # | Gap | What to build |
|---|---|---|
| C1 | `where` has no size limit (about 5,400 tokens now, and growing) | show the active sprints in full and the others as one line each; show only the warnings that touch the sprint's files; set a hard budget (M2) |
| C2 | The rules file is 335 lines, read by every chat (~4,600 tokens) | rewrite around sprints; drop board instructions unless planned sprints are on; budget under 2,000 tokens (M2) |
| C3 | A rule can quote a number the code no longer has (650 km becomes 325 km and nothing is flagged) | when a rule cites a constant, record its value too; a changed value flags the rule |
| C4 | Adding one log line counts as "rewired" and blocks a page | ignore logging and print calls when comparing what a function calls |
| C5 | The keeper runs only if the agent remembers, and nothing checks | the log records whether the keeper ran after each save; `where` and the owner's page show "save X: notebook not updated" |
| C6 | "This code has no test" items never close (19 open) | the item closes once the suggestion is passed to the owner; the owner turns it into a bug or short sprint, or dismisses it |
| C7 | TypeScript: `grep` and `read-slice` don't work, the fingerprint is one line | make `grep` and `read-slice` language-neutral; make the TypeScript fingerprint include what a function calls |
| C8 | The map points at the right file only about half the time | sprint pages and the glossary feed the search; re-measure with `eval-map` after each change (M3) |
| C9 | Full automation only in Claude Code | every automatic step also exists as one command, and the rules for other tools tell them when to run it; test with Codex and Cursor (M6) |
| C10 | Almost nothing in the notebook is signed by the owner | closing a sprint asks the owner to confirm its "Learned" items in one click; the owner's page shows "N decisions unsigned" |

## D · Can't be fully stopped, so make it visible

On one machine, the owner and an agent run the same git and the same files. Anthill can't tell them apart, so the aim is that nothing changes quietly.

| # | Gap | What Anthill does |
|---|---|---|
| D1 | Hooks can be skipped with `--no-verify` | the post-commit hook still runs. It flags any save on main, or with a secret, that the pre-commit check should have refused, and shows it red |
| D2 | An agent can claim to be the owner (`ANTHILL_OWNER=1`, `--by "<owner>"`) | owner-only commands are logged with the tool and chat that ran them; one run from an agent chat shows red. **Option to explore:** confirm owner actions through a macOS system prompt (Touch ID), which an agent can't click |
| D3 | Locked files only block Claude's edit tool, not shell commands | the tamper check runs on every `where` and shows any change to `owner/` or the rules that didn't come through `config set` or `onboard` |
| D4 | An "owner's answer" can be written straight into a page | every answer made on the owner's page leaves a log entry. An answer on a page with no matching entry shows "not from the owner's page" |
| D5 | An agent could mark its own work done by editing the files | a sprint closes only by running its finishing check, which is logged. "Done" with no passing run shows red |
| D6 | The owner's page key needs a real terminal, which can be faked | same as D2: a system prompt instead of a terminal check, if it works out |

## E · Remove or park

| # | What | Why |
|---|---|---|
| E1 | Pool mode (several agents run by Anthill) | **keep, and make it real** (owner, 5 Oct: needed for long sprints with lots of independent work). Becomes *parallel pieces*: the owner tells one lead chat to work on the sprint, and Anthill guides it to start helper agents for the independent parts, wave by wave. Needs tests, a planning check that no two pieces in a wave share a file, short helper briefs, and a visible holding branch. See `01-structure.md` §3 |
| E2 | The test/code split and the auditor | both leak (the builder can edit the tester's files; the auditor isn't read-only). Replace them with the **locked finishing check**: the agent can't edit the check it must pass |
| E3 | The 30-minute automatic release of a claim | silently frees a piece a slow chat still holds. Replace it with a heartbeat each chat sends, and show a "possibly abandoned" piece on the owner's page before anything is released |
| E4 | `tidy`, Obsidian picture, `impact`, `card`, `control` as separate commands | barely used. Fold them into `where` and `start`, or remove them (M8) |

---

## Order, folded into the build

| Build step (from `01-structure.md`) | Gaps closed along the way |
|---|---|
| 1. Clean out | A4, A5 |
| 2. New layout | A1, B8 |
| 3. Sprint pages | A2, A3, B1, B5, B6, C1, C2, C5, C6, C10, D4, D5, E2 |
| 4. Skills | A5 |
| 5. Regroup the code | B2, B3, B4, B7, E4 |
| 6. Ship | C9 |
| 7. Parallel pieces | E1, E3 |
| then | C3, C4, C7, C8 (the map); D1, D2, D3, D6 (visibility) |

What can't be closed, only measured: whether Anthill makes the owner faster (M1), and whether agents keep the rules that are only asked (M7).
