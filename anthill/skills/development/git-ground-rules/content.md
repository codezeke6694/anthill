# git-ground-rules — What a shared repository cannot survive without

## Purpose

Loaded every session. These are the rules where breaking one, once, costs
**someone else** — lost work, a broken `main`, a leaked key. Everything that
only makes history messier is a habit, and lives in `git-playbook`.

Read the rule; if the moment calls for the method, `anthill skill get git-playbook`.

## The eight rules

1. **Commit or stash before you pull, switch branch, merge or rebase.**
   Git only protects committed work. An uncommitted fix is the one thing a
   pull can destroy. A local commit costs nothing and can be reworded later.
   *Enforced by: nothing. Git has no hook before a pull. This one is yours.*

2. **Work on a branch. Never commit directly on `main`.**
   `main` is what everyone branches from; a change on it is one nobody agreed
   to and everybody inherits.
   *Enforced by: `execution.protected_branches`.*

3. **`main` always works.** Nothing merges into it without the full test suite
   passing on the merged result — not on your branch before the merge.
   *Enforced by: the anthill gate, for work that goes through the board.*

4. **A conflict is resolved when the tests pass, not when the markers are gone.**
   Clean-looking text can still be broken code (an import the other side
   moved, a name it renamed). Run the tests before `git add` on a resolution.
   *Enforced by: nothing. This one is yours.*

5. **Never rewrite history someone else has.** No force push, no rebase, no
   amend on a commit that has been pushed to a shared branch. To catch up,
   `git merge origin/main` — always safe, even on a pushed branch.
   *Enforced by: `execution.guard_hygiene` (refuses a force push).*

6. **No secrets in the repository.** No keys, tokens, passwords, `.env`,
   `.pem`. A secret is public from the first push, and deleting it later does
   not take it back — a key that was ever pushed must be rotated. Share the
   shape with `.env.example`.
   *Enforced by: `execution.guard_hygiene`.*

7. **No junk.** `.DS_Store`, `__pycache__/`, `node_modules/`, `.venv/`, build
   output, editor swap files. They belong in `.gitignore`, not in history.
   *Enforced by: `execution.guard_hygiene`.*

8. **Never bypass a hook, and never push or merge into `main` unless the owner
   asked for that push.** No `--no-verify`. A refusal is information: read it,
   do what it says, and if you think the hook is wrong, say so and stop.
   *Enforced by: `execution.push_requires_owner` for pushes; the rest by you.*

## When something has gone wrong

- `git merge --abort` / `git rebase --abort` — back to before you started.
- `git reflog` — every place HEAD has been. Committed work is almost never
  truly lost; find its hash here and `git switch -c rescue <hash>`.
- Lost uncommitted work is usually gone. That is why rule 1 is first.
