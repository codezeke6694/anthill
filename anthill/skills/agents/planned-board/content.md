# planned-board — A planned sprint on the job board

## Purpose
A planned sprint can be cut into pieces ("units"), each owning certain files and
proven by its own check. The job board hands the pieces out one at a time and
refuses to close one that has not proved itself. Load this before any
`anthill work` command. Day-to-day short and bug sprints do not use the board.

## Steps

**1. Is a piece already yours?** After `anthill where`:

```bash
anthill work status --repo .
```

- It names a unit `in_flight` → that is likely yours. Read its brief,
  `.anthill/local/board/work/*/briefs/<unit>.md`, before touching any code.
- It says `board_is_behind` → the plan changed since the board was loaded. Run
  `anthill work load --repo .`, or `work next` reports "drained" while work waits.
- Nothing ready and nothing behind → there is no board work for you. Say so.

**2. Claim, build, prove, close.**

```bash
anthill work next --repo .  --worker <you>   # claims one, prints the brief
#   build inside the unit's `owns` paths and nowhere else
anthill map build                            # the gate refuses a stale map
anthill work gate --repo .  --unit <id>      # ownership, tests, map, audit
anthill work done --repo .  --unit <id>      # refused unless the gate passed
```

**3. Read the gate's exit code; it says what to do next.**

| Code | Meaning | What you do |
|---|---|---|
| `0` | passed | `work done` |
| `1` | a test failed, or an audit refuses the work | fix the work |
| `3` | nobody has reviewed this state yet | not your fault, costs no attempt: an auditor reviews it, then re-gate |
| `64` | you wrote outside `owns` (the file is named) | revert that file; it belongs to another unit |
| `65` | `done` without a passing gate | run the gate |
| `66` | gated, but will not merge: two units claim one file | a plan bug: escalate, do not resolve it yourself |

**4. Stuck?**

```bash
anthill work escalate --repo . --unit <id> --reason "<what stopped you>"
```

Then stop. A unit escalated for a cause since fixed comes back only with
`anthill work reopen --repo . --unit <id> --reason "..." --by "<owner>"`, and only
when the owner told you to.

## Don't
- Don't edit anything under `.anthill/local/board/` by hand: state edited directly
  is indistinguishable from tampering and records nobody's decision.
- Don't widen a unit's boundary to fix something next to it.
- A command that seems missing is a real answer: say so and ask. Don't invent a
  workaround.
