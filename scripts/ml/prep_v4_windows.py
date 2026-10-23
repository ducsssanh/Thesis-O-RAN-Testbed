#!/usr/bin/env python3
"""Build per-UE sliding windows from the v4 dataset for baseline + LSTM training.

  .venv-ml/bin/python -I scripts/ml/prep_v4_windows.py --data research/datasets/oran_flooding_v4 \
      --out artifacts/ml/v4 [--window 10] [--seed 20261023]

One window = N consecutive seconds of ONE UE in ONE run (rows are 1 s apart); its label is
the label of its LAST second (the xApp labels the newest vector). Window kinds:
  main  - all N seconds in the same pNN phase, same BENIGN/MALICIOUS label, no guard second
          (guard = first/last 3 s of a phase). Train set = main only; headline eval = main.
  edge  - last second in a BENIGN/MALICIOUS phase but not main (crosses the phase start or
          touches a guard second). Eval only: time-to-detect from the phase start.
  idle  - all N seconds IDLE. Eval only: false alarms on an idle UE. Never a training target.
roll_v4.npz (tabular GBDT): causal rolling mean/std/slope/max over 5/10/30 s + the 1 s value, per window end.
Split by meta_run_id (never by row): every meta_pair has both classes in every split.
Features = the 31 telemetry columns, never meta_*. Magnitudes go through log1p, percentages /100,
then a z-score fitted on the train main windows; a missing value (stale URR/prof) becomes 0
(= the train mean) after scaling.
"""
import argparse, json, pathlib
import numpy as np, pandas as pd

PCT = ("prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct")
KINDS = {"main": 0, "edge": 1, "idle": 2}


def feature_cols(df):
    return [c for c in df.columns if c.split("_")[0] in ("rate", "thp", "prb", "cell", "urr", "prof")]


def transform(df, cols):
    X = np.empty((len(df), len(cols)), np.float32)
    for j, c in enumerate(cols):
        v = df[c].to_numpy(np.float64)
        X[:, j] = v / 100.0 if c in PCT else np.log1p(np.clip(v, 0, None))
    return X


def split_runs(df, seed, n_test, n_val, tries=500):
    """Random run split until every meta_pair shows all its labels (both classes for the attack
    pairs; BENIGN for benign_benign, MALICIOUS for both_attack) in train, val and test."""
    runs = np.array(sorted(df.meta_run_id.unique()))
    act = df[df.label.isin(["BENIGN", "MALICIOUS"])]
    cov = act.groupby(["meta_run_id", "meta_pair"]).label.agg(lambda s: frozenset(s)).reset_index()
    full = act.groupby("meta_pair").label.agg(lambda s: frozenset(s)).to_dict()
    pairs = sorted(full)
    rng = np.random.default_rng(seed)
    for _ in range(tries):
        p = rng.permutation(runs)
        sp = {"test": set(p[:n_test]), "val": set(p[n_test:n_test + n_val]), "train": set(p[n_test + n_val:])}
        ok = True
        for name, rs in sp.items():
            c = cov[cov.meta_run_id.isin(rs)].groupby("meta_pair").label.agg(lambda s: frozenset().union(*s))
            if any(c.get(pr, frozenset()) != full[pr] for pr in pairs):
                ok = False
                break
        if ok:
            return {k: sorted(v) for k, v in sp.items()}
    raise SystemExit("no run split covers every pair in every split")


ROLL_W = (5, 10, 30)
GATE_KBPS = 50.0


