# 04 · Does Graphify make the map better?

13 Oct 2026, on LogiAstro. **Answer: no, not for finding where a task lives.
Keep Anthill's map; Graphify is only worth it later, for languages Anthill
cannot read (PHP, Go, Java…).**

## The test

The map's own exam, unchanged: 168 past LogiAstro commits, each title asked as
a task with that commit hidden from Anthill's history; the answer is the files
it changed. Graphify 0.9.88 built its graph of the same code (`extract
--code-only`, no AI, 9 s: 4,913 symbols, 12,587 links), from a `git archive`
copy so nothing was written into the project.

Script: `experiments/graphify_compare.py` (run from the project root with
`PYTHONPATH=<anthill>`; the graph path is at its top).

| | first guess right | in top three | within one step |
|---|---|---|---|
| Anthill alone | **52%** | **67%** | 79% |
| Graphify alone (`graphify query`) | 19% | 44% | 70% |
| Anthill, Graphify's vote added to the ranking | 39–42% | 61–62% | 80% |
| Anthill, Graphify's links added to "one step" | 52% | 67% | 85% |

## Why the 85% does not count

"One step" counts a question found when the right file is a direct neighbour
of a top-three guess. Graphify's links grow that neighbour list from a median
of 20 files to 52. Adding the same number of *random* files scores 86%, so the
gain is list length, not knowledge: the agent would just have more to read.

## What it means

- Graphify answers "how is this code connected?", not "where does this task
  live?". Its query starts from name matches and walks outward; on task-shaped
  questions its first guess is right one time in five.
- The map's misses are a ranking problem — huge files doing many jobs, task
  words that are not code words — and Graphify's links do not fix ranking.
- Graphify's real advantage is breadth: ~40 languages through tree-sitter.
  If Anthill needs PHP (AutoDev's project) or Go, using Graphify's extractor for
  those files is cheaper than writing readers — measured the same way first.

## What to take from it (owner, 13 Oct)

The test above measured finding a task's file. Graphify's strength is
elsewhere: it links **functions**, not files. On LogiAstro, Anthill knows 185
places and ~440 file-to-file pathways; Graphify knows ~4,900 symbols and
~12,600 links. The owner agreed three things are worth building into Anthill:

1. **Function-level reach.** "What does this change reach?" answered as "these
   four functions call the one you changed", not "every file that imports this
   file". Matters most in huge multi-job files (Reach AI's 2,000-line
   `contacts.ts`). Anthill has callers for some Python today; none for
   TypeScript.
2. **More languages.** ~40 through tree-sitter: PHP for AutoDev's project, Go,
   Java…
3. **A trust label on every link.** Read directly from the code, or inferred
   by resolution, so an agent knows how far to rely on it.

**How.** Graphify stays optional. Anthill runs on plain Python with no
packages, and should keep doing so. When `graphify` is installed, the map
build runs `graphify update` and reads its `graph.json` for function links,
extra languages and labels. When it is not, everything works as now. Its
licence (Apache-2.0) allows this.

**Order, each one measured on the project's own history first:**

1. *Reach exam.* Past commits that changed several files: show each map the
   first file, ask what else the change reaches, score against the files that
   really changed. Anthill's pathways vs Graphify's function links. Decides
   whether 1 is worth building.
2. Build function-level reach into the card (`anthill start`) and `verify`,
   from Graphify when present.
3. Trust labels on the card's links.
4. Extra languages, when a project needs one (AutoDev/PHP first); `eval-map`
   on that project before and after.

## Result of the reach exam (13 Oct): do not build function-level reach

Script: `experiments/graphify_reach.py`. Past commits that changed 2+ mapped
files; each changed file takes a turn as the start; a map scores by naming the
other files the commit changed. "Right" is the share of named files that really
changed; "random" is a list of the same length picked at random.

**LogiAstro** (116 commits, 334 starts)

| | caught | random | right | files named |
|---|---|---|---|---|
| Anthill pathways | 28% | 4% | 8% | 7 |
| Graphify, file to file | 41% | 10% | 6% | 10 |
| Graphify, callers of the changed functions | 8% | 1% | 20% | 0–1 |
| Anthill + Graphify callers | 28% | 4% | 7% | 7 |

Only where a function's name or inputs changed (146 starts), when its callers
must change: Anthill 34% caught, Graphify callers 15%, together still 34%.

**Reach AI** (65 commits; its big multi-job files were the case for this)

| | caught | random | right | files named |
|---|---|---|---|---|
| Anthill pathways | 32% | 1% | 16% | 4 |
| Graphify, file to file | 40% | 6% | 13% | 4 |
| Graphify, callers of the changed functions | 1% | 0% | 100% | 0 |
| Anthill + Graphify callers | 32% | 6% | 16% | 4 |

**What it means.** Every file Graphify's function callers named was already on
Anthill's list: adding them caught nothing new on either project. Their callers
mostly sit in the same file or in tests. Graphify's file-to-file links catch a
little more only by naming more files, and are right less often per file named.
So items 1 and 3 of the plan above are dropped. Item 4 (languages) stands, for
when a project is in a language Anthill cannot read; measure it the same way.

What co-change cannot see: a caller that would break but was not edited in the
same commit. That needs failing-test history, which neither project keeps.

Found on the way: Anthill's map lists test files inside `.worktrees/` as a
file's tests (LogiAstro), so cards can point at another chat's copy.
