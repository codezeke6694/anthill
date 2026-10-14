"""Tests judged by name: a test broken before the sprint does not hold it shut."""
import shlex
import subprocess
import sys

from anthill import testnames
from anthill.sprint import page
from conftest import TOOL_ROOT, commit_all


def test_failing_names_from_each_runner():
    assert testnames.failing("FAILED tests/a.py::test_x - assert 1 == 2\nERROR tests/b.py::test_y") == \
        {"tests/a.py::test_x", "tests/b.py::test_y"}
    assert testnames.failing("FAIL: test_round (pkg.tests.RoundTest)") == {"test_round (pkg.tests.RoundTest)"}
    assert testnames.failing("  ✓ adds\n  ✕ rounds half up (3 ms)\n  × keeps the sign") == \
        {"rounds half up", "keeps the sign"}
    assert testnames.failing("--- FAIL: TestRefund (0.00s)") == {"TestRefund"}
    assert testnames.failing("ok 1 - a\nnot ok 2 - refunds round half up # at x") == {"refunds round half up"}
    assert testnames.failing(" FAIL  src/refund.test.ts\n  ● Test suite failed to run") == {"src/refund.test.ts (file)"}
    assert testnames.failing("Traceback: something broke") == set()


def test_the_rule_compares_names_not_counts():
    base = {"check": "c", "failing": ["old_a", "old_b"]}
    assert testnames.judge(base, "c", False, "FAILED t.py::x\n")["passed"] is False      # unnamed old -> new name
    v = testnames.judge({"check": "c", "failing": ["t.py::a", "t.py::b"]}, "c", False, "FAILED t.py::a\n")
    assert v["passed"] and v["still_failing"] == ["t.py::a"] and v["fixed"] == ["t.py::b"]
    v = testnames.judge({"check": "c", "failing": ["t.py::a"]}, "c", False, "FAILED t.py::b\n")
    assert not v["passed"] and v["new_failures"] == ["t.py::b"] and v["fixed"] == ["t.py::a"]
    assert not testnames.judge({"check": "c", "failing": ["t.py::a"]}, "c", False, "it crashed")["passed"]
    assert not testnames.judge({"check": "other", "failing": ["t.py::a"]}, "c", False, "FAILED t.py::a")["passed"]
    assert testnames.judge(None, "c", True, "")["passed"]
    assert testnames.judge(base, "c", True, "")["fixed"] == ["old_a", "old_b"]


def cli(project, *args):
    return subprocess.run([sys.executable, str(TOOL_ROOT / "anthill" / "cli.py"), "sprint", *args],
                          cwd=project.root, capture_output=True, text=True, timeout=300)


def test_a_sprint_closes_past_a_test_that_was_already_broken(project):
    (project.root / "tests" / "core" / "test_old.py").write_text("def test_old_break():\n    assert False\n")
    commit_all(project.root, "an old break")
    check = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider tests/core"
    r = cli(project, "start", "Rounding", "--kind", "short", "--check", check)
    assert r.returncode == 0, r.stderr
    g = page.load(project, "rounding")
    assert g["baseline"]["failing"] == ["tests/core/test_old.py::test_old_break"]

    r = cli(project, "done", "--sprint", "rounding")
    g = page.load(project, "rounding")
    assert g["status"] == "done", r.stdout + r.stderr
    assert g["result"]["still_failing"] == ["tests/core/test_old.py::test_old_break"]
    assert "already failing before this sprint" in r.stdout


def test_a_new_failing_test_still_holds_it_shut(project):
    (project.root / "tests" / "core" / "test_old.py").write_text("def test_old_break():\n    assert False\n")
    commit_all(project.root, "an old break")
    check = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider tests/core"
    cli(project, "start", "Rounding", "--kind", "short", "--check", check)
    (project.root / "tests" / "core" / "test_new.py").write_text("def test_new_break():\n    assert False\n")
    r = cli(project, "done", "--sprint", "rounding")
    g = page.load(project, "rounding")
    assert g["status"] != "done"
    assert g["result"]["new_failures"] == ["tests/core/test_new.py::test_new_break"]
    assert "new failures: tests/core/test_new.py::test_new_break" in r.stdout


def test_no_baseline_when_asked_or_when_there_is_no_check(project):
    r = cli(project, "start", "Quick", "--check", "true", "--no-baseline")
    assert r.returncode == 0 and "baseline" not in page.load(project, "quick")
    cli(project, "start", "Plain")
    assert "baseline" not in page.load(project, "plain")
    cli(project, "baseline", "quick")
    assert page.load(project, "quick")["baseline"]["passed"] is True
