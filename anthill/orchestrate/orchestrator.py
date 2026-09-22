#!/usr/bin/env python3
"""The execution plane: many agents, one repository, no human reading diffs.

Ported from the working Peregrine implementation rather than reinvented -- that
one is proven (23/23 units, 703 tests, zero ownership violations across four
waves of real agents), and every comment below marks a behaviour that was earned
by a run going wrong. The load-bearing rule is that an agent cannot assert
completion: only a passing gate closes a unit.

Three authorities the model cannot forge, one per plane:
  navigation  -- a structural fingerprint, so it cannot claim an address
  intent      -- a human attestation, so it cannot claim intent
  execution   -- a gate's exit code, so it cannot claim done   <- this file

Zero dependencies beyond git and the standard library.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any

# The fallback run directory, and a path the ownership check exempts. Named
# for this tool rather than the one it was ported from: `.sagework` was a
# leftover that survived the port because it is a string literal, not an
# identifier -- the sweep that removed the old package name checked imports.
WORK_DIR = ".anthill/work"
CONTRACT_FILE = "contract.json"
STALE_LOCK_SECONDS = 1800  # 30 min without a heartbeat -> reclaimable

BLOCKED = "blocked"      # dependencies not satisfied
READY = "ready"          # claimable
CLAIMED = "claimed"      # a worker holds the lock
GATED = "gated"          # gate passed, awaiting done
DONE = "done"            # complete and merged into the dependency graph
ESCALATED = "escalated"  # exceeded escalate_after, needs a human

TERMINAL = {DONE, ESCALATED}

REQUIRED_UNIT_FIELDS = ("id", "gate", "owns")

# Exit codes are the worker protocol, so they are part of the contract:
EXIT_WAIT = 3            # nothing ready yet, but work is in flight
EXIT_DRAINED = 4         # nothing left that can ever run
EXIT_OWNERSHIP = 64      # wrote outside its owns
EXIT_NO_GATE = 65        # asked to close without a passing gate
EXIT_CONFLICT = 66       # gated but will not merge
EXIT_TERMINAL = 67       # already done or escalated
# A gate ending 3 means "not reviewed yet", not "wrong". A coordination gap, so
# it is reported and retried rather than charged to the unit.
EXIT_NOT_REVIEWED = 3


class OrchestratorError(RuntimeError):
    """Raised instead of exiting, so the CLI decides how to report."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe(unit_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", unit_id)


def write_json_atomic(path: Path, data: dict) -> None:
    """Write via temp + rename so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def run(cmd: list[str] | str, cwd: Path | None = None,
        capture: bool = True,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          shell=isinstance(cmd, str),
                          capture_output=capture, text=True, env=env)


def exec_env() -> dict[str, str]:
    """The environment a gate runs in. Never the bare worktree's."""
    from anthill import context as _ctx
    try:
        return _ctx.current().exec_env()
    except Exception:                                  # pragma: no cover
        return dict(os.environ)


# --------------------------------------------------------------------- store

