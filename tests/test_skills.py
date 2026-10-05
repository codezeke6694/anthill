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

    names = {r["name"] for r in skills.load_all(project, "local")}
    assert names == {"git-rules"}
    always_on = [s["name"] for s in skills.listing(project, always_on=True)["skills"]]
    assert "git-rules" in always_on
    assert "claude-setup" not in always_on and "_template" not in always_on


def test_must_skills_ship_with_anthill_and_a_project_skill_wins(project):
    names = {r["name"]: r for r in skills.load_all(project)}
    for must in ("find-your-way", "git-ground-rules", "git-playbook", "skill-creator", "planned-board"):
        assert names[must]["scope"] == "global", must
    assert "Propose" in skills.get(project, "skill-creator")["content"]
    always = {s["name"] for s in skills.listing(project, always_on=True)["skills"]}
    assert {"find-your-way", "git-ground-rules"} <= always
    # the project's own copy of a shipped skill is the one read
    _skill(skills.skills_dir(project), "agents/find-your-way", "reference")
    mine = [r for r in skills.load_all(project) if r["name"] == "find-your-way"]
    assert len(mine) == 1 and mine[0]["scope"] == "local" and mine[0]["overrides_global"]


def test_a_skill_is_made_only_with_the_owners_yes(project):
    import pytest
    with pytest.raises(SystemExit):
        skills.new(project, "testing/sign-in-headless", "Sign in without a browser window", "")
    out = skills.new(project, "testing/sign-in-headless", "Sign in without a browser window", "owner")
    y = (project.root / out["created"] / "skill.yaml").read_text()
    assert "approved_by: owner" in y and "approved_on:" in y
    assert "sign-in-headless" in (skills.skills_dir(project) / "INDEX.md").read_text()
    assert "(ships with Anthill)" in (skills.skills_dir(project) / "INDEX.md").read_text()
