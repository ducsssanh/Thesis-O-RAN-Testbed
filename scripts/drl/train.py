#!/usr/bin/env python3
"""Standard Double DQN on exact replays and the calibrated classifier + threshold baseline (DRL design 4, 5, 7). One process, one thread, one fold. GroupKFold by run; L3 phases never in training; 15 % of the training runs pick the checkpoint.
Writes the first-alarm second of each test episode and scenario. Usage: train.py {dqn|clf} --fold k --seed s [--cfa 50] [--steps 300000] [--drop protocol] --out f.json"""
import argparse, json, pickle
import numpy as np, torch, torch.nn as nn
from sklearn.model_selection import GroupKFold
ap = argparse.ArgumentParser()
ap.add_argument("mode"); ap.add_argument("--fold", type=int, required=True); ap.add_argument("--seed", type=int, default=0); ap.add_argument("--cfa", type=float, default=50); ap.add_argument("--steps", type=int, default=300000)
ap.add_argument("--drop", default=""); ap.add_argument("--data", default="artifacts/drl/episodes.pkl"); ap.add_argument("--out", required=True)
a = ap.parse_args()
torch.set_num_threads(1); torch.manual_seed(a.seed); rng = np.random.default_rng(a.seed)
D = pickle.load(open(a.data, "rb")); E = D["episodes"]
runs = np.array(sorted({e["run"] for e in E}))
tr_i, te_i = list(GroupKFold(5).split(runs, groups=runs))[a.fold]
perm = rng.permutation(tr_i); n_in = max(1, int(.15 * len(perm)))
inner, train = set(runs[perm[:n_in]]), set(runs[perm[n_in:]]); test = set(runs[te_i])
use = lambda e: e["other_evasion"] != "L3"             # L3 phases, attacker and benign client, are test only
TR = [e for e in E if e["run"] in train and use(e)]; IN = [e for e in E if e["run"] in inner and use(e)]; TE = [e for e in E if e["run"] in test]
base = np.vstack([e["scen"]["honest"] for e in TR]); mu, sd = base.mean(0), base.std(0) + 1e-6
drop = np.array(D["protocol"], int) if a.drop == "protocol" else np.array([], int)


def windows(f):
    x = (f - mu) / sd
    if drop.size:
        x[:, drop] = 0
    w = np.zeros((len(x), 300), np.float32)
    for t in range(len(x)):
        lo = max(0, t - 9); seg = x[lo:t + 1]
        w[t, 300 - 30 * len(seg):] = seg.ravel()
    return w


def build(eps):
    return [(e, {k: windows(v) for k, v in e["scen"].items()}) for e in eps]


TRW, INW, TEW = build(TR), build(IN), build(TE)
net = lambda: nn.Sequential(nn.Linear(300, 128), nn.ReLU(), nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 2 if a.mode == "dqn" else 1))


def pick(e, w):
    """Half honest, half one of the tamper scenarios of this episode."""
    keys = [k for k in w if k != "honest"]
    return "honest" if (not keys or rng.random() < .5) else keys[rng.integers(len(keys))]


def first_alarm(score, thr=0.0):
    i = np.flatnonzero(score > thr)
    return int(i[0]) if i.size else -1


