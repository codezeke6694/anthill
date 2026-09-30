"""The push hook reads the config, and the config alone."""
from pathlib import Path

from anthill import guard
from conftest import reload


def test_push_refused_by_default(project):
    report, code = guard.check_push(project, project.root, ["work/x"])
    assert code == guard.REFUSE


def test_push_allowed_when_config_says_so(project):
    project.config["execution"]["push_requires_owner"] = False
    project.config["execution"]["protected_branches"] = ["main"]
    project.save_config()
    ctx = reload(project)
    report, code = guard.check_push(ctx, ctx.root, ["work/x"])
    assert code == guard.ALLOW
    report, code = guard.check_push(ctx, ctx.root, ["main"])
    assert code == guard.REFUSE