class Store:
    """Everything the execution plane knows, on disk."""

    def __init__(self, repo: Path, root: Path | None = None):
        """`repo` is the repository being worked; `root` is where state is kept.

        They are separate on purpose: keeping run state out of the target repo
        means working a project leaves no orchestrator litter inside it. The
        default preserves the old in-repo layout for a caller that wants it.
        """
        self.repo = Path(repo).resolve()
        self.root = Path(root).resolve() if root else self.repo / WORK_DIR
        self.state_dir = self.root / "state"
        self.locks_dir = self.root / "locks"
        self.wt_dir = self.root / "wt"
        self.esc_dir = self.root / "escalations"
        self.briefs_dir = self.root / "briefs"

    def init_dirs(self) -> None:
        for d in (self.root, self.state_dir, self.locks_dir, self.wt_dir,
                  self.esc_dir, self.briefs_dir, self.root / "logs"):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def contract_path(self) -> Path:
        return self.root / CONTRACT_FILE

    def canonical_contract(self) -> Path:
        """Where `sprint compile` writes, if this run has a project context."""
        try:
            from anthill import context as _c
            return _c.current().contracts_dir / "contract.json"
        except Exception:                                  # pragma: no cover
            return self.contract_path

    def board_is_behind(self) -> bool:
        """Has the approved contract moved on since the board was seeded?"""
        canon = self.canonical_contract()
        if not canon.exists() or not self.contract_path.exists():
            return False
        if canon.resolve() == self.contract_path.resolve():
            return False
        return canon.stat().st_mtime > self.contract_path.stat().st_mtime

    def load_contract(self) -> dict:
        if not self.contract_path.exists():
            raise OrchestratorError(
                f"no contract at {self.contract_path}; "
                f"generate one with `board --out {self.contract_path}`")
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        validate_contract(contract)
        return contract

    # -- unit state ------------------------------------------------------

    def state_path(self, unit_id: str) -> Path:
        return self.state_dir / f"{safe(unit_id)}.json"

    def read_state(self, unit_id: str) -> dict:
        p = self.state_path(unit_id)
        if not p.exists():
            return {"id": unit_id, "status": BLOCKED, "attempts": 0}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"id": unit_id, "status": BLOCKED, "attempts": 0}

    def write_state(self, unit_id: str, state: dict) -> None:
        state["updated_at"] = now()
        write_json_atomic(self.state_path(unit_id), state)

    def all_states(self, contract: dict) -> dict[str, dict]:
        return {u["id"]: self.read_state(u["id"]) for u in contract["units"]}

    # -- locks -----------------------------------------------------------

    def lock_path(self, unit_id: str) -> Path:
        return self.locks_dir / f"{safe(unit_id)}.lock"

    def acquire(self, unit_id: str, worker: str) -> bool:
        """Atomic claim. O_EXCL is the whole handshake -- first writer wins, and
        every loser gets a clean False with no partial state to clean up."""
        payload = json.dumps({"unit": unit_id, "worker": worker,
                              "pid": os.getpid(), "claimed_at": now(),
                              "heartbeat": time.time()}, indent=2)
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path(unit_id),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
        return True

    def read_lock(self, unit_id: str) -> dict | None:
        p = self.lock_path(unit_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def heartbeat(self, unit_id: str, worker: str) -> bool:
        lock = self.read_lock(unit_id)
        if not lock or lock.get("worker") != worker:
            return False
        lock["heartbeat"] = time.time()
        write_json_atomic(self.lock_path(unit_id), lock)
        return True

    def release_lock(self, unit_id: str) -> None:
        self.lock_path(unit_id).unlink(missing_ok=True)


# ------------------------------------------------------------------ contract

def validate_contract(contract: dict) -> None:
    units = contract.get("units")
    if not isinstance(units, list) or not units:
        raise OrchestratorError("contract has no units")
    seen: set[str] = set()
    for unit in units:
        for field in REQUIRED_UNIT_FIELDS:
            if field not in unit:
                raise OrchestratorError(
                    f"unit {unit.get('id', '<no id>')!r} missing required field {field!r}")
        if unit["id"] in seen:
            raise OrchestratorError(f"duplicate unit id {unit['id']!r}")
        seen.add(unit["id"])
    # Every declared dependency must exist, or the graph is a lie.
    for unit in units:
        for dep in deps_of(unit):
            if dep not in seen:
                raise OrchestratorError(
                    f"unit {unit['id']!r} depends on unknown unit {dep!r}")
    cycle = find_cycle(units)
    if cycle:
        raise OrchestratorError("dependency cycle: " + " -> ".join(cycle))


def deps_of(unit: dict) -> list[str]:
    """Only real ordering constraints. A path collision is deliberately NOT a
    dependency -- collisions are solved by path ownership, and treating them as
    edges is what makes a graph needlessly deep and a board needlessly slow."""
    return list(unit.get("needs_data", [])) + list(unit.get("needs_iface", []))


def find_cycle(units: list[dict]) -> list[str] | None:
    graph = {u["id"]: deps_of(u) for u in units}
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for dep in graph.get(node, []):
            if color[dep] == GREY:
                return stack[stack.index(dep):] + [dep]
            if color[dep] == WHITE:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


# ---------------------------------------------------------------- scheduling

def compute_waves(units: list[dict]) -> list[list[str]]:
    """Topological levelling. A unit sits one level below its deepest
    dependency, so wave N can run entirely in parallel. Waves are computed,
    never authored."""
    graph = {u["id"]: deps_of(u) for u in units}
    level: dict[str, int] = {}
    indegree = {uid: len(set(d)) for uid, d in graph.items()}
    dependents: dict[str, list[str]] = defaultdict(list)
    for uid, ds in graph.items():
        for dep in set(ds):
            dependents[dep].append(uid)

    queue = deque(sorted(uid for uid, n in indegree.items() if n == 0))
    for uid in queue:
        level[uid] = 0
    while queue:
        uid = queue.popleft()
        for child in dependents[uid]:
            level[child] = max(level.get(child, 0), level[uid] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    waves: dict[int, list[str]] = defaultdict(list)
    for uid, lvl in level.items():
        waves[lvl].append(uid)
    return [sorted(waves[i]) for i in sorted(waves)]


def critical_path(units: list[dict]) -> list[str]:
    """The longest chain -- the only thing that sets wall-clock time once agents
    are cheap and plentiful."""
    graph = {u["id"]: deps_of(u) for u in units}
    memo: dict[str, list[str]] = {}

    def longest(uid: str) -> list[str]:
        if uid in memo:
            return memo[uid]
        best: list[str] = []
        for dep in graph.get(uid, []):
            chain = longest(dep)
            if len(chain) > len(best):
                best = chain
        memo[uid] = best + [uid]
        return memo[uid]

    return max((longest(u["id"]) for u in units), key=len, default=[])


def ready_units(contract: dict, states: dict[str, dict]) -> list[dict]:
    out = []
    for unit in contract["units"]:
        st = states[unit["id"]]
        if st["status"] in TERMINAL or st["status"] in (CLAIMED, GATED):
            continue
        if all(states.get(d, {}).get("status") == DONE for d in deps_of(unit)):
            out.append(unit)
    return out


def find_unit(contract: dict, unit_id: str) -> dict:
    for unit in contract["units"]:
        if unit["id"] == unit_id:
            return unit
    raise OrchestratorError(f"no unit {unit_id!r} in the contract")


# ----------------------------------------------------------------- ownership

def matches_any(rel_path: str, patterns: list[str]) -> bool:
    p = PurePath(rel_path)
    for pattern in patterns:
        try:
            if p.full_match(pattern):     # py3.13+, understands **
                return True
        except AttributeError:            # pragma: no cover - older interpreters
            if fnmatch.fnmatch(rel_path, pattern.replace("**/", "*")):
                return True
    return False


def changed_files(worktree: Path, base: str) -> list[str]:
    out = run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=worktree)
    files = [f for f in out.stdout.splitlines() if f.strip()]
    # Uncommitted work counts too -- an agent that has not committed is still
    # accountable for what it touched. `-uall` is load-bearing: plain
    # --porcelain collapses a wholly-untracked directory to "kernel/", which
    # matches no file pattern and would fail every honest agent.
    out2 = run(["git", "status", "--porcelain", "-uall"], cwd=worktree)
    for line in out2.stdout.splitlines():
        if len(line) > 3:
            path = line[3:].strip()
            if " -> " in path:            # rename: blame the destination
                path = path.split(" -> ", 1)[1]
            files.append(path.strip('"').rstrip("/"))
    return sorted({f for f in files if f})


# Artefacts the *gate itself* creates while running in the worktree. The gate
# runs between the claim and the ownership check, so anything it generates is
# caused by the orchestrator, not by the agent -- the same reasoning that skips
# symlinks. Measured: `pytest` writes `__pycache__/*.pyc` under a directory the
# unit does not own, which failed an agent whose only edit was inside `owns`.
DEFAULT_ARTEFACT_IGNORE = (
    "**/__pycache__/**", "**/*.pyc", "**/*.pyo",
    "**/node_modules/**", "**/.pytest_cache/**", "**/.ruff_cache/**",
    "**/*.egg-info/**", "**/.DS_Store", "**/.mypy_cache/**",
    # The orchestrator's own state and the host's settings. In an isolated
    # worktree these never appear -- a fresh checkout has no state changes -- so
    # the omission was invisible until a unit ran in place, where every file
    # `install` had written showed up as an ownership violation and failed an
    # agent that had touched nothing but its own district.
    ".anthill/**", "**/.anthill/**", ".claude/**", "**/.claude/**",
    ".venv/**", "**/.venv/**", "venv/**",
)


# A file that was already gone when the unit was claimed. `_digest` cannot
# describe one -- there are no bytes to hash -- so the baseline used to skip it
# and every in-place unit inherited a permanent violation for every file deleted
# since its base. On LogiAstro that was 144 files, 41 of which surfaced; the
# unit was charged with all of them and escalated. Absence is a state the
# baseline has to be able to record, the same as any other.
ABSENT_AT_CLAIM = "<absent>"


def _state_of(path: Path) -> str:
    """How a file looked, in the one vocabulary `seeded` speaks."""
    return _digest(path) if path.is_file() else ABSENT_AT_CLAIM


def check_ownership(worktree: Path, owns: list[str], base: str,
                    artefact_ignore: tuple[str, ...] | list[str] | None = None,
                    seeded: dict[str, str] | None = None
                    ) -> tuple[list[str], list[str]]:
    """Returns (violations, ignored_artefacts).

    An empty violations list means the agent stayed inside its boundary. The
    second list is returned rather than dropped so the exclusion is visible: a
    silently ignored path is how a real violation would hide.

    Symlinks are skipped for the same reason as artefacts -- a setup hook creates
    them to supply gitignored build output, and blaming a worker for the link the
    orchestrator asked for is a false positive.
    """
    ignore = list(artefact_ignore if artefact_ignore is not None
                  else DEFAULT_ARTEFACT_IGNORE)
    seeded = seeded or {}
    violations, ignored = [], []
    for f in changed_files(worktree, base):
        if f.startswith(WORK_DIR + "/") or matches_any(f, owns):
            continue
        if (worktree / f).is_symlink():
            continue
        if matches_any(f, ignore):
            ignored.append(f)
            continue
        # A seeded file is the orchestrator's doing, not the agent's -- but only
        # while it is untouched. Comparing the recorded state keeps the boundary
        # real in both directions: an agent that edits a seeded file outside its
        # owns is in violation, and so is one that recreates a file that was
        # already deleted when it started.
        if f in seeded:
            if _state_of(worktree / f) == seeded[f]:
                ignored.append(f)
                continue
            violations.append(f)
            continue
        violations.append(f)
    return violations, ignored


# ------------------------------------------------------------------ worktrees

def integration_branch(contract: dict) -> str:
    """Where passing units accumulate. Defaults to `integration` rather than the
    base branch so the operator's own checkout is never touched -- integration is
    promoted in batches, after reading gate results.

    Falsy means unconfigured, not "the empty branch". `sprint compile` omits an
    empty `integration_branch`, but a hand-written contract can carry `""`, and
    `dict.get(key, default)` hands back the empty string whenever the key exists
    and is falsy. `git diff "...HEAD"` against an empty base resolves to the
    working tree and blames the unit for the whole of it.
    """
    return contract.get("integration_branch") or "integration"


def head_commit(worktree: Path) -> str:
    res = run(["git", "rev-parse", "HEAD"], cwd=worktree)
    return res.stdout.strip() if res.returncode == 0 else ""


def current_branch(worktree: Path) -> str:
    res = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree)
    return res.stdout.strip() if res.returncode == 0 else ""


