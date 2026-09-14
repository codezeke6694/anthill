# The Ant Hill — How LogiAstro Gets Built

**Document status:** Working model for the build system. Companion to `01-core-idea.md` (what we're building); this is *how*.
**Last updated:** 2026-09-03

> **Superseded in part.** The tooling described here was reorganised into the
> `anthill/` package (see `anthill/README.md`), which added the sprint plane,
> the builder/auditor roles, the audit gate, and installable project
> resolution. The model in §1–§6 still holds; the file paths and command names
> do not. `emergent_agent/` no longer exists in this repository.

---

## 1. The Model

> We are building something. As we build, we make a blueprint of the code. When we need to check something, we search the blueprint rather than crawling the tunnels — and send targeted work there.
>
> Code blocks are **chambers**. The functions calling them are **tunnels**. Each chamber connects to different tunnels landing on other areas.
>
> The **orchestrator** digs chambers and tunnels. The **knowledge builder** draws the blueprint while the orchestrator works. The **navigator** remembers everything and knows how the blueprint works.

This is not a metaphor laid over the tooling. It is what the tooling computes.

| Ant hill | What it actually is |
|---|---|
| **Chamber** | a *node* — one responsibility node per module (a behaviour boundary) |
| **Tunnel** | a *route* — the within-repo import graph, lifted to node-level |
| **Which tunnels land here** | `consumers`, computed per node |
| **The blueprint** | `.anthill/build/maps/codebase.json` — nodes, anchors, routes, consumers |
| **Consult the blueprint, don't crawl** | `cli.py start "<goal>"` → one bounded card + an address → `read-slice` reads *that symbol only* |
| **Targeted work sent to a chamber** | a board unit whose `owns` = that chamber's paths |
| **The navigator remembers** | the **structural fingerprint** — signature + callee set + caller set, body deliberately excluded |

That last row is what makes "the navigator remembers everything" real. It answers one question deterministically: *has the thing I cited changed shape?*

- Edit a formula **inside** a chamber → body changes, fingerprint holds → no claim is stale.
- **Re-dig** the chamber or **re-route** its tunnels → fingerprint breaks → claims need review.

Weeks of ordinary work invalidate nothing. A change that could falsify a recorded statement is caught mechanically. No model calls at build time or query time.

---

## 2. Three Authorities an Agent Cannot Forge

The load-bearing idea. One authority per plane:

| Plane | Role in the hill | Authority | What it prevents |
|---|---|---|---|
| **Navigation** | the navigator | structural fingerprint | claiming an address that isn't there |
| **Intent** | the blueprint's meaning | a human's signature (`intent_attested_by`) | claiming intent |
| **Execution** | the foreman | a gate's exit code | claiming "done" |

**An agent cannot assert completion.** `work done` returns `EXIT_NO_GATE (65)` unless a gate actually passed. Nothing else closes a unit.

### The foreman digs nothing

Important correction to the model: the orchestrator does **not** cut chambers. The **agents** dig. The orchestrator is the foreman — it hands out chambers, provisions each digger an isolated git worktree, enforces that nobody digs outside their assignment, and refuses to sign off without proof.

That distinction is the leverage point, not a quibble. Because the foreman signs off, the foreman is where we clip on *"no sign-off without a blueprint entry."* See §5.

---

## 3. Two Regimes

A knowledge page may only scope work if **all** of these hold:

- `verified_against: logiastro@<sha>` — a real, reachable commit, not `REPLACE_ME`
- a `footprint` whose globs **match actual files on disk**
- no footprint overlap with any other page
- no symbol drift since the pin

So a page describing a chamber that does not exist yet is **refused**. Deliberately — refusal is the safe default, because one stale page becomes a wrong board.

### Regime 1 — `build` mode (where LogiAstro is today)

Zero code means every area reports:

> *"no page can scope work yet, so every area starts in build mode"*

Here, humans and Claude dig the first chamber of each area the normal way. The orchestrator contributes nothing. What we *can* do now: declare the areas, and accumulate pages as honest drafts (`verified_against: REPLACE_ME` → flagged `draft_pin`, correctly refused from scoping work).

### Regime 2 — `improve` mode (once a chamber exists and is committed)

The full loop turns on:

```
1. build_map.py            → draw the blueprint: nodes, anchors, routes
                             + structural fingerprints
2. author the page         → footprint globs + verified_against logiastro@<sha>
   cli.py pages            → validate frontmatter, pin, footprint, overlap
3. cli.py readiness        → that area flips build → improve
4. cli.py board            → CONTRACT: one unit per verifying page
                             owns  = footprint + the page itself
                             gate  = tests AND blueprint_fresh   ← §5
                             brief = its BR- rules, quoted with stable IDs
5. cli.py work pool -n 4   → 4 diggers race for units. No dispatcher.
                             Each wins an atomic claim + its own worktree
6. the digger works        → reads the page, edits ONLY inside `owns`
7. cli.py work gate        → ownership check, then the gate
                             wrote outside owns? EXIT_OWNERSHIP (64)
8. cli.py work done        → no passing gate? refused. Else merge to integration
                             the unit owns its page: re-pin it to the new commit
9. cli.py verify           → re-check every recorded claim vs the live tree
```

**Why parallel diggers are safe.** Pages must *partition* the code — overlapping footprints are a validation error. Ownership is by path, not by lock, so collisions are structurally impossible rather than negotiated. A dead digger's lock ages out and its chamber returns to the board. That is the whole scheduler, and it is why adding diggers needs no coordination.

**What controls parallelism.** A page's `related` becomes `needs_data` — a *serialising* dependency — because the schema cannot say which relations are interface-only, and assuming the parallel-friendly answer would let a digger build against an interface that is not frozen. Declare `needs_iface` explicitly to let units run concurrently.

---

## 4. The Gap This System Had

The design already intended the blueprint to grow alongside the code. Every unit **owns its own page**, and the brief instructs:

> "This unit owns its page as well as its code. When the change lands, update the page: re-pin `verified_against` to the commit you produce, correct any rule the change makes untrue, and add a History line. Never fill `intent_attested_by` — that is a human's signature."

But that was an **instruction**, not an **enforcement**. Three reasons:

1. `build_map.py` is a pure function of the working tree — it can only draw chambers that already exist, so the blueprint lags the digging by one run.
2. A page cannot be finalised until its chamber exists (the footprint must resolve).
3. **The gate never looked at the blueprint.** `work done` needed one thing: a passing test command. And `cli.py verify` reports drift but **always exits 0**.

Net effect: a digger could cut a chamber, pass its tests, close its unit, and never draw the tunnel. The hill grows; the blueprint quietly rots; nothing objects.

---

## 5. The Ratchet — `anthill blueprint`

Blueprint freshness is now a **gate condition**. Composed into any gate:

```bash
python3 -m pytest -q tests/sensing/ && anthill blueprint
```

*"You cannot close a chamber without drawing it"* stops being advice in a brief and becomes the same kind of fact as a failing test.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | blueprint holds for everything in scope |
| `1` | stale claims in scope, or coverage below `--min-coverage` |
| `2` | usage / environment error |

### Scoping — why the default is not the whole ledger

The maps cover the entire tree, so an unscoped check would fail unit A for drift that unit B caused. The gate runs with `cwd` set to the unit's own worktree and receives **no environment variables** (only `setup_cmd` does), so `owns` cannot be passed in from outside.

It doesn't need to be: **the worktree's diff against the integration branch *is* this unit's footprint.** Scope to that and blame lands where it belongs.

This is safe against the "my change broke someone else's claim" case because drift is *graded*, not flattened. A change that alters some other symbol's caller set scores `recontextualized` (severity 1) — below the refusal threshold by design. What fails a unit is drift in a symbol it actually touched.

### Drift severities

| Drift | Severity | Refuses by default | Meaning |
|---|---|---|---|
| `missing` | 4 | yes | the symbol is gone entirely |
| `moved` | 3 | yes | same name, different file |
| `reshaped` | 3 | yes | the signature moved — the recorded contract is wrong |
| `rewired` | 2 | yes | its callee set changed — it does other things now |
| `recontextualized` | 1 | no | its callers moved — impact has shifted |

### Options

| Flag | Effect |
|---|---|
| `--all` | check the whole ledger, not just this worktree's diff |
| `--base REF` | ref to diff against (default: `integration`, `main`, `master`) |
| `--threshold N` | minimum severity that refuses (default 2) |
| `--knowledge DIR` | knowledge dir (default `.anthill/knowledge`) |
| `--contract PATH` | also check execution-plane ownership claims |
| `--min-coverage PCT` | also refuse if the share of mapped files with a page is below `PCT` |
| `--require-claims` | refuse when the ledger is empty — an *undrawn* blueprint is not a fresh one |
| `--json` | machine-readable output |

`--require-claims` closes the quietest failure mode: nothing recorded means nothing can be found stale, so an empty ledger would otherwise pass.

### Verified behaviour

Tested end to end against the real tree:

| Step | Result |
|---|---|
| Blueprint drawn, tree untouched | `holds` — exit 0, 66/66 claims checked |
| Signature changed, blueprint not redrawn | `stale` — exit 1, names the symbol and the remedy |
| Blueprint redrawn | `holds` — exit 0 |
| Empty ledger | passes with a loud warning; `--require-claims` makes it exit 1 |

The refusal message is specific rather than generic — it names the drift kind, the address, and what to do about it (`the signature moved -- the recorded contract is now wrong`).

---

## 6. Two Commands That Measure Blueprint Drift

- **`cli.py coverage`** — chambers that exist but no blueprint entry explains, ranked by size, because size is the proxy for risk. It exists because a real bug was traced to an 813-line file with two map anchors and *zero* knowledge rules, and nothing in the system said so.
- **`cli.py verify`** — blueprint entries that no longer match their chamber, with the drift **attributed** rather than reduced to pass/fail. "Its signature changed" and "its callers changed" demand different responses.
- **`cli.py harvest`** — a collapsed tunnel becomes a marked hazard: an escalation (the moment a rule turned out to be wrong about the code) is drafted into a page instead of dying in a log.

---

## 7. Inherited Doctrine — From Prose Rules to Mechanical Gates

The predecessor system (Peregrine, "mother product") ran the *same* ideas as **prose instructions to agents**. The current system is the enforced version. Worth knowing which is which, because the prose half still carries things the enforced half dropped.

| Idea | Prose version (Peregrine) | Enforced version (now) |
|---|---|---|
| Path ownership | `**Owns:** …` / `**Never touches:** …` in a role file | `check_ownership()` over `git diff`; `EXIT_OWNERSHIP (64)` |
| Proof of done | "Never mark a task done unless the `verify:` commands pass" | gate exit code; `done` refused with `EXIT_NO_GATE (65)` |
| Claiming work | "claim a section" | atomic lock + isolated worktree; races settle themselves |
| Blocked | "write an issue, set status blocked, **stop**. Do not guess, do not work around" | `escalate`, `escalate_after: 2`, then `harvest` → knowledge |
| Interfaces | "Contracts are read-only. If a contract seems wrong, write an issue and stop" | `needs_iface` / `needs_data` dependency edges |

### Still worth taking from the prose layer

Things the enforced system has no equivalent for:

1. **Roles.** Peregrine had Planner / Backend / Frontend / Database / Auditor, each with a declared scope. The current board has no notion of role — every unit is identical. LogiAstro will have a TypeScript frontend and a Python backend, so role-scoped diggers matter.
2. **A constitution with an explicit authority chain:**
   ```
   Owner directive → CONSTITUTION.md → AGENTS.md → backlog → repo code
   ```
   Single human-owned source of truth that outranks everything, editable only by the Planner. The current system has `intent_attested_by` (a human signature per page) but nothing that outranks a page.
3. **Load-order discipline.** *"Load only what your role specifies. No more."* This is exactly *consult the blueprint, don't crawl the tunnels* — stated as context hygiene.
4. **The task-size cap.** *"If a task lists more than 3 files, write an issue asking the Planner to split it — do not proceed."* A cheap, effective guard against units that cannot be reasoned about.

---

## 8. Prerequisites

| # | Needed | Status |
|---|---|---|
| 1 | `git init` + a first commit | **Missing.** Everything depends on it — worktrees, `verified_against` shas, commit-reachability checks |
| 2 | Retarget `INCLUDE_DIRS` in `build_map.py:41` and `structure.py:37` | Blocked until a source layout exists. **The two must match** or callers look spuriously deleted |
| 3 | Declared areas for `kb init` | Derivable from `01-core-idea.md` — e.g. `mapping`, `sensing`, `alerts`, `tasks`, `dashboard`, `insights` |
| 4 | A test suite + per-area gate commands | **The load-bearing one.** ⬇ |

**On #4.** The gate *is* the enforcement mechanism. The predecessor's gate config records why explicit file lists beat a templated pattern: a templated gate "collected all 969 tests and proved nothing." LogiAstro has zero tests, so every unit would be born ungated — and an ungated unit cannot prove itself.

**Practical read: this system pays off if LogiAstro is test-first from day one.** If tests come later, the navigation and intent planes still work; the multi-agent execution plane does not.

---

## 9. Known Limitations

- **Structural fingerprinting is Python-only.** `build_map.py` and `structure.py` parse with `ast`. Non-Python citations degrade to a path-existence check. The knowledge plane itself is language-neutral — "a page is markdown in every project" — so a TypeScript frontend gets pages, boards, gates, and ownership, but **not** structural drift detection.
- **The blueprint lags by one run.** `build_map.py` must be re-run after structural change. The gate in §5 is what forces that to happen.
- **`.anthill/build/` is generated output** and is gitignored by `anthill install`.

---

## 10. Open Decisions

- Source layout for LogiAstro (settles prerequisite #2)
- Final area list (settles #3)
- Test framework and per-area gate commands (settles #4)
- Whether to port the role system and constitution from §7, or run role-less initially
- Whether `--min-coverage` becomes a gate condition, and at what floor, once real coverage exists
