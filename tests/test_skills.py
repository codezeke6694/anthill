"""Skills: what a chat is told to load."""
from __future__ import annotations

from anthill import skills


def _skill(root, rel, load_class):
    d = root / rel
    d.mkdir(parents=True)
    (d / "skill.yaml").write_text(f"name: {d.name}\nload_class: {load_class}\nalways_on: true\n")
    (d / "content.md").write_text("# " + d.name + "\n")


def test_retired_and_template_skills_are_not_listed(project):
    root = skills.skills_dir(project)
    _skill(root, "development/git-rules", "bootstrap")
    _skill(root, "_archive/old-set/agents/claude-setup", "bootstrap")
    _skill(root, "_template", "bootstrap")

    names = {r["name"] for r in skills.load_all(project)}
    assert names == {"git-rules"}
    always_on = skills.listing(project, always_on=True)
    assert [s["name"] for s in always_on["skills"]] == ["git-rules"]
    assert always_on["total_installed"] == 1