def ownership_base(contract: dict, state: dict) -> str:
    """The commit a unit's footprint is measured from.

    A branch name is the wrong thing to diff a unit against: it names a moving
    target the unit did not pick and cannot control. What the boundary actually
    means is "what changed since this unit started", and the only honest
    expression of that is the commit HEAD was on when the unit was claimed.

    Measured on LogiAstro. The configured integration branch had fallen 147
    commits behind, so a unit whose entire footprint was two new files inside
    its own `owns` was charged with 41 violations -- every one of them a file
    somebody else had deleted a fortnight earlier. The failure names the agent,
    so it reads as a boundary mistake rather than as the configuration error it
    is, and nothing in the output said which base produced it.

    `base_commit` is recorded at claim time in both modes. The branch fallback
    serves only states written before that field existed.
    """
    return state.get("base_commit") or integration_branch(contract)


def ensure_integration(store: Store, contract: dict) -> tuple[Path | None, str]:
    """Merges happen in a dedicated worktree, never in the operator's checkout."""
    target = integration_branch(contract)
    base = contract.get("base_branch", "main")
    wt = store.root / "integration"
    if not wt.exists():
        exists = run(["git", "rev-parse", "--verify", "--quiet", target],
                     cwd=store.repo).returncode == 0
        run(["git", "worktree", "prune"], cwd=store.repo)
        cmd = (["git", "worktree", "add", str(wt), target] if exists
               else ["git", "worktree", "add", "-b", target, str(wt), base])
        res = run(cmd, cwd=store.repo)
        if res.returncode != 0:
            return None, (res.stderr or res.stdout).strip()
    return wt, target


