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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthill import context as _ctx

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
    """Open a sprint. Archives any open one rather than losing it."""
    p = current_path(ctx)
    archived = None
    if p.exists():
        prev = json.loads(p.read_text(encoding="utf-8"))
        dest = ctx.sprints_dir / "archive" / f"{prev.get('slug', 'sprint')}.json"
        _write(dest, prev)
        archived = str(dest)
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
    out = {"created": str(p), "sprint": sprint["name"], "goal": goal}
    if archived:
        out["archived_previous"] = archived
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


def assemble_gate(ctx: _ctx.Context, unit_id: str, tests: str,
                  kind: str = "impl") -> str:
    """tests -> blueprint freshness -> audit. In that order, and never rebuilt here.

    The gate must not run `map build` itself: rebuilding regenerates every
    fingerprint from the live tree, so the freshness check could never fail and
    the ratchet would be decorative. The builder rebuilds; the gate verifies.
    """
    tests = spec_gate_for(tests) if kind == "spec" else tests.strip()
    parts = [tests] if tests.strip() else []
    bp = ctx.config.get("blueprint") or {}
    flags = ""
    if bp.get("require_page"):
        flags += " --require-page"
    if int(bp.get("min_coverage", -1)) >= 0:
        flags += f" --min-coverage {int(bp['min_coverage'])}"
    parts.append("anthill blueprint" + flags)
    if (ctx.config.get("audit") or {}).get("required", True):
        parts.append(f"anthill audit check {unit_id}")
    return " && ".join(parts)


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
                else ("spec" if u["id"].endswith(".spec") else "impl")),
            "brief": _brief(ctx, u, sprint),
            "needs_iface": u.get("depends_on") or [],
            "needs_data": [],
            "escalate_after": 2,
        })

    ids = {u["id"] for u in units}
    dangling = [{"unit": u["id"], "needs": d}
                for u in units for d in u["needs_iface"] if d not in ids]
    for u in units:
        u["needs_iface"] = [d for d in u["needs_iface"] if d in ids]

    ex = ctx.config.get("execution") or {}
    contract = {
        "version": 1,
        "project": (ctx.config.get("project") or {}).get("name") or ctx.root.name,
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
    return {
        "contract": str(dest),
        "unit_count": len(units),
        "units": [{"id": u["id"], "owns": u["owns"], "gate": u["gate"]} for u in units],
        "dangling_edges": dangling,
        "ungated_units": ungated,
        "warning": ("units without a gate cannot prove themselves"
                    if ungated else ""),
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
    lines.append("Before calling the gate: run your tests, run `anthill map build`, "
                 "and update the knowledge page for this area (re-pin "
                 "verified_against, correct any rule your change made untrue, add "
                 "a History line). The gate refuses a stale blueprint.")
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


def status(ctx: _ctx.Context) -> dict[str, Any]:
    """One screen: what the human needs to know and nothing else."""
    sprint = load(ctx)
    by_status: dict[str, list[str]] = {}
    for u in sprint["units"]:
        by_status.setdefault(u["status"], []).append(u["id"])
    return {
        "sprint": sprint["name"],
        "goal": sprint["goal"],
        "status": sprint["status"],
        "units": len(sprint["units"]),
        "by_status": by_status,
        "next_action": sprint.get("next_action", ""),
        "decisions": sprint.get("decisions", []),
    }
