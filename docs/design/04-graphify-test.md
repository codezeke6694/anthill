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