def provision_worktree(store: Store, contract: dict, unit_id: str) -> tuple[Path, str]:
    # Cut from the integration branch so the tree already contains every
    # dependency this unit was cleared to build on.
    _, base = ensure_integration(store, contract)
    branch = f"unit/{safe(unit_id)}"
    wt = store.wt_dir / safe(unit_id)
    if wt.exists():
        return wt, branch
    # Stale registrations outlive deleted directories and would otherwise block
    # every retry of a unit that previously crashed.
    run(["git", "worktree", "prune"], cwd=store.repo)
    res = run(["git", "worktree", "add", "-B", branch, str(wt), base], cwd=store.repo)
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip()
        if "already used by worktree" in err:
            run(["git", "worktree", "remove", "--force", str(wt)], cwd=store.repo)
            run(["git", "worktree", "prune"], cwd=store.repo)
            res = run(["git", "worktree", "add", "-B", branch, str(wt), base],
                      cwd=store.repo)
        if res.returncode != 0:
            raise OrchestratorError((res.stderr or res.stdout).strip())
    return wt, branch


def working_state(repo: Path, extra: list[str] | None = None) -> list[str]:
    """Repo-relative paths whose working-tree content a fresh worktree lacks.

    A worktree carries committed content only, so it misses files that are
    untracked and the newer version of files that are modified. `extra` globs are
    resolved against the working directory regardless of gitignore, which is the
    only way to reach content git has been told to ignore -- and that is not an
    edge case: this repository ignores `tests/` outright ("files stay on disk, just
    untracked"), so all 80 of its test files are invisible to every git listing and
    a gate naming one cannot run in any worktree without being told to bring it.
    """
    out: set[str] = set()
    for args in (["git", "ls-files", "--others", "--exclude-standard"],
                 ["git", "diff", "--name-only"]):
        res = run(args, cwd=repo)
        out.update(l.strip() for l in res.stdout.splitlines() if l.strip())
    for pattern in extra or []:
        try:
            for q in repo.glob(pattern):
                if q.is_file():
                    out.add(str(q.relative_to(repo)))
        except (ValueError, OSError):
            continue
    return sorted(p for p in out
                  if not p.startswith(WORK_DIR + "/")
                  and "__pycache__" not in p and not p.endswith(".pyc"))


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def seed_worktree(repo: Path, wt: Path, paths: list[str]) -> dict[str, str]:
    """Copy the working-tree version of `paths` into a fresh worktree.

    Returns path -> digest so the ownership check can tell a file the orchestrator
    placed from one the agent wrote. Seeding is NOT free of consequence: the
    worktree is then a working state rather than a clean git state, which is why it
    is opt-in per contract and reported on every claim.
    """
    seeded: dict[str, str] = {}
    for rel in paths:
        src = repo / rel
        if not src.is_file():
            continue
        dst = wt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError:
            continue
        seeded[rel] = _digest(dst)
    return seeded


def commit_unit_work(store: Store, unit: dict, state: dict) -> None:
    """Commit whatever the unit produced, on its own branch.

    An agent that forgets to commit would otherwise pass its gate -- the gate
    sees working-tree files -- and then merge nothing, because the branch has no
    commits. The whole run reports success and produces an empty integration
    branch, so the orchestrator commits on the agent's behalf.

    Stage ONLY what the unit owns. `git add -A` would also commit whatever a
    setup hook put in the worktree: a node_modules symlink, for instance, which
    then merges into the integration branch and becomes a self-referential link
    that destroys the real directory.
    """
    wt = Path(state.get("worktree") or store.repo)
    for pattern in unit["owns"]:
        spec = pattern[:-3] if pattern.endswith("/**") else pattern
        run(["git", "add", "-A", "--", f":(glob){spec}" if "*" in spec else spec],
            cwd=wt)
    run(["git", "reset", "-q", "--", WORK_DIR], cwd=wt)
    if run(["git", "diff", "--cached", "--name-only"], cwd=wt).stdout.strip():
        run(["git", "commit", "-q", "-m", f"anthill: {unit['id']}"], cwd=wt)


def integrate(store: Store, contract: dict, unit: dict, state: dict) -> tuple[bool, str]:
    """Merge a gated unit branch into the integration branch.

    Serialised through a lock file: git allows one merge at a time in a checkout,
    and several workers finish at once.
    """
    guard = store.locks_dir / "_integrate.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            break
        except FileExistsError:
            time.sleep(1)
    else:
        return False, "timed out waiting for the integration lock"
    try:
        commit_unit_work(store, unit, state)
        wt, target = ensure_integration(store, contract)
        if wt is None:
            return False, f"could not prepare the integration worktree: {target}"
        res = run(["git", "merge", "--no-ff", "-m",
                   f"anthill: {unit['id']} (gate passed)", state["branch"]], cwd=wt)
        if res.returncode != 0:
            conflicts = run(["git", "diff", "--name-only", "--diff-filter=U"],
                            cwd=wt).stdout.strip()
            run(["git", "merge", "--abort"], cwd=wt)
            if conflicts:
                return False, "conflicting paths:\n  " + "\n  ".join(
                    conflicts.splitlines()[:10])
            return False, (res.stderr or res.stdout).strip()
        return True, ""
    finally:
        guard.unlink(missing_ok=True)


# ------------------------------------------------------------------ lifecycle

