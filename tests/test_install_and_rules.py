"""Re-installing keeps the owner's settings; the prose says what the config does."""
from anthill import install as inst, control, configure, rules
from conftest import reload, read_config


def test_force_reinstall_keeps_execution_settings(project):
    project.config["execution"]["push_requires_owner"] = False
    project.config["execution"]["protected_branches"] = []
    project.config["execution"]["mode"] = "pool"
    project.config["audit"]["required"] = False
    project.save_config()
    ctx = reload(project)
    out = inst.install(ctx, project_name="Proj", force=True)
    assert out["created"]
    cfg = read_config(ctx)
    assert cfg["execution"]["push_requires_owner"] is False
    assert cfg["execution"]["protected_branches"] == []
    assert cfg["execution"]["mode"] == "pool"
    assert cfg["audit"]["required"] is False


def test_claude_md_git_rules_follow_the_config(project):
    text = (project.root / "CLAUDE.md").read_text()
    assert "pre-push hook refuses every push" in text       # default: True
    configure.set_value(project, "execution.push_requires_owner", "false", by="owner")
    configure.set_value(project, "execution.protected_branches", "", by="owner")
    ctx = reload(project)
    inst.install(ctx, project_name="Proj", force=True)
    text = (ctx.root / "CLAUDE.md").read_text()
    assert "does **not** refuse pushes" in text
    assert "No branch is protected by a hook" in text
    assert "push unless the owner asked for this push" in text  # the rule survives


def test_role_file_and_brief_agree_on_map_build(project):
    builder = (project.roles_dir / "builder.md").read_text()
    assert "Run `anthill map build` before the gate" in builder
    assert "--reason" in builder and "--why" not in builder
    project.config["execution"]["isolate"] = True
    project.save_config()
    ctx = reload(project)
    inst.install(ctx, project_name="Proj", force=True)
    builder = (ctx.roles_dir / "builder.md").read_text()
    assert "Do **not** run `anthill map build`" in builder
    assert "Do **not** run `anthill map build`" in (ctx.root / "CLAUDE.md").read_text()


def test_agents_md_carries_the_same_git_rules(project):
    agents = (project.root / "AGENTS.md").read_text()
    claude = (project.root / "CLAUDE.md").read_text()
    assert rules._git_short(project) in agents
    assert rules._git_short(project) in claude


def test_control_sees_a_fresh_install_as_unchanged(project):
    out = control.check(project)
    states = {r["file"]: r["state"] for r in out["files"]}
    for f in ("CLAUDE.md", "AGENTS.md", ".anthill/owner/roles/builder.md"):
        assert states[f] == "unchanged", states


def test_control_reports_render_pending_after_config_change(project):
    configure.set_value(project, "execution.push_requires_owner", "false", by="owner")
    ctx = reload(project)
    out = control.check(ctx)
    states = {r["file"]: r["state"] for r in out["files"]}
    assert states["CLAUDE.md"] == "stale"
    assert states["AGENTS.md"] == "stale"
    assert "install --force" in out["next"]


def test_the_rules_file_is_about_sprints_and_within_its_budget(project):
    from anthill import rules
    text = (project.root / "CLAUDE.md").read_text()
    assert len(text) // 4 <= rules.RULES_BUDGET_TOKENS, len(text) // 4
    assert "anthill sprint start" in text and "anthill sprint go" in text
    assert ".anthill/owner/charter.md" in text and "CONSTITUTION.md" not in text
    assert "anthill work next" not in text                 # the board's detail is a skill now
    for stop in ("customers would see", "live data", "money", "pushing, or merging", "cannot be restored"):
        assert stop in text