def rolling(df, X, cols, keys=("meta_run_id", "meta_supi")):
    """Causal rolling features per `keys` group on the transformed values: the value itself (1 s) and
    mean/std/slope/max over the past 5/10/30 s (min 2 points). Default groups = (run, UE): history
    crosses phase starts into the gap / previous phase. keys + meta_phase = history CUT at the
    phase start (leak diagnostic only; a deployed xApp does not know phase boundaries)."""
    names = ["%s@1" % c for c in cols] + ["%s@%d_%s" % (c, w, s) for w in ROLL_W for s in ("mean", "std", "slope", "max")
                                          for c in cols]
    R = np.full((len(df), len(names)), np.nan, np.float32)
    R[:, :len(cols)] = X
    for _, g in df.groupby(list(keys), sort=False):
        ix = g.index.to_numpy()
        x = pd.DataFrame(X[ix], columns=cols)
        t = pd.Series(np.arange(len(ix), dtype=float))
        xt = x.mul(t, axis=0)
        j = len(cols)
        for w in ROLL_W:
            rx = x.rolling(w, min_periods=2)
            mt = t.rolling(w, min_periods=2).mean()
            vt = t.rolling(w, min_periods=2).var(ddof=0)
            mx = rx.mean()
            slope = xt.rolling(w, min_periods=2).mean().sub(mx.mul(mt, axis=0)).div(vt, axis=0)
            for stat in (mx, rx.std(ddof=0), slope, rx.max()):
                R[ix, j:j + len(cols)] = stat.to_numpy(np.float32)
                j += len(cols)
    return R, names