def plan(store: Store) -> dict[str, Any]:
    contract = store.load_contract()
    units = contract["units"]
    waves = compute_waves(units)
    path = critical_path(units)
    return {
        "project": contract.get("project", ""),
        "unit_count": len(units),
        "wave_count": len(waves),
        "waves": [{"wave": i, "units": w} for i, w in enumerate(waves)],
        "widest_wave": max((len(w) for w in waves), default=0),
        "critical_path": path,
        "critical_path_length": len(path),
        "ungated": [u["id"] for u in units if not str(u.get("gate", "")).strip()],
    }


def status(store: Store) -> dict[str, Any]:
    contract = store.load_contract()
    states = store.all_states(contract)
    counts: dict[str, int] = defaultdict(int)
    for st in states.values():
        counts[st["status"]] += 1
    ready = [u["id"] for u in ready_units(contract, states)]
    return {
        "project": contract.get("project", ""),
        "unit_count": len(contract["units"]),
        "by_status": dict(counts),
        "ready": ready,
        "ready_count": len(ready),
        "in_flight": [uid for uid, st in states.items()
                      if st["status"] in (CLAIMED, GATED)],
        "escalated": [uid for uid, st in states.items()
                      if st["status"] == ESCALATED],
        "done": sorted(uid for uid, st in states.items() if st["status"] == DONE),
        "complete": all(st["status"] in TERMINAL for st in states.values()),
    }


def build_brief(store: Store, contract: dict, unit: dict, state: dict) -> dict:
    """The unit brief is the contract with the agent: task-local context only,
    no global docs and no other units' details. That is what keeps token cost
    flat as the project grows."""
    brief_file = store.briefs_dir / f"{safe(unit['id'])}.md"
    if not brief_file.exists():
        store.briefs_dir.mkdir(parents=True, exist_ok=True)
        brief_file.write_text(
            f"# {unit['id']}\n\n{unit.get('brief', '')}\n", encoding="utf-8")
    return {
        "unit": unit["id"],
        "title": unit.get("title", ""),
        "brief": unit.get("brief", ""),
        "brief_file": str(brief_file),
        "owns": unit["owns"],
        "gate": unit["gate"],
        "worktree": state.get("worktree", ""),
        "branch": state.get("branch", ""),
        "attempts": state.get("attempts", 0),
        "escalate_after": unit.get("escalate_after", 2),
        "seeded_files": state.get("seeded_count", 0),
        "rules": ("Edit only inside owns. Prove the work with the gate. "
                  "You cannot mark yourself done."
                  + (" This worktree was seeded with the repo's uncommitted working "
                     "state, so it is not a clean commit."
                     if state.get("seeded_count") else "")),
    }


def claim(store: Store, worker: str, unit_id: str = "",
          isolate: bool | None = None) -> tuple[dict[str, Any], int]:
    """Atomically claim the next ready unit and return its brief.

    "Nothing ready" and "nothing left to do" are different facts, and a worker
    that conflates them exits during a long dependency and leaves the next wave
    to run single-file. EXIT_WAIT means wait; EXIT_DRAINED means stop.
    """
    contract = store.load_contract()
    if isolate is None:
        if "isolate" in contract:
            isolate = bool(contract["isolate"])
        else:
            try:
                from anthill import context as _c
                isolate = bool((_c.current().config.get("execution") or {})
                               .get("isolate", False))
            except Exception:                      # pragma: no cover
                isolate = False
    reap_stale(store, contract)
    states = store.all_states(contract)

    candidates = ready_units(contract, states)
    if unit_id:
        candidates = [u for u in candidates if u["id"] == unit_id]
    # Shallowest first: unblock the widest set of dependents soonest.
    dependents_count: dict[str, int] = defaultdict(int)
    for u in contract["units"]:
        for d in deps_of(u):
            dependents_count[d] += 1
    candidates.sort(key=lambda u: (-dependents_count[u["id"]], u["id"]))

    for unit in candidates:
        if not store.acquire(unit["id"], worker):
            continue  # another worker won the race; try the next one
        state = states[unit["id"]]
        state.update({"status": CLAIMED, "owner": worker, "claimed_at": now()})
        if isolate:
            try:
                wt, branch = provision_worktree(store, contract, unit["id"])
            except OrchestratorError as exc:
                store.release_lock(unit["id"])
                raise
            state["worktree"] = str(wt)
            state["branch"] = branch
            # Where this unit started. Recorded now, while it is a fact, rather
            # than re-derived at gate time from a branch that has moved since.
            state["base_commit"] = head_commit(wt)
            # A fresh worktree has no gitignored artefacts -- no node_modules, no
            # local database. Whatever the gate needs to run, this hook supplies.
            if contract.get("seed_working_state"):
                seeded = seed_worktree(
                    store.repo, wt,
                    working_state(store.repo, contract.get("seed_paths")))
                state["seeded"] = seeded
                state["seeded_count"] = len(seeded)
            setup = contract.get("setup_cmd")
            if setup:
                env = dict(os.environ, REPO=str(store.repo), WORKTREE=str(wt),
                           UNIT=unit["id"])
                res = subprocess.run(setup, shell=True, cwd=str(wt), env=env,
                                     capture_output=True, text=True)
                if res.returncode != 0:
                    store.release_lock(unit["id"])
                    raise OrchestratorError(
                        f"setup_cmd failed for {unit['id']}: "
                        f"{(res.stderr or res.stdout).strip()[:400]}")
        else:
            state["worktree"] = str(store.repo)
            # The branch actually checked out, not the contract's base. In place
            # the unit works on whatever the operator has open; recording `main`
            # here sent `done` off to merge a branch the unit never touched.
            state["branch"] = current_branch(store.repo) or contract.get("base_branch", "main")
            # In place there is no branch that means "where this unit started",
            # so the commit is the only thing that does. Everything below, and
            # the ownership check at gate time, measures from here.
            base = head_commit(store.repo)
            state["base_commit"] = base
            # Working in place means the unit inherits whatever the operator had
            # already left dirty, and the ownership check would blame it for all
            # of it -- observed: an agent failed for CLAUDE.md, which install had
            # written before the unit existed. Baseline it, in the shape `seeded`
            # uses, so pre-existing content is exempt while any further change to
            # those files is still a violation.
            pre = {}
            for rel in changed_files(store.repo, base):
                q = store.repo / rel
                if not q.is_symlink():
                    pre[rel] = _state_of(q)
            state["seeded"] = pre
            state["seeded_count"] = len(pre)
            state["in_place"] = True
        store.write_state(unit["id"], state)
        return build_brief(store, contract, unit, state), 0

    # Re-read state before deciding "wait" versus "nothing left". The snapshot
    # above is stale by now, and the window is real: a claimer holds its lock
    # from the atomic acquire but only writes CLAIMED after provisioning a
    # worktree, which takes git a few hundred milliseconds. A worker that judged
    # from the stale snapshot saw the unit as merely blocked, concluded the board
    # was stuck, and exited for good -- measured with three workers on a
    # one-unit first wave, where two of the three quit at startup and the run
    # silently degraded to a single worker.
    #
    # The lock is the authoritative claim signal precisely because it is taken
    # atomically and first, so a held lock counts as in flight on its own.
    states = store.all_states(contract)
    remaining = [u for u in contract["units"]
                 if states[u["id"]]["status"] not in TERMINAL]
    in_flight = [u for u in remaining
                 if states[u["id"]]["status"] in (CLAIMED, GATED)
                 or store.read_lock(u["id"]) is not None]
    if not remaining:
        return {"status": "drained", "reason": "every unit is terminal"}, EXIT_DRAINED
    if not in_flight:
        return {"status": "stuck",
                "reason": "units remain but none are ready and none are in "
                          "flight -- their dependencies escalated",
                "remaining": [u["id"] for u in remaining][:20]}, EXIT_DRAINED
    return {"status": "waiting",
            "reason": f"{len(in_flight)} unit(s) in flight; more work will open up",
            "in_flight": [u["id"] for u in in_flight]}, EXIT_WAIT


