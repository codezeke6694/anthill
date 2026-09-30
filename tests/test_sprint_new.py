"""Opening a sprint never destroys the previous one."""
from anthill.sprint import backlog


def test_archive_name_is_not_overwritten(project):
    backlog.new(project, "S1", "one")
    backlog.add_unit(project, "a", "A", ["pkg/**"], "pytest tests/core")
    first = backlog.new(project, "S1", "two")
    assert first["archived_previous"].endswith("archive/s1.json")
    assert first["units_left_behind"] == ["a.impl"]
    backlog.add_unit(project, "b", "B", ["pkg/**"], "pytest tests/core")
    second = backlog.new(project, "S1", "three")
    assert second["archived_previous"] != first["archived_previous"]
    assert (project.sprints_dir / "archive" / "s1.json").exists()
    assert "b.impl" in second["units_left_behind"]
