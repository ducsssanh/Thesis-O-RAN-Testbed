"""Reconstruct user sessions from the reduced (rnti,sec) table and emit the distributions the twinning plan needs."""
import sys, numpy as np, pandas as pd

GAP = 10  # s; same-RNTI silence > GAP starts a new user (matches IMDEA notebook)
r = pd.read_parquet(sys.argv[1])
r = r[r["ul_bytes"] > 0]  # UL-active seconds only (the reduced table now also holds DL-only seconds)
r = r.sort_values(["rnti", "sec"]).reset_index(drop=True)
r["mbps"] = r["ul_bytes"] * 8 / 1e6  # one second's UL in Mbit/s

# session id: new when RNTI changes or silence exceeds GAP
newsess = (r["rnti"] != r["rnti"].shift()) | (r["sec"] - r["sec"].shift() > GAP)
r["sess"] = newsess.cumsum()

def qs(s, ps=(.5, .9, .95, .99)):
    s = s.dropna()
    return {f"p{int(p*100)}": round(float(np.quantile(s, p)), 4) for p in ps} if len(s) else {}

# --- per active-second UL rate (the anchor for attack load & "heavy benign") ---
print("ACTIVE-SECOND UL Mbit/s:", qs(r["mbps"]), "mean", round(r["mbps"].mean(), 4), "max", round(r["mbps"].max(), 2))

# --- per session ---
sess = r.groupby("sess").agg(rnti=("rnti", "first"), active=("sec", "size"),
                             s0=("sec", "min"), s1=("sec", "max"),
                             mean_mbps=("mbps", "mean"), max_mbps=("mbps", "max"),
                             bytes=("ul_bytes", "sum"))
sess["wall"] = sess["s1"] - sess["s0"] + 1
sess["duty"] = sess["active"] / sess["wall"]
print("SESSIONS:", len(sess))
print("  active-seconds:", qs(sess["active"]))
print("  wallclock s:", qs(sess["wall"]))
print("  duty cycle:", qs(sess["duty"]))
print("  session mean Mbit/s:", qs(sess["mean_mbps"]))
# heavy sessions: mean rate in 0.4-1.2 Mbit/s band (load-matched to attacks)
band = sess[(sess.mean_mbps >= 0.4) & (sess.mean_mbps <= 1.2)]
print(f"  sessions with mean UL in [0.4,1.2] Mbit/s: {len(band)} ({100*len(band)/len(sess):.1f}%)")

# --- ON/OFF structure within sessions: consecutive active seconds = ON run; internal gap = OFF run ---
on_runs, off_runs = [], []
for _, grp in r.groupby("sess"):
    secs = grp["sec"].to_numpy()
    d = np.diff(secs)
    # ON run lengths: split where gap>1
    run = 1
    for gap in d:
        if gap == 1:
            run += 1
        else:
            on_runs.append(run); off_runs.append(int(gap - 1)); run = 1
    on_runs.append(run)
on_runs = pd.Series(on_runs); off_runs = pd.Series(off_runs) if off_runs else pd.Series([0])
print("ON-run s:", qs(on_runs), "mean", round(on_runs.mean(), 2))
print("OFF-gap s (within session):", qs(off_runs), "mean", round(off_runs.mean(), 2))

# --- concurrency: distinct sessions active per second ---
conc = r.groupby("sec")["sess"].nunique()
print("CONCURRENT users/sec:", qs(conc), "mean", round(conc.mean(), 1), "max", int(conc.max()))
