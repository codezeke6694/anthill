#!/usr/bin/env python3
"""Sprints: the human-facing plane, and the bridge to the enforced one.

Two formats, deliberately. A sprint is what a human reads and approves --
titles, specs, acceptance criteria, dependency order. A contract is what the
orchestrator enforces -- ids, owned paths, gate commands. Keeping them separate
is what lets the human edit intent without hand-writing shell, and lets the
foreman enforce without interpreting prose.

`compile()` is the one-way door between them. It is the moment a discussion
becomes a boundary, so it is also where the gate is assembled: tests, then
blueprint freshness, then the audit check. A unit whose gate is only its tests
can pass while leaving the blueprint stale, which is the failure this whole
system exists to prevent.

THE SPEC/IMPL SPLIT
-------------------
`add_unit(..., split=True)` emits two units instead of one:

    <area>.spec   owns the tests      written first
    <area>.impl   owns the code       depends on .spec

The builder of `.impl` therefore cannot edit the tests it must pass -- not by
policy, by ownership check. On a cold start, where an agent would otherwise
author both the work and the definition of correct, this is the only structural
defence available.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any

from anthill import context as _ctx
from anthill import rules

MAX_FILES = 3               # the mother product's cap; a larger unit is unreasonable
STATUS = ("pending", "in_flight", "blocked", "done")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def current_path(ctx: _ctx.Context) -> Path:
    return ctx.sprints_dir / "current.json"


def load(ctx: _ctx.Context) -> dict[str, Any]:
    p = current_path(ctx)
    if not p.exists():
        raise SystemExit(f"anthill: no sprint at {p}; start one with `anthill sprint new`")
    return json.loads(p.read_text(encoding="utf-8"))


def new(ctx: _ctx.Context, name: str, goal: str, owner: str = "") -> dict[str, Any]:
    """Open a sprint. Archives any open one rather than losing it.

    "Rather than losing it" is a promise, so it has to survive the case where
    the archive name is already taken. The filename was the slug alone, and a
    slug is neither unique nor under anyone's control -- on LogiAstro,
    `archive/sprint-1.json` already existed while the live sprint was also
    `sprint-1`, so opening a new one would have overwritten the earlier archive
    with no prompt and no copy. `.anthill/` is gitignored, so there is no second
    copy anywhere and nothing to recover from.
    """
    p = current_path(ctx)
    archived = None
    dropped: list[str] = []
    if p.exists():
        prev = json.loads(p.read_text(encoding="utf-8"))
        slug = prev.get("slug", "sprint")
        dest = ctx.sprints_dir / "archive" / f"{slug}.json"
        if dest.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = ctx.sprints_dir / "archive" / f"{slug}.{stamp}.json"
        _write(dest, prev)
        archived = str(dest)
        # Units of the closed sprint vanish from the board: `work load` will
        # report them as dropped and `work next` will not serve them again.
        # Their state files survive, which is right, but the units become
        # unreachable through the normal flow -- so say which ones, before the
        # fact rather than after.
        dropped = [u["id"] for u in prev.get("units", []) if u.get("id")]
    sprint = {
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "goal": goal,
        "owner": owner,
        "opened_at": _now(),
        "status": "planning",
        "units": [],
        "decisions": [],
        "next_action": "add units, then `anthill sprint compile`",
    }
    _write(p, sprint)
    out: dict[str, Any] = {"created": str(p), "sprint": sprint["name"], "goal": goal}
    if archived:
        out["archived_previous"] = archived
    if dropped:
        out["units_left_behind"] = dropped
        out["note"] = (f"{len(dropped)} unit(s) of the previous sprint are no "
                       f"longer on the board; their state files are kept but "
                       f"`work next` will not serve them")
    return out


def add_unit(ctx: _ctx.Context, area: str, title: str, owns: list[str],
             gate: str, spec: str = "", context_note: str = "",
             depends_on: list[str] | None = None, contract: str = "",
             role: str = "builder", split: bool = False,
             test_owns: list[str] | None = None,
             spec_gate: str = "") -> dict[str, Any]:
    """Add one unit, or a spec/impl pair when `split` is set."""
    sprint = load(ctx)
    existing = {u["id"] for u in sprint["units"]}
    added: list[dict[str, Any]] = []

    def make(uid: str, t: str, o: list[str], g: str, deps: list[str],
             s: str) -> dict[str, Any]:
        if uid in existing:
            raise SystemExit(f"anthill: unit {uid!r} already in this sprint")
        if len(o) > MAX_FILES and not any("**" in x or "*" in x for x in o):
            raise SystemExit(
                f"anthill: unit {uid!r} lists {len(o)} files (cap is {MAX_FILES}). "
                "Split it, or own a directory glob instead of enumerating files.")
        existing.add(uid)
        return {
            "id": uid, "area": area, "role": role, "title": t,
            "status": "pending", "owns": o, "gate": g,
            "depends_on": deps, "contract": contract,
            "context": context_note, "spec": s,
            "added_at": _now(),
        }

    if split:
        t_owns = test_owns or [f"tests/{area}/**"]
        spec_unit = make(f"{area}.spec", f"{title} — tests", t_owns, gate,
                          list(depends_on or []),
                          s=(spec or "") + "\n\nWrite the tests that define correct "
                            "behaviour for this area. Do not write the implementation.\n"
                            "Your gate proves the tests import and collect -- it does NOT "
                            "require them to pass. They should fail until the "
                            f"{area}.impl unit lands.")
        if spec_gate:
            spec_unit["spec_tests"] = spec_gate
        added.append(spec_unit)
        added.append(make(f"{area}.impl", f"{title} — implementation", owns, gate,
                          [f"{area}.spec"] + list(depends_on or []),
                          s=(spec or "") + "\n\nImplement until the tests in "
                            f"tests/{area}/ pass. You do not own those tests and "
                            "cannot change them."))
    else:
        added.append(make(f"{area}.impl" if "." not in area else area, title,
                          owns, gate, list(depends_on or []), spec))

    sprint["units"].extend(added)
    _write(current_path(ctx), sprint)
    return {"added": [u["id"] for u in added], "unit_count": len(sprint["units"]),
            "split": split}


def spec_gate_for(tests: str) -> str:
    """A `.spec` unit proves its tests EXIST and IMPORT -- never that they pass.

    Found by running the loop: giving spec and impl the same gate meant the spec
    unit had to make its own tests green, which is the opposite of test-first.
    Written correctly, the tests fail until the implementation lands, so the
    spec unit could never close and the whole split deadlocked.

    Collection is the honest proof at this stage: the tests are syntactically
    valid, they import, and pytest can see them. `--collect-only` is inserted
    for a pytest command; anything else must be supplied explicitly, because
    silently reinterpreting an arbitrary shell command would be worse than
    asking.
    """
    tests = tests.strip()
    if not tests:
        return ""
    if "pytest" in tests and "--collect-only" not in tests:
        return tests.replace("pytest", "pytest --collect-only", 1)
    return tests


# ------------------------------------------------------- does the gate bite?

# Everything `assemble_gate` appends. Stripped before looking for test paths, so
# `anthill audit check x` is not mistaken for the unit's own test selection.
_APPENDED = ("anthill blueprint", "anthill audit check", "anthill map")


def _test_command(gate: str) -> str:
    """The part of a gate that is supposed to run the unit's tests."""
    kept = [seg.strip() for seg in gate.split("&&")
            if seg.strip() and not any(seg.strip().startswith(a) for a in _APPENDED)]
    return " && ".join(kept)


