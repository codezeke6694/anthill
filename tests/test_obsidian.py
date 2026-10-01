"""The anthill drawn in Obsidian: chambers linked by their pathways, work hung on them."""
import subprocess
from pathlib import Path

from anthill import obsidian
from anthill.knowledge import claims
from conftest import commit_all

TOOL = Path(__file__).resolve().parents[1] / "bin" / "anthill"


def run(repo, *args):
    r = subprocess.run([str(TOOL), *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout


def test_chambers_link_to_what_they_use_and_the_work_on_them(project):
    (project.root / "pkg" / "billing").mkdir()
    (project.root / "pkg" / "billing" / "__init__.py").write_text('"""Charging customers."""\n')
    (project.root / "pkg" / "billing" / "invoice.py").write_text('"""Invoices."""\nfrom pkg.core import add\n\ndef total(a, b):\n    return add(a, b)\n')
    commit_all(project.root, "billing")
    wk = project.knowledge_dir / "work"
    wk.mkdir(parents=True, exist_ok=True)
    (wk / "refunds.md").write_text("---\nid: refunds\ntype: work\ntitle: Refunds on the receipt\nstate: in-progress\n"
                                   "branch: work/test\n---\n\n## Where\n\n- `pkg/billing/invoice.py`\n")
    run(project.root, "map", "build")
    out = obsidian.build(project)
    assert out["chambers"] >= 2
    mp = project.knowledge_dir / "_map"
    billing = (mp / "chambers" / "pkg.billing.md").read_text()
    assert "[[_map/chambers/pkg|pkg]]" in billing                # a pathway: billing uses pkg
    assert "[[work/refunds|Refunds on the receipt]]" in billing  # the work hangs on its chamber
    assert "[[_map/chambers/pkg.billing" in (mp / "chambers" / "pkg.md").read_text()   # and the way back
    assert "Start here.md" in [p.name for p in mp.iterdir()]


def test_it_redraws_with_the_map_and_no_check_reads_it(project):
    run(project.root, "map", "build")
    run(project.root, "obsidian")
    note = project.knowledge_dir / "_map" / "chambers" / "pkg.md"
    note.write_text("---\nid: x\n---\n\n- **BR-X-y:** stale (sg: gone.py::nothing)\n")
    run(project.root, "map", "build")                          # the hook's redraw
    assert "BR-X-y" not in note.read_text()
    assert not [c for c in claims.from_knowledge(project.knowledge_dir) if "_map" in c["source"]]
