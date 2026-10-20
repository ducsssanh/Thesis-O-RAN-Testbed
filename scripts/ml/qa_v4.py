#!/usr/bin/env python3
"""QA for a v4 dataset build (subset of v4 plan §7.2 that applies from Phase 1 on).

  .venv-ml/bin/python -I scripts/ml/qa_v4.py --data research/datasets/oran_flooding_v4_pilot RUN_DIR [RUN_DIR ...]

Writes <data>/qa_report.md:
  - independent causality audit: for every row, the URR/profiler/KPM record it used
    is re-located in the RAW files by its source_ts and checked arrival_ts <= t
    (does not trust the builder);
  - C5 comparison: share of the SAME run's v3-style xApp feature rows that used a
    future (+1 s) URR/profiler sample -- the leak v4 removes;
  - age distributions, feature presence by label;
  - design balance (label x UE) -- flags the C1 confound if a UE is single-class;
  - achieved vs offered per (phase, UE) from metrics.json (achieved_ok, +-10%).
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_dataset_v4 as B


def causality_audit(df, runs):
    srcs = {}
    for rd in runs:
        rd = pathlib.Path(rd); rid = "/".join(rd.parts[-4:])
        srcs[rid] = {"kpm": B.load_kpm(rd), "urr": B.load_urr(rd), "prof": B.load_prof(rd)}
    viol, checked = {"kpm": 0, "urr": 0, "prof": 0}, {"kpm": 0, "urr": 0, "prof": 0}
    for _, r in df.iterrows():
        s = srcs.get(r["meta_run_id"])
        if s is None:
            continue
        t = r["meta_t_unix"]
        for kind, agecol in (("kpm", "meta_kpm_age_s"), ("urr", "meta_urr_age_s"), ("prof", "meta_prof_age_s")):
            age = r[agecol]
            if pd.isna(age):
                continue
            src = t - age
            cands = [x for x in s[kind] if x["supi"] == r["meta_supi"] and abs(x["source_ts"] - src) < 1e-4]
            if not cands:
                continue
            checked[kind] += 1
            # the builder picks the latest causal record; if ANY candidate with this source arrived <= t it is causal
            if min(c["arrival_ts"] for c in cands) > t + 1e-9:
                viol[kind] += 1
    return viol, checked


def c5_leak(runs):
    tot = urr_f = prof_f = 0
    for rd in runs:
        for line in (pathlib.Path(rd) / "defense/features.jsonl").read_text().splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            tot += 1
            urr_f += int(o.get("urr_offset_s", 0) == 1)
            prof_f += int(o.get("prof_offset_s", 0) == 1)
            # negative age = record arrived after the KPM sample it was joined to
    return tot, urr_f, prof_f


def achieved(runs, tol=0.10):
    out = []
    for rd in runs:
        m = json.loads((pathlib.Path(rd) / "metrics.json").read_text())
        for ph, ues in (m.get("phases") or {}).items():
            for ue, v in ues.items():
                if not isinstance(v, dict):
                    continue                          # e.g. duration_s
                off = v.get("offered_ul_mbps") or 0
                if off <= 0:
                    continue
                dn = v.get("dn_ul_mbps")
                urr = v.get("urr_ul_kbps")
                # IP-level achieved rate (URR counts IP packets at the UPF); the DN counter is
                # UDP payload only, which under-reads small packets by the header share.
                ratio = (urr / 1000.0 / off) if urr is not None else None
                out.append({"phase": ph, "ue": ue, "offered": off, "at_dn": dn, "urr_mbps": None if urr is None else round(urr / 1000, 3),
                            "ratio": None if ratio is None else round(ratio, 3),
                            "achieved_ok": ratio is not None and abs(ratio - 1) <= tol})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    root = pathlib.Path(a.data)
    df = pd.read_parquet(root / "rows.parquet")
    L = []
    L.append(f"# v4 QA report — `{root}`\n")
    L.append(f"Rows: {len(df)} · " + " · ".join(f"{k} {v}" for k, v in df['label'].value_counts().items()) + "\n")

    viol, checked = causality_audit(df, a.runs)
    L.append("## 1. Causality audit (independent of the builder)\n")
    L.append("| stream | rows checked | violations (arrival_ts > t) |\n|---|---:|---:|")
    for k in ("kpm", "urr", "prof"):
        L.append(f"| {k} | {checked[k]} | **{viol[k]}** |")
    tot, uf, pf = c5_leak(a.runs)
    L.append(f"\nFor comparison, the v3-style xApp join (`defense/features.jsonl`) of the same run: {tot} rows, "
             f"**{uf} ({100*uf/max(tot,1):.1f}%) used a future (+1 s) URR sample and {pf} ({100*pf/max(tot,1):.1f}%) "
             f"a future profiler sample** — the C5 leak the v4 build removes.\n")

    L.append("## 2. Data age (s) at the row's second\n")
    L.append("| stream | median | p90 | max | present % |\n|---|---:|---:|---:|---:|")
    for k, f in (("kpm", "rate_ul_kbps"), ("urr", "urr_ul_kbps"), ("prof", "prof_ul_kbps")):
        s = df[f"meta_{k}_age_s"].dropna()
        L.append(f"| {k} | {s.median():.2f} | {s.quantile(.9):.2f} | {s.max():.2f} | {100*df[f].notna().mean():.1f} |")
    L.append("\nPresence by label (URR / profiler):\n")
    L.append("| label | URR % | prof % |\n|---|---:|---:|")
    for lab, g in df.groupby("label"):
        L.append(f"| {lab} | {100*g['urr_ul_kbps'].notna().mean():.1f} | {100*g['prof_ul_kbps'].notna().mean():.1f} |")

    L.append("\n## 3. Design balance (excl. IDLE)\n")
    nb = df[df.label != "IDLE"]
    ct = pd.crosstab(nb["meta_ue"], nb["label"])
    try:
        L.append(ct.to_markdown())
    except ImportError:
        L.append("```\n" + ct.to_string() + "\n```")
    pm = (nb.label == "MALICIOUS").groupby(nb["meta_ue"]).mean()
    flag = [ue for ue, p in pm.items() if not 0.45 <= p <= 0.55]
    L.append(f"\nP(malicious | UE): " + ", ".join(f"{u} {p:.2f}" for u, p in pm.items()) +
             (f"\n\n**C1 confound present** — {flag} outside [0.45, 0.55]: label ≈ UE identity. "
              "Expected for a v3 scenario; v4 role-swapping campaign design (Phase 3) must fix it." if flag else "\n\nBalanced."))

    L.append("\n## 4. Achieved vs offered (DN, ±10%)\n")
    ach = achieved(a.runs)
    L.append("| phase | ue | offered Mbit/s | URR (IP) Mbit/s | DN payload Mbit/s | URR/offered | achieved_ok |\n|---|---|---:|---:|---:|---:|---|")
    for r in ach:
        L.append(f"| {r['phase']} | {r['ue']} | {r['offered']} | {r['urr_mbps']} | {r['at_dn']} | {r['ratio']} | {'yes' if r['achieved_ok'] else '**no**'} |")
    ok = sum(r["achieved_ok"] for r in ach)
    L.append(f"\nachieved_ok: {ok}/{len(ach)} phase-UE pairs (target ≥ 90%).")

    (root / "qa_report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
