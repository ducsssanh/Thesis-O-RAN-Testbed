#!/usr/bin/env python3
"""Double DQN trained on the whole replay with both actions known. On an exact replay the outcome of an alarm is known at every second, so no exploration is needed: every second of every training episode and scenario gives a fixed target for alarm and a Bellman target for continue.
This removes the epsilon noise of train.py. Options: --hist adds 2 usage-history inputs from the profiler (composed offline, see scripts/ml/history_features.py); --gru reads second by second. The classifier gets the same inputs through --mode clf. Selection is on the inner split only.
Usage: train_fq.py --fold k --seed s --cfa c [--mode dqn|clf] [--hist] [--drop protocol] [--steps n] [--lr x] [--hidden a,b] --out f.json"""
import argparse, json, pickle
import numpy as np, torch, torch.nn as nn
from sklearn.model_selection import GroupKFold
ap = argparse.ArgumentParser()
ap.add_argument("--mode", default="dqn"); ap.add_argument("--fold", type=int, required=True); ap.add_argument("--seed", type=int, default=0); ap.add_argument("--cfa", type=float, default=50); ap.add_argument("--steps", type=int, default=300000)
ap.add_argument("--hist", action="store_true"); ap.add_argument("--drop", default=""); ap.add_argument("--lr", type=float, default=3e-4); ap.add_argument("--hidden", default="128,64"); ap.add_argument("--gamma", type=float, default=.99); ap.add_argument("--wd", type=float, default=0.0); ap.add_argument("--dropout", type=float, default=0.0); ap.add_argument("--every", type=int, default=25000); ap.add_argument("--target", type=int, default=2000); ap.add_argument("--data", default="artifacts/drl/episodes.pkl"); ap.add_argument("--levels", default="artifacts/drl/window_levels.json"); ap.add_argument("--out", required=True)
a = ap.parse_args()
torch.set_num_threads(1); torch.manual_seed(a.seed); rng = np.random.default_rng(a.seed)
D = pickle.load(open(a.data, "rb")); E = D["episodes"]
runs = np.array(sorted({e["run"] for e in E}))
tr_i, te_i = list(GroupKFold(5).split(runs, groups=runs))[a.fold]
perm = rng.permutation(tr_i); n_in = max(1, int(.15 * len(perm)))
inner, train = set(runs[perm[:n_in]]), set(runs[perm[n_in:]]); test = set(runs[te_i])
use = lambda e: e["other_evasion"] != "L3"
key = lambda e: "|".join((e["run"], e["phase"], e["supi"]))
TR = [e for e in E if e["run"] in train and use(e)]; IN = [e for e in E if e["run"] in inner and use(e)]; TE = [e for e in E if e["run"] in test]
base = np.vstack([e["scen"]["honest"] for e in TR]); mu, sd = base.mean(0), base.std(0) + 1e-6
drop = np.array(D["protocol"], int) if a.drop == "protocol" else np.array([], int)
NH = 2 if a.hist else 0
LV = json.load(open(a.levels)) if a.hist else {}
HIST_S, GAP = 300, 10


def pool(eps):
    p = {}
    for e in eps:
        if not e["attack"] and not e["client"]:
            f = e["scen"]["honest"]; core = np.expm1(f[:, 6])
            p.setdefault(e["band"], []).append(np.c_[core * 125 >= 1000, f[:, 6]])
    return p


POOLS = {"train": pool([e for e in E if e["run"] in train | inner]), "test": pool([e for e in E if e["run"] in test])}
LVL = {w: {b: np.array([np.log1p(np.expm1(c[:, 1]).sum() * 125) for c in v]) for b, v in p.items()} for w, p in POOLS.items()}


def history(e, f, which):
    """Busy share and mean log core rate of [t-300, t-10), the part before the episode drawn from benign episodes of the band, nearest in level to this episode's twin window."""
    cand = POOLS[which][e["band"]]; lv = LVL[which][e["band"]]
    near = np.argsort(np.abs(lv - np.log1p(LV[key(e)])))[:15]
    h = np.vstack([cand[i] for i in rng.choice(near, size=4)])
    core = np.expm1(f[:, 6])
    x = np.vstack([h, np.c_[core * 125 >= 1000, f[:, 6]]])
    c = np.vstack([np.zeros((1, 2)), np.cumsum(x, axis=0)])
    out = np.zeros((len(f), 2), np.float32)
    for i in range(len(f)):
        hi = len(h) + i - GAP + 1; lo = max(0, hi - HIST_S)
        out[i] = (c[hi] - c[lo]) / max(hi - lo, 1)
    return out


