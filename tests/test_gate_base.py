"""Every step of a gate measures from the commit the unit was claimed at."""
import os
import subprocess

from anthill.gates import blueprint
from anthill.orchestrate import orchestrator as work
from conftest import git

CONTRACT = {
    "version": 1, "project": "Proj", "base_branch": "main", "mode": "solo",
    "units": [{"id": "core.impl", "owns": ["pkg/**", "out.txt"],
               "gate": "sh -c 'echo base=$ANTHILL_UNIT_BASE unit=$ANTHILL_UNIT > out.txt'",
               "needs_iface": [], "needs_data": [], "escalate_after": 0}],
}


def test_gate_hands_the_unit_base_to_its_steps(project):
    root = project.work_root / "proj"
    st = work.Store(project.root, root=root)
    st.init_dirs()
    work.write_json_atomic(st.contract_path, CONTRACT)
    work.claim(st, "solo", "core.impl", isolate=False)
    base = st.read_state("core.impl")["base_commit"]
    out, code = work.gate(st, "core.impl")
    assert code == 0, out
    text = (project.root / "out.txt").read_text()
    assert f"base={base}" in text and "unit=core.impl" in text


def test_blueprint_prefers_the_unit_base_over_branch_names(project, monkeypatch):
    # an `integration` branch far behind is exactly the trap
    git(project.root, "branch", "integration")
    head = git(project.root, "rev-parse", "HEAD")
    monkeypatch.delenv("ANTHILL_UNIT_BASE", raising=False)
    assert blueprint._detect_base(project.root, "") == "integration"
    monkeypatch.setenv("ANTHILL_UNIT_BASE", head)
    assert blueprint._detect_base(project.root, "") == head
    assert blueprint._detect_base(project.root, "main") == "main"   # explicit wins
    monkeypatch.setenv("ANTHILL_UNIT_BASE", "not-a-ref")
    assert blueprint._detect_base(project.root, "") == "integration"  # unresolvable: ignored
