# git-playbook — Working in a shared repository

## Purpose

The method behind `git-ground-rules`. Look it up when you are about to resolve
a conflict, catch up with `main`, open a pull request, tidy commits, or recover
something. General to any repository; the worked example is a real incident.

Where this playbook and the ground rules differ, the ground rules win. Where
either differs from an instruction the owner gave in this conversation, the
owner wins.

Adapted from *Git for Professionals* (freeCodeCamp, Tobias Günther).

---

## 0. Picture where the work is

Three places, and a file moves between them only when you say so:

| Place | What it is | Safe? |
|---|---|---|
| Working directory | the files you are editing | **no** — a pull, checkout or bad merge can destroy it |
| Staging area | the draft of the next commit (`git add`) | no |
| Repository | committed history (`git commit`) | yes — very hard to lose |

A **commit** is a snapshot of the whole tree plus a pointer to its parent.
A **branch** is a movable label on one commit — it copies nothing and costs
nothing. Committing slides the current label forward; nothing else moves.

**What never gets committed** goes in `.gitignore`: installed dependencies
(`.venv/`, `node_modules/`), secrets (`.env` — commit `.env.example` instead),
build output, OS and editor files, dumps and personal notes. A `.gitignore`
rule only counts once it is *committed* — staged-but-uncommitted, it works on
your machine and ignores nothing on anyone else's.

---

## 1. The perfect commit

**One change per commit.** If a session touched three unrelated things, make
three commits. Otherwise one of them can never be reverted without the others.

```bash
git add -p path/to/file     # step through each hunk: y / n / s (split)
git commit                  # just that idea
git add other/file
git commit                  # the next one
```

**Say why, not what.** The diff shows what. The message is for the person
reading it in six months:

```
Retell a chain's whole screen in one call, not one per lane and node

Opening a chain of ten lanes and fifteen nodes made twenty-five model
calls, sequentially, each with its own 120s timeout, before the screen
could draw anything. <what was wrong, how it was measured, what to be
careful of>
```

- Subject under ~70 characters, imperative ("Retell…", not "Retold…").
- Blank line, then the reasoning.
- ❌ `fixed match.py merge confict and ignored context folder` — three
  changes (a merge fix, an ignore rule, a script rewrite the subject never
  mentions) in one commit.

---

## 2. Branches

- **`main`** is long-running: never committed to directly, only merged into,
  always runs.
- **Everything else** is short-lived: cut from current `main`, one piece of
  work, merged back, deleted.

Naming — readable in a branch list six weeks later:

```
feature/ticket-module        new work
fix/delta-marker-timezone    a bug
spike/geohash-bucketing      an experiment, may be thrown away
work/<what-you-are-doing>    an agent's branch in an anthill repo
```

**Branches do not stop two people editing one file. Ownership does.** Agree
who owns which files *before* branching. Two branches that never touch the
same file merge with zero conflicts, every time. A conflict is almost always
a symptom of unclear ownership, not a git problem. In an anthill repo, a
unit's `owns` globs are that agreement — stay inside them.

---

## 3. Pull requests

A PR is a request to merge, wrapped in a conversation that stays attached to
the code. A merge done without one keeps no record of what was questioned or
agreed.

A good description carries:

1. **What changed and why this approach.**
2. **How you know it works** — the test output, pasted. `767 passed, 2 skipped`
   beats "tested locally".
3. **What you deliberately left out**, so the reviewer does not report it
   missing.
4. **Anything crossing an ownership boundary** — that always needs a second
   pair of eyes.

Review is a second opinion, not the proof. The proof is the test suite and,
in an anthill repo, the gate. Opening a PR means pushing, and pushing is the
owner's call (ground rule 8).

---

## 4. Merge conflicts

A conflict is git refusing to guess, not an error. Nothing is broken yet.

### The worked example — why "no markers" is not "resolved"

A fix to `relevance/match.py` sat **uncommitted**. Someone ran `git pull origin
main`. Main had meanwhile moved helper functions out of that same file into
another module. Git had three versions to reconcile: the ancestor (646 lines),
main's (614), and the uncommitted fix (674).

It was merged by hand and looked finished — no markers anywhere. But it had
taken main's new import block, which no longer imported `re`, while keeping the
old functions that needed it:

```
File "app/search/match.py", line 230, in <module>
    BREAK = re.compile(
NameError: name 're' is not defined
```

The app would not start. Two lessons: commit before you pull (the fix was only
recovered from the reflog by luck), and a resolution is finished when the tests
pass.

### The method

1. **Stop and look.**
   ```bash
   git status        # which files are unmerged
   git diff          # both sides
   ```
