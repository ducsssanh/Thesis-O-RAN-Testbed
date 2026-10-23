#!/usr/bin/env python3
"""Model sidecar of the xApp classifier, v4 cross-domain defence (live stage B).

Speaks the classifier interface of classifier.c external() on the xApp loopback:
  POST /classify  {"supi", "since_seq", "now_ms", "window": [feature vectors, oldest first],
                   "core": {"urr": latest URR record received | null, "prof": latest profile | null}}
               urr: {observed_at, received_ms, session_epoch, ur_seqn, duration_seconds, ul/dl_bytes, ul/dl_packets,
                     history: [{seq, session, duration, received_ms}] receiver ring, arrival order}
               prof: {observed_at, received_ms, window_ms, + the profile body counters}
               -> {"label", "score", "layer", "kind", "reason", "level", "kt", "ct", "integrity", "engine"}
  GET  /healthz   versions + sha256 of spec, models, integrity rule and engine
  GET  /state     per SUPI: steps, trust values, last decision
  POST /reset     {} all SUPIs | {"supi"}: drop the per-UE state (start of a run)
  POST /mode      {"mode": ran-only|core-only|xd-naive|xd-trust-v1|xd-trust-v2} (+ reset)
While the xApp reports a UPF block / rate limit in force for the UE (newest vector's core_action), the
KPM<->URR integrity rule is not evaluated (the UPF drops what the RAN still carries).
One request = one step of the engine for that SUPI when the newest vector is new (a repeated seq
returns the cached answer). The step's row has the dataset semantics of build_dataset_v4: the newest
KPM (NaN when older than 3 s), the latest URR / profiler record received (NaN when older than 4 s or
the URR period is unknown), ages measured from now_ms. Features, scores and decisions come from
scripts/ml/defence_engine_v4.py, the code of the offline replay. The acting configuration is --mode;
the other four run in shadow (logged, never acted on).
Reply level: 3 when the L3 rule holds, 1 while L1 holds, else 0; label attack when level >= 1.
Every step is appended to --log (JSONL): row, z, trust, integrity, decisions of every config, latency.
Usage: sidecar_v4.py [--port 8091] [--models DIR] [--mode xd-trust-v2] [--log PATH]
"""
import argparse, datetime, hashlib, json, math, pathlib, signal, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = pathlib.Path(__file__).resolve().parent
for p in (HERE, HERE.parents[1] / "ml"):
    if (p / "defence_engine_v4.py").exists():
        sys.path.insert(0, str(p))
import numpy as np
import defence_engine_v4 as D

VERSION = "v4-live-2"
KPM_AGE_CAP, CORE_AGE_CAP = 3.0, D.CORE_AGE_S
KPM = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
       "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
URR = ["urr_ul_kbps", "urr_dl_kbps", "urr_ul_pps", "urr_dl_pps"]
PROF_COUNTS = ["tcp", "tcp_syn", "udp", "icmp", "frag", "dns", "gtp_in_gtp"]
PROF = ["prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps", "prof_ul_mean_bytes", "prof_dl_mean_bytes"] + \
       ["prof_ul_" + c for c in PROF_COUNTS] + ["prof_dl_" + c for c in PROF_COUNTS if c not in ("dns", "gtp_in_gtp")] + \
       ["prof_ul_dst_estimate"]


def iso(s):
    """ISO-8601 (optional fraction, Z) -> unix seconds (as build_dataset_v4.iso)."""
    s = s.rstrip("Z")
    frac = 0.0
    if "." in s:
        s, f = s.split(".", 1)
        frac = float("0." + f)
    dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp() + frac


def urr_rate(u):
    """URR rates of the latest record: volume / period, period = its cumulative duration minus that of
    its causal predecessor (latest record received before it, same session, lower seq), as
    build_dataset_v4.urr_at. u["history"]: the receiver's ring, arrival order, newest = u."""
    hist = u.get("history") or []
    prev = None
    for h in reversed(hist[:-1]):
        if h.get("session") == u.get("session_epoch") and (h.get("seq") or 0) < (u.get("ur_seqn") or 0):
            prev = h
            break
    if prev is None or u.get("duration_seconds") is None or prev.get("duration") is None:
        return None
    d = u["duration_seconds"] - prev["duration"]
    if d <= 0:
        return None
    return {"urr_ul_kbps": max(u["ul_bytes"], 0) * 8 / 1000.0 / d, "urr_dl_kbps": max(u["dl_bytes"], 0) * 8 / 1000.0 / d,
            "urr_ul_pps": max(u["ul_packets"], 0) / d, "urr_dl_pps": max(u["dl_packets"], 0) / d}