DIM = 300 + NH


def windows(e, f, which):
    x = (f - mu) / sd
    if drop.size:
        x[:, drop] = 0
    w = np.zeros((len(x), DIM), np.float32)
    for t in range(len(x)):
        lo = max(0, t - 9); seg = x[lo:t + 1]
        w[t, 300 - 30 * len(seg):300] = seg.ravel()
    if NH:
        w[:, 300:] = history(e, f, which)
    return w


def build(eps, which):
    return [(e, {k: windows(e, v, which) for k, v in e["scen"].items()}) for e in eps]


TRW, INW, TEW = build(TR, "train"), build(IN, "train"), build(TE, "test")
h = [int(x) for x in a.hidden.split(",")]


def mlp(out, dim=None, hid=None, drop=None):
    L, d = [], dim or DIM
    for u in hid or h:
        L += [nn.Linear(d, u), nn.ReLU()]
        if (a.dropout if drop is None else drop) > 0:
            L.append(nn.Dropout(a.dropout if drop is None else drop))
        d = u
    return nn.Sequential(*L, nn.Linear(d, out))


def first(s, thr=0.0):
    i = np.flatnonzero(s > thr)
    return int(i[0]) if i.size else -1


def ep_return(lab, al, cfa):
    stop = len(lab) if al < 0 else al
    r = -float(lab[:stop].sum())
    if al >= 0 and not lab[al]:
        r -= cfa
    return r


res = {}
if a.mode == "stack":
    # stopping policy on a calibrated posterior: the classifier is fit on one part of the training runs, the policy on its out-of-sample logits from the other part, so the policy can reproduce a threshold or CUSUM and can only add to them through what it learns about time
    tr_runs = sorted(train); rng.shuffle(tr_runs); cut = int(.65 * len(tr_runs)); R1 = set(tr_runs[:cut])
    A1 = [(e, w) for e, w in TRW if e["run"] in R1]; A2 = [(e, w) for e, w in TRW if e["run"] not in R1]
    M = mlp(1, drop=0.0); opt = torch.optim.Adam(M.parameters(), lr=a.lr); bce = nn.BCEWithLogitsLoss()
    X = np.vstack([w[k] for e, w in A1 for k in w]); Y = np.concatenate([e["run_lab"] for e, w in A1 for k in w]).astype(np.float32)
    for ep in range(15):
        o = rng.permutation(len(X))
        for j in range(0, len(o), 256):
            i = o[j:j + 256]; l = bce(M(torch.from_numpy(X[i])).squeeze(1), torch.from_numpy(Y[i])); opt.zero_grad(); l.backward(); opt.step()
    del X, Y
    M.eval(); pi = float(np.concatenate([e["run_lab"] for e, w in A1]).mean()); prior = float(np.log(pi / (1 - pi)))
    IDX = {n: i for i, n in enumerate(D["names"])}

    def seq(e, w):
        """logits of the last 10 s, the CUSUM of them, the second-old evidence, gate state, usage history: all known at second t"""
        out = {}
        with torch.no_grad():
            for k, x in w.items():
                l = M(torch.from_numpy(x)).squeeze(1).numpy().clip(-20, 20)
                n = len(l); f = np.zeros((n, 15), np.float32); st = 0.0
                for t in range(n):
                    lo = max(0, t - 9); seg = l[lo:t + 1]
                    f[t, 10 - len(seg):10] = seg / 10
                    st = max(0.0, st + float(l[t] - prior)); f[t, 10] = np.log1p(st)
                raw = e["scen"][k]
                f[:, 11] = raw[:, IDX["masked"]]; f[:, 12] = raw[:, IDX["c_t"]] / 3
                if NH:
                    f[:, 13:15] = x[:, 300:302]
                out[k] = f
        return out
    S2 = [(e, seq(e, w)) for e, w in A2]; SI = [(e, seq(e, w)) for e, w in INW]; ST = [(e, seq(e, w)) for e, w in TEW]
    X = np.vstack([w[k] for e, w in S2 for k in w]); Lab = np.concatenate([e["run_lab"] for e, w in S2 for k in w]).astype(np.float32)
    Last = np.zeros(len(Lab), bool); p = 0
    W = []
    for e, w in S2:
        ks = list(w)
        for k in ks:
            p += len(e["run_lab"]); Last[p - 1] = True; W.append(np.full(len(e["run_lab"]), .5 if k == "honest" else .5 / (len(ks) - 1)))
    W = np.concatenate(W); CW = np.cumsum(W / W.sum()); N = len(X)
    Q = mlp(2, dim=15, hid=[32, 16], drop=0.0); T = mlp(2, dim=15, hid=[32, 16], drop=0.0); T.load_state_dict(Q.state_dict())
    opt = torch.optim.Adam(Q.parameters(), lr=a.lr, weight_decay=a.wd); hub = nn.SmoothL1Loss()
    Xt = torch.from_numpy(X); ra = torch.from_numpy(np.where(Lab > 0, 0.0, -a.cfa).astype(np.float32)); rc = torch.from_numpy(-Lab); last = torch.from_numpy(Last.astype(np.float32))
    best, best_sd = -1e18, None

    def score(sets):
        tot, cnt = 0.0, 0
        with torch.no_grad():
            for e, w in sets:
                for k, x in w.items():
                    q = Q(torch.from_numpy(x)).numpy(); tot += ep_return(e["run_lab"], first(q[:, 1] - q[:, 0]), a.cfa); cnt += 1
        return tot / cnt
    for step in range(1, a.steps + 1):
        i = torch.from_numpy(np.searchsorted(CW, rng.random(256)).clip(max=N - 1)).long()
        q = Q(Xt[i]); nxt = (i + 1).clamp(max=N - 1)
        with torch.no_grad():
            na = Q(Xt[nxt]).argmax(1, keepdim=True); y = rc[i] + a.gamma * (1 - last[i]) * T(Xt[nxt]).gather(1, na).squeeze(1)
        l = hub(q[:, 1], ra[i]) + ((1 - last[i]) * nn.functional.smooth_l1_loss(q[:, 0], y, reduction="none")).mean()
        opt.zero_grad(); l.backward(); nn.utils.clip_grad_norm_(Q.parameters(), 10); opt.step()
        if step % a.target == 0:
            T.load_state_dict(Q.state_dict())
        if step % a.every == 0:
            v = score(SI); print(step, "inner return %.3f" % v, flush=True)
            if v > best:
                best, best_sd = v, {k: c.clone() for k, c in Q.state_dict().items()}
    Q.load_state_dict(best_sd)
    with torch.no_grad():
        for e, w in ST:
            res[key(e)] = {k: first((lambda q: q[:, 1] - q[:, 0])(Q(torch.from_numpy(x)).numpy())) for k, x in w.items()}
    out = dict(mode="stack", fold=a.fold, seed=a.seed, cfa=a.cfa, inner=best, alarms=res)
