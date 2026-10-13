"""What does a change reach? Anthill's file pathways vs Graphify's function links.

A past commit that changed several mapped files is a question: start from one of
the files it changed (and, for the function-level variants, the functions it
changed there), predict which other files the change reaches, and score against
the files the commit really changed. Every changed file takes a turn as the start.

A longer list catches more by size alone, so each prediction is also scored
against a random list of the same length, and precision is reported beside recall.

Run from the project root with PYTHONPATH=<anthill>.
"""
import json, random, re, subprocess, statistics
from collections import defaultdict
from pathlib import Path

S = Path(__file__).parent
GRAPH = S / "out/graphify-out/graph.json"
ROOT = Path.cwd()

from anthill.navigate import router
from anthill.knowledge import evaluate

nodes = router._nodes()
node_files = {n["node_id"]: n["file"] for n in nodes if n.get("file")}
by_file = {n["file"]: n for n in nodes if n.get("file")}
mapped = set(by_file)
qs = [q for q in evaluate.history_questions(router.REPO_ROOT, node_files) if len(q["expected_files"]) >= 2]

# ---- Anthill: the pathways a card shows (what this file uses, what uses it)
def anthill_reach(f):
    n = by_file.get(f) or {}
    out = {node_files.get(r.get("go_to")) for r in n.get("routes") or []}
    out |= {node_files.get(c) for c in n.get("consumers") or []}
    return {x for x in out if x and x != f}

# ---- Graphify: symbol graph
g = json.load(open(GRAPH))
gfile = {n["id"]: n.get("source_file") or "" for n in g["nodes"]}
gname = {n["id"]: re.sub(r"\(\)$", "", n.get("label", "")) for n in g["nodes"]}
CALLISH = {"calls", "indirect_call", "references", "uses", "inherits", "method"}
callers, callees, fnear = defaultdict(set), defaultdict(set), defaultdict(set)
for e in g["links"]:
    a, b, rel = e["source"], e["target"], e.get("relation")
    if rel == "rationale_for":
        continue
    fa, fb = gfile.get(a, ""), gfile.get(b, "")
    if fa and fb and fa != fb:
        fnear[fa].add(fb); fnear[fb].add(fa)
    if rel in CALLISH:
        callers[b].add(a); callees[a].add(b)
symbols_in = defaultdict(dict)
for nid, f in gfile.items():
    if f:
        symbols_in[f].setdefault(gname[nid], set()).add(nid)

DEF = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)|^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"
                 r"|^\s*(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|function|\w+\s*=>)"
                 r"|^\s*class\s+(\w+)|^\s{2,}(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{")

def changed_functions(commit, f):
    """Names of the functions a commit edited in one file, from its diff and the file as it was then."""
    try:
        text = subprocess.run(["git", "show", f"{commit}:{f}"], capture_output=True, text=True, cwd=ROOT).stdout.splitlines()
        diff = subprocess.run(["git", "show", "-U0", "--format=", commit, "--", f], capture_output=True, text=True, cwd=ROOT).stdout
    except Exception:
        return set()
    lines = set()
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, cnt = int(m.group(1)), int(m.group(2) or 1)
        lines.update(range(start, start + max(cnt, 1)))
    names = set()
    for ln in lines:
        for i in range(min(ln, len(text)) - 1, -1, -1):
            m = DEF.match(text[i])
            if m:
                names.add(next(x for x in m.groups() if x)); break
    return names

def graphify_reach(commit, f, mode):
    if mode == "file":
        return {x for x in fnear.get(f, ()) if x != f}
    ids = set()
    for name in changed_functions(commit, f):
        ids |= symbols_in[f].get(name, set())
    out = set()
    for i in ids:
        out |= {gfile[c] for c in callers[i]}
        if mode == "callers+callees":
            out |= {gfile[c] for c in callees[i]}
    return {x for x in out if x and x != f}

random.seed(7)
pool = sorted(mapped)
res = defaultdict(lambda: {"found": 0, "wanted": 0, "named": 0, "rand_found": 0, "sizes": []})
for q in qs:
    want = set(q["expected_files"])
    for start in want:
        others = want - {start}
        preds = {
            "Anthill pathways (file to file)": anthill_reach(start),
            "Graphify, file to file": graphify_reach(q["commit"], start, "file"),
            "Graphify, callers of the changed functions": graphify_reach(q["commit"], start, "callers"),
            "Graphify, callers + callees of the changed functions": graphify_reach(q["commit"], start, "callers+callees"),
        }
        preds["Anthill pathways + Graphify callers"] = preds["Anthill pathways (file to file)"] | preds["Graphify, callers of the changed functions"]
        for name, p in preds.items():
            p &= mapped
            r = res[name]
            r["found"] += len(p & others); r["wanted"] += len(others); r["named"] += len(p); r["sizes"].append(len(p))
            rnd = set(random.sample([x for x in pool if x != start], min(len(p), len(pool) - 1)))
            r["rand_found"] += len(rnd & others)

print(f"{len(qs)} past changes that touched 2+ mapped files; each changed file takes a turn as the start\n")
print(f"{'':52s} {'caught':>7s} {'random':>7s} {'right':>6s} {'files named':>11s}")
for name, r in res.items():
    rec = 100 * r["found"] / r["wanted"]; rnd = 100 * r["rand_found"] / r["wanted"]
    prec = 100 * r["found"] / max(1, r["named"])
    print(f"{name:52s} {rec:6.0f}% {rnd:6.0f}% {prec:5.0f}% {statistics.median(r['sizes']):11.0f}")
print("\ncaught = share of the other changed files the map named; random = the same number of files picked at random;"
      "\nright = share of the named files that really changed; files named = median list length")

# ---- Only where a function's shape changed: its first line (name, inputs) was edited.
def shape_changed(commit, f):
    diff = subprocess.run(["git", "show", "-U0", "--format=", commit, "--", f], capture_output=True, text=True, cwd=ROOT).stdout
    return any(l.startswith(("+", "-")) and not l.startswith(("+++", "---")) and DEF.match(l[1:]) for l in diff.splitlines())

res2 = defaultdict(lambda: {"found": 0, "wanted": 0, "named": 0, "sizes": []})
starts = 0
for q in qs:
    want = set(q["expected_files"])
    for start in want:
        if not shape_changed(q["commit"], start):
            continue
        starts += 1
        others = want - {start}
        preds = {"Anthill pathways (file to file)": anthill_reach(start),
                 "Graphify, file to file": graphify_reach(q["commit"], start, "file"),
                 "Graphify, callers of the changed functions": graphify_reach(q["commit"], start, "callers")}
        preds["Anthill pathways + Graphify callers"] = preds["Anthill pathways (file to file)"] | preds["Graphify, callers of the changed functions"]
        for name, p in preds.items():
            p &= mapped; r = res2[name]
            r["found"] += len(p & others); r["wanted"] += len(others); r["named"] += len(p); r["sizes"].append(len(p))
print(f"\nOnly starts where a function's name or inputs changed ({starts} of them):")
for name, r in res2.items():
    print(f"{name:52s} caught {100*r['found']/r['wanted']:3.0f}%  right {100*r['found']/max(1,r['named']):3.0f}%  files named {statistics.median(r['sizes']):.0f}")