def write_escalation(store: Store, unit: dict, state: dict) -> Path:
    gate = state.get("gate", {})
    store.esc_dir.mkdir(parents=True, exist_ok=True)
    path = store.esc_dir / f"{safe(unit['id'])}.md"
    tail = gate.get("output_tail", "")
    path.write_text(
        f"# ESCALATION — {unit['id']}\n\n"
        f"- attempts: {state.get('attempts')}\n"
        f"- gate: `{gate.get('cmd')}`\n"
        f"- exit: {gate.get('exit')}\n"
        f"- worktree: {state.get('worktree')}\n"
        f"- at: {now()}\n\n"
        f"## Failing output\n\n```\n{tail}\n```\n"
        # A silent gate (`grep -q ... && cmd`) produces no output at all, which
        # is how an escalation ends up with an empty evidence block. Say so here
        # rather than leaving a reader to wonder whether it was lost.
        + ("\n_The gate produced no output, so the cause must be reproduced by "
           "running it again._\n" if not tail.strip() else ""),
        encoding="utf-8")
    return path


def record_gate(store: Store, unit: dict, state: dict, cmd: str,
                exit_code: int, output: str) -> None:
    state["gate"] = {"cmd": cmd, "exit": exit_code, "at": now(),
                     "output_tail": output}
    if exit_code == 0:
        state["status"] = GATED
    elif exit_code == EXIT_NOT_REVIEWED:
        state["status"] = CLAIMED
        state["awaiting_audit"] = True
    elif exit_code == EXIT_OWNERSHIP:
        # `escalate_after` exists to catch a unit that cannot make its tests
        # pass. A boundary mistake is a different animal: the offending file is
        # named in the output, reverting it is seconds of work, and the check
        # runs before the gate command so nothing about the unit's actual work
        # has been tested yet. Charging it an attempt spends half the budget on
        # the cheapest, most self-evident class of failure there is -- two of
        # them escalated a unit here before its gate had ever run once.
        state.pop("awaiting_audit", None)
        state["status"] = CLAIMED
    else:
        state.pop("awaiting_audit", None)
        state["attempts"] = state.get("attempts", 0) + 1
        # `escalate_after: 0` means never. In solo mode the contract is compiled
        # that way: one interactive agent escalates when it has judged it
        # cannot finish, and a counter that decides for it produced three
        # escalations on this tool's first project -- every one of them false.
        limit = int(unit.get("escalate_after", 2) or 0)
        if limit and state["attempts"] >= limit:
            state["status"] = ESCALATED
            write_escalation(store, unit, state)
            store.release_lock(unit["id"])
        else:
            state["status"] = CLAIMED
    store.write_state(unit["id"], state)