elif a.mode == "dqn":
    # keep each scenario equally likely per episode: honest gets the weight of the tamper scenarios together
    X, Lab, Last, W = [], [], [], []
    for e, w in TRW:
        ks = list(w); nt = len(ks) - 1
        for k in ks:
            X.append(w[k]); Lab.append(e["run_lab"]); l = np.zeros(len(e["run_lab"]), bool); l[-1] = True; Last.append(l)
            W.append(np.full(len(l), .5 if k == "honest" else .5 / nt))
    X = np.vstack(X); Lab = np.concatenate(Lab).astype(np.float32); Last = np.concatenate(Last); W = np.concatenate(W); W = W / W.sum()
    N = len(X); print("states", N, flush=True)
    Q, T = mlp(2), mlp(2); T.load_state_dict(Q.state_dict())
    opt = torch.optim.Adam(Q.parameters(), lr=a.lr, weight_decay=a.wd); hub = nn.SmoothL1Loss()
    Xt = torch.from_numpy(X); ra = torch.from_numpy(np.where(Lab > 0, 0.0, -a.cfa).astype(np.float32)); rc = torch.from_numpy(-Lab); last = torch.from_numpy(Last.astype(np.float32))
    CW = np.cumsum(W); idx_all = np.empty(0, np.int64)
    best, best_sd, pos = -1e18, None, 0

    def score(sets):
        tot, cnt = 0.0, 0
        Q.eval()
        with torch.no_grad():
            for e, w in sets:
                for k, x in w.items():
                    q = Q(torch.from_numpy(x)).numpy(); tot += ep_return(e["run_lab"], first(q[:, 1] - q[:, 0]), a.cfa); cnt += 1
        Q.train()
        return tot / cnt
    for step in range(1, a.steps + 1):
        if pos + 256 > len(idx_all):                  # a small block at a time: a full sample of the steps would take 0.3 GB
            idx_all = np.searchsorted(CW, rng.random(256 * 2000)).clip(max=N - 1); pos = 0
        i = torch.from_numpy(idx_all[pos:pos + 256]); pos += 256
        i = i.long()
        q = Q(Xt[i])
        nxt = (i + 1).clamp(max=N - 1)
        with torch.no_grad():
            na = Q(Xt[nxt]).argmax(1, keepdim=True); y = rc[i] + a.gamma * (1 - last[i]) * T(Xt[nxt]).gather(1, na).squeeze(1)
        keep = 1 - last[i]                             # end of phase is truncation: no continue target there
        l = hub(q[:, 1], ra[i]) + (keep * nn.functional.smooth_l1_loss(q[:, 0], y, reduction="none")).mean()
        opt.zero_grad(); l.backward(); nn.utils.clip_grad_norm_(Q.parameters(), 10); opt.step()
        if step % a.target == 0:
            T.load_state_dict(Q.state_dict())
        if step % a.every == 0:
            v = score(INW); print(step, "inner return %.3f" % v, flush=True)
            if v > best:
                best, best_sd = v, {k: c.clone() for k, c in Q.state_dict().items()}
    Q.load_state_dict(best_sd); Q.eval()
    with torch.no_grad():
        for e, w in TEW:
            res[key(e)] = {k: first((lambda q: q[:, 1] - q[:, 0])(Q(torch.from_numpy(x)).numpy())) for k, x in w.items()}
    out = dict(mode="dqn", fold=a.fold, seed=a.seed, cfa=a.cfa, inner=best, alarms=res)
