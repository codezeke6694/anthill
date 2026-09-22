"""One sanctioned writer for a denied file."""
import pytest

from anthill import configure
from conftest import reload, read_config


def test_set_records_who_and_what(project):
    out = configure.set_value(project, "execution.push_requires_owner", "false", by="kamal")
    assert out["from"] is True and out["to"] is False
    assert read_config(project)["execution"]["push_requires_owner"] is False
    hist = configure.history(reload(project))
    assert hist[-1]["by"] == "kamal" and hist[-1]["key"] == "execution.push_requires_owner"


def test_unknown_key_refused(project):
    with pytest.raises(SystemExit):
        configure.set_value(project, "execution.secret_door", "1", by="x")


def test_by_is_required(project):
    with pytest.raises(SystemExit):
        configure.set_value(project, "audit.required", "false", by="")


def test_types_are_enforced(project):
    with pytest.raises(SystemExit):
        configure.set_value(project, "audit.required", "maybe", by="x")
    with pytest.raises(SystemExit):
        configure.set_value(project, "execution.mode", "swarm", by="x")
    out = configure.set_value(project, "execution.protected_branches", "main, release", by="x")
    assert out["to"] == ["main", "release"]
    out = configure.set_value(project, "blueprint.min_coverage", "40", by="x")
    assert out["to"] == 40


def test_dry_run_writes_nothing(project):
    before = read_config(project)
    configure.set_value(project, "audit.required", "false", by="x", write=False)
    assert read_config(project) == before