def _path_tokens(command: str) -> list[str]:
    """Arguments that name a file or a glob, as opposed to flags and verbs."""
    tokens = []
    for raw in command.replace("&&", " ").split():
        tok = raw.strip("'\"")
        if tok.startswith("-") or "=" in tok.split("/")[0]:
            continue
        if "/" in tok or tok.endswith((".py", ".ts", ".tsx", ".mjs", ".js")):
            tokens.append(tok)
    return tokens


def _overlaps(token: str, glob: str) -> bool:
    """Could `token` and `glob` ever name the same file?

    Compared as directory prefixes, in both directions. A gate is written by a
    human aiming at a tree (`pytest tests/core`) while `owns` describes the same
    tree as a pattern (`tests/core/**`), and neither string matches the other
    under any glob rule -- so a literal comparison refuses exactly the
    test-first sprints this check exists to protect.
    """
    root = glob.split("*")[0].rstrip("/")
    tok = token.split("*")[0].rstrip("/")
    if not root:                      # an owns glob of `**` owns everything
        return True
    if not tok:
        return False
    return tok == root or tok.startswith(root + "/") or root.startswith(tok + "/")


def gate_selection(ctx: _ctx.Context, gate: str, owns_union: list[str]) -> tuple[str, list[str]]:
    """Does this gate command actually select any test file?

    Returns one of:
      `selects`          -- names at least one path that exists, or that a unit
                            in this sprint is going to create
      `selects_nothing`  -- names paths, and not one of them can ever match
      `wrong_extension`  -- names a concrete file that does not exist while a
                            file with the same name and a different extension
                            does (`tokens.test.ts` beside `tokens.test.mjs`)
      `unverifiable`     -- names no paths at all (`npm test`, bare `pytest`);
                            what it runs is decided by a config file this cannot
                            read

    The extension case is separate because directory overlap cannot see it: the
    path is inside a unit's `owns`, so it "resolves", and `test -s` on it fails
    forever. That failure charges an attempt, so it was about to send a unit
    back to escalation the moment its real problem was fixed.

    This exists because of the worst outcome the system can produce. A gate
    pointed at a glob that matches nothing exits 0, `work done` accepts it, and
    the unit closes having proved nothing -- the system is not stuck, it is
    confidently wrong, and green is the one signal everything else trusts. It
    nearly happened here: two units were given `npm --prefix web test`, while
    `web/vite.config.ts` pins vitest to `../tests/mapping-web/**`, and the tests
    in question lived in `tests/design-system/`. They would never have been
    collected. It was caught by reading the runner config on a hunch.

    A path inside some unit's `owns` counts as resolving even when it does not
    exist yet: under test-first the `.spec` unit writes those files after the
    contract is compiled, so requiring them on disk now would refuse every
    correctly-ordered sprint.
    """
    command = _test_command(gate)
    tokens = _path_tokens(command)
    if not tokens:
        return ("unverifiable" if command.strip() else "selects_nothing"), []
    unresolved = []
    misnamed = []
    for tok in tokens:
        if list(ctx.root.glob(tok)):
            continue
        sib = _sibling_with_other_suffix(ctx.root, tok)
        if sib:
            misnamed.append(f"{tok} (found {sib})")
            continue
        if any(PurePath(tok).full_match(g) for g in owns_union):
            continue
        if any(_overlaps(tok, g) for g in owns_union):
            continue
        unresolved.append(tok)
    if misnamed:
        return "wrong_extension", misnamed
    if unresolved and len(unresolved) == len(tokens):
        return "selects_nothing", unresolved
    return "selects", unresolved