else:
    M = mlp(1); opt = torch.optim.Adam(M.parameters(), lr=a.lr); bce = nn.BCEWithLogitsLoss()
    Xs, Ys = [], []
    for e, w in TRW:
        for k in w:
            Xs.append(w[k]); Ys.append(e["run_lab"])
    X = np.vstack(Xs); Y = np.concatenate(Ys).astype(np.float32)
    for ep in range(15):
        o = rng.permutation(len(X))
        for j in range(0, len(o), 256):
            i = o[j:j + 256]; l = bce(M(torch.from_numpy(X[i])).squeeze(1), torch.from_numpy(Y[i])); opt.zero_grad(); l.backward(); opt.step()
    XI = np.vstack([w[k] for e, w in INW for k in w]); YI = np.concatenate([e["run_lab"] for e, w in INW for k in w]).astype(np.float32)
    with torch.no_grad():
        li = M(torch.from_numpy(XI)).squeeze(1)
    temp = torch.ones(1, requires_grad=True); o2 = torch.optim.LBFGS([temp], lr=.1, max_iter=50)

    def clos():
        o2.zero_grad(); v = bce(li / temp.clamp(min=.05), torch.from_numpy(YI)); v.backward(); return v
    o2.step(clos); Tm = float(temp.detach().clamp(min=.05))
    grid = np.r_[np.linspace(-6, 6, 25), np.linspace(7, 30, 24)]
    hgrid = np.geomspace(1, 3000, 30); pi = float(Y.mean()); prior = float(np.log(pi / (1 - pi))); cus = {}

    def scan(sets):
        al, cu = {}, {}
        for e, w in sets:
            with torch.no_grad():
                r = {k: M(torch.from_numpy(x)).squeeze(1).numpy() / Tm for k, x in w.items()}
            al[key(e)] = {k: [first(v, float(g)) for g in grid] for k, v in r.items()}
            cc = {}
            for k, v in r.items():
                st, c = 0.0, np.zeros(len(v))
                for t, l in enumerate(v - prior):
                    st = max(0.0, st + float(l)); c[t] = st
                cc[k] = [first(c, float(x)) for x in hgrid]
            cu[key(e)] = cc
        return al, cu
    ai, ci = scan(INW); res, cus = scan(TEW)
    LAB = {key(e): e["run_lab"] for e in E}
    pick = {}
    for cfa in (10, 50, 200):                          # the operating point of each cost, from the inner split only
        v = [np.mean([ep_return(LAB[k], sc[s][g], cfa) for k, sc in ai.items() for s in sc]) for g in range(len(grid))]
        c = [np.mean([ep_return(LAB[k], sc[s][g], cfa) for k, sc in ci.items() for s in sc]) for g in range(len(hgrid))]
        pick[str(cfa)] = dict(clf=int(np.argmax(v)), cusum=int(np.argmax(c)), inner_clf=float(max(v)), inner_cusum=float(max(c)))
    out = dict(mode="clf", fold=a.fold, seed=a.seed, temperature=Tm, grid=grid.tolist(), hgrid=hgrid.tolist(), prior=prior, alarms=res, cusum=cus, pick=pick)
out.update(hist=a.hist, drop=a.drop, hidden=a.hidden, lr=a.lr, steps=a.steps)
json.dump(out, open(a.out, "w")); print("done", a.out, flush=True)
