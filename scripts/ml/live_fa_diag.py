import sys, json, runpy, numpy as np
sys.argv=["live_report.py","research/datasets/oran_flooding_live/manifest","/dev/null","--boot","1"]
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    g=runpy.run_path("scripts/ml/live_report.py")
E=g["E"]; outcome=g["outcome"]
rows=[]
for e in E:
    for k in ("soft","block"):
        o=outcome(e,e[k])
        if o["early"]:
            first=next(t for t,v in enumerate(e[k]) if v)
            kind="attacker pre-onset" if e["attack"] else ("benign, other UE attacking" if e["other_case"]!="benign_only" else "benign-only phase")
            rows.append((k,kind,e["run"],e["phase"],e["ue"],e["band"],first,e["on"] if e["attack"] else None, e["case"] or e["other_case"], int(np.sum(e["masked"][:first+1]))))
import collections
print(collections.Counter((r[0],r[1]) for r in rows))
for r in rows: print(r)