def _sibling_with_other_suffix(root: Path, token: str) -> str:
    """`tests/x/tokens.test.ts` when only `tests/x/tokens.test.mjs` exists."""
    if "*" in token:
        return ""
    p = PurePath(token)
    d = root / p.parent
    if not d.is_dir() or not p.suffix:
        return ""
    stem = p.name[: -len(p.suffix)]
    for q in d.iterdir():
        if q.is_file() and q.name != p.name and q.name.startswith(stem + "."):
            return str(PurePath(p.parent) / q.name)
    return ""


def mapped_by_blueprint(ctx: _ctx.Context, owns: list[str]) -> bool:
    """Can the blueprint say anything at all about what this unit owns?

    The map parses Python under the configured source roots, so a unit whose
    every owned path sits in `exclude_parts` -- the whole frontend tree, the
    tests tree -- gets a gate step that passes no matter what it did. A step
    that cannot fail is not a check; it is a line of output that looks like one,
    and on a red gate it sends the reader looking in the wrong place.

    Deliberately conservative: only an owns glob whose leading directory is
    *explicitly excluded* counts as unmapped. Anything ambiguous keeps the
    check, because wrongly dropping it weakens a real gate while wrongly keeping
    it only costs a no-op.
    """
    if not owns:
        return False
    _, _, exclude = ctx.source_roots()
    for glob in owns:
        head = PurePath(glob).parts[0] if PurePath(glob).parts else ""
        if head and head not in exclude:
            return True
    return False


def assemble_gate(ctx: _ctx.Context, unit_id: str, tests: str,
                  kind: str = "impl", owns: list[str] | None = None) -> str:
    """tests -> blueprint freshness -> audit. In that order, and never rebuilt here.

    The gate must not run `map build` itself: rebuilding regenerates every
    fingerprint from the live tree, so the freshness check could never fail and
    the ratchet would be decorative. The builder rebuilds; the gate verifies.

    The blueprint step is dropped for a unit the map does not cover -- see
    `mapped_by_blueprint`. The audit step never is: an audit is about intent,
    and intent applies to a stylesheet exactly as much as to a parser.
    """
    tests = spec_gate_for(tests) if kind == "spec" else tests.strip()
    parts = [tests] if tests.strip() else []
    if owns is not None and not mapped_by_blueprint(ctx, owns):
        parts.extend(audit_step(ctx, unit_id))
        return " && ".join(parts)
    bp = ctx.config.get("blueprint") or {}
    flags = ""
    if bp.get("require_page"):
        flags += " --require-page"
    if int(bp.get("min_coverage", -1)) >= 0:
        flags += f" --min-coverage {int(bp['min_coverage'])}"
    parts.append("anthill blueprint" + flags)
    parts.extend(audit_step(ctx, unit_id))
    return " && ".join(parts)


