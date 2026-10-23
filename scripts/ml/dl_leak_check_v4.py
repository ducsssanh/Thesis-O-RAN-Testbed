#!/usr/bin/env python3
"""Indirect-DL leak check through RAN UL (v4).

  .venv-ml/bin/python -I scripts/ml/dl_leak_check_v4.py [--data research/datasets/oran_flooding_v4]

Designed benign DL feedback makes the UE send RLC status / HARQ-ACK / CSI on the UL, which could
inflate prb_ul_pct and thp_ul_kbps relative to the UL user-plane volume. Compares, on active
non-guard rows with URR UL > 10 kbps, the ratios
  prb_ul_pct / urr_ul_kbps   and   thp_ul_kbps / urr_ul_kbps
between BENIGN and MALICIOUS: medians per load level x victim_mode, and the univariate AUC of each
ratio (P(score MAL > BEN); 0.5 = no signal; |AUC-0.5| > 0.1 flags a leak), overall, per stratum and
per meta_pair. Writes reports/dl_leak_check_v4.md.
"""
import argparse, pathlib
import numpy as np, pandas as pd
from sklearn.metrics import roc_auc_score

RATIOS = {"prb_per_kbps": ("prb_ul_pct", "urr_ul_kbps"), "thp_per_urr": ("thp_ul_kbps", "urr_ul_kbps")}
CONTROL = "icmp_flood~icmp_ping"


def auc(g, col):
    y = (g.label == "MALICIOUS").astype(int)
    if y.nunique() < 2 or len(g) < 20:
        return None
    return round(float(roc_auc_score(y, g[col])), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research/datasets/oran_flooding_v4")
    a = ap.parse_args()
    data = pathlib.Path(a.data)
    df = pd.read_parquet(data / "rows.parquet")
    r = df[df.label.isin(["BENIGN", "MALICIOUS"]) & (df.meta_guard == 0) & (df.urr_ul_kbps > 10)].copy()
    for k, (num, den) in RATIOS.items():
        r[k] = r[num] / r[den]
    r = r.dropna(subset=list(RATIOS))
    L = ["# Indirect-DL leak check through RAN UL (v4)\n",
         "Rows: active, non-guard, URR UL > 10 kbps (n = %d). AUC = univariate ROC-AUC of the ratio for "
         "MALICIOUS vs BENIGN; 0.5 = no signal, flag if |AUC − 0.5| > 0.1.\n" % len(r)]
    L.append("## Overall\n\n| ratio | median BEN | median MAL | AUC | AUC excl. icmp control |\n|---|---:|---:|---:|---:|")
    flags = {}
    for k in RATIOS:
        m = r.groupby("label")[k].median()
        a_all, a_x = auc(r, k), auc(r[r.meta_pair != CONTROL], k)
        flags[k] = a_x
        L.append("| `%s` | %.4g | %.4g | %s | %s |" % (k, m.get("BENIGN"), m.get("MALICIOUS"), a_all, a_x))
    for k in RATIOS:
        L.append("\n## `%s` by load × victim_mode\n\n| load | victim | n | median BEN | median MAL | AUC |\n|---:|---|---:|---:|---:|---:|" % k)
        for (ld, vm), g in r.groupby(["meta_load_mbps", r.meta_victim_mode.fillna("-")]):
            m = g.groupby("label")[k].median()
            L.append("| %g | %s | %d | %s | %s | %s |" % (ld, vm, len(g), "%.4g" % m["BENIGN"] if "BENIGN" in m else "-",
                                                    "%.4g" % m["MALICIOUS"] if "MALICIOUS" in m else "-", auc(g, k)))
    L.append("\n## AUC per meta_pair\n\n| pair | " + " | ".join("`%s`" % k for k in RATIOS) + " |\n|---|" + "---:|" * len(RATIOS))
    for pr, g in r.groupby("meta_pair"):
        if "~" in str(pr):
            L.append("| %s | " % pr + " | ".join(str(auc(g, k)) for k in RATIOS) + " |")
    trig = any(v is not None and abs(v - 0.5) > 0.1 for v in flags.values())
    L.append("\n**Trigger (|AUC − 0.5| > 0.1 overall, excl. control): %s** — %s" % (
        "YES" if trig else "NO", "add the URR+prof-only UL variant and the RAN-UL with/without PRB ablation"
        if trig else "RAN UL features kept as is"))
    out = data / "reports"
    out.mkdir(exist_ok=True)
    (out / "dl_leak_check_v4.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