def windows(df, N):
    """Yield (row index of the last second, kind) for every window of N contiguous seconds."""
    lab = df.label.to_numpy()
    ph = df.meta_phase.fillna("").to_numpy()
    guard = df.meta_guard.fillna(0).to_numpy().astype(bool)
    act = np.isin(lab, ["BENIGN", "MALICIOUS"])
    idle = lab == "IDLE"
    out_end, out_kind = [], []
    for _, g in df.groupby(["meta_run_id", "meta_supi"], sort=False):
        ix = g.index.to_numpy()                      # positional (df was reset)
        t = g.meta_t_unix.to_numpy()
        for k in range(N - 1, len(ix)):
            w = ix[k - N + 1:k + 1]
            if t[k] - t[k - N + 1] > N - 1 + 0.5:    # a hole inside the window
                continue
            e = w[-1]
            if act[e]:
                main = (ph[w] == ph[e]).all() and str(ph[e]).startswith("p") and (lab[w] == lab[e]).all() \
                    and not guard[w].any()
                out_end.append(e); out_kind.append(KINDS["main"] if main else KINDS["edge"])
            elif idle[w].all():
                out_end.append(e); out_kind.append(KINDS["idle"])
    return np.array(out_end), np.array(out_kind, np.int8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research/datasets/oran_flooding_v4")
    ap.add_argument("--out", default="artifacts/ml/v4")
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261023)
    ap.add_argument("--n-test", type=int, default=18)
    ap.add_argument("--n-val", type=int, default=14)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(pathlib.Path(a.data) / "rows.parquet")
    df = df.sort_values(["meta_run_id", "meta_supi", "meta_t_unix"]).reset_index(drop=True)
    cols = feature_cols(df)
    X = transform(df, cols)
    sp = split_runs(df, a.seed, a.n_test, a.n_val)
    end, kind = windows(df, a.window)
    run_of = df.meta_run_id.to_numpy()[end]
    split = np.where(np.isin(run_of, sp["test"]), 2, np.where(np.isin(run_of, sp["val"]), 1, 0)).astype(np.int8)
    # scaler on train main windows (their N seconds), NaN-aware
    tr_rows = np.unique((end[(split == 0) & (kind == 0)][:, None] - np.arange(a.window)[None, ::-1]).ravel())
    mu = np.nanmean(X[tr_rows], axis=0); sd = np.nanstd(X[tr_rows], axis=0); sd[sd < 1e-6] = 1.0
    Z = np.nan_to_num((X - mu) / sd, nan=0.0).astype(np.float32)
    W = Z[end[:, None] - np.arange(a.window)[None, ::-1]]          # [n, N, F], oldest first
    lab = df.label.to_numpy()[end]
    y = (lab == "MALICIOUS").astype(np.int8)
    m = {c: df[c].to_numpy()[end] for c in ("meta_run_id", "meta_supi", "meta_ue", "meta_phase", "meta_pair",
                                             "meta_victim_mode", "meta_backend", "meta_load_mbps",
                                             "meta_attack_active", "meta_t_since_phase_start")}
    pair = pd.Series(m["meta_pair"]).fillna("").astype(str).to_numpy().astype(str)
    # generator cell of the window's own flow: schedule model and the label-side family
    af = df.meta_attack_family.fillna("").astype(str).to_numpy()[end]
    bc = df.meta_benign_class.fillna("").astype(str).to_numpy()[end]
    schedule = np.where(lab == "MALICIOUS", [x.split("/")[-1] for x in af], bc).astype(str)
    family = np.array([(pr.split("~")[0] if l == "MALICIOUS" else pr.split("~")[-1]) if pr else ""
                       for pr, l in zip(pair, lab)]).astype(str)
    # per-window aggregates for the tabular baselines (mean, std, min, max, last over the window)
    raw = X[end[:, None] - np.arange(a.window)[None, ::-1]]
    agg = np.concatenate([np.nanmean(raw, 1), np.nanstd(raw, 1), np.nanmin(raw, 1), np.nanmax(raw, 1), raw[:, -1]], 1)
    # activity gate (deployment rule, evaluated as a secondary operating point): classify only when the
    # UE's UL over the window averages >= GATE_KBPS (URR, profiler if URR is stale); never a feature
    ul = df.urr_ul_kbps.to_numpy(float)
    ul = np.where(np.isnan(ul), df.prof_ul_kbps.to_numpy(float), ul)
    gate = np.nanmean(ul[end[:, None] - np.arange(a.window)[None, ::-1]], 1) >= GATE_KBPS
    np.savez_compressed(out / "windows_v4.npz", X=W, y=y, kind=kind, split=split, agg=agg.astype(np.float32),
                        label=lab.astype(str), run=m["meta_run_id"].astype(str), ue=m["meta_ue"].astype(str),
                        phase=m["meta_phase"].astype(str), pair=pair,
                        victim=pd.Series(m["meta_victim_mode"]).fillna("").astype(str).to_numpy().astype(str),
                        backend=pd.Series(m["meta_backend"]).fillna("").astype(str).to_numpy().astype(str),
                        load=np.nan_to_num(m["meta_load_mbps"].astype(float)),
                        attack_active=np.nan_to_num(m["meta_attack_active"].astype(float), nan=-1),
                        t_since=np.nan_to_num(m["meta_t_since_phase_start"].astype(float), nan=-1),
                        gate=gate, schedule=schedule, family=family, mean=mu, std=sd)
    R, roll_names = rolling(df, X, cols)
    np.savez_compressed(out / "roll_v4.npz", R=R[end], names=np.array(roll_names))
    df["_ph"] = df.meta_phase.fillna("")
    Rc, _ = rolling(df, X, cols, keys=("meta_run_id", "meta_supi", "_ph"))
    np.savez_compressed(out / "roll_cut_v4.npz", R=Rc[end], names=np.array(roll_names))
    miss = {lb: {c: round(float(df.loc[df.label == lb, c].isna().mean()), 4) for c in ("urr_ul_kbps", "prof_ul_kbps")}
            for lb in ("BENIGN", "MALICIOUS", "IDLE")}
    cnt = {s: {k: {"n": int(((split == si) & (kind == ki)).sum()),
                   "pos": int(y[(split == si) & (kind == ki)].sum())} for k, ki in KINDS.items()}
           for s, si in (("train", 0), ("val", 1), ("test", 2))}
    meta = {"dataset": "oran_flooding_v4", "window_s": a.window, "features": cols, "n_features": len(cols),
            "agg_features": ["%s_%s" % (s, c) for s in ("mean", "std", "min", "max", "last") for c in cols],
            "transform": "log1p(magnitudes), pct/100, z-score on train main windows, NaN->0 after scaling",
            "label": "MALICIOUS=1 / BENIGN=0 at the window's last second; IDLE never a target",
            "gate": "window mean UL (URR, else profiler) >= %g kbps" % GATE_KBPS, "kinds": KINDS, "split_seed": a.seed, "split_runs": sp, "counts": cnt,
            "missing_rate_by_label": miss}
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps({"features": len(cols), "windows": int(len(end)), "counts": cnt, "missing": miss}, indent=1))


if __name__ == "__main__":
    main()