def audit_step(ctx: _ctx.Context, unit_id: str) -> list[str]:
    """The audit condition, honest about what it is worth here.

    `audit check` exits 3 while nobody has reviewed the unit, and a required
    audit makes that block the close. When the builder and the auditor are the
    same identity the tool itself says a PASS "carries almost no information" --
    yet the step was mandatory, and its absence produced the first false
    escalation on the first real sprint. So with no independence the step runs
    `--optional`: a recorded FAIL still refuses, a missing review no longer
    holds the unit hostage to a formality.
    """
    if not (ctx.config.get("audit") or {}).get("required", True):
        return []
    from anthill import roles as roles_mod
    try:
        ind = roles_mod.independence(ctx).get("independence", "")
    except Exception:                                   # pragma: no cover
        ind = ""
    flag = " --optional" if ind == "none" else ""
    return [f"anthill audit check {unit_id}{flag}"]


def compile_contract(ctx: _ctx.Context, out: Path | None = None,
                     base_branch: str = "") -> dict[str, Any]:
    """Turn the approved sprint into a contract the orchestrator enforces.

    An auditor unit is emitted for every builder unit, owning nothing -- so the
    auditor is read-only by ownership check rather than by instruction.
    """
    sprint = load(ctx)
    if not sprint["units"]:
        raise SystemExit("anthill: this sprint has no units")

    units: list[dict[str, Any]] = []
    for u in sprint["units"]:
        units.append({
            "id": u["id"],
            "title": u["title"],
            "role": u.get("role", "builder"),
            "owns": u["owns"],
            "gate": assemble_gate(
                ctx, u["id"],
                # An explicit spec command is used verbatim; a derived one is
                # transformed. Either way the blueprint and audit conditions are
                # appended by assemble_gate -- a unit cannot opt out of those.
                u.get("spec_tests") or u.get("gate", ""),
                kind="verbatim" if u.get("spec_tests")
                else ("spec" if u["id"].endswith(".spec") else "impl"),
                owns=u["owns"]),
            "brief": _brief(ctx, u, sprint),
            # `needs_iface` is what the orchestrator schedules on. `depends_on`
            # is carried alongside it because the contract is described as the
            # source of truth for what a unit waits on, and a reader of the
            # contract alone could not see the dependency graph at all.
            "depends_on": list(u.get("depends_on") or []),
            "needs_iface": u.get("depends_on") or [],
            "needs_data": [],
            # 0 means never: in solo mode one interactive agent escalates by
            # judgement, not by count. See rules.escalation_rule.
            "escalate_after": 2 if rules.mode(ctx) == "pool" else 0,
        })

    ids = {u["id"] for u in units}
    dangling = [{"unit": u["id"], "needs": d}
                for u in units for d in u["needs_iface"] if d not in ids]
    for u in units:
        u["needs_iface"] = [d for d in u["needs_iface"] if d in ids]

    # Does each gate actually bite? A gate that selects no tests is the only
    # failure on this list that lets bad work through rather than blocking good
    # work, so it is refused here rather than reported.
    owns_union = [g for u in units for g in u["owns"]]
    vacuous, unverifiable, misnamed = [], [], []
    for u in units:
        if not u["gate"].strip():
            continue
        verdict, unresolved = gate_selection(ctx, u["gate"], owns_union)
        if verdict == "selects_nothing":
            vacuous.append({"unit": u["id"], "gate": u["gate"],
                            "matches_nothing": unresolved})
        elif verdict == "wrong_extension":
            misnamed.append({"unit": u["id"], "gate": u["gate"], "files": unresolved})
        elif verdict == "unverifiable":
            unverifiable.append({"unit": u["id"], "gate": u["gate"]})
    if misnamed:
        detail = "\n".join(
            f"  {m['unit']}\n    gate: {m['gate']}\n    "
            f"names a file that does not exist, next to one that does: "
            f"{', '.join(m['files'])}" for m in misnamed)
        raise SystemExit(
            "anthill: refusing to compile -- these gates name the wrong file "
            "extension, so they would fail forever and charge the unit for it:\n"
            + detail + "\n\nFix the gate with `anthill sprint set-gate <unit> "
            "\"<command>\"` and compile again.")
    if vacuous:
        detail = "\n".join(
            f"  {v['unit']}\n    gate: {v['gate']}\n    matches nothing: "
            f"{', '.join(v['matches_nothing'])}" for v in vacuous)
        raise SystemExit(
            "anthill: refusing to compile -- these gates select no test file, "
            "so they would pass without proving anything:\n" + detail +
            "\n\nA gate that cannot fail closes its unit on an empty result. "
            "Point it at a path the unit or its paired .spec unit owns.")

    ex = ctx.config.get("execution") or {}
    contract = {
        "version": 1,
        "project": (ctx.config.get("project") or {}).get("name") or ctx.root.name,
        "mode": rules.mode(ctx),
        "isolate": bool(ex.get("isolate", False)),
        "base_branch": base_branch or ex.get("base_branch") or "main",
        "kernel_path": "",
        "sprint": sprint["name"],
        "seed_working_state": bool(ex.get("seed_working_state")),
        "seed_paths": list(ex.get("seed_paths") or []),
        "units": units,
    }
    dest = out or (ctx.contracts_dir / "contract.json")
    _write(dest, contract)

    sprint["status"] = "execution"
    sprint["compiled_at"] = _now()
    sprint["contract"] = str(dest)
    sprint["next_action"] = "`anthill work plan`, then run the pool"
    _write(current_path(ctx), sprint)

    ungated = [u["id"] for u in units if not u["gate"].strip()]
    unmapped = [u["id"] for u in units if not mapped_by_blueprint(ctx, u["owns"])]
    # A spec unit whose gate needs its tests to *pass* can only close once the
    # implementation exists, which is the deadlock the split was built to
    # avoid. Two units here were created that way with an explicit --spec-gate.
    spec_must_pass = [u["id"] for u in units
                      if u["id"].endswith(".spec") and "pytest" in u["gate"]
                      and "--collect-only" not in _test_command(u["gate"])]
    warnings = []
    if ungated:
        warnings.append("units without a gate cannot prove themselves")
    if spec_must_pass:
        warnings.append(
            "these .spec gates require the tests to PASS, so they cannot close "
            "before the implementation exists (use --collect-only): "
            + ", ".join(spec_must_pass))
    if unverifiable:
        warnings.append(
            "these gates name no test path, so what they run is decided by a "
            "runner config this cannot read -- check the config points at the "
            "unit's tests: "
            + ", ".join(v["unit"] for v in unverifiable))
    if unmapped:
        warnings.append(
            "the blueprint step was left out for units the map does not cover "
            "(every owned path is in source.exclude_parts): " + ", ".join(unmapped))
    return {
        "contract": str(dest),
        "unit_count": len(units),
        "units": [{"id": u["id"], "owns": u["owns"], "gate": u["gate"]} for u in units],
        "mode": rules.mode(ctx),
        "spec_gates_requiring_pass": spec_must_pass,
        "dangling_edges": dangling,
        "ungated_units": ungated,
        "unverifiable_gates": unverifiable,
        "blueprint_skipped": unmapped,
        "warning": "; ".join(warnings),
    }


