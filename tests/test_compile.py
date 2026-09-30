"""A gate has to be able to fail, and the contract has to say what mode it runs in."""
import json

import pytest

from anthill.sprint import backlog
from anthill import roles as roles_mod
from conftest import reload


def _sprint(ctx, gate="pytest tests/core", owns="pkg/**", spec_gate=""):
    backlog.new(ctx, "S1", "goal", owner="o")
    backlog.add_unit(ctx, "core", "Core", [owns], gate, split=True, spec_gate=spec_gate)


def test_compile_carries_depends_on_and_solo_mode(project):
    _sprint(project)
    out = backlog.compile_contract(project)
    contract = json.loads(open(out["contract"]).read())
    assert contract["mode"] == "solo"
    impl = next(u for u in contract["units"] if u["id"] == "core.impl")
    assert impl["depends_on"] == ["core.spec"]
    assert impl["escalate_after"] == 0


def test_pool_mode_gets_an_attempt_budget(project):
    project.config["execution"]["mode"] = "pool"
    project.save_config()
    ctx = reload(project)
    _sprint(ctx)
    out = backlog.compile_contract(ctx)
    contract = json.loads(open(out["contract"]).read())
    assert all(u["escalate_after"] == 2 for u in contract["units"])


def test_spec_gate_collects_only(project):
    _sprint(project)
    out = backlog.compile_contract(project)
    spec = next(u for u in out["units"] if u["id"] == "core.spec")
    assert spec["gate"].startswith("pytest --collect-only tests/core")


def test_blueprint_step_dropped_for_unmapped_units(project):
    # the frontend tree is outside the map, as on a real project
    project.config["source"]["exclude_parts"].append("web")
    project.save_config()
    ctx = reload(project)
    _sprint(ctx, gate="node --test tests/core/*.mjs", owns="web/**")
    out = backlog.compile_contract(ctx)
    for u in out["units"]:
        assert "anthill blueprint" not in u["gate"], u
    assert set(out["blueprint_skipped"]) == {"core.spec", "core.impl"}


def test_audit_is_optional_when_builder_audits_itself(project):
    roles_mod.assign(project, "builder", "claude", by="o")
    roles_mod.assign(project, "auditor", "claude", by="o")
    _sprint(project)
    out = backlog.compile_contract(project)
    for u in out["units"]:
        assert "audit check " + u["id"] + " --optional" in u["gate"], u["gate"]


def test_audit_is_required_with_a_separate_auditor(project):
    roles_mod.assign(project, "builder", "claude", by="o")
    roles_mod.assign(project, "auditor", "codex", by="o")
    _sprint(project)
    out = backlog.compile_contract(project)
    for u in out["units"]:
        assert "--optional" not in u["gate"]


def test_gate_pointing_at_nothing_is_refused(project):
    _sprint(project, gate="pytest tests/nowhere")
    with pytest.raises(SystemExit) as e:
        backlog.compile_contract(project)
    assert "select no test file" in str(e.value)


def test_gate_with_wrong_extension_is_refused(project):
    (project.root / "tests" / "core" / "tokens.test.mjs").write_text("")
    _sprint(project, gate="node --test tests/core/tokens.test.mjs",
            spec_gate="test -s tests/core/tokens.test.ts")
    with pytest.raises(SystemExit) as e:
        backlog.compile_contract(project)
    assert "wrong file extension" in str(e.value)
    assert "tokens.test.mjs" in str(e.value)


def test_set_gate_then_compile(project):
    (project.root / "tests" / "core" / "tokens.test.mjs").write_text("")
    _sprint(project, gate="node --test tests/core/tokens.test.mjs",
            spec_gate="test -s tests/core/tokens.test.ts")
    backlog.set_gate(project, "core.spec", spec_gate="test -s tests/core/tokens.test.mjs")
    out = backlog.compile_contract(project)
    spec = next(u for u in out["units"] if u["id"] == "core.spec")
    assert spec["gate"].startswith("test -s tests/core/tokens.test.mjs")
    sprint = backlog.load(project)
    unit = next(u for u in sprint["units"] if u["id"] == "core.spec")
    assert unit["gate_history"][0]["from"]["spec_tests"].endswith(".ts")


def test_set_gate_unknown_unit(project):
    _sprint(project)
    with pytest.raises(SystemExit):
        backlog.set_gate(project, "nope.impl", gate="true")


def test_brief_says_run_map_build_in_place(project):
    _sprint(project)
    out = backlog.compile_contract(project)
    contract = json.loads(open(out["contract"]).read())
    assert "Run `anthill map build` before the gate" in contract["units"][0]["brief"]
    assert "Nothing escalates on its own" in contract["units"][0]["brief"]


def test_status_reads_the_board(project):
    from anthill.orchestrate import orchestrator as work
    _sprint(project)
    out = backlog.compile_contract(project)
    before = backlog.status(project)
    assert before["source"].startswith("sprint file")
    st = work.Store(project.root, root=project.state / "build" / "work" / project.root.name)
    st.init_dirs()
    work.load_board(st, project.contracts_dir / "contract.json")
    work.claim(st, "solo", "core.spec", isolate=False)
    after = backlog.status(project)
    assert after["source"] == "board"
    assert "core.spec" in after["by_status"]["in flight"]
    assert "core.impl" in after["by_status"]["blocked"]


def test_spec_gate_that_must_pass_is_warned(project):
    backlog.new(project, "S1", "goal", owner="o")
    backlog.add_unit(project, "core", "Core", ["pkg/**"], "pytest tests/core",
                     split=True, spec_gate="pytest tests/core")
    out = backlog.compile_contract(project)
    assert out["spec_gates_requiring_pass"] == ["core.spec"]
    assert "require the tests to PASS" in out["warning"]
