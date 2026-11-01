"""Per-application packet priors for the benign twin (TRAFFIC-TWINNING-PLAN §4.A, step 1.4): from the Korean 5G
captures, the empirical UL and DL packet-size distribution (101 quantiles of the captured length), the protocol mix
and the packet rates, for the apps mapped to the rate bands (P1 Roblox, YouTube Live; P2 Battleground, Teamfight
Tactics; P3 GeForce Now; P4 Zoom). UE side and direction are found as in inspect_kr5g.py.
Usage: kr5g_app_priors.py <kr5g dir> <out.json>"""
import json, sys, numpy as np, pandas as pd

APPS = {"Roblox_1": "P1", "YouTube_Live_2": "P1", "Battleground_3": "P2", "Teamfight_Tactics_6": "P2",
        "GeForce_Now_8": "P3", "Zoom_2": "P4"}
src, dst = sys.argv[1:]
priors = {}
for app, band in APPS.items():
    d = pd.read_csv(f"{src}/{app}.csv", usecols=["Time", "Source", "Destination", "Protocol", "Length"],
                    low_memory=False)
    d["Time"] = pd.to_datetime(d["Time"], errors="coerce")
    d = d.dropna(subset=["Time"]).sort_values("Time")
    counts = d["Source"].value_counts()
    ue = next((ip for ip in counts.index if str(ip).startswith("10.")), counts.index[0])
    span = (d["Time"].iloc[-1] - d["Time"].iloc[0]).total_seconds() or 1
    up, dn = d[d["Source"] == ue], d[d["Destination"] == ue]
    grid = np.linspace(0, 1, 101)
    priors[app] = {
        "band": band, "span_s": round(span),
        "ul_size_q": np.quantile(up["Length"], grid).round().astype(int).tolist(),
        "dl_size_q": np.quantile(dn["Length"], grid).round().astype(int).tolist(),
        "ul_proto": up["Protocol"].value_counts(normalize=True).head(6).round(4).to_dict(),
        "ul_pps": round(len(up) / span, 2), "dl_pps": round(len(dn) / span, 2),
        "dl_ul_bytes": round(float(dn["Length"].sum() / max(up["Length"].sum(), 1)), 3),
    }
    print(app, band, "UL size p5/50/95", priors[app]["ul_size_q"][5], priors[app]["ul_size_q"][50],
          priors[app]["ul_size_q"][95], "UL pps", priors[app]["ul_pps"])
json.dump({"source": "Korean 5G app captures (data/external/kr5g)", "length": "captured frame length, bytes",
           "apps": priors}, open(dst, "w"), indent=1)