def load_board(store: Store, source: Path, write: bool = True) -> dict[str, Any]:
    """Seed or refresh the board from a compiled contract.

    `sprint compile` writes the contract the owner approved; the orchestrator
    reads a copy inside the run directory. Nothing joined the two, so extending
    a sprint from 8 units to 12 left the board on the old 8 and `work next`
    reported "drained" -- every unit on a board nobody had told about the new
    work. The gap went unnoticed for two weeks because every test of the
    orchestrator copied the file by hand first.

    Existing unit state is preserved: a unit that is already `done` stays done.
    Units the new contract drops are reported rather than deleted, because their
    state is the only record that the work happened.
    """
    source = Path(source)
    if not source.exists():
        raise OrchestratorError(f"no contract at {source}; run `sprint compile` first")
    contract = json.loads(source.read_text(encoding="utf-8"))
    validate_contract(contract)
    new_ids = [str(u["id"]) for u in contract["units"]]

    old_ids: list[str] = []
    if store.contract_path.exists():
        try:
            old_ids = [str(u["id"]) for u in
                       json.loads(store.contract_path.read_text(encoding="utf-8")
                                  ).get("units") or []]
        except (OSError, json.JSONDecodeError):
            old_ids = []

    have_state = sorted(p.stem for p in store.state_dir.glob("*.json")) \
        if store.state_dir.exists() else []
    added = [u for u in new_ids if u not in old_ids]
    dropped = [u for u in old_ids if u not in new_ids]
    # State for a unit no contract declares. Left alone: it is the only record
    # that the work happened, and `work status` reads the contract so it never
    # surfaces there.
    orphaned = [s for s in have_state if s not in new_ids]

    if write:
        store.init_dirs()
        write_json_atomic(store.contract_path, contract)

    return {
        "board": str(store.contract_path),
        "from": str(source),
        "units": len(new_ids),
        "added": added,
        "dropped": dropped,
        "orphaned_state": orphaned,
        "written": write,
        "note": ("existing unit state is kept, so anything already done stays "
                 "done; new units start unclaimed"),
    }


def reopen(store: Store, unit_id: str, reason: str = "",
           by: str = "") -> tuple[dict[str, Any], int]:
    """Return an escalated or blocked unit to the board.

    Written because its absence forced hand-editing of a state file. An
    escalation is a considered verdict; once a human has looked, there has to be
    a sanctioned way to say "fixed, try again". Editing JSON is indistinguishable
    from tampering and leaves no record of who decided what.

    A `done` unit is never reopened: its work is already merged.
    """
    contract = store.load_contract()
    unit = find_unit(contract, unit_id)
    state = store.read_state(unit["id"])
    if state["status"] == DONE:
        return ({"refused": f"{unit_id} is done; its work is already merged. "
                            "Add a new unit rather than reopening this one."},
                EXIT_TERMINAL)
    previous = state["status"]
    state.setdefault("reopened", []).append(
        {"at": now(), "from": previous, "by": by or "(unattributed)",
         "reason": reason, "attempts_cleared": state.get("attempts", 0)})
    cleared = state.get("attempts", 0)
    state["status"] = READY
    state["attempts"] = 0
    state.pop("owner", None)
    state.pop("awaiting_audit", None)
    store.write_state(unit["id"], state)
    store.release_lock(unit["id"])
    esc = store.root / "escalations" / f"{safe(unit_id)}.md"
    if esc.exists():
        esc.replace(esc.with_suffix(".resolved.md"))
    return ({"unit": unit_id, "was": previous, "now": READY,
             "attempts_cleared": cleared, "reason": reason or "(none given)",
             "note": "the unit is claimable again; its worktree and commits are "
                     "untouched"}, 0)


def gate(store: Store, unit_id: str) -> tuple[dict[str, Any], int]:
    """Ownership check, then the unit's own gate. The exit code becomes the only
    fact that matters about this unit."""
    contract = store.load_contract()
    unit = find_unit(contract, unit_id)
    state = store.read_state(unit["id"])

    # An agent that escalated has already given a considered verdict. Running the
    # gate over the top of it burns a second attempt and can overwrite the
    # escalation -- observed with a unit that reached attempts=2 for a contract
    # bug it had correctly diagnosed on the first pass.
    if state["status"] in TERMINAL:
        return {"refused": f"{unit['id']} is already {state['status']}"}, EXIT_TERMINAL

    worktree = Path(state.get("worktree") or store.repo)
    base = ownership_base(contract, state)
    violations, ignored = check_ownership(
        worktree, unit["owns"], base,
        artefact_ignore=contract.get("artefact_ignore"),
        seeded=state.get("seeded"))
    if violations:
        # Name the base. Without it the failure reads as a pure accusation --
        # "you wrote outside owns" -- and a misconfigured base is indistinguish-
        # able from a real boundary breach, which is how 41 files somebody else
        # deleted got charged to a unit that had touched none of them.
        record_gate(store, unit, state, cmd="<ownership>", exit_code=EXIT_OWNERSHIP,
                    output=f"wrote outside owns, measured against {base}:\n  "
                           + "\n  ".join(violations))
        return {"unit": unit["id"], "result": "ownership_violation",
                "measured_against": base,
                "violations": violations,
                "ignored_artefacts": ignored}, EXIT_OWNERSHIP

    # The gate's steps that diff the tree -- `anthill blueprint`, `anthill audit
    # check` -- used to pick their own base, and picked `integration`: a branch
    # 147 commits stale here, so a unit that changed nothing was refused for 404
    # files' worth of somebody else's drift. The base a unit is measured from is
    # a fact this function already holds; hand it down.
    env = dict(exec_env(), ANTHILL_UNIT=unit["id"], ANTHILL_UNIT_BASE=base)
    res = run(unit["gate"], cwd=worktree, env=env)
    output = (res.stdout or "") + (res.stderr or "")
    record_gate(store, unit, state, cmd=unit["gate"],
                exit_code=res.returncode, output=output[-4000:])
    after = store.read_state(unit["id"])
    return {"unit": unit["id"], "gate": unit["gate"], "exit": res.returncode,
            "result": "passed" if res.returncode == 0 else "failed",
            "ignored_artefacts": ignored,
            "status": after["status"], "attempts": after.get("attempts", 0),
            "output_tail": output[-2000:]}, res.returncode


