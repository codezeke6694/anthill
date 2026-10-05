# Anthill

A notebook and a set of rules that live inside your project, so any AI chat can
pick up the work where the last one stopped — without you explaining it again —
and cannot quietly break what you agreed.

It is a command-line tool, not an AI. The chats call it, read what it prints,
and follow its rules.

## What it does

| Job | What it means | Commands |
|---|---|---|
| **Remember the work** | every piece of work is a sprint page any chat can continue; decisions, warnings and lessons live on a shared shelf | `where`, `sprint`, `note`, `resume` |
| **Find the way in the code** | a map of the code, redrawn after every commit | `orient`, `start`, `map build`, `eval-map` |
| **Guard the project** | no commits on `main`, no push the owner did not run, no secrets or junk, files agents may not edit | git hooks, `guard`, `control` |
| **Prove work is done** | an agent cannot declare itself finished; a check has to pass | `sprint done`, the job board |
| **Keep the owner in the loop** | one page with every question waiting on the owner, answered in a click | `ui`, `score`, `trail` |

## Install

Pull Anthill into the project, and install from there:

```bash
cd your-project
git clone https://github.com/<owner>/anthill anthill
./anthill/bin/anthill install --name "Your Project" --stack "Python"
```

Then commit the notebook — `.anthill/owner/`, `.anthill/sprints/`,
`.anthill/knowledge/`, `.anthill/skills/` — so your team shares it. Everything
else Anthill makes is hidden from git on its own.

A project that already ran an older Anthill moves to this layout with
`./anthill/bin/anthill migrate` (it shows the plan first; `--apply` moves).

## One project, one Anthill: what travels and what stays

```
your-project/
├── anthill/           the tool, from this repository        (hidden from git)
└── .anthill/
    ├── owner/         charter, settings, roles, history      travels · agents may not edit
    ├── sprints/       one page per sprint                    travels
    ├── knowledge/     decisions, warnings, code pages        travels
    ├── skills/        this project's own skills              travels
    └── local/         the log, the map, the job board        stays on this laptop
```

The folder decides; nobody decides file by file. The rules each AI reads
(`CLAUDE.local.md`, `AGENTS.md`), the locked-file list and the git hooks are
generated on each laptop from the shared settings, so every laptop follows the
same rules.

### The team stays on one Anthill

`owner/settings.json` records the Anthill version the project uses.

```bash
./anthill/bin/anthill update                      # this laptop -> the team's version
./anthill/bin/anthill update --latest --by owner  # the owner moves the team forward
```

`anthill where` says so when a laptop runs a different Anthill from the team.

## Sprints

All work is a sprint, of three kinds:

- **short** — one feature, steps found by looking at the screen
- **bug** — starts with a test that shows the break
- **planned** — laid out up front; its pieces can run on the job board

```bash
anthill sprint start "Refunds on the receipt" --kind short --check "pytest -q tests/refunds" --step "Show the line"
anthill sprint step --done 1
anthill sprint decided "Round half up" --because "the owner's pricing note"
anthill sprint block "Show refunds as a negative line? I recommend yes."
anthill sprint done        # runs the check; only a pass closes it
```

Any chat, in any tool, can continue any sprint. When the owner says "end to
end", `anthill sprint go`: the chat keeps working until the check passes,
decides what written decisions already settle, and stops only for what the
owner alone decides — what customers see, live data, money, pushing or merging
into main, deleting.

Closing a sprint files its **Learned** lines on the shared shelf: a `Warning:`
reaches every later sprint, a `Decision:` waits for the owner's signature, a
`Rule:` waits for the keeper to put it on its code page.

## Skills

The must-have skills ship in `anthill/skills/` and are read from there, so
`anthill update` keeps them current. A project's own skills live in
`.anthill/skills/`; an agent that notices a repeated procedure asks the owner
before making one (`anthill skill new ... --approved-by <owner>`).

## Which AI tools

Claude Code gets everything, including what hooks do on their own: the pick-up
note when a chat starts, the save before its memory is compressed, the push back
when an "end to end" chat stops early, the locked files. Other tools (Codex,
Cursor) read the same rules from `AGENTS.md` and run those steps themselves.

## Known limits

- **On one laptop, an agent and the owner run the same programs.** Anthill
  cannot tell them apart, so most rules are asked, not enforced. What it cannot
  stop it shows: an answer that did not come from the owner's page, a sprint
  closed without its check.
- **The map is built for Python.** TypeScript is read roughly; the notebook,
  guards and sprints work for any language.
- **The map's first suggestion is right about half the time**
  (`anthill eval-map` measures it on your own history).
- **The job board and running several agents at once work on one laptop.**

## Tests

```bash
python3 -m pytest tests -q
```

The suite installs the tool into throwaway repositories, with the real hooks,
and drives it the way chats do.