def row_from_request(req):
    """One telemetry row as of now_ms (build_dataset_v4 semantics). Returns (row, newest vector)."""
    w = req.get("window") or []
    v = w[-1] if w else {}
    now = (req.get("now_ms") if req.get("now_ms") is not None else v.get("at_ms", 0)) / 1000.0
    row = {"t": now, "seq": v.get("seq"), "e2_node": v.get("e2_node", ""), "amf_ue_ngap_id": v.get("amf_ue_ngap_id"),
           "core_action": v.get("core_action", "none")}
    row["kpm_age_s"] = now - v["collect_ms"] / 1000.0 if "collect_ms" in v else math.nan
    ok = row["kpm_age_s"] <= KPM_AGE_CAP
    for f in KPM:
        row[f] = float(v.get(f, math.nan)) if ok else math.nan
    core = req.get("core") or {}
    u = core.get("urr")
    row["urr_age_s"] = now - iso(u["observed_at"]) if u else math.nan
    rate = urr_rate(u) if u else None
    if rate and row["urr_age_s"] <= CORE_AGE_CAP:
        row.update(rate)
    else:
        row.update({f: math.nan for f in URR})
    p = core.get("prof")
    row["prof_age_s"] = now - iso(p["observed_at"]) if p else math.nan
    if p and row["prof_age_s"] <= CORE_AGE_CAP:
        wd = (p.get("window_ms") or 1000) / 1000.0
        row.update({"prof_ul_kbps": p.get("ul_bytes", 0) * 8 / 1000.0 / wd, "prof_dl_kbps": p.get("dl_bytes", 0) * 8 / 1000.0 / wd,
                    "prof_ul_pps": p.get("ul_pkts", 0) / wd, "prof_dl_pps": p.get("dl_pkts", 0) / wd,
                    "prof_ul_mean_bytes": p["ul_bytes"] / p["ul_pkts"] if p.get("ul_pkts") else 0.0,
                    "prof_dl_mean_bytes": p["dl_bytes"] / p["dl_pkts"] if p.get("dl_pkts") else 0.0,
                    "prof_ul_dst_estimate": float(p.get("ul_dst_estimate", 0.0))})
        for c in PROF_COUNTS:
            row["prof_ul_" + c] = p.get("ul_" + c, 0)
            if c not in ("dns", "gtp_in_gtp"):
                row["prof_dl_" + c] = p.get("dl_" + c, 0)
    else:
        row.update({f: math.nan for f in PROF})
    return row, v


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class UE:
    def __init__(self, cols, rule):
        self.feat = D.OnlineFeatures(cols)
        self.dec = {c: D.DecisionState(c, *rule) for c in D.CONFIGS}
        self.last_seq = None
        self.answer = None
        self.steps = 0
        self.last = {}


