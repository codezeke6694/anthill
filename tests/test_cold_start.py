"""An agent arriving cold: the map sees the frontend, knows the tests and the
history, the exam scores it honestly, and `orient` puts it all on one page.

Run through the real CLI, because the map modules bind the project root when
they are imported -- which is also exactly how an agent meets them.
"""
import json
import subprocess
from pathlib import Path

from anthill.navigate import scripts
from conftest import commit_all

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def anthill(repo: Path, *args: str) -> str:
    r = subprocess.run([str(TOOL), *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def frontend(repo: Path) -> None:
    write(repo, "web/package.json", json.dumps({"scripts": {"test": "vitest", "build": "vite build"}}))
    write(repo, "web/src/lib/theme.ts",
          "/** Light or dark, remembered, defaulting to light.\n *\n *  More words. */\n\n"
          "export const KEY = 'theme';\nexport function initialTheme(): string { return 'light'; }\n")
    write(repo, "web/src/pages/Home.tsx",
          "import { initialTheme } from '../lib/theme';\n\n"
          "/** The portfolio, at a glance. */\nexport function Home() { return initialTheme(); }\n")
    write(repo, "tests/web/theme.test.ts",
          "import { initialTheme } from '../../web/src/lib/theme';\n")


def built(repo: Path) -> dict:
    anthill(repo, "map", "build")
    return json.loads((repo / ".anthill/build/maps/codebase.json").read_text())


# --- the frontend reader ------------------------------------------------------

def test_reader_takes_the_opening_comment_exports_and_relative_imports(tmp_path):
    frontend(tmp_path)
    m = scripts.extract(tmp_path / "web/src/pages/Home.tsx", tmp_path)
    assert [s["name"] for s in m["symbols"]] == ["Home"]
    assert m["mod_doc"] == "The portfolio, at a glance."     # the export's doc stands in
    assert m["file_imports"] == {"web/src/lib/theme.ts"}
    t = scripts.extract(tmp_path / "web/src/lib/theme.ts", tmp_path)
    assert scripts.first_sentence(t["mod_doc"]) == "Light or dark, remembered, defaulting to light."


def test_discovery_finds_src_under_a_package_and_skips_node_modules(tmp_path):
    frontend(tmp_path)
    write(tmp_path, "web/node_modules/x/package.json", "{}")
    assert scripts.discover(tmp_path) == ["web/src"]
    assert scripts.discover(tmp_path, ["nope", "web"]) == ["web"]   # configured wins


def test_locate_fingerprints_the_declaration_line(tmp_path):
    frontend(tmp_path)
    hit = scripts.locate(tmp_path / "web/src/lib/theme.ts", "initialTheme")
    assert hit["line_start"] == 6
    assert scripts.locate(tmp_path / "web/src/lib/theme.ts", "gone") is None


# --- the map ------------------------------------------------------------------

def test_map_has_frontend_nodes_with_pathways_and_tests(project):
    frontend(project.root)
    commit_all(project.root, "Open in light by default")
    nodes = {n["node_id"]: n for n in built(project.root)["nodes"]}
    home, theme = nodes["web.pages.Home"], nodes["web.lib.theme"]
    assert home["file"] == "web/src/pages/Home.tsx"
    assert {"go_to": "web.lib.theme"}.items() <= home["routes"][0].items()
    assert theme["consumers"] == ["web.pages.Home"]
    assert theme["tests"] == ["tests/web/theme.test.ts"]
    assert "pkg.core" in nodes and nodes["pkg.core"]["tests"] == ["tests/core/test_add.py"]


def test_map_carries_commit_subjects_as_history(project):
    frontend(project.root)
    commit_all(project.root, "Open in light by default")
    theme = {n["node_id"]: n for n in built(project.root)["nodes"]}["web.lib.theme"]
    assert [e["s"] for e in theme["history"]] == ["Open in light by default"]


def test_frontend_anchors_do_not_go_stale_in_the_blueprint(project):
    frontend(project.root)
    commit_all(project.root, "frontend")
    built(project.root)
    r = subprocess.run([str(TOOL), "blueprint"], cwd=project.root, capture_output=True, text=True)
    assert "web/src" not in r.stdout, r.stdout


def test_router_finds_a_task_by_the_words_people_used(project):
    frontend(project.root)
    commit_all(project.root, "frontend")
    (project.root / "web/src/lib/theme.ts").write_text(
        (project.root / "web/src/lib/theme.ts").read_text() + "\n// dark\n")
    commit_all(project.root, "Open the app in dark mode by default")
    built(project.root)
    out = json.loads(anthill(project.root, "start", "make dark mode the default again"))
    assert out["card"]["you_are_here"]["file"] == "web/src/lib/theme.ts"
    assert "Open the app in dark mode by default" in out["card"]["recent_changes"]


# --- the exam -----------------------------------------------------------------

def test_exam_hides_the_commit_it_asks_about(project):
    frontend(project.root)
    commit_all(project.root, "frontend")
    (project.root / "pkg/core.py").write_text("def add(a, b):\n    return b + a\n")
    commit_all(project.root, "Zebra quokka marmalade")      # words nothing else contains
    built(project.root)
    res = json.loads(anthill(project.root, "eval-map", "--all"))
    q = [m for m in res["misses"] if m["question"] == "Zebra quokka marmalade"]
    # its only vocabulary is its own subject, so with that hidden it cannot be found
    assert q and q[0]["expected_files"] == ["pkg/core.py"]


# --- orientation --------------------------------------------------------------

def test_orient_names_chambers_proofs_and_rules(project):
    frontend(project.root)
    commit_all(project.root, "frontend")
    built(project.root)
    page = anthill(project.root, "orient")
    assert page.startswith("# You are in ")
    assert "**web.pages**" in page and "**pkg**" in page
    assert "`npm --prefix web test`" in page
    assert "anthill start" in page
    o = json.loads(anthill(project.root, "orient", "--json"))
    web_lib = next(c for c in o["chambers"] if c["chamber"] == "web.lib")
    assert web_lib["used_by"] == ["web.pages"] and web_lib["test_dirs"] == ["tests/web"]


def test_agent_docs_tell_a_cold_agent_to_orient_first(project):
    from anthill import rules
    for doc in ("CLAUDE.md", "AGENTS.md"):
        text = (project.root / doc).read_text()
        assert "anthill orient" in text and rules.cold_start_rule(project) in text