def done(store: Store, unit_id: str) -> tuple[dict[str, Any], int]:
    """The load-bearing rule of the whole system: an agent cannot assert
    completion. Only a passing gate closes a unit."""
    contract = store.load_contract()
    unit = find_unit(contract, unit_id)
    state = store.read_state(unit["id"])
    g = state.get("gate") or {}

    if g.get("exit") != 0:
        return {"refused": f"{unit['id']} has no passing gate "
                           f"(exit={g.get('exit', 'never run')})",
                "next": "run the gate first"}, EXIT_NO_GATE

    # Integrate before closing. Without this a unit's output stays on its own
    # branch, and every downstream worktree -- cut from the integration branch --
    # starts from a tree that does not contain its dependencies.
    #
    # Not in place. There the unit's work is already in the operator's tree, on
    # the branch they have open, next to their own uncommitted edits -- and
    # `commit_unit_work` stages by `owns` glob, so it would commit whatever of
    # theirs happened to fall inside the unit's paths. The unit closes; what to
    # commit, and when, stays the operator's call.
    in_place = bool(state.get("in_place"))
    if (not in_place and state.get("branch")
            and state["branch"] != integration_branch(contract)):
        ok, detail = integrate(store, contract, unit, state)
        if not ok:
            state["status"] = ESCALATED
            state["escalation_reason"] = f"merge conflict: {detail}"
            store.write_state(unit["id"], state)
            write_escalation(store, unit, state)
            store.release_lock(unit["id"])
            return {"refused": f"{unit['id']} passed its gate but will not merge",
                    "detail": detail,
                    "meaning": "units own disjoint paths, so a conflict means two "
                               "units claim the same file -- a contract bug, not a "
                               "code bug"}, EXIT_CONFLICT

    state["status"] = DONE
    state["done_at"] = now()
    store.write_state(unit["id"], state)
    store.release_lock(unit["id"])

    out: dict[str, Any] = {"unit": unit["id"], "status": DONE}
    # A finished sprint whose blueprint still describes the tree from before it
    # ran is worse than no blueprint: it is confidently out of date.
    states = store.all_states(contract)
    if not [u["id"] for u in contract["units"]
            if states.get(u["id"], {}).get("status") != DONE]:
        out["sprint_complete"] = True
        out["blueprint"] = _refresh_blueprint(store)
    return out, 0


def _refresh_blueprint(store: Store) -> dict[str, Any]:
    """Redraw the map over the integrated tree, and report the intent gap.

    Failure never fails the unit: the work is merged and gated, and a map that
    could not be rebuilt is a reporting problem.
    """
    try:
        from anthill import integrate as _integrate, context as _ctx
        from anthill.navigate import build_map, structure
        ctx = _ctx.current()
        # In place, the integration worktree exists but holds nothing -- units
        # merge into the repo itself. Scanning it produced a blueprint of zero
        # nodes for a sprint that had just landed two files.
        contract = store.load_contract()
        in_place = not contract.get("isolate", False)
        tree = store.repo if in_place else (
            _integrate.integration_tree(ctx) or store.repo)
        build_map.REPO_ROOT = tree
        structure.REPO_ROOT = tree
        inc, top = _ctx.discover_sources(tree, set(build_map.EXCLUDE_PARTS))
        cfg = ctx.config.get("source") or {}
        build_map.INCLUDE_DIRS = cfg.get("include_dirs") or inc
        build_map.INCLUDE_TOPLEVEL = cfg.get("include_toplevel") or top
        structure.INCLUDE_DIRS = build_map.INCLUDE_DIRS
        structure.INCLUDE_TOPLEVEL = build_map.INCLUDE_TOPLEVEL
        m = build_map.build()
        build_map.OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        build_map.OUT_PATH.write_text(json.dumps(m, indent=2), encoding="utf-8")
        gap = _integrate.report_gap(ctx, tree)
        return {"nodes": len(m["nodes"]),
                "anchors": sum(len(n["anchors"]) for n in m["nodes"]),
                "scanned": str(tree),
                "intent_gap": {k: gap.get(k) for k in
                               ("share_explained", "files_with_no_page")}}
    except Exception as exc:                            # pragma: no cover
        return {"error": f"blueprint not refreshed: {exc}"}


def release(store: Store, unit_id: str) -> dict[str, Any]:
    contract = store.load_contract()
    unit = find_unit(contract, unit_id)
    state = store.read_state(unit["id"])
    if state["status"] not in TERMINAL:
        state["status"] = BLOCKED
        state.pop("owner", None)
        store.write_state(unit["id"], state)
    store.release_lock(unit["id"])
    return {"unit": unit["id"], "released": True, "status": state["status"]}


def escalate(store: Store, unit_id: str, reason: str) -> dict[str, Any]:
    contract = store.load_contract()
    unit = find_unit(contract, unit_id)
    state = store.read_state(unit["id"])
    state["status"] = ESCALATED
    state["escalation_reason"] = reason
    store.write_state(unit["id"], state)
    path = write_escalation(store, unit, state)
    store.release_lock(unit["id"])
    return {"unit": unit["id"], "status": ESCALATED, "escalation": str(path)}


def silence_seconds(store: Store, unit_id: str) -> float | None:
    lock = store.read_lock(unit_id)
    if not lock:
        return None
    hb = lock.get("heartbeat")
    return None if hb is None else max(0.0, time.time() - float(hb))


def reap_stale(store: Store, contract: dict) -> list[str]:
    """A worker that died holding a lock must not block its unit forever.

    Only silence is evidence -- a claim with a fresh heartbeat is left alone
    however long it has been running.
    """
    reaped = []
    for unit in contract["units"]:
        uid = unit["id"]
        state = store.read_state(uid)
        if state["status"] != CLAIMED:
            continue
        quiet = silence_seconds(store, uid)
        if quiet is not None and quiet > STALE_LOCK_SECONDS:
            state["status"] = BLOCKED
            state.pop("owner", None)
            store.write_state(uid, state)
            store.release_lock(uid)
            reaped.append(uid)
    return reaped
