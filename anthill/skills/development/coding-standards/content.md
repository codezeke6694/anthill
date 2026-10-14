# coding-standards — How code is written here

## Purpose

Load this before you write or change code. Without it, each chat brings its own
taste, and the codebase reads like it was written by forty people. The rules
come from AutoDev's starter pack (marko-hq/autodev, `policy/starter-pack`),
reworded for Anthill; the four marked *checked* are also looked at by a script
after every commit.

A project may add stricter rules of its own (a local skill, or its knowledge
pages). It may not loosen these. Where a project's own convention and a rule
here disagree, follow the project and say so in the commit.

## The rules

1. **The simplest solution that works.** No new layer, file or abstraction
   unless it removes real duplication or the project already uses that pattern.
   Ask: could this be done with fewer concepts?

2. **Reuse what exists.** Before writing a helper, find the one already here.
   Two call sites are not a pattern; build nothing for a third caller that does
   not exist yet.

3. **Small functions, one job per file.** A function you cannot read without
   scrolling is doing more than one thing. Split by job, never just to hit a
   line count. *Checked: one new block over 60 lines is flagged.*

4. **Name every status, code and limit once.** A bare `"blocked"`, `650` or
   `3` in a comparison cannot be found, renamed or checked against a page that
   quotes it. Use the project's constant or enum; add to it if missing.

5. **Comment only the why.** A comment earns its place when a reader could not
   recover the reason from the code: a decision, a constraint, a trap. One or
   two lines. Never restate the line below. *Checked: comment-heavy additions
   are flagged.*

6. **Show the tool's own error.** When a command or library fails, surface what
   it said. One vague sentence in its place turns a one-line fix into a hunt.

7. **No personal paths, accounts or hostnames in code.** One module reads the
   environment and builds paths; nothing else names `/Users/...`, a home
   directory or a private host. Code must run for someone who is not you.
   *Checked: personal paths are flagged.*

8. **A change in behaviour comes with a test.** Cover the behaviour, not just
   the changed lines: include a failing case and a boundary.

9. **Changing a contract bumps its version.** A saved file's shape, an API
   response, a config key -- anything read by code you did not change in the
   same commit. Bump its version and keep reading the old shape.

10. **Shorter, where it costs no clarity.** Remove what your change made dead.
    No defensive branches for cases that cannot happen, no scaffolding nothing
    uses. Never trade a readable line for a clever one.

11. **New packages are the owner's call.** Adding a dependency is a supply-chain
    decision. *Checked: a changed dependency list stops at the commit and asks
    the owner.*

## Not here, on purpose

What git, secrets and pushing need is in `git-ground-rules`. How to find your
way in the code is `find-your-way`.
