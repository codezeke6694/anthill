#!/usr/bin/env python3
"""`anthill config`: the one sanctioned writer of `anthill.config.json`.

The config file is denied to the agent, and rightly: it holds the settings that
bind the agent. But the owner gave a direct instruction that needed one field
changed, and the agent's only move was to hand back a block of JSON to paste.
`onboard` already solves this shape for the constitution -- a denied file with
one blessed writer that fills a known set of fields. This is the same door for
the execution settings.

Deliberately narrow. Only keys on the allowlist can be set, each with a type,
so a typo cannot invent a setting and a stray value cannot break a hook. Every
change is appended to a history with who asked for it, because a setting that
changed with no record is indistinguishable from tampering.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from anthill import context as _ctx

HISTORY_FILE = "config-history.json"

# key -> (type, help). `list` values are comma-separated on the command line.
ALLOWED: dict[str, tuple[str, str]] = {
    "execution.mode": ("choice:solo,pool",
                       "solo: one interactive agent; pool: several headless agents"),
    "execution.isolate": ("bool", "work in a fresh worktree per unit"),
    "execution.base_branch": ("str", "the branch units are cut from"),
    "execution.integration_branch": ("str", "where gated units merge (pool mode)"),
    "execution.protected_branches": ("list", "branches the pre-commit hook refuses"),
    "execution.push_requires_owner": ("bool", "pre-push hook refuses every push"),
    "execution.guard_ownership": ("bool", "pre-commit refuses unowned product source"),
    "execution.guard_hygiene": ("bool", "pre-commit refuses secrets and junk files; "
                                        "pre-push refuses a force push"),
    "execution.venv": ("str", "virtualenv gates run with"),
    "audit.required": ("bool", "a unit cannot close without an audit record"),
    "audit.escalate_verdicts": ("list", "verdicts that escalate to a human"),
    "blueprint.require_page": ("bool", "every gate also requires a knowledge page"),
    "blueprint.min_coverage": ("int", "gate refuses below this share of files with a page"),
    "anthill.version": ("str", "the Anthill commit this project uses; `anthill update` "
                               "brings every laptop to it"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_value(kind: str, raw: str) -> Any:
    if kind == "bool":
        v = raw.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        raise SystemExit(f"anthill: expected true/false, got {raw!r}")
    if kind == "int":
        try:
            return int(raw)
        except ValueError:
            raise SystemExit(f"anthill: expected an integer, got {raw!r}")
    if kind == "list":
        return [x.strip() for x in raw.split(",") if x.strip()]
    if kind.startswith("choice:"):
        choices = kind.split(":", 1)[1].split(",")
        v = raw.strip().lower()
        if v not in choices:
            raise SystemExit(f"anthill: expected one of {', '.join(choices)}, got {raw!r}")
        return v
    return raw


def get(ctx: _ctx.Context, key: str) -> Any:
    block, _, field = key.partition(".")
    return (ctx.config.get(block) or {}).get(field)


def set_value(ctx: _ctx.Context, key: str, raw: str, by: str,
              write: bool = True) -> dict[str, Any]:
    if key not in ALLOWED:
        raise SystemExit(
            f"anthill: {key!r} is not a setting this command may change.\n"
            f"  Allowed: {', '.join(sorted(ALLOWED))}")
    if not by.strip():
        raise SystemExit("anthill: --by is required; a setting that changed with no "
                         "record of who asked is indistinguishable from tampering")
    kind, _ = ALLOWED[key]
    value = parse_value(kind, raw)
    block, _, field = key.partition(".")
    before = get(ctx, key)
    ctx.config.setdefault(block, {})
    ctx.config[block][field] = value
    entry = {"at": _now(), "key": key, "from": before, "to": value, "by": by.strip()}
    if write:
        ctx.save_config()
        hp = ctx.history_dir / HISTORY_FILE
        hist: list = []
        if hp.exists():
            try:
                hist = json.loads(hp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                hist = []
        hist.append(entry)
        hp.write_text(json.dumps(hist, indent=2) + "\n", encoding="utf-8")
    out = {"set": key, "from": before, "to": value, "by": by.strip(),
           "written": write}
    # These are rendered into the agent docs and the hooks; say so.
    if block == "execution" and field in ("push_requires_owner", "protected_branches",
                                          "guard_hygiene", "isolate", "mode"):
        out["next"] = ("`anthill install --force` re-renders CLAUDE.md, AGENTS.md "
                       "and the role files so the prose matches this setting")
    if key in ("execution.mode", "audit.required"):
        out["next"] = (out.get("next", "") + "; " if out.get("next") else "") + \
            "`anthill sprint compile && anthill work load --repo .` so gates pick it up"
    return out


def show(ctx: _ctx.Context) -> dict[str, Any]:
    return {k: {"value": get(ctx, k), "type": ALLOWED[k][0], "help": ALLOWED[k][1]}
            for k in ALLOWED}


def history(ctx: _ctx.Context) -> list:
    hp = ctx.history_dir / HISTORY_FILE
    if not hp.exists():
        return []
    try:
        return json.loads(hp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="anthill config",
        description="Read or change a setting. The only sanctioned writer of "
                    "anthill.config.json.")
    ap.add_argument("--project", default="")
    sub = ap.add_subparsers(dest="sub", required=True)
    sub.add_parser("show", help="Every changeable setting and its current value")
    st = sub.add_parser("set", help="Change one setting")
    st.add_argument("key", help="e.g. execution.push_requires_owner")
    st.add_argument("value")
    st.add_argument("--by", default="", help="Who asked for this change (required)")
    st.add_argument("--dry-run", action="store_true")
    sub.add_parser("history", help="Every change ever made through this command")
    args = ap.parse_args(argv)

    ctx = _ctx.resolve(args.project or None)
    if not ctx.installed:
        print(f"anthill: not installed in {ctx.root}", file=sys.stderr)
        return 2
    if args.sub == "show":
        print(json.dumps(show(ctx), indent=2))
    elif args.sub == "set":
        print(json.dumps(set_value(ctx, args.key, args.value, args.by,
                                   write=not args.dry_run), indent=2))
    else:
        print(json.dumps(history(ctx), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
