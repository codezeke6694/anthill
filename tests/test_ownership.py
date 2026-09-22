"""The boundary is measured from where the unit started, in the tree it works in."""
from pathlib import Path

from anthill.orchestrate import orchestrator as work
from conftest import commit_all, git

CONTRACT = {
    "version": 1, "project": "Proj", "base_branch": "main", "mode": "solo",
    "units": [{"id": "core.impl", "owns": ["pkg/**"], "gate": "true",
               "needs_iface": [], "needs_data": [], "escalate_after": 0}],
}


def _store(ctx) -> work.Store:
    root = ctx.state / "build" / "work" / "proj"
    st = work.Store(ctx.root, root=root)
    st.init_dirs()
    work.write_json_atomic(st.contract_path, CONTRACT)
    return st


def test_in_place_claim_records_claim_commit_and_branch(project):
    st = _store(project)
    git(project.root, "switch", "-q", "-c", "work/thing")
    brief, code = work.claim(st, "solo", "core.impl", isolate=False)
    assert code == 0
    state = st.read_state("core.impl")
    assert state["base_commit"] == git(project.root, "rev-parse", "HEAD")
    assert state["branch"] == "work/thing"
    assert state["in_place"] is True


def test_file_deleted_before_claim_is_not_a_violation(project):
    # a file outside owns, deleted and committed before the unit exists
    (project.root / "web" / "app.ts").unlink()
    commit_all(project.root, "drop web")
    st = _store(project)
    work.claim(st, "solo", "core.impl", isolate=False)
    (project.root / "pkg" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    out, code = work.gate(st, "core.impl")
    assert code == 0, out


def test_edit_outside_owns_is_named_with_the_base(project):
    st = _store(project)
    work.claim(st, "solo", "core.impl", isolate=False)
    (project.root / "web" / "app.ts").write_text("export const x = 2;\n")
    out, code = work.gate(st, "core.impl")
    assert code == work.EXIT_OWNERSHIP
    assert out["violations"] == ["web/app.ts"]
    assert out["measured_against"] == st.read_state("core.impl")["base_commit"]


def test_ownership_failure_costs_no_attempt(project):
    st = _store(project)
    work.claim(st, "solo", "core.impl", isolate=False)
    (project.root / "web" / "app.ts").write_text("x")
    work.gate(st, "core.impl")
    work.gate(st, "core.impl")
    state = st.read_state("core.impl")
    assert state["attempts"] == 0
    assert state["status"] == work.CLAIMED


def test_solo_mode_never_auto_escalates(project):
    st = _store(project)
    c = dict(CONTRACT)
    c["units"] = [dict(CONTRACT["units"][0], gate="false")]
    work.write_json_atomic(st.contract_path, c)
    work.claim(st, "solo", "core.impl", isolate=False)
    for _ in range(4):
        out, code = work.gate(st, "core.impl")
        assert code == 1
    state = st.read_state("core.impl")
    assert state["attempts"] == 4
    assert state["status"] == work.CLAIMED


def test_pool_mode_escalates_at_the_limit(project):
    st = _store(project)
    c = dict(CONTRACT)
    c["units"] = [dict(CONTRACT["units"][0], gate="false", escalate_after=2)]
    work.write_json_atomic(st.contract_path, c)
    work.claim(st, "w1", "core.impl", isolate=False)
    work.gate(st, "core.impl")
    out, code = work.gate(st, "core.impl")
    assert st.read_state("core.impl")["status"] == work.ESCALATED
    out, code = work.gate(st, "core.impl")
    assert code == work.EXIT_TERMINAL


def test_done_in_place_closes_without_merging_or_committing(project):
    st = _store(project)
    git(project.root, "switch", "-q", "-c", "work/thing")
    work.claim(st, "solo", "core.impl", isolate=False)
    (project.root / "pkg" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    head_before = git(project.root, "rev-parse", "HEAD")
    out, code = work.gate(st, "core.impl")
    assert code == 0
    out, code = work.done(st, "core.impl")
    assert code == 0, out
    assert st.read_state("core.impl")["status"] == work.DONE
    # nothing was committed on the operator's behalf, no branch was merged
    assert git(project.root, "rev-parse", "HEAD") == head_before
    assert "integration" not in git(project.root, "branch", "--list", "integration")
    assert git(project.root, "status", "--porcelain").strip()


def test_done_refused_without_a_gate(project):
    st = _store(project)
    work.claim(st, "solo", "core.impl", isolate=False)
    out, code = work.done(st, "core.impl")
    assert code == work.EXIT_NO_GATE
