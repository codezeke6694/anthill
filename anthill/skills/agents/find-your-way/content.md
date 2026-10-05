# find-your-way — Starting cold in this codebase

## Purpose

Loaded every session. You know nothing about this repository yet; these two
commands give you the picture and the place, faster than reading the tree.
Neither changes anything.

## The two commands

```bash
anthill orient                                  # the codebase on one page
anthill start "<the task, in your own words>"   # where that task lives
```

- `orient` — what the product is, its chambers and what each does, how they
  connect, what changed recently, the owner's words for things, how to prove
  a change, and the rules.
- `start` — a card: the file, `look_here_first` (the lines that match your
  task), `if_you_change_this` (who uses it, the tests that name it, and a
  warning when no test covers it), and the written rules about it.

## How to use the card

The card says where to start, not where it ends. The top candidate is right
about half the time, and the right file is in the top three about three times
in four. So:

1. Read the live code at `look_here_first`.
2. If it is not the deciding line, check the other candidates
   (`anthill card <node_id> --goal "<task>"`) or follow `possible_routes` and
   `direct_consumers`.
3. Grep freely. The map is a head start, not a fence.
4. Before you change anything, read `if_you_change_this`, and run the tests it
   names.

## When the words do not match

The owner says "Home", the code says `Chains`. `.anthill/knowledge/GLOSSARY.md`
maps one to the other, and `start` uses it. If you learn a new pairing, add a
line there.
