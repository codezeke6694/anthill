"""Where the target project is — the one thing every other module needs.

The ported code computed its own root as `Path(__file__).parents[1]`, which
silently required the tool to live *inside* the repository it works on. That is
fine for a tool vendored into one codebase and wrong for a tool you install.
Anthill is installed, so the project root is discovered, not assumed.

Resolution order, most explicit first:

    1. `--project` on the command line          (an operator said so)
    2. `$ANTHILL_PROJECT`                       (a runner said so)
    3. `git rev-parse --show-toplevel` from cwd (the tree says so)
    4. the current working directory            (last resort, and it says so)

Everything derived from the root lives under one state directory, so an install
is one directory to inspect, back up, or delete. Nothing is written outside it
except what a unit legitimately owns.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

STATE_DIRNAME = ".anthill"
CONFIG_FILE = "anthill.config.json"

# Kept out of the code that scans a tree, because "which directories are source"
# is a per-project fact and hardcoding it is what made the ported map builder
# unusable in any repository but its own.
DEFAULT_CONFIG: dict[str, Any] = {
    "project": {"name": "", "slug": ""},
    "source": {
        # Directories build_map/structure scan. Empty means "discover top-level
        # dirs that contain .py, excluding the excludes" -- see discover_sources.
        "include_dirs": [],
        "include_toplevel": [],
        # `tests` is excluded from the *source* set on purpose: the blueprint
        # navigates product behaviour, and a test explains itself. The ported
        # version excluded it too. Tests still reach the map as a node's
        # validation stops.
        "exclude_parts": ["__pycache__", "archive", "_archive", "venv", ".venv",
                          ".git", "node_modules", "build", "dist", ".anthill",
                          "tests", "test"],
        "district_prefix": {},
    },
    "knowledge": {"dir": "knowledge", "areas": [], "registries": []},
    "execution": {"base_branch": "main", "integration_branch": "",
                  # `solo`: one interactive agent working in place; nothing
                  # escalates by count and no worker identity is required.
                  # `pool`: several headless agents, isolated worktrees,
                  # attempt budgets. Solo is how the tool is actually used.
                  "mode": "solo",
                  "seed_paths": [], "seed_working_state": False,
                  # Directories prepended to PATH when a gate or an agent runs.
                  # Empty means "discover the project's virtualenv".
                  "env_path": [], "venv": "",
                  # Isolation buys exactly one thing: several agents at once.
                  # Ownership is enforced either way. Off by default, because a
                  # single agent pays the whole cost -- code that never appears
                  # in the owner's folder -- for a benefit it is not using.
                  "isolate": False,
                  # Branches an agent may not commit to or push. The owner
                  # merges into these; nothing else does.
                  "protected_branches": ["main", "master"],
                  # Pushing is the owner's act, not an agent's -- any branch,
                  # not only a protected one. A push leaves the machine and
                  # reaches other people; a local commit does not.
                  "push_requires_owner": True,
                  # Refuse a commit of product source no claimed unit owns.
                  # Off by default: it only makes sense once a project has
                  # decided every change goes through the board, and until then
                  # it refuses ordinary work on a branch -- measured, 21 files
                  # at once. Branch and push protection are separate and stay on.
                  "guard_ownership": False},
    "gates": {},
    # Blueprint conditions compiled into every gate. `require_page` is off by
    # default because a project's first sprints legitimately have no pages yet;
    # turn it on once an area has one, and thereafter no unit can add source
    # without describing it.
    "blueprint": {"require_page": False, "min_coverage": -1},
    "roles": ["planner", "builder", "auditor"],
    "audit": {"required": True, "escalate_verdicts": ["ARCH NOTE"]},
}


@dataclass
class Context:
    """One resolved view of an installation. Passed, never re-derived."""
    root: Path
    origin: str                      # how the root was found, for error messages
    config: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ locations
    @property
    def state(self) -> Path:
        return self.root / STATE_DIRNAME

    @property
    def config_path(self) -> Path:
        return self.state / CONFIG_FILE

    @property
    def knowledge_dir(self) -> Path:
        rel = (self.config.get("knowledge") or {}).get("dir") or "knowledge"
        return self.state / rel

    @property
    def maps_dir(self) -> Path:
        return self.state / "maps"

    @property
    def contracts_dir(self) -> Path:
        return self.state / "contracts"

    @property
    def units_dir(self) -> Path:
        return self.state / "units"

    @property
    def audits_dir(self) -> Path:
        return self.state / "audits"

    @property
    def sprints_dir(self) -> Path:
        return self.state / "sprints"

    @property
    def log_dir(self) -> Path:
        return self.state / "log"

    @property
    def roles_dir(self) -> Path:
        return self.state / "roles"

    @property
    def constitution(self) -> Path:
        return self.root / "CONSTITUTION.md"

    @property
    def installed(self) -> bool:
        return self.config_path.exists()

    # --------------------------------------------------------------- source
    def source_roots(self) -> tuple[list[str], list[str], set[str]]:
        src = self.config.get("source") or {}
        include = list(src.get("include_dirs") or [])
        toplevel = list(src.get("include_toplevel") or [])
        exclude = set(src.get("exclude_parts") or DEFAULT_CONFIG["source"]["exclude_parts"])
        if not include and not toplevel:
            include, toplevel = discover_sources(self.root, exclude)
        return include, toplevel, exclude

    def has_source(self) -> bool:
        """Brownfield or greenfield -- the question `install` branches on."""
        include, toplevel, _ = self.source_roots()
        return bool(include or toplevel)

    def exec_env(self) -> dict[str, str]:
        """`os.environ` with the project's tooling reachable.

        Applied to gates and to agent processes alike: an agent that cannot run
        the gate it is told to satisfy is in exactly the same bind as a gate
        that cannot run itself.
        """
        import os as _os
        env = dict(_os.environ)
        ex = self.config.get("execution") or {}
        extra: list[str] = []
        venv = find_venv(self.root, str(ex.get("venv") or ""))
        if venv:
            for sub in ("bin", "Scripts"):
                if (venv / sub).exists():
                    extra.append(str(venv / sub))
            env["VIRTUAL_ENV"] = str(venv)
        # The tool's own bin, because compiled gates call `anthill blueprint`
        # and `anthill audit check`. Without this a gate got past pytest and
        # then died 127 on its own commands -- a failure that looks identical
        # to the missing test runner and was mistaken for it.
        tool_bin = Path(__file__).resolve().parents[1] / "bin"
        if tool_bin.exists():
            extra.append(str(tool_bin))
        for entry in (ex.get("env_path") or []):
            q = Path(entry)
            extra.append(str(q if q.is_absolute() else self.root / q))
        if extra:
            env["PATH"] = ":".join(extra + [env.get("PATH", "")])
        # A worktree is not the project root, so anything importing the package
        # by name needs the root on the path as well.
        env["PYTHONPATH"] = ":".join(
            [str(self.root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env["ANTHILL_PROJECT"] = str(self.root)
        return env

    def save_config(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.config, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)


VENV_NAMES = (".venv", "venv", ".virtualenv", "env")


def find_venv(root: Path, configured: str = "") -> Path | None:
    """The project's virtualenv, if it has one.

    A unit worktree is a fresh checkout of committed content, so it contains no
    virtualenv -- the venv is gitignored, and rightly so. That is why a gate
    running bare `pytest` inside a worktree died with exit 127, `command not
    found`, which would have killed every worker in a pool before any of them
    did a thing. Copying the environment in is not the answer; referencing it
    on PATH is.
    """
    if configured:
        p = (root / configured) if not Path(configured).is_absolute() else Path(configured)
        return p if (p / "bin").exists() or (p / "Scripts").exists() else None
    for name in VENV_NAMES:
        cand = root / name
        if (cand / "bin").exists() or (cand / "Scripts").exists():
            return cand
    return None


def discover_sources(root: Path, exclude: set[str]) -> tuple[list[str], list[str]]:
    """Top-level directories that actually contain Python, plus top-level .py.

    Discovery rather than configuration for the first run: an installer that
    demands a directory list before the operator has one is an installer that
    does not run. The result is written into config, where it can be corrected.
    """
    dirs, files = [], []
    if not root.exists():
        return dirs, files
    for child in sorted(root.iterdir()):
        name = child.name
        if name in exclude or name.startswith("."):
            continue
        if child.is_dir():
            if any(p for p in child.rglob("*.py")
                   if not (exclude & set(p.relative_to(root).parts))):
                dirs.append(name)
        elif child.suffix == ".py":
            files.append(name)
    return dirs, files


def _git_toplevel(start: Path) -> Path | None:
    """The MAIN worktree's root -- never a linked worktree's.

    This distinction is load-bearing and was found by running a gate. Every gate
    executes with cwd inside the unit's linked worktree, where
    `--show-toplevel` reports the *worktree* path. The install lives in the main
    checkout, so resolving to the worktree made every `anthill` call inside a
    gate report "not installed" -- which is to say, the audit and blueprint
    conditions could never run at all.

    `--git-common-dir` points at the shared `.git` directory from anywhere in
    the family, so its parent is the main root in both a linked worktree and the
    main one.
    """
    def _run(args: list[str]) -> str | None:
        try:
            r = subprocess.run(["git", *args], cwd=start, capture_output=True,
                               text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    common = _run(["rev-parse", "--git-common-dir"])
    if common:
        cdir = Path(common)
        if not cdir.is_absolute():
            cdir = (start / cdir).resolve()
        if cdir.name == ".git" and cdir.parent.exists():
            return cdir.parent
    top = _run(["rev-parse", "--show-toplevel"])
    return Path(top) if top else None


def resolve(project: str | Path | None = None) -> Context:
    """Find the project, then load its config if it has been installed."""
    if project:
        root, origin = Path(project).expanduser().resolve(), "--project"
    elif os.environ.get("ANTHILL_PROJECT"):
        root = Path(os.environ["ANTHILL_PROJECT"]).expanduser().resolve()
        origin = "$ANTHILL_PROJECT"
    elif (top := _git_toplevel(Path.cwd())) is not None:
        root, origin = top.resolve(), "git main worktree"
    else:
        root, origin = Path.cwd().resolve(), "cwd (no git repository found)"

    ctx = Context(root=root, origin=origin, config=dict(DEFAULT_CONFIG))
    cfg = root / STATE_DIRNAME / CONFIG_FILE
    if cfg.exists():
        try:
            loaded = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"anthill: {cfg} is not readable JSON: {exc}")
        merged = dict(DEFAULT_CONFIG)
        for k, v in loaded.items():
            merged[k] = {**merged[k], **v} if isinstance(v, dict) and isinstance(
                merged.get(k), dict) else v
        ctx.config = merged
    return ctx


@lru_cache(maxsize=1)
def current() -> Context:
    """The ambient context, for ported modules that cannot take a parameter yet.

    A cache rather than a global so tests can clear it; `current.cache_clear()`.
    """
    return resolve()
