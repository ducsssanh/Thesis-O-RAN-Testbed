"""Summarise one Korean-5G app capture: UL/DL split, packet-size and inter-arrival distribution, protocol mix.
UE IP is 10.x; we treat packets from the UE as uplink. Pure observation of benign app behaviour."""
import sys, pandas as pd, numpy as np

f = sys.argv[1]
d = pd.read_csv(f, usecols=["Time", "Source", "Destination", "Protocol", "Length"], low_memory=False)
d["Time"] = pd.to_datetime(d["Time"], errors="coerce")
d = d.dropna(subset=["Time"]).sort_values("Time").reset_index(drop=True)
# UE side = the private 10.x endpoint that appears as Source most often
src_counts = d["Source"].value_counts()
ue = next((ip for ip in src_counts.index if str(ip).startswith("10.")), src_counts.index[0])
up = d[d["Source"] == ue]
dn = d[d["Destination"] == ue]
span = (d["Time"].iloc[-1] - d["Time"].iloc[0]).total_seconds() or 1

def q(s, p): return float(np.quantile(s.dropna(), p)) if len(s.dropna()) else float("nan")

print(f"== {f.split('/')[-1]}  ue={ue} span={span:.0f}s pkts={len(d)}")
print(f"   proto={d['Protocol'].value_counts().head(5).to_dict()}")
print(f"   UL pkts={len(up)} ({len(up)*100//len(d)}%)  DL pkts={len(dn)}  UL Mbit/s={up['Length'].sum()*8/1e6/span:.3f}  DL Mbit/s={dn['Length'].sum()*8/1e6/span:.3f}")
print(f"   UL pktsize p5/50/95={q(up.Length,.05):.0f}/{q(up.Length,.5):.0f}/{q(up.Length,.95):.0f}")
# inter-arrival on uplink (ms)
iat = up["Time"].diff().dt.total_seconds().mul(1000)
print(f"   UL inter-arrival ms p50/p95={q(iat,.5):.2f}/{q(iat,.95):.2f}  UL pkts/s mean={len(up)/span:.1f}")
# per-second UL bytes series -> burstiness
ups = up.set_index("Time")["Length"].resample("1s").sum().fillna(0)
print(f"   UL bytes/s p50/p95={q(ups,.5):.0f}/{q(ups,.95):.0f}  nonzero-sec frac={np.mean(ups>0):.2f}")
