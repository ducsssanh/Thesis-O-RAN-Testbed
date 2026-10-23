#!/usr/bin/env python3
"""Cross-domain defence engine v4: ONE implementation shared by the offline replay
(fusion_v4.run_engine) and the live xApp sidecar (scripts/k8s/classifier/sidecar_v4.py).

Per UE, one step per second (one telemetry row: the latest KPM, URR and profiler as of that
second, dataset semantics of build_dataset_v4):
  OnlineFeatures  transform + causal rolling (1 s value, mean/std/slope/max over 5/10/30 s) of the
                  newest row, the same numbers as prep_v4_windows.rolling on the whole timeline
  Scorer          the 3 frozen GBDT models (xd, core, ran), z = p / threshold
  DecisionState   KPM<->URR integrity rule, kpm_trust / core_trust, trust-weighted fusion, fair-use
                  rules, 3-of-5 L1, L3 after L1 held L3_HOLD_S s (+ both-layer rule) for one
                  configuration (CONFIGS; see fusion_v4 for the rationale of each)
Parameters (tau, m, bias) come from models/integrity_rule.json; the constants below are frozen.
"""
import json, math, pathlib, sys
from collections import deque
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                    # prep_v4_windows next to this file
ROOT = HERE.parents[1]
MODELS = ROOT / "artifacts/ml/v4/models"

FAIR_UL_KBPS, CELL_CONGESTED = 2000.0, 80.0
GATE_KBPS = 50.0
INT_W, HOLD_S, RAMP_S, CORE_AGE_S = 10, 60, 30, 4.0
L3_HOLD_S = 10
K5_W, K5_K = 5, 3                     # L1: fused alarm in 3 of the last 5 s
RULE_W, RULE_K = 4, 3                 # fair-use rules: 3 of 4 samples
ROLL_W = (5, 10, 30)
CONFIGS = ("RAN-only (xApp KPM)", "core-only (5GC)", "cross-domain naive", "cross-domain trust-weighted",
           "cross-domain trust-weighted v2")
MODES = dict(zip(("ran-only", "core-only", "xd-naive", "xd-trust-v1", "xd-trust-v2"), CONFIGS))


def load_rule(models=MODELS):
    r = json.loads((pathlib.Path(models) / "integrity_rule.json").read_text())
    return r["chosen"]["tau"], r["chosen"]["m"], r["bias"]


# ---------------------------------------------------------------- features (one row at a time)
class OnlineFeatures:
    """Rolling features of the newest row of one UE timeline: prep_v4_windows.transform + rolling (the
    training code) run on the UE's history, so the vector is bit-identical to the offline one. History
    is capped at MAX_HIST rows (the sidecar is reset at every run start; past the cap the slope's row
    index restarts, a float-rounding difference only)."""
    MAX_HIST = 3600

    def __init__(self, cols):
        self.cols = list(cols)
        self.names = ["%s@1" % c for c in self.cols] + ["%s@%d_%s" % (c, w, s) for w in ROLL_W
                                                        for s in ("mean", "std", "slope", "max") for c in self.cols]
        self.X = deque(maxlen=self.MAX_HIST)
        self.truncated = 0

    def push(self, row):
        """row: {raw feature: value or NaN}. Returns the float32 feature vector (len(names))."""
        import pandas as pd
        import prep_v4_windows as P
        one = pd.DataFrame([{c: row.get(c, np.nan) for c in self.cols}], dtype=np.float64)
        if len(self.X) == self.MAX_HIST:
            self.truncated += 1
        self.X.append(P.transform(one, self.cols)[0])
        X = np.stack(self.X)
        R, names = P.rolling(pd.DataFrame({"meta_run_id": np.zeros(len(X), int), "meta_supi": 0}), X, self.cols)
        assert names == self.names
        return R[-1]