2. **Read all three versions**, not just the markers:
   ```bash
   git show :1:path/to/file    # common ancestor — the one people skip
   git show :2:path/to/file    # ours
   git show :3:path/to/file    # theirs
   ```
   The ancestor tells you what each side was *trying* to do. Check what the
   other side moved or renamed — imports, helpers, signatures.
3. **Rewrite the region** so it reads as if one person wrote it. Delete every
   marker.
4. **Prove it**: run the full test suite, and start the app if it has a start
   command. Only then:
5. **Finish**: `git add <file>` then `git commit`.

`git merge --abort` puts everything back as it was. There is never a reason to
press on while confused.

---

## 5. Merge or rebase

Both bring one line of work into another. They differ in what happens to
history.

- **Merge** adds a commit joining the two lines. Your commits keep their
  hashes. Records what really happened.
- **Rebase** lifts your commits off, moves the branch to a new base, and
  replays them. A commit's identity includes its parent, so every replayed
  commit is a *new* commit with a new hash — the originals are discarded.

That is why the one rule follows: **never rebase (or amend) a commit anyone
else has.** Their copy and yours are now different objects, and git cannot
tell they were ever the same work.

| Use merge | Use rebase |
|---|---|
| bringing a feature into `main` | tidying your own local branch |
| catching up a branch that is already pushed | catching up a branch nobody else has pulled |

**`git merge origin/main` into your branch is never the wrong answer** — safe
even on a pushed branch. You lose only the straight line.

### Catch up often, not at the end

A branch that has not caught up is tested against a world that no longer
exists; its suite can be green about the wrong thing. In the worked example the
branch sat behind while main moved ten commits and 126 files — a refactor of
the very file being edited, a new dependency, a start-up migration. It all
arrived in one pull, and three unrelated failures happened in the same minute.
Caught up weekly, each would have been met alone, on a quiet branch.

```bash
git fetch origin
git merge origin/main          # or, if the branch is still only yours:
git rebase origin/main         #   git rebase --continue / --skip / --abort
# then run the tests — that is the point of catching up
```

Do it weekly and again before opening a PR.

### Tidying your own commits (not yet pushed)

Turning `wip`, `typo`, `fix the typo` into one honest commit. A person uses
`git rebase -i origin/main` and edits the list (`pick`, `reword`, `squash`,
`fixup`, `drop`). An agent cannot drive that editor. The equivalent, for
commits nobody else has:

```bash
git log --oneline origin/main..HEAD    # confirm these are all yours, unpushed
git reset --soft origin/main           # keep every change, drop the commits
git add -p && git commit               # recommit as the honest sequence
```

Or fold a fix into an earlier commit as you go. Setting the sequence editor to
`:` accepts git's plan without opening an editor, so this does work from an
agent session:

```bash
git commit --fixup <hash-of-the-commit-it-fixes>
GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash origin/main
```

---

## 6. Recovery

| Situation | Do |
|---|---|
| Need to pull with uncommitted work | `git stash`, `git pull`, `git stash pop` — or just commit |
| Merge or rebase went wrong midway | `git merge --abort` / `git rebase --abort` |
| A commit seems lost (bad reset, rebase, branch deleted) | `git reflog`, find the hash, `git switch -c rescue <hash>` |
| Uncommitted work was overwritten | usually gone — which is why you commit first |
| A secret was committed | unstage if not committed; if it was ever pushed, **rotate the key** — removing it from history does not un-publish it |

---

## 7. Two people, two features

1. **Agree the boundary first.** You own `tasks/` and `tests/tasks/`; I own
   `insights/` and `tests/insights/`; neither touches `relevance/`. Ten minutes
   here saves every conflict later.
2. **Each branch from current `main`.**
   ```bash
   git switch main && git pull && git switch -c feature/ticket-module
   ```
3. **Work independently, commit in small pieces** — whenever one idea is done.
4. **Catch up with `main` weekly** and before the PR (section 5), then run the
   tests.
5. **Prove it, then open the PR** — full tests, linters, type check, the app
   starting; paste the output in.
6. **Merge, then delete the branch.**
   ```bash
   git switch main && git pull
   git merge --no-ff feature/ticket-module   # keeps the feature visible as a unit
   git branch -d feature/ticket-module
   ```

Neither person is blocked, neither sees a conflict, and `main` works the whole
time — not because git is clever, but because the files were divided before the
branches were made.

For an agent: steps 5's push and step 6 are the owner's (ground rule 8). Commit
locally, prove it, then say what is ready and wait.

---

## Card

| Every day | |
|---|---|
| `git status` | where is everything |
| `git add -p` / `git commit` | one idea at a time |
| `git fetch && git merge origin/main` | catch up, then test |
| `git stash` | park uncommitted work |
| `git merge --abort` · `git rebase --abort` | back to before |
| `git reflog` | find anything you committed |
