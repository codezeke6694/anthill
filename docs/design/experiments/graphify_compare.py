"""Anthill's map vs Graphify vs both, on LogiAstro's own past changes.

Run from the LogiAstro root with PYTHONPATH=~/anthill. Same questions, same
scoring as `anthill eval-map`: a past commit's title is the task, the files it
changed are the answer, asked with that commit hidden from Anthill's history.
"""
import json, re, subprocess, sys
from collections import defaultdict
from pathlib import Path

S = Path(__file__).parent
GRAPH = S / "out/graphify-out/graph.json"
GFY = str(Path.home() / ".local/bin/graphify")

from anthill.navigate import router
from anthill.knowledge import evaluate

nodes = router._nodes()
node_files = {n["node_id"]: n["file"] for n in nodes if n.get("file")}
by_id = {n["node_id"]: n for n in nodes}
file_to_node = {f: n for n, f in node_files.items()}
qs = evaluate.history_questions(router.REPO_ROOT, node_files)

# Graphify's graph: file-level neighbours (any edge between symbols in two files).
g = json.load(open(GRAPH))
gfile = {n["id"]: n.get("source_file") or "" for n in g["nodes"]}
gnear = defaultdict(set)
for e in g["links"]:
    a, b = gfile.get(e["source"], ""), gfile.get(e["target"], "")
    if a and b and a != b and e.get("relation") != "rationale_for":
        gnear[a].add(b); gnear[b].add(a)

cache = S / "gquery-cache.json"
gcache = json.loads(cache.read_text()) if cache.exists() else {}

def graphify_files(q: str) -> list[str]:
    """Files in the order Graphify's query surfaces them: start nodes first, then the walk."""
    if q not in gcache:
        out = subprocess.run([GFY, "query", q, "--graph", str(GRAPH), "--budget", "20000"],
                             capture_output=True, text=True, cwd=S / "src").stdout
        gcache[q] = out
    seen, files = set(), []
    for m in re.finditer(r"^NODE .*?\[src=([^ \]]*)", gcache[q], re.M):
        f = m.group(1)
        if f and f not in seen:
            seen.add(f); files.append(f)
    return files

def anthill_files(q, commit, k):
    return [node_files.get(r["node_id"]) for r in router._rank_nodes(q, k, frozenset([commit]))]

def anthill_near(files):
    near = set()
    for f in files:
        node = by_id.get(file_to_node.get(f)) or {}
        near.update(node_files.get(r.get("go_to")) for r in node.get("routes") or [])
        near.update(node_files.get(c) for c in node.get("consumers") or [])
    return near

def fuse(a: list, b: list, wb: float, k=60):
    """Reciprocal-rank fusion: Anthill's order plus a weighted vote from Graphify's."""
    s = defaultdict(float)
    for i, f in enumerate(a): s[f] += 1 / (k + i)
    for i, f in enumerate(b): s[f] += wb / (k + i)
    return sorted(s, key=lambda f: -s[f])

def score(rows):
    n = len(rows)
    return {k: round(100 * sum(r[k] for r in rows) / n) for k in ("top1", "top3", "one_step")}

variants = defaultdict(list)
for q in qs:
    want = set(q["expected_files"])
    a10 = anthill_files(q["question"], q["commit"], 10)
    gf = [f for f in graphify_files(q["question"]) if f in file_to_node][:10]
    def row(top, near):
        top = top[:3]
        return {"top1": bool(top) and top[0] in want, "top3": any(f in want for f in top),
                "one_step": any(f in want for f in top) or bool(near & want)}
    a3 = a10[:3]
    variants["1 Anthill alone"].append(row(a3, anthill_near(a3)))
    variants["2 Graphify alone"].append(row(gf, set().union(*(gnear[f] for f in gf[:3])) if gf else set()))
    variants["3 Anthill + Graphify one-step"].append(
        row(a3, anthill_near(a3) | set().union(*(gnear[f] for f in a3 if f))))
    for wb in (0.3, 0.6, 1.0):
        fz = fuse(a10, gf, wb)
        variants[f"4 Anthill ranked with Graphify vote {wb}"].append(
            row(fz, anthill_near(fz[:3]) | set().union(*(gnear[f] for f in fz[:3] if f))))

cache.write_text(json.dumps(gcache))
print(f"{len(qs)} past changes")
for name, rows in variants.items():
    print(f"{name:45s} {score(rows)}")

# How many files does "one step" offer the agent? A bigger set passes more often by size alone.
import statistics, random
sz_a, sz_ag, hit_rand = [], [], []
random.seed(1)
allf = list(file_to_node)
for q in qs:
    a3 = [f for f in anthill_files(q["question"], q["commit"], 3) if f]
    na = anthill_near(a3) - {None}
    ng = set().union(*(gnear[f] for f in a3)) if a3 else set()
    extra = (ng - na) - set(a3)
    sz_a.append(len(na)); sz_ag.append(len(na | ng))
    # same number of extra files, picked at random from the map: does that also lift one-step?
    want = set(q["expected_files"])
    base = any(f in want for f in a3) or bool(na & want)
    rnd = set(random.sample(allf, min(len(extra), len(allf))))
    hit_rand.append(base or bool(rnd & want))
print("files one step away, median: Anthill", statistics.median(sz_a), "| Anthill+Graphify", statistics.median(sz_ag))
print("one_step if the same number of extra files were picked at random:", round(100*sum(hit_rand)/len(hit_rand)))