class Sidecar:
    def __init__(self, models, mode, log=None):
        from threadpoolctl import threadpool_limits
        threadpool_limits(1)                             # one-row predicts: OpenMP threads cost ~50 ms per call
        models = pathlib.Path(models)
        self.scorer = D.Scorer(models)
        self.rule = D.load_rule(models)
        self.cols = self.scorer.spec["raw_features"]
        self.cols_idx = None
        self.mode = mode
        self.ues = {}
        self.lock = threading.Lock()
        self.log = open(log, "a") if log else None
        self.hashes = {"spec": sha(models / "spec.json"), "integrity_rule": sha(models / "integrity_rule.json"),
                       "engine": sha(D.__file__), "sidecar": sha(__file__),
                       **{"model_" + k: sha(models / v["file"]) for k, v in self.scorer.spec["models"].items()}}
        names = D.OnlineFeatures(self.cols).names
        self.cols_idx = self.scorer.index(names)
        self.counts = {"requests": 0, "steps": 0, "repeats": 0, "errors": 0, "seq_gaps": 0}
        self.trace = None                                # list: every step's internals (parity test)

    def health(self):
        import sklearn, joblib
        return {"ok": True, "version": VERSION, "mode": self.mode, "config": D.MODES[self.mode],
                "rule": dict(zip(("tau", "m", "bias"), self.rule)), "sklearn": sklearn.__version__,
                "joblib": joblib.__version__, "numpy": np.__version__, "sha256": self.hashes, "counts": self.counts}

    def score(self, r):
        x = r[None, :]
        return {k: float(m.predict_proba(x[:, self.cols_idx[k]])[0, 1] / self.scorer.spec["models"][k]["threshold"])
                for k, m in self.scorer.models.items()}

    def classify(self, req):
        t0 = time.perf_counter()
        supi = req.get("supi") or ""
        with self.lock:
            self.counts["requests"] += 1
            u = self.ues.get(supi)
            if u is None:
                u = self.ues[supi] = UE(self.cols, self.rule)
            row, v = row_from_request(req)
            if u.answer is not None and row["seq"] is not None and row["seq"] == u.last_seq:
                self.counts["repeats"] += 1
                return u.answer
            if u.last_seq is not None and row["seq"] is not None and row["seq"] > u.last_seq + 1:
                self.counts["seq_gaps"] += 1
            u.last_seq = row["seq"]
            R = u.feat.push(row)
            z = self.score(R)
            enforced = row["core_action"] in ("block", "ratelimit")
            dec = {c: s.step(row["rate_ul_kbps"], row["urr_ul_kbps"], row["prof_ul_kbps"], row["urr_age_s"],
                             row["cell_prb_ul_pct"], z, enforced) for c, s in u.dec.items()}
            cfg = D.MODES[self.mode]
            d = dec[cfg]
            level = 3 if d["l3"] else 1 if d["l1"] else 0
            label = "attack" if level else "suspicious" if d["hit"] else "benign"
            zmain = d["zf"] if d["zf"] == d["zf"] else max(z["xd"] if cfg == D.CONFIGS[2] else 0.0,
                                                          z["ran"] if cfg == D.CONFIGS[0] else 0.0,
                                                          z["core"] if cfg == D.CONFIGS[1] else 0.0)
            kind = ("kpm_integrity_under" if d["under"] else "core_rule" if d["core_rule"] else
                    "ran_rule" if d["ran_rule"] and d["kt"] >= 0.5 else "model") if d["hit"] else ""
            ans = {"label": label, "score": round(min(1.0, max(0.0, zmain / 2)), 4), "layer": D.layer_of(cfg, d),
                   "level": level, "kind": kind,
                   "reason": "%s z_xd %.2f z_core %.2f z_ran %.2f kt %.2f ct %.0f%s held %d" % (
                       self.mode, z["xd"], z["core"], z["ran"], d["kt"], d["ct"], " INTEGRITY" if d["integrity"] else "",
                       d["held"]),
                   "kt": d["kt"], "ct": d["ct"], "integrity": d["integrity"], "engine": VERSION}
            u.answer, u.steps = ans, u.steps + 1
            u.last = {"t": row["t"], "kt": d["kt"], "ct": d["ct"], "integrity": d["integrity"], "level": level,
                      "label": label, "e2_node": row["e2_node"], "steps": u.steps, "seq": row["seq"]}
            self.counts["steps"] += 1
            lat = (time.perf_counter() - t0) * 1000
            if self.trace is not None:
                self.trace.append({"supi": supi, "row": row, "R": R, "z": z, "dec": dec, "latency_ms": lat})
            if self.log:
                rec = {"ts": time.time(), "supi": supi, "mode": self.mode, "seq": row["seq"], "step": u.steps,
                       "row": {k: (None if isinstance(x, float) and x != x else x) for k, x in row.items()},
                       "z": z, "kt": d["kt"], "ct": d["ct"], "integrity": d["integrity"], "under": d["under"],
                       "lr": None if d["lr"] != d["lr"] else d["lr"], "label": label, "layer": ans["layer"], "level": level,
                       "kind": kind, "latency_ms": round(lat, 3),
                       "configs": {k: {"hit": x["hit"], "l1": x["l1"], "l3": x["l3"], "integrity": x["integrity"]}
                                   for k, x in zip(D.MODES, dec.values())}}
                self.log.write(json.dumps(rec) + "\n")
                self.log.flush()
            return ans

    def state(self):
        with self.lock:
            return {"mode": self.mode, "counts": self.counts, "ues": {s: u.last for s, u in self.ues.items()}}

    def reset(self, supi=None):
        with self.lock:
            if supi:
                self.ues.pop(supi, None)
            else:
                self.ues.clear()
            if self.log:
                self.log.write(json.dumps({"ts": time.time(), "event": "reset", "supi": supi, "mode": self.mode}) + "\n")
                self.log.flush()
        return {"reset": supi or "all"}

    def set_mode(self, mode):
        if mode not in D.MODES:
            raise ValueError(mode)
        self.mode = mode
        self.reset()
        return {"mode": mode, "config": D.MODES[mode]}


def serve(sc, port):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/healthz":
                return self.reply(200, sc.health())
            if self.path == "/state":
                return self.reply(200, sc.state())
            self.reply(404, {"error": "GET /healthz|/state, POST /classify|/reset|/mode"})

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path == "/classify":
                    return self.reply(200, sc.classify(req))
                if self.path == "/reset":
                    return self.reply(200, sc.reset(req.get("supi")))
                if self.path == "/mode":
                    return self.reply(200, sc.set_mode(req.get("mode")))
                return self.reply(404, {"error": "POST /classify|/reset|/mode"})
            except Exception as e:                      # the xApp falls back to its rules on any non-200
                sc.counts["errors"] += 1
                self.reply(500, {"error": "%s: %s" % (type(e).__name__, e)})

        def log_message(self, *a):
            pass

    HTTPServer(("127.0.0.1" if sc_bind_local else "0.0.0.0", port), Handler).serve_forever()


sc_bind_local = True


def main():
    global sc_bind_local
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--models", default=str(D.MODELS))
    ap.add_argument("--mode", choices=sorted(D.MODES), default="xd-trust-v2")
    ap.add_argument("--log", default="/tmp/sidecar_v4.jsonl")
    ap.add_argument("--bind-all", action="store_true", help="listen on 0.0.0.0 (tests only; the xApp uses loopback)")
    a = ap.parse_args()
    sc_bind_local = not a.bind_all
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # PID 1 in the pod: no default SIGTERM action
    pathlib.Path(a.log).parent.mkdir(parents=True, exist_ok=True)
    sc = Sidecar(a.models, a.mode, a.log)
    h = sc.health()
    print(json.dumps({"start": h["version"], "mode": h["mode"], "sha256": h["sha256"], "sklearn": h["sklearn"]}), flush=True)
    serve(sc, a.port)


if __name__ == "__main__":
    main()
