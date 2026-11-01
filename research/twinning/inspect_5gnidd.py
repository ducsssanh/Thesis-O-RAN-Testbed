"""Summarise 5G-NIDD per-attack argus flows: tool, packet size, per-flow rate, sources (one row per attack file)."""
import sys, glob, pandas as pd, numpy as np

COLS = ["StartTime", "LastTime", "Dur", "SrcAddr", "DstAddr", "Proto", "Dport", "TotPkts", "SrcPkts", "SrcBytes",
        "sMeanPktSz", "SrcRate", "SrcLoad", "SIntPkt", "SrcJitAct", "State", "Label", "Attack Type", "Attack Tool"]

def q(s, p):
    s = s.dropna()
    return float(np.quantile(s, p)) if len(s) else float("nan")

for f in sorted(glob.glob(sys.argv[1] + "/*.csv")):
    d = pd.read_csv(f, low_memory=False)
    d.columns = [{"attack type": "Attack Type", "attack tool": "Attack Tool"}.get(c.strip().lower(), c.strip()) for c in d.columns]
    d = d[[c for c in COLS if c in d.columns]]
    a = d[d["Label"] != "Benign"]
    b = d[d["Label"] == "Benign"]
    if a.empty:
        continue
    print(f"== {f.split('/')[-1]}  attack flows={len(a)} benign flows={len(b)}  tool={list(a['Attack Tool'].unique()[:3])}"
          f"  type={list(a['Attack Type'].unique()[:3])}")
    print(f"   proto={a['Proto'].value_counts().head(3).to_dict()}  state={a['State'].value_counts().head(3).to_dict()}"
          f"  srcs={a['SrcAddr'].nunique()} dsts={a['DstAddr'].nunique()} dports={a['Dport'].nunique()}")
    print(f"   pkts/flow p50={q(a.TotPkts,.5):.0f} p99={q(a.TotPkts,.99):.0f}  dur p50={q(a.Dur,.5):.3f}s"
          f"  sMeanPktSz p5/50/95={q(a.sMeanPktSz,.05):.0f}/{q(a.sMeanPktSz,.5):.0f}/{q(a.sMeanPktSz,.95):.0f}"
          f"  SrcLoad(bit/s) p50={q(a.SrcLoad,.5):.0f} p95={q(a.SrcLoad,.95):.0f}"
          f"  SIntPkt(ms) p50={q(a.SIntPkt,.5):.3f}")
    # aggregate attack rate per source: bytes / (span of flows)
    span = a.groupby("SrcAddr").agg(bytes=("SrcBytes", "sum"), pkts=("SrcPkts", "sum"), n=("SrcBytes", "size"))
    # attack load per second, binned on the flow start (argus prints mm:ss.d)
    sec = a["StartTime"].astype(str).str.slice(0, 5)
    ps = a.groupby(sec).agg(pkts=("SrcPkts", "sum"), bytes=("SrcBytes", "sum"))
    print(f"   per-second (by flow start) seconds={len(ps)} pkts/s p50={q(ps.pkts,.5):.0f} p95={q(ps.pkts,.95):.0f}"
          f"  Mbit/s p50={q(ps.bytes,.5)*8/1e6:.3f} p95={q(ps.bytes,.95)*8/1e6:.3f}")
    print("   per-source totals:", span.sort_values("bytes", ascending=False).head(3).to_dict("index"))
