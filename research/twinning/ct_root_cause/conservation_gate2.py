"""Second offline test of a byte-conservation gate. Over the last W seconds D = sum(core - KPM). Allowed: theta0 (few packets)
+ L * larger of the last two core seconds (bytes in flight at a boundary) + rho * sum(core) (small real drift, measured about 1 %).
Benign: share of active seconds in violation. Tamper starts at each 30th active second of UE traffic, as a real attack starts
mid-traffic; latency = seconds of traffic until the first violation; bytes hidden until then. Usage: conservation_gate2.py <band>=<campaign>..."""
import glob, json, sys, numpy as np
BETA = 57
def load(run):
    by = {}
    for l in open(run + "/defense/features.jsonl"):
        x = json.loads(l)
        by.setdefault(x["supi"], {})[round(x["at_ms"] / 1000)] = (x["rate_ul_kbps"] * 125, max(x["prof_ul_kbps"] * 125 - BETA * x["prof_ul_pps"], 0))
    return [np.array([v[t] for t in sorted(v)]) for v in by.values()]
def viol(k, c, W, th0, L, rho):
    out = np.zeros(len(k), bool)
    for i in range(len(k)):
        if k[i] == 0 and c[i] == 0:
            continue
        a = max(0, i - W + 1)
        D, S = (c[a:i + 1] - k[a:i + 1]).sum(), c[a:i + 1].sum()
        out[i] = abs(D) > th0 + L * max(c[i], c[i - 1] if i else 0) + rho * S
    return out
for W, th0, L, rho in ((30, 3000, .2, .02), (30, 5000, .2, .02), (30, 5000, .3, .03), (15, 5000, .2, .02)):
    print("W %d theta0 %d L %.1f rho %.2f" % (W, th0, L, rho))
    for spec in sys.argv[1:]:
        band, pats = spec.split("=")
        runs = [r for p in pats.split(",") for r in glob.glob(sorted(glob.glob("artifacts/experiments/" + p))[-1] + "/runs/*/*") if glob.glob(r + "/defense/features.jsonl")]
        n = o = 0
        rows = {f: [] for f in (.8, 1.25, .33, 2)}
        hid = {f: [] for f in rows}
        missed = {f: 0 for f in rows}
        for r in runs:
            for a in load(r):
                k, c = a[:, 0], a[:, 1]
                active = np.flatnonzero((k > 0) | (c > 0))
                v = viol(k, c, W, th0, L, rho)
                n += active.size; o += int(v.sum())
                for s in active[20::30]:
                    for f in rows:
                        kk = k.copy(); kk[s:] = kk[s:] * f
                        vv = viol(kk, c, W, th0, L, rho)[s:]
                        act = (kk[s:] > 0) | (c[s:] > 0)
                        if vv.any():
                            j = int(np.argmax(vv))
                            rows[f].append(int(act[:j + 1].sum()))
                            hid[f].append(abs(kk[s:s + j + 1] - k[s:s + j + 1]).sum())
                        else:
                            missed[f] += 1
        s = " ".join("x%s lat q50/q90 %s/%s bytes q50 %d miss %d/%d |" % (f, int(np.median(rows[f])) if rows[f] else -1, int(np.percentile(rows[f], 90)) if rows[f] else -1, np.median(hid[f]) if hid[f] else 0, missed[f], missed[f] + len(rows[f])) for f in rows)
        print("  %-3s runs %d benign violations %.2f%% (%d/%d) | %s" % (band, len(runs), 100 * o / max(n, 1), o, n, s))
