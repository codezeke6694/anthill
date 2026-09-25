"""The hooks refuse secrets, junk and rewritten history -- and nothing else.

Fake credentials are assembled at runtime so this file is not itself a secret
to any scanner, this one included.
"""
import subprocess

from anthill import configure, guard, hygiene, rules
from anthill import install as inst
from conftest import git, commit_all, reload

AWS = "AKIA" + "Q" * 16
GITHUB = "ghp_" + "a1" * 18
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"


def hygienic(project):
    configure.set_value(project, "execution.guard_hygiene", "true", by="owner")
    return reload(project)


def stage(ctx, rel, text):
    path = ctx.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(ctx.root, "add", "-f", rel)


def commit_refused(ctx) -> bool:
    r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "x"], cwd=ctx.root,
                       capture_output=True, text=True)
    return r.returncode != 0


# --- what counts --------------------------------------------------------------

def test_env_files_are_secrets_but_their_templates_are_not():
    assert hygiene.secret_file(".env")
    assert hygiene.secret_file("config/.env.production")
    assert not hygiene.secret_file(".env.example")
    assert not hygiene.secret_file("docs/.env.template")
    assert hygiene.secret_file("deploy/id_ed25519")
    assert not hygiene.secret_file("deploy/id_ed25519.pub")
    assert hygiene.secret_file("certs/server.pem")


def test_junk_is_machine_local_noise():
    assert hygiene.junk_file(".DS_Store")
    assert hygiene.junk_file("pkg/__pycache__/core.cpython-312.pyc")
    assert hygiene.junk_file("web/node_modules/react/index.js")
    assert not hygiene.junk_file("pkg/core.py")
    assert not hygiene.junk_file("docs/node_modules.md")


def test_only_added_lines_are_read_and_the_secret_is_masked():
    diff = ("+++ b/app.py\n@@ -1,0 +10,2 @@\n+ok = 1\n+key = '" + AWS + "'\n"
            "--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-" + GITHUB + "\n")
    found = hygiene.secret_lines(diff)
    assert found == [{"file": "app.py", "line": 11, "kind": "AWS access key",
                      "starts": "AKIAQQ…"}]


def test_prose_about_passwords_is_not_a_secret():
    diff = "+++ b/README.md\n@@ -0,0 +1 @@\n+Set password = your own; sk-short\n"
    assert hygiene.secret_lines(diff) == []


# --- the commit hook ----------------------------------------------------------

def test_off_by_default_so_an_upgrade_changes_nothing(project):
    stage(project, ".DS_Store", "x")
    assert guard.check_hygiene(project, project.root) is None


def test_commit_refuses_a_key_in_code(project):
    ctx = hygienic(project)
    stage(ctx, "pkg/settings.py", f"TOKEN = '{GITHUB}'\n")
    report, code = guard.check(ctx, ctx.root)
    assert code == guard.REFUSE
    assert report["hygiene"][0]["file"] == "pkg/settings.py"
    assert GITHUB not in str(report)              # the refusal does not repeat it
    assert commit_refused(ctx)


def test_commit_refuses_env_pem_and_junk(project):
    ctx = hygienic(project)
    stage(ctx, ".env", "X=1\n")
    stage(ctx, "keys/k.txt", PEM + "\n")
    stage(ctx, ".DS_Store", "x")
    report, code = guard.check(ctx, ctx.root)
    kinds = {(p["file"], p["problem"]) for p in report["hygiene"]}
    assert kinds == {(".env", "secret"), ("keys/k.txt", "secret"),
                     (".DS_Store", "junk")}


def test_ordinary_work_commits(project):
    ctx = hygienic(project)
    stage(ctx, "pkg/core.py", "def add(a, b):\n    return a + b + 0\n")
    stage(ctx, ".env.example", "API_KEY=\n")
    assert guard.check_hygiene(ctx, ctx.root) is None
    assert not commit_refused(ctx)


def test_the_owner_gets_no_exception_for_a_secret(project, monkeypatch):
    ctx = hygienic(project)
    monkeypatch.setenv("ANTHILL_OWNER", "1")
    stage(ctx, ".env", "X=1\n")
    assert guard.check_hygiene(ctx, ctx.root) is not None


# --- the push hook ------------------------------------------------------------

def _history(ctx):
    """A remote tip, a normal follow-up, and a rewrite of the remote tip."""
    base = git(ctx.root, "rev-parse", "HEAD")
    (ctx.root / "pkg" / "a.py").write_text("a = 1\n")
    remote_tip = commit_all(ctx.root, "pushed")
    (ctx.root / "pkg" / "b.py").write_text("b = 1\n")
    extended = commit_all(ctx.root, "on top")
    git(ctx.root, "reset", "-q", "--hard", base)
    (ctx.root / "pkg" / "c.py").write_text("c = 1\n")
    rewritten = commit_all(ctx.root, "replaced")
    return remote_tip, extended, rewritten


def _update(local, remote, branch="work/x"):
    return [("refs/heads/" + branch, local, "refs/heads/" + branch, remote)]


def test_push_that_adds_commits_is_not_a_rewrite(project):
    ctx = hygienic(project)
    tip, extended, _ = _history(ctx)
    assert guard.check_force(ctx, ctx.root, _update(extended, tip)) is None


def test_force_push_is_refused(project):
    ctx = hygienic(project)
    tip, _, rewritten = _history(ctx)
    report, code = guard.check_force(ctx, ctx.root, _update(rewritten, tip))
    assert code == guard.REFUSE and report["rewriting"] == ["work/x"]


def test_unknown_remote_tip_counts_as_a_rewrite(project):
    ctx = hygienic(project)
    head = git(ctx.root, "rev-parse", "HEAD")
    assert guard.check_force(ctx, ctx.root, _update(head, "f" * 40)) is not None


def test_new_and_deleted_branches_are_not_rewrites(project):
    ctx = hygienic(project)
    head = git(ctx.root, "rev-parse", "HEAD")
    assert guard.check_force(ctx, ctx.root, _update(head, "0" * 40)) is None
    assert guard.check_force(ctx, ctx.root, _update("0" * 40, head)) is None


def test_owner_may_rewrite_a_work_branch_but_never_main(project, monkeypatch):
    ctx = hygienic(project)
    tip, _, rewritten = _history(ctx)
    monkeypatch.setenv("ANTHILL_OWNER", "1")
    assert guard.check_force(ctx, ctx.root, _update(rewritten, tip)) is None
    assert guard.check_force(ctx, ctx.root,
                             _update(rewritten, tip, branch="main")) is not None


# --- the prose ----------------------------------------------------------------

def test_rules_mention_hygiene_only_when_it_is_on(project):
    assert "guard_hygiene" not in rules.git_rules(project)
    ctx = hygienic(project)
    inst.install(ctx, project_name="Proj", force=True)
    assert "execution.guard_hygiene" in (ctx.root / "CLAUDE.md").read_text()
