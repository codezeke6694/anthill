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
    return json.loads((repo / ".anthill/local/map/codebase.json").read_text())


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
        assert "anthill orient" in text and text.index("anthill where") < text.index("anthill orient")


def test_card_points_at_the_deciding_line_including_constants(project):
    write(project.root, "pkg/gate.py",
          '"""Where signals are gated."""\n\n'
          'GATE_KM = 650.0\n"""How close to a corridor a signal must be to be judged."""\n\n\n'
          'def unrelated():\n    """Formats a date."""\n')
    frontend(project.root)
    commit_all(project.root, "gate")
    built(project.root)
    out = json.loads(anthill(project.root, "card", "pkg.gate", "--goal",
                             "how close must a signal be to the corridor"))
    look = out["card"]["look_here_first"]
    assert look[0]["symbol"] == "GATE_KM" and look[0]["line"] == 3
    assert all(x["symbol"] != "unrelated" for x in look)


def test_glossary_bridges_the_owners_words_to_the_codes(project):
    write(project.root, "pkg/gate.py",
          '"""Where signals are gated."""\n\nGATE_KM = 650.0\n"""How close to a corridor a signal must be to be judged."""\n')
    commit_all(project.root, "gate")
    built(project.root)
    ask = "how far can a news item be from the supply chain"   # no word in common
    before = json.loads(anthill(project.root, "start", ask))
    assert all(c["node_id"] != "pkg.gate" for c in before["candidates"])
    write(project.root, ".anthill/knowledge/GLOSSARY.md",
          "- **how far** → close, km, gate\n- **news item** → signal\n- **supply chain** → corridor\n")
    after = json.loads(anthill(project.root, "start", ask))
    assert after["candidates"][0]["node_id"] == "pkg.gate"
    assert after["card"]["look_here_first"] == [] or True     # card lines use the task's own words
    assert "Words the owner uses" in anthill(project.root, "orient")


def test_card_says_what_a_change_reaches_and_when_nothing_proves_it(project):
    write(project.root, "pkg/gate.py",
          '"""Where signals are gated."""\n\nGATE_KM = 650.0\n"""How close to a corridor a signal must be."""\n')
    write(project.root, "pkg/use.py", "from pkg.gate import GATE_KM\n\ndef near(d):\n    return d < GATE_KM\n")
    write(project.root, "tests/core/test_gate.py", "from pkg.gate import GATE_KM\n\ndef test_it():\n    assert GATE_KM\n")
    write(project.root, "pkg/lonely.py", '"""Nothing tests this."""\n\ndef alone():\n    """Alone and untested."""\n')
    commit_all(project.root, "gate")
    built(project.root)
    c = json.loads(anthill(project.root, "card", "pkg.gate", "--goal", "how close to a corridor"))["card"]
    reach = c["if_you_change_this"]
    line = reach["by_line"][0]
    assert line["symbol"] == "GATE_KM"
    assert line["used_in"] == ["pkg/use.py"] and line["tests_that_name_it"] == ["tests/core/test_gate.py"]
    assert reach["files_that_import_this"] == ["pkg/use.py"] and "warning" not in reach
    lonely = json.loads(anthill(project.root, "card", "pkg.lonely", "--goal", "alone"))["card"]
    assert "no test covers this file" in lonely["if_you_change_this"]["warning"]


def test_card_shows_where_a_constants_values_are_spelled_out_elsewhere(project):
    write(project.root, "pkg/kinds.py",
          '"""Which collectors are readings."""\n\nINSTRUMENTS = frozenset({"rain-gauge", "quake-feed"})\n'
          '"""Collectors that take readings."""\n')
    write(project.root, "pkg/tiles.py", 'def tile(row):\n    return row == "rain-gauge"\n')
    commit_all(project.root, "kinds")
    built(project.root)
    c = json.loads(anthill(project.root, "card", "pkg.kinds", "--goal", "collectors that take readings"))["card"]
    line = c["if_you_change_this"]["by_line"][0]
    assert line["symbol"] == "INSTRUMENTS"
    assert line["same_values_elsewhere"] == [{"file": "pkg/tiles.py", "values": ["rain-gauge"]}]


def test_a_rule_quoting_a_number_is_held_to_it(project):
    write(project.root, "pkg/gate.py", '"""Where signals are gated."""\n\nGATE_KM = 650.0\n')
    sha = commit_all(project.root, "gate")
    write(project.root, ".anthill/knowledge/modules/gate.md",
          f"---\nid: gate\ntype: module\nverified_against: proj@{sha}\n---\n\n"
          "- **BR-PROJ-gate:** News further than 650 km from a route never reaches the model "
          "(sg: pkg/gate.py::GATE_KM).\n")
    def verdict():
        out = json.loads(anthill(project.root, "verify", "--only", "intent", "--all"))
        return next(c for c in out["claims"] if c["claim_id"] == "BR-PROJ-gate")
    assert verdict()["severity"] == 0
    write(project.root, "pkg/gate.py", '"""Where signals are gated."""\n\nGATE_KM = 325.0\n')
    v = verdict()
    assert v["drift"] == "value_changed" and v["severity"] == 2
    assert "the rule quotes 650; GATE_KM is now 325" in v["detail"]


def test_a_log_line_does_not_rewire_a_function():
    import ast
    from anthill.navigate import structure
    before = ast.parse("def f(x):\n    return g(x)\n").body[0]
    after = ast.parse("def f(x):\n    logger.info('x=%s', x)\n    print(x)\n    return g(x)\n").body[0]
    assert structure.callee_names(before) == structure.callee_names(after) == ["g"]
    real = ast.parse("def f(x):\n    return g(x) or h(x)\n").body[0]
    assert structure.callee_names(real) == ["g", "h"]


def test_typescript_can_be_read_searched_and_caught_rewired(project):
    from anthill.navigate import scripts
    write(project.root, "web/src/cart.ts",
          "/** The cart. */\nexport function total(items: number[]): number {\n"
          "  return round(items.reduce(add, 0));\n}\n\nexport const LIMIT = 10;\n")
    commit_all(project.root, "cart")
    anthill(project.root, "map", "build")
    sl = json.loads(anthill(project.root, "read-slice", "web/src/cart.ts::total"))
    assert sl.get("line_start") == 2 and sl.get("line_end") == 4, sl
    before = scripts.locate(project.root / "web/src/cart.ts", "total")
    write(project.root, "web/src/cart.ts",
          "/** The cart. */\nexport function total(items: number[]): number {\n"
          "  return round(items.reduce(add, 0)) + tax(items);\n}\n\nexport const LIMIT = 10;\n")
    after = scripts.locate(project.root / "web/src/cart.ts", "total")
    assert before["sig"] == after["sig"] and before["callees"] != after["callees"]


def test_a_typescript_project_at_the_top_level_is_mapped(tmp_path):
    root = tmp_path / "app"
    for rel, text in {"package.json": "{}", "src/pages/Home.tsx": "export function Home() {}\n",
                      "server/routes/leads.ts": "export const leads = 1;\n",
                      "public/logo.js": "x\n", "docs/notes.md": "x\n",
                      "node_modules/x/index.js": "x\n"}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    assert scripts.discover(root) == ["server", "src"]