def _brief(ctx: _ctx.Context, unit: dict, sprint: dict) -> str:
    lines = [f"Role: {unit.get('role', 'builder')}. "
             f"Read .anthill/roles/{unit.get('role', 'builder')}.md before anything else.",
             f"Sprint: {sprint['name']} — {sprint['goal']}",
             f"Unit: {unit['title']}"]
    if unit.get("contract"):
        lines.append(f"Contract (read-only, implement exactly): {unit['contract']}")
    if unit.get("context"):
        lines.append(f"Context: {unit['context']}")
    if unit.get("spec"):
        lines.append(f"Spec:\n{unit['spec']}")
    lines.append("Before calling the gate: run your tests and update the knowledge "
                 "page for this area (re-pin verified_against, correct any rule "
                 "your change made untrue, add a History line). "
                 + rules.map_build_rule(ctx))
    lines.append(rules.escalation_rule(ctx))
    lines.append("Never fill intent_attested_by — that is a human's signature.")
    return "\n".join(lines)


# ------------------------------------------------------------------- lessons

def record_lesson(ctx: _ctx.Context, area: str, lesson: str,
                  unit: str = "", kind: str = "lesson") -> dict[str, Any]:
    """A lesson is filed under the area it came from, not into a chronology.

    A log written for completeness is never read. A lesson attached to an area
    surfaces the next time that area is worked, which is the only moment it can
    change an outcome.
    """
    p = ctx.log_dir / "lessons" / f"{area}.json"
    entries = []
    if p.exists():
        try:
            entries = json.loads(p.read_text(encoding="utf-8")).get("entries", [])
        except (OSError, json.JSONDecodeError):
            entries = []
    entries.append({"at": _now(), "unit": unit, "kind": kind, "lesson": lesson})
    _write(p, {"area": area, "entries": entries})
    return {"area": area, "recorded": len(entries), "path": str(p)}


