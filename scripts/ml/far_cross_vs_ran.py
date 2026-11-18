#!/usr/bin/env python3
"""Cross-domain vs RAN-only (XGBoost on KPM only, artifacts/clf/abl/R093_kpm, the "KPM only" model of report section 7.4)
at matched false-alarm rates on the out-of-fold scores: same computation as far_curves.py (at_far, cluster bootstrap by run,
McNemar, Wilcoxon), third model added. Writes research/clf/FAR_cross_vs_ran_oof.txt. Usage (repo root): far_cross_vs_ran.py"""
import sys
sys.argv = sys.argv[:1]
src = open("scripts/ml/far_curves.py").read().split("\nrng = np.random.default_rng(0)")[0]
a = '("core only", ["artifacts/clf/abl/R090_core"], "artifacts/clf/abl/R090_core.json")]'
assert src.count(a) == 1
src = src.replace(a, a[:-1] + ',\n          ("RAN only", ["artifacts/clf/abl/R093_kpm"], "artifacts/clf/abl/R093_kpm.json")]')
exec(compile(src, "far_curves", "exec"))
rng = np.random.default_rng(0)
L = ["Cross-domain vs RAN only (KPM), out-of-fold, at matched FAR (most sensitive threshold with FAR <= x)"]
for tn, fs in (("block", [0.10, 0.23, 0.27, 0.378, 0.5]), ("rate limit", [0.5, 1.0, 1.5, 2.0])):
    d = res[("RAN only", tn)]["dep"]
    L.append("\n== %s == RAN-only deployed: threshold %.4f FAR %.3f " % (tn, d["th"], d["far"]) +
             " ".join("%s DR %.1f%% med %.1f s" % (g, d["m"][g]["dr"], d["m"][g]["med"]) for g in GROUPS))
    for g in GROUPS:
        L.append("  %s (n = %d)" % (g, d["m"][g]["n"]))
        for f in fs:
            ca, cb = at_far(res[("cross-domain", tn)]["curve"], f), at_far(res[("RAN only", tn)]["curve"], f)
            ma, mb = ca["m"][g], cb["m"][g]; ka = ma["keys"]
            oa = sum(ca["R"][k]["det"] and not cb["R"][k]["det"] for k in ka); ob = sum(cb["R"][k]["det"] and not ca["R"][k]["det"] for k in ka)
            pm = binomtest(oa, oa + ob).pvalue if oa + ob else 1.0
            both = [k for k in ka if ca["R"][k]["det"] and cb["R"][k]["det"]]
            dif = np.array([ca["R"][k]["delay"] - cb["R"][k]["delay"] for k in both])
            pw = wilcoxon(dif).pvalue if np.any(dif != 0) else 1.0
            ci_d, ci_m = boot(ca, cb, g, rng)
            L.append("    FAR<=%.3f | cross %.3f DR %5.1f%% med %4.1f s | RAN %.3f DR %5.1f%% med %4.1f s | DR diff %+5.1f [%+5.1f, %+5.1f] %d/%d p=%.2g | med diff %+4.1f s [%+4.1f, %+4.1f] Wilcoxon p=%.2g (n=%d)" % (
                f, ca["far"], ma["dr"], ma["med"], cb["far"], mb["dr"], mb["med"], ma["dr"] - mb["dr"], *ci_d, oa, ob, pm, ma["med"] - mb["med"], *ci_m, pw, len(both)))
open("research/clf/FAR_cross_vs_ran_oof.txt", "w").write("\n".join(L) + "\n")
print("\n".join(L))