results = {}
if a.mode == "dqn":
    Q, T = net(), net(); T.load_state_dict(Q.state_dict())
    opt = torch.optim.Adam(Q.parameters(), lr=3e-4); loss_f = nn.SmoothL1Loss()
    cap, B = 200000, 256
    S = np.zeros((cap, 300), np.float32); S2 = np.zeros((cap, 300), np.float32); A = np.zeros(cap, np.int64); R = np.zeros(cap, np.float32); Dn = np.zeros(cap, np.float32)
    n = p = 0; best, best_sd = -1e18, None; step = 0; e_w = None; t = 0

    def score(sets, sample=None):
        tot, cnt = 0.0, 0
        with torch.no_grad():
            for e, w in sets:
                for k, x in w.items():
                    q = Q(torch.from_numpy(x)).numpy(); al = first_alarm(q[:, 1] - q[:, 0]); lab = e["run_lab"]
                    stop = len(lab) if al < 0 else al
                    r = -float(lab[:stop].sum())
                    if al >= 0 and not lab[al]:
                        r -= a.cfa
                    tot += r; cnt += 1
        return tot / cnt
    while step < a.steps:
        e, w = TRW[rng.integers(len(TRW))]; x = w[pick(e, w)]; lab = e["run_lab"]
        for t in range(len(lab)):
            eps = max(.05, 1 - .95 * step / (a.steps / 3))
            if rng.random() < eps:
                act = int(rng.integers(2))
            else:
                with torch.no_grad():
                    act = int(Q(torch.from_numpy(x[t]).unsqueeze(0)).argmax())
            if act == 1:
                r, done, nx = (0.0 if lab[t] else -a.cfa), 1.0, x[t]
            else:
                if t == len(lab) - 1:                  # end of phase is truncation: the last transition is dropped
                    break
                r, done, nx = (-1.0 if lab[t] else 0.0), 0.0, x[t + 1]
            S[p] = x[t]; S2[p] = nx; A[p] = act; R[p] = r; Dn[p] = done; p = (p + 1) % cap; n = min(n + 1, cap); step += 1
            if n >= B:
                i = rng.integers(n, size=B)
                s, s2 = torch.from_numpy(S[i]), torch.from_numpy(S2[i])
                with torch.no_grad():
                    na = Q(s2).argmax(1, keepdim=True); y = torch.from_numpy(R[i]) + .99 * (1 - torch.from_numpy(Dn[i])) * T(s2).gather(1, na).squeeze(1)
                q = Q(s).gather(1, torch.from_numpy(A[i]).unsqueeze(1)).squeeze(1)
                l = loss_f(q, y); opt.zero_grad(); l.backward(); nn.utils.clip_grad_norm_(Q.parameters(), 10); opt.step()
            if step % 2000 == 0:
                T.load_state_dict(Q.state_dict())
            if step % 25000 == 0:
                v = score(INW)
                print(step, "inner return %.2f" % v, flush=True)
                if v > best:
                    best, best_sd = v, {k: c.clone() for k, c in Q.state_dict().items()}
            if act == 1 or step >= a.steps:
                break
    Q.load_state_dict(best_sd)
    with torch.no_grad():
        for e, w in TEW:
            results["|".join((e["run"], e["phase"], e["supi"]))] = {k: first_alarm((lambda q: q[:, 1] - q[:, 0])(Q(torch.from_numpy(x)).numpy())) for k, x in w.items()}
    out = dict(mode="dqn", fold=a.fold, seed=a.seed, cfa=a.cfa, inner=best, alarms=results)
else:
    M = net(); opt = torch.optim.Adam(M.parameters(), lr=3e-4); bce = nn.BCEWithLogitsLoss()
    X = np.vstack([w[k] for e, w in TRW for k in w]); Y = np.concatenate([e["run_lab"] for e, w in TRW for k in w]).astype(np.float32)
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
    hgrid = np.geomspace(1, 3000, 30); pi = float(Y.mean()); prior = float(np.log(pi / (1 - pi))); cusum = {}
    for e, w in TEW:
        with torch.no_grad():
            r = {k: M(torch.from_numpy(x)).squeeze(1).numpy() / Tm for k, x in w.items()}
        key = "|".join((e["run"], e["phase"], e["supi"]))
        results[key] = {k: [first_alarm(v, float(g)) for g in grid] for k, v in r.items()}
        cus = {}
        for k, v in r.items():                         # CUSUM on the log-odds minus the prior log-odds
            st, c = 0.0, np.zeros(len(v))
            for t, l in enumerate(v - prior):
                st = max(0.0, st + float(l)); c[t] = st
            cus[k] = [first_alarm(c, float(h)) for h in hgrid]
        cusum[key] = cus
    out = dict(mode="clf", fold=a.fold, seed=a.seed, temperature=Tm, grid=grid.tolist(), hgrid=hgrid.tolist(), prior=prior, alarms=results, cusum=cusum)
out.update(drop=a.drop, runs_train=len(train), runs_inner=len(inner), runs_test=len(test))
json.dump(out, open(a.out, "w"))
print("done", a.out, flush=True)