class Scorer:
    """The 3 frozen GBDT models; z = p / threshold (z >= 1: that model's alarm)."""

    def __init__(self, models=MODELS):
        import joblib
        models = pathlib.Path(models)
        self.spec = json.loads((models / "spec.json").read_text())
        self.models = {k: joblib.load(models / v["file"]) for k, v in self.spec["models"].items()}

    def index(self, names):
        ix = {n: i for i, n in enumerate(names)}
        return {k: [ix[c] for c in self.spec["models"][k]["features"]] for k in self.models}

    def z(self, R, names):
        """R: [n, len(names)] -> {model: z [n]}"""
        cols = self.index(names)
        return {k: m.predict_proba(R[:, cols[k]])[:, 1] / self.spec["models"][k]["threshold"] for k, m in self.models.items()}


# ---------------------------------------------------------------- decisions (one step per row)
def _mean(d):
    v = [x for x in d if x == x]
    return sum(v) / len(v) if v else math.nan


class DecisionState:
    """Escalation state of one UE under one configuration. step() takes the row's raw inputs:
    kpm_ul (KPM rate UL kbps), urr_ul (URR UL kbps or NaN), prof_ul (profiler UL kbps or NaN),
    urr_age (s, NaN = none), cell_ul (cell PRB UL %), z = {xd, core, ran}."""

    def __init__(self, cfg, tau, m, bias):
        assert cfg in CONFIGS, cfg
        self.cfg, self.tau, self.m, self.bias = cfg, tau, m, bias
        self.i = -1
        self.ul_core, self.ul_ran = deque(maxlen=INT_W), deque(maxlen=INT_W)
        self.ks, self.us, self.fresh = deque(maxlen=INT_W), deque(maxlen=INT_W), deque(maxlen=INT_W)
        self.rr, self.cr = deque(maxlen=RULE_W), deque(maxlen=RULE_W)
        self.h_hit, self.h_core, self.h_ran = deque(maxlen=K5_W), deque(maxlen=K5_W), deque(maxlen=K5_W)
        self.run_len = 0
        self.held = 0
        self.last_integ = -10 ** 9

    def step(self, kpm_ul, urr_ul, prof_ul, urr_age, cell_ul, z):
        self.i += 1
        i = self.i
        kpm = 0.0 if kpm_ul != kpm_ul else float(kpm_ul)
        has_urr = urr_ul == urr_ul
        fresh = (99.0 if urr_age != urr_age else urr_age) <= CORE_AGE_S and has_urr
        ct = float(fresh)
        cell = 0.0 if cell_ul != cell_ul else cell_ul
        # activity gate: core view if fresh, else RAN view (10 s means)
        self.ul_core.append(urr_ul if has_urr else prof_ul)
        self.ul_ran.append(kpm)
        ul_core, ul_ran = _mean(self.ul_core), sum(self.ul_ran) / len(self.ul_ran)
        # KPM<->URR integrity rule over INT_W s
        self.ks.append(kpm)
        self.us.append(urr_ul if has_urr else 0.0)
        self.fresh.append(fresh)
        full = len(self.ks) == INT_W
        ks, us = (sum(self.ks), sum(self.us)) if full else (math.nan, math.nan)
        fresh_w = full and all(self.fresh)
        active = max(ks, us) / INT_W > GATE_KBPS if full else False
        lr = math.log(max(ks, 1.0) / max(us, 1.0)) - self.bias if full else math.nan
        viol = fresh_w and active and abs(lr) > self.tau
        self.run_len = self.run_len + 1 if (viol and i) else int(viol)
        integ = self.run_len >= self.m
        if integ:
            self.last_integ = i
        under = integ and lr < 0
        dt = i - self.last_integ
        kt = 0.0 if dt <= HOLD_S else min(1.0, (dt - HOLD_S) / RAMP_S)
        # fair-use rules (3 of 4)
        self.rr.append(kpm > FAIR_UL_KBPS and cell >= CELL_CONGESTED)
        self.cr.append((urr_ul if has_urr else 0.0) > FAIR_UL_KBPS and fresh)
        ran_rule, core_rule = sum(self.rr) >= RULE_K, sum(self.cr) >= RULE_K
        zx, zc, zr = z["xd"], z["core"], z["ran"]
        cfg, zf = self.cfg, math.nan
        if cfg == CONFIGS[0]:                    # RAN-only: no core data at all
            gate = ul_ran >= GATE_KBPS
            hit = (zr >= 1 and gate) or ran_rule
            core_hit, ranside, ktu = False, hit, 1.0
        elif cfg == CONFIGS[1]:                  # core-only
            gate = ul_core >= GATE_KBPS and ct > 0
            hit = (zc >= 1 and gate) or core_rule
            core_hit, ranside, ktu = hit, False, 1.0
        elif cfg == CONFIGS[2]:                  # naive cross-domain: one model, no trust, no integrity rule
            gate = (ul_core if ct > 0 else ul_ran) >= GATE_KBPS
            hit = (zx >= 1 and gate) or ran_rule or core_rule
            core_hit, ranside, ktu = hit, hit, 1.0
        else:                                    # proposed (v1 / v2)
            gate = (ul_core if ct > 0 else ul_ran) >= GATE_KBPS
            zf = kt * ct * zx + (1 - kt) * ct * zc + kt * (1 - ct) * zr
            hit = (zf >= 1 and gate) or (ran_rule and kt >= 0.5) or core_rule
            core_hit = (zc >= 1 and gate and ct > 0) or core_rule
            ranside = (zr >= 1 and gate and kt >= 0.5) or (ran_rule and kt >= 0.5)
            if cfg == CONFIGS[4]:
                hit, core_hit = hit or under, core_hit or under
            ktu = kt
        hit, core_hit, ranside = bool(hit), bool(core_hit), bool(ranside)
        self.h_hit.append(hit); self.h_core.append(core_hit); self.h_ran.append(ranside)
        l1 = sum(self.h_hit) >= K5_K
        self.held = self.held + 1 if (l1 and i) else int(l1)
        if cfg in CONFIGS[3:]:
            k_core, k_ran = sum(self.h_core) >= K5_K, sum(self.h_ran) >= K5_K
            l3 = self.held >= L3_HOLD_S and k_core and (k_ran or ktu < 0.5)
        else:
            k_core = k_ran = None
            l3 = self.held >= L3_HOLD_S
        return {"hit": hit, "core_hit": core_hit, "ran_hit": ranside, "l1": l1, "l3": l3, "held": self.held,
                "integrity": bool(integ) if cfg in CONFIGS[3:] else False, "under": bool(under),
                "kt": ktu, "ct": ct, "lr": lr, "zf": zf, "gate": bool(gate),
                "ran_rule": bool(ran_rule), "core_rule": bool(core_rule), "k_core": k_core, "k_ran": k_ran}


def layer_of(cfg, d):
    """Layer reported to the xApp policy: 'both' when the L3 rule of the configuration is met
    (for trust-weighted: core in 3 of 5 and RAN in 3 of 5, or core alone while kpm_trust < 0.5)."""
    if d["l3"]:
        return "both"
    if cfg == CONFIGS[0]:
        return "ran"
    if cfg == CONFIGS[1]:
        return "core"
    if d["core_hit"] and d["ran_hit"]:
        return "both"
    return "core" if d["core_hit"] else "ran"


def run_timeline(cfg, kpm_ul, urr_ul, prof_ul, urr_age, cell_ul, z, tau, m, bias):
    """All steps of one UE timeline (arrays) -> {key: array}. Used by the offline replay."""
    st = DecisionState(cfg, tau, m, bias)
    zx, zc, zr = z["xd"], z["core"], z["ran"]
    rows = [st.step(kpm_ul[i], urr_ul[i], prof_ul[i], urr_age[i], cell_ul[i], {"xd": zx[i], "core": zc[i], "ran": zr[i]})
            for i in range(len(kpm_ul))]
    return {k: np.array([r[k] for r in rows]) for k in ("hit", "l1", "l3", "integrity", "kt", "ct")}
