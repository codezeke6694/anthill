#!/usr/bin/env python3
"""The worker pool: N agents, one board, no dispatcher.

The pool is deliberately dumb. Nothing decides who does what -- every worker
races for the next ready unit and the atomic claim settles it. A worker that dies
just stops pulling; its lock ages out and the work returns to the board. That is
the whole scheduler, and it is why adding workers needs no coordination.

Ported from the proven shell pool, with one improvement the shell version needed
a comment to work around: the heartbeat runs as a daemon thread rather than a
backgrounded `sleep`, so it cannot hold a pipe open and hang the run.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import sys as _sys
if str(Path(__file__).resolve().parents[2]) not in _sys.path:
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anthill.orchestrate import orchestrator as work

IDLE_SLEEP = 10        # seconds between polls when nothing is ready
IDLE_LIMIT = 10        # consecutive empty polls before a worker gives up
FAILURE_LIMIT = 5      # hard failures are infrastructure, never spin on them
HEARTBEAT_EVERY = 60

DEFAULT_PROMPT = """\
You are a worker agent. Build exactly the unit described below, and nothing else.

Non-negotiable:
- Write only inside the unit's `owns` paths. Anything else is an ownership
  violation and the gate will refuse the unit.
- If you need a change outside your paths, stop and say so. Do not reach for it.
- Do not weaken, skip, or edit the gate to make it pass.
- Run the gate command yourself and iterate until it exits 0.
- You cannot mark yourself done. The pool closes the unit when the gate passes.

If the brief carries a previous failure, read it first and fix that specific
failure. Do not rebuild the unit from scratch.

UNIT BRIEF (JSON):
{brief}
"""


class _Heartbeat:
    """Keeps a claim alive while an agent works. Stops on exit, always."""

    def __init__(self, store: work.Store, unit_id: str, worker: str):
        self._store, self._unit, self._worker = store, unit_id, worker
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_EVERY):
            if not self._store.heartbeat(self._unit, self._worker):
                return   # the lock is gone or someone else holds it now

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()


def _run_agent(agent_cmd: str, brief: dict, worktree: Path, log_path: Path,
               prompt_template: str, timeout: int) -> int:
    """Hand the brief to the agent, in its own worktree.

    The brief arrives on stdin, so any command that reads stdin works -- a shell
    one-liner for a smoke test, a real coding agent in production.
    """
    payload = prompt_template.format(brief=json.dumps(brief, indent=2))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {brief['unit']} @ {work.now()} ===\n")
        log.flush()
        try:
            res = subprocess.run(agent_cmd, shell=True, cwd=str(worktree),
                                 input=payload, text=True, timeout=timeout,
                                 env=work.exec_env(),
                                 stdout=log, stderr=subprocess.STDOUT)
            return res.returncode
        except subprocess.TimeoutExpired:
            log.write(f"\nagent timed out after {timeout}s\n")
            return 124


def _worker_loop(store: work.Store, name: str, agent_cmd: str, isolate: bool,
                 prompt_template: str, timeout: int, idle_sleep: float,
                 events: list[dict], lock: threading.Lock) -> None:
    idle = failures = 0
    log_path = store.root / "logs" / f"{name}.log"

    def note(**kw: Any) -> None:
        with lock:
            events.append({"worker": name, "at": work.now(), **kw})

    while True:
        try:
            brief, code = work.claim(store, worker=name, isolate=isolate)
        except work.OrchestratorError as exc:
            failures += 1
            note(event="claim_error", detail=str(exc)[:300])
            if failures >= FAILURE_LIMIT:
                note(event="gave_up", reason=f"{failures} hard failures")
                return
            time.sleep(5)
            continue

        if code == work.EXIT_DRAINED:
            note(event="finished", reason=brief.get("reason", ""))
            return
        if code == work.EXIT_WAIT:
            # Work is in flight elsewhere. Waiting is correct; exiting is not --
            # a worker that quits here leaves the next wave to run single-file.
            idle += 1
            if idle >= IDLE_LIMIT:
                note(event="idle_limit", reason="work still in flight elsewhere")
                return
            time.sleep(idle_sleep)
            continue

        idle = failures = 0
        unit_id = brief["unit"]
        note(event="claimed", unit=unit_id)

        if agent_cmd:
            with _Heartbeat(store, unit_id, name):
                rc = _run_agent(agent_cmd, brief, Path(brief["worktree"]),
                                log_path, prompt_template, timeout)
            note(event="agent_exit", unit=unit_id, code=rc)

        gate_payload, grc = work.gate(store, unit_id)
        if grc == 0:
            _, drc = work.done(store, unit_id)
            note(event="done" if drc == 0 else "close_refused",
                 unit=unit_id, code=drc)
        elif grc == work.EXIT_TERMINAL:
            # The agent already gave a considered verdict; the pool must not
            # overwrite it by gating on top and burning another attempt.
            note(event="already_resolved", unit=unit_id)
        else:
            note(event="gate_failed", unit=unit_id, code=grc,
                 status=gate_payload.get("status", ""))
            if store.read_state(unit_id)["status"] not in work.TERMINAL:
                work.release(store, unit_id)


def run(store: work.Store, workers: int, agent_cmd: str = "",
        isolate: bool | None = None, prompt_template: str = DEFAULT_PROMPT,
        timeout: int = 3600, idle_sleep: float = IDLE_SLEEP) -> dict[str, Any]:
    """Run the board to completion with `workers` concurrent agents.

    An empty `agent_cmd` is a rehearsal: units are claimed and gated with no
    agent in between, which exercises the board and the gates without spending
    anything. Useful for proving a generated contract before trusting it.
    """
    contract = store.load_contract()
    plan = work.plan(store)
    events: list[dict] = []
    lock = threading.Lock()

    threads = [
        threading.Thread(
            target=_worker_loop,
            args=(store, f"w{i + 1}", agent_cmd, isolate, prompt_template,
                  timeout, idle_sleep, events, lock),
            daemon=True)
        for i in range(max(1, workers))
    ]
    started = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = work.status(store)
    return {
        "project": contract.get("project", ""),
        "workers": len(threads),
        "rehearsal": not agent_cmd,
        "waves": plan["wave_count"],
        "critical_path_length": plan["critical_path_length"],
        "elapsed_seconds": round(time.time() - started, 1),
        "events": events,
        "final": final,
        "log_dir": str(store.root / "logs"),
    }
