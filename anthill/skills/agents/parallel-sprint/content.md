# parallel-sprint — Lead a planned sprint with helpers

## Purpose
A big planned sprint often holds parts that do not depend on each other: tests
for six screens, six adapters, six report pages. The owner talks to you, the
lead. You start one helper per independent piece, each in its own copy of the
project, and Anthill checks what each one brings back before it lands. The
owner never opens extra chats.

Worth it for big sprints only: every helper reads its own context, so the cost
grows with the number of helpers. A sprint of two small pieces is faster done by
you, one after the other.

## Steps

1. **Pieces.** If the sprint has none yet, cut it into pieces with the owner's
   plan in hand. Each names the files it owns and the check that proves it:
   ```bash
   anthill sprint piece add <sprint> "Tests for the Home screen" --owns "web/src/pages/Home*" --owns "tests/home/**" --check "npx vitest run tests/home"
   anthill sprint piece add <sprint> "Export button" --owns "web/src/pages/Report.tsx" --check "..." --after tests-for-the-report-screen
   ```
   Anthill refuses two pieces that would run at once and own the same file. Make
   one wait (`--after`) or split the files.

2. **Waves.** `anthill sprint waves <sprint>` says what can run now.

3. **Start the wave, all at once.** For every piece it lists, start one helper
   (in Claude Code: the Agent tool, `isolation: "worktree"`, all in one message
   so they run in parallel). The helper's whole prompt is its brief:
   `anthill sprint brief <sprint> <piece>`. Give it nothing else; the brief
   already carries the warnings and decisions that touch its files.

4. **Referee each report.** A helper ends with `BRANCH: <name>`:
   ```bash
   anthill sprint referee <sprint> <piece> --branch <name>
   ```
   - accepted → it is on the holding branch, `sprint/<sprint>`.
   - refused: outside its files, check failed, or a clash → read the reason. Send
     the same helper back once with it, or do the fix yourself. Never widen a
     piece's files to make it pass.

5. **Questions.** A helper that ends with `QUESTION: ...` stopped for the owner:
   `anthill sprint ask <sprint> <piece> "<the question>"`. Carry on with the other
   pieces; the owner answers from their page, and you resume that piece with
   the answer.

6. **Next wave.** Back to step 2 until every piece is in.

7. **Finish.** Tell the owner what is on `sprint/<sprint>` and what was refused,
   in a few lines. Merging the holding branch is the owner's call. When it is
   merged, `anthill sprint done --sprint <sprint>` runs the sprint's own check.

## Don't
- Don't start a helper without its brief, or with more than its brief.
- Don't let a helper push, merge or touch `main`. The referee merges, onto the
  holding branch only.
- Don't run two helpers on pieces of different waves at once.
- Don't answer a helper's QUESTION yourself unless the owner's written decisions
  already settle it; then log it with `anthill sprint decided`.