def lessons_for(ctx: _ctx.Context, area: str) -> dict[str, Any]:
    p = ctx.log_dir / "lessons" / f"{area}.json"
    if not p.exists():
        return {"area": area, "entries": [], "note": "nothing recorded for this area yet"}
    return json.loads(p.read_text(encoding="utf-8"))


def set_gate(ctx: _ctx.Context, unit_id: str, gate: str = "",
             spec_gate: str = "") -> dict[str, Any]:
    """Change what proves a unit, after the fact.

    `add-unit` was the only writer, so a gate typed with the wrong extension
    could only be corrected by editing the sprint JSON by hand -- the thing every
    other part of this tool refuses to require. The sprint is re-marked as
    needing a compile, because the contract still carries the old command.
    """
    sprint = load(ctx)
    unit = next((u for u in sprint["units"] if u["id"] == unit_id), None)
    if unit is None:
        raise SystemExit(f"anthill: no unit {unit_id!r} in this sprint")
    if not gate and not spec_gate:
        raise SystemExit("anthill: give --gate, --spec-gate, or both")
    before = {"gate": unit.get("gate", ""), "spec_tests": unit.get("spec_tests", "")}
    if gate:
        unit["gate"] = gate.strip()
    if spec_gate:
        unit["spec_tests"] = spec_gate.strip()
    unit.setdefault("gate_history", []).append(
        {"at": _now(), "from": before,
         "to": {"gate": unit.get("gate", ""), "spec_tests": unit.get("spec_tests", "")}})
    sprint["next_action"] = "`anthill sprint compile`, then `anthill work load`"
    _write(current_path(ctx), sprint)
    return {"unit": unit_id, "gate": unit.get("gate", ""),
            "spec_tests": unit.get("spec_tests", ""),
            "next": "anthill sprint compile && anthill work load --repo ."}


def board_states(ctx: _ctx.Context) -> dict[str, str]:
    """Unit status as the board computes it, keyed by unit id. Empty if no board.

    Computed, not read off disk: a unit nobody has touched has no state file
    yet, and the board still knows whether it is blocked or ready.
    """
    from anthill.orchestrate import orchestrator as work
    root = ctx.state / "build" / "work" / re.sub(r"[^A-Za-z0-9._-]+", "-", ctx.root.name)
    if not (root / "contract.json").exists():
        return {}
    store = work.Store(ctx.root, root=root)
    try:
        st = work.status(store)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for label, key in (("done", "done"), ("ready", "ready"),
                       ("escalated", "escalated")):
        for uid in st.get(key) or []:
            out[uid] = label
    for uid in st.get("in_flight") or []:
        out[uid] = "in flight"
    try:
        for u in store.load_contract().get("units") or []:
            out.setdefault(str(u["id"]), "blocked")
    except Exception:
        pass
    return out


def status(ctx: _ctx.Context) -> dict[str, Any]:
    """One screen: what the human needs to know and nothing else.

    Unit status comes from the board when there is one. The sprint file kept
    its own `pending` on every unit forever -- nothing ever wrote back -- so
    `sprint status` said sixteen pending while `work status` said eight done.
    Two records of one fact, never reconciled, is how a reader stops trusting
    both.
    """
    sprint = load(ctx)
    board = board_states(ctx)
    by_status: dict[str, list[str]] = {}
    for u in sprint["units"]:
        st = board.get(u["id"]) or u.get("status", "pending")
        if u["id"] not in board and u.get("status") == "pending":
            st = "not on board"
        by_status.setdefault(st, []).append(u["id"])
    return {
        "sprint": sprint["name"],
        "goal": sprint["goal"],
        "status": sprint["status"],
        "units": len(sprint["units"]),
        "by_status": by_status,
        "source": "board" if board else "sprint file (no board yet)",
        "next_action": sprint.get("next_action", ""),
        "decisions": sprint.get("decisions", []),
    }
