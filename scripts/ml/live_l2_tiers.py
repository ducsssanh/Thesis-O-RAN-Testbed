import sys, numpy as np
SRC = open("scripts/ml/live_report.py").read().split("rng = np.random.default_rng(0)")[0]
sys.argv = ["live_report.py", "research/datasets/oran_flooding_live5/manifest", "/dev/null"]
ns = {"__file__": "scripts/ml/live_report.py"}; exec(compile(SRC, "live_report", "exec"), ns)
E = [e for rid, rd in sorted(ns["kept"].items()) for e in ns["episodes"](rd, rid)]
oc = ns["outcome"]
L2 = [e for e in E if e["attack"] and e["ev"] == "L2"]
print("L2 attacks", len(L2))
for c in ("honest", "mimic", "hide0.1", None):
    A = [e for e in L2 if c is None or e["case"] == c]
    rs = [oc(e, e["soft"]) for e in A]; rb = [oc(e, e["block"]) for e in A]
    miss_b = [i for i, r in enumerate(rb) if not r["det"]]
    rl = sum(rs[i]["det"] for i in miss_b)
    print(c or "all", "rate %d/%d" % (sum(r["det"] for r in rs), len(A)), "block %d/%d" % (sum(r["det"] for r in rb), len(A)),
          "| block misses %d, of which rate-limited %d" % (len(miss_b), rl),
          "| either tier %d/%d" % (sum(a["det"] or b["det"] for a, b in zip(rs, rb)), len(A)),
          "| median rate delay %.1f s" % np.nanmedian([r["delay"] for r in rs]))
    if c is None:
        for i in miss_b:
            e = A[i]; print("   miss", e["run"], e["phase"], e["case"], "band", e["band"], "active s after onset", sum(e["active"][e["on"]:]), "rate det", rs[i]["det"], "rate delay", rs[i]["delay"])
