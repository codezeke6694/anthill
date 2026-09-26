"""After a commit: what it left undone is listed, remembered, handed off, and
cleared by whoever fixes it."""
import json
import subprocess
from pathlib import Path

from anthill import install as inst, rules
from conftest import commit_all, reload

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def anthill(repo: Path, *args: str) -> str:
    r = subprocess.run([str(TOOL), *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def screens(repo: Path) -> None:
    write(repo, "web/package.json", "{}")
    write(repo, "web/src/pages/Home.tsx", "/** The portfolio. */\nexport function Home() { return 1; }\n")


def upkeep(repo: Path, *args: str) -> dict:
    anthill(repo, "map", "build")
    return json.loads(anthill(repo, "upkeep", "--json", *args))


def test_a_new_screen_without_a_glossary_line_is_listed(project):
    screens(project.root)
    write(project.root, ".anthill/knowledge/GLOSSARY.md", "- **the adder** → add\n")
    commit_all(project.root, "home")
    out = upkeep(project.root)
    assert any(i["subject"] == "screen:web/src/pages/Home.tsx" for i in out["open"])


def test_a_glossary_line_naming_vanished_code_is_listed(project):
    write(project.root, ".anthill/knowledge/GLOSSARY.md", "- **adding** → add, zebracorn\n")
    commit_all(project.root, "g")
    items = [i for i in upkeep(project.root)["open"] if i["kind"] == "glossary"]
    assert len(items) == 1 and "zebracorn" in items[0]["detail"] and "add," not in items[0]["detail"]


def test_changed_code_no_test_imports_is_listed_and_tested_code_is_not(project):
    write(project.root, "pkg/lonely.py", '"""Alone."""\n\ndef alone():\n    return 1\n')
    (project.root / "pkg/core.py").write_text("def add(a, b):\n    return b + a\n")
    commit_all(project.root, "two changes")
    subjects = {i["subject"] for i in upkeep(project.root)["open"]}
    assert "file:pkg/lonely.py" in subjects
    assert "file:pkg/core.py" not in subjects          # tests/core/test_add.py imports it


def test_the_list_survives_and_clears_itself_when_fixed(project):
    write(project.root, "pkg/lonely.py", '"""Alone."""\n\ndef alone():\n    return 1\n')
    commit_all(project.root, "lonely")
    first = upkeep(project.root, "--record")
    assert first["open"]
    # an unrelated commit does not lose it
    write(project.root, "README.md", "hi\n")
    commit_all(project.root, "readme")
    assert any(i["subject"] == "file:pkg/lonely.py" for i in upkeep(project.root, "--record")["open"])
    saved = json.loads(anthill(project.root, "upkeep", "--open", "--json"))
    assert any(i["subject"] == "file:pkg/lonely.py" for i in saved["open"])
    # somebody adds the test: it clears
    write(project.root, "tests/core/test_lonely.py", "from pkg.lonely import alone\n")
    commit_all(project.root, "test lonely")
    # the post-commit hook re-checked on that commit and cleared it already
    saved = json.loads(anthill(project.root, "upkeep", "--open", "--json"))
    assert not any(i["subject"] == "file:pkg/lonely.py" for i in saved["open"])


def test_the_commit_itself_prints_the_list(project):
    write(project.root, "pkg/lonely.py", '"""Alone."""\n\ndef alone():\n    return 1\n')
    subprocess.run(["git", "add", "-A"], cwd=project.root, check=True)
    r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "x"],
                       cwd=project.root, capture_output=True, text=True)
    assert r.returncode == 0
    assert "anthill upkeep:" in r.stdout + r.stderr and "anthill-keeper" in r.stdout + r.stderr


def test_install_writes_the_keeper_and_the_handoff_rule(project):
    keeper = (project.root / ".claude/agents/anthill-keeper.md").read_text()
    assert keeper.startswith("---\nname: anthill-keeper\n")
    assert "intent_attested_by" in keeper and "Never" in keeper
    for doc in ("CLAUDE.md", "AGENTS.md"):
        assert rules.upkeep_rule(project) in (project.root / doc).read_text()


def test_a_rule_citing_a_constant_is_not_reported_missing(project):
    write(project.root, "pkg/gate.py", "GATE_KM = 650.0\n")
    commit_all(project.root, "gate")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project.root,
                          capture_output=True, text=True).stdout.strip()
    write(project.root, ".anthill/knowledge/modules/core/core.md",
          f"---\nid: core\ntype: module\ntitle: Core\nverified_against: proj@{head}\n---\n\n"
          "## Rules\n\n- **BR-X-gate:** The gate is wide (sg: pkg/gate.py::GATE_KM).\n")
    (project.root / "pkg/gate.py").write_text("GATE_KM = 700.0\n")    # content, not shape
    commit_all(project.root, "wider")
    assert not [i for i in upkeep(project.root)["open"] if i["kind"] == "knowledge"]
