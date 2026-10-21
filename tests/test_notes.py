"""A project's own notes are the record; Anthill finds and uses them (owner, 21 Oct)."""
from anthill import configure, install, notes, rules
from conftest import commit_all, reload

LOG = """# Learnings

### Adding a negative number returned zero — 2026-08-14
**Problem:** add(-1, 2) gave 0.
**Cause:** `pkg/core.py` clamped below zero.
**Fix:** `core.add` no longer clamps.

### Totals doubled on retry — 2026-08-20
**Problem:** a retried batch counted twice.
**Cause:** no idempotency key in `pkg/core.py`.
**Fix:** keyed by batch id.

### The web page showed stale numbers — 2026-09-01
**Problem:** a cached figure.
**Cause:** `web/app.ts` read once at load.
**Fix:** read on every view.
"""


def keep_notes(project):
    r = project.root
    (r / "docs" / "plans").mkdir(parents=True)
    (r / "docs" / "LEARNINGS.md").write_text(LOG)
    (r / "docs" / "plans" / "CORE_HANDOVER.md").write_text("# Core arithmetic\n\nLives in `pkg/core.py`.\n")
    page = r / "kb" / "modules" / "core" / "adding.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nid: adding\ntype: module\ntitle: Adding\nfootprint:\n  - pkg/core.py\n---\n# Adding\n")
    (r / "kb" / "KNOWLEDGE-RULES.md").write_text("rules\n")
    with (r / ".gitignore").open("a") as f:
        f.write("docs/\n")
    commit_all(r, "notes")


def use(project, *paths):
    configure.set_value(project, "knowledge.project_notes", ",".join(paths), by="kamal")
    return reload(project)


def test_the_scan_finds_lessons_handovers_and_pages_and_says_what_git_does_not_hold(project):
    keep_notes(project)
    found = notes.scan(project)
    assert found["lessons"] == [{"path": "docs/LEARNINGS.md", "entries": 3, "in_git": False}]
    assert found["handovers"][0]["path"] == "docs/plans/" and found["handovers"][0]["in_git"] is False
    assert found["pages"] == [{"path": "kb/", "in_git": True}]


def test_each_lesson_is_linked_to_the_code_it_names(project):
    keep_notes(project)
    ctx = use(project, "docs/LEARNINGS.md", "docs/plans")
    by_title = {x["title"]: x["files"] for x in notes.lessons(ctx)}
    assert by_title["Adding a negative number returned zero"] == ["pkg/core.py"]
    assert by_title["The web page showed stale numbers"] == ["web/app.ts"]
    r = notes.relevant(ctx, ["pkg/core.py"], "negative number")
    assert r["lessons"][0]["title"] == "Adding a negative number returned zero"
    assert all("web/app.ts" not in x["files"] for x in r["lessons"])
    assert r["handovers"] == [{"title": "Core arithmetic", "page": "docs/plans/CORE_HANDOVER.md"}]


def test_nothing_is_used_until_the_owner_chooses(project):
    keep_notes(project)
    assert notes.relevant(project, ["pkg/core.py"]) == {"lessons": [], "handovers": []}
    assert "This project's own notes" not in rules.rules_file_v2(project, "Proj", "")


def test_the_rules_and_the_keeper_point_at_the_project_s_notes(project):
    keep_notes(project)
    ctx = use(project, "docs/LEARNINGS.md", "docs/plans", "kb")
    text = rules.rules_file_v2(ctx, "Proj", "")
    assert "## This project's own notes" in text
    assert "`docs/LEARNINGS.md`: **Lessons**" in text and "not in git" in text
    assert "`kb`: **Module pages**" in text
    assert "filed on the\n`Warning:`" not in text and "not in the sprint" in text
    assert "an entry in the project's lesson log" in text
    keeper = install.render_keeper(ctx)
    assert "Bring the page in `docs/plans`" in keeper and "Never write a lesson" in keeper


def test_the_card_shows_what_was_learned_about_this_code(project, monkeypatch):
    keep_notes(project)
    ctx = use(project, "docs/LEARNINGS.md", "docs/plans")
    from anthill import context as _ctx
    from anthill.navigate import router
    fake = lambda: ctx                                   # noqa: E731
    fake.cache_clear = lambda: None                      # the fixture clears it on the way out
    monkeypatch.setattr(_ctx, "current", fake)
    here = router._learned_here("pkg/core.py", "fix adding")
    assert {x["title"] for x in here["lessons"]} == {"Adding a negative number returned zero", "Totals doubled on retry"}
    assert router._learned_here("pkg/__init__.py", "") is None


def test_install_says_what_notes_it_found(project):
    keep_notes(project)
    out = install.install(reload(project), project_name="Proj", stack="Python", write=True, force=True,
                          run_survey=False)
    assert out["project_notes"]["found"]["lessons"] == ["docs/LEARNINGS.md"]
    assert "knowledge.project_notes" in out["project_notes"]["next"]


def test_a_project_s_own_claude_md_is_not_locked_when_anthill_writes_its_own(project):
    (project.root / "CLAUDE.md").write_text("# Our own rules\n")
    commit_all(project.root, "own rules")
    project.config.setdefault("install", {})["local"] = True
    assert "CLAUDE.md" not in install.protected_paths(project)
    assert "CLAUDE.local.md" in install.protected_paths(project)
    project.config["install"]["local"] = False
    assert "CLAUDE.md" in install.protected_paths(project)


def test_the_new_settings_can_be_changed_the_proper_way(project):
    out = configure.set_value(project, "execution.risky_paths", "pgstore/schema/**,pgstore/migrate*.py", by="kamal")
    assert out["to"] == ["pgstore/schema/**", "pgstore/migrate*.py"]
    configure.set_value(project, "execution.dependencies_need_owner", "false", by="kamal")
    configure.set_value(project, "execution.code_checks", "false", by="kamal")
    ctx = reload(project)
    from anthill import codecheck, risky
    assert risky.is_risky(ctx, "pgstore/schema/009_new.sql") and not risky.deps_need_owner(ctx)
    assert codecheck.limits(ctx) is None


def test_a_reinstall_keeps_the_owner_s_choice_of_notes(project):
    keep_notes(project)
    ctx = use(project, "docs/LEARNINGS.md", "docs/plans")
    install.install(ctx, project_name="Proj", stack="Python", write=True, force=True, run_survey=False)
    ctx = reload(ctx)
    assert notes.in_use(ctx) == ["docs/LEARNINGS.md", "docs/plans"]
    assert "## This project's own notes" in (ctx.root / install.rules_file(ctx)).read_text()
