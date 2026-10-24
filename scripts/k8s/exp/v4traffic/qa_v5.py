#!/usr/bin/env python3
"""QA of v5 live attempts (the supervisor runs it after every chunk of ~50 runs).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/qa_v5.py CAMP_DIR [CAMP_DIR ...] [--out report.md]

Per attempt (every run dir, valid or not):
  run_ok        meta_run_ok and the reason of a failed attempt (error / integrity / profiler)
  readiness     wait before each traffic phase (s); a readiness timeout is a failed attempt
  fallbacks     xApp classifier fallbacks to the rules during the run (snapshot end - start), located by the
                sidecar steps slower than SLOW_MS (xApp timeout 200 ms) +- 1 s: inside a traffic phase window of
                live_eval_v5 ([t_start, t_end + 2 s]) or not; a fallback with no slow step at all is unexplained
  residual      anything left at the run start: UPF policies, an xApp level > 0, a KPM tamper
  stale KPM     sidecar steps whose KPM was older than 3 s (would enter the integrity rule as
                missing KPM; never seen in the pilot, must stay 0)
A valid run with a fallback in a traffic phase (or one no slow sidecar step explains) is FLAGGED: it stays
valid and the final report repeats every metric without the flagged runs (sensitivity). Gap/idle fallbacks
are counted only. STOP (exit 1) only on serious errors: a residual policy/level/tamper at a run start, a
sidecar whose per-run p99 latency exceeds P99_MAX_MS (systematic: fallbacks everywhere), a
stale-KPM step in a valid run, or fewer than MIN_OK of >= MIN_N attempts valid (testbed broken).
"""
import argparse, json, pathlib, sys

SLOW_MS = 150.0
P99_MAX_MS = 200.0                     # = the xApp timeout: beyond it most decisions would be fallbacks
MIN_OK, MIN_N = 0.50, 10           # the valid-rate stop needs >= MIN_N attempts: a chunk cut short by the
                                   # campaign's 2-failures stop is a testbed failure, handled by the recovery


def jsonl(p):
    try:
        with open(p) as f:
            for l in f:
                try:
                    yield json.loads(l)
                except ValueError:
                    pass
    except OSError:
        return


def attempt(rd):
    rd = pathlib.Path(rd)
    m = json.loads((rd / "run.json").read_text())
    r = {"dir": str(rd), "id": m.get("manifest_id"), "scenario": m.get("scenario"), "config": m.get("config"),
         "ok": m.get("meta_run_ok") == 1, "why": ""}
    if not r["ok"]:
        r["why"] = (m.get("error") or "; ".join((m.get("integrity") or {}).get("reasons") or [])
                    or "; ".join((m.get("prof_assert") or {}).get("reasons") or []) or m.get("status") or "?")[:200]
    r["readiness_timeout"] = "readiness:" in (m.get("error") or "")
    r["waits"] = [ph["readiness"]["wait_s"] for ph in m.get("phases") or [] if ph.get("readiness")]
    s0, s1 = [json.loads((rd / ("meta/snapshot_%s.json" % k)).read_text()) if (rd / ("meta/snapshot_%s.json" % k)).exists() else {}
              for k in ("start", "end")]
    fb = lambda s: ((s.get("defense_state") or {}).get("classifier") or {}).get("fallbacks")
    r["fallbacks"] = fb(s1) - fb(s0) if fb(s0) is not None and fb(s1) is not None else None
    res = []
    if s0:
        n = (s0.get("upf_v1_ues") or {}).get("count") or 0
        if n:
            res.append("%d UPF policies" % n)
        lv = [u["supi"][-4:] for u in (s0.get("defense_state") or {}).get("ues") or [] if u.get("level")]
        if lv:
            res.append("xApp level > 0: " + ",".join(lv))
        if (s0.get("defense_state") or {}).get("tamper"):
            res.append("tamper on")
    r["residual"] = res
    steps = [o for o in jsonl(rd / "defense/sidecar.jsonl") if "row" in o]
    r["stale_kpm_steps"] = sum(1 for o in steps if o["row"].get("kpm_age_s") is None or o["row"]["kpm_age_s"] > 3.0)
    win = [(ph["name"], ph["t_start"], ph["t_end"] + 2) for ph in m.get("phases") or [] if ph["name"].startswith("p")]
    slow = [o["ts"] for o in steps if (o.get("latency_ms") or 0) > SLOW_MS]
    r["fallback_in_phase"] = sorted({n for t in slow for n, a, b in win if a <= t + 1 and t - 1 <= b})
    r["fallback_unlocated"] = int(bool(r["fallbacks"]) and not slow)
    lat = sorted(o.get("latency_ms") or 0 for o in steps)
    r["p99_ms"] = lat[int(0.99 * (len(lat) - 1))] if lat else None
    return r


def qa(camps):
    A = [attempt(rj.parent) for c in camps for rj in sorted(pathlib.Path(c).glob("runs/*/rep-*/run.json"))]
    stop = []
    if any(a["residual"] for a in A):
        stop.append("residual state at a run start")
    flagged = [a for a in A if a["ok"] and a["fallbacks"] and (a["fallback_in_phase"] or a["fallback_unlocated"])]
    for a in A:
        a["flagged"] = a in flagged
    if any(a["p99_ms"] is not None and a["p99_ms"] > P99_MAX_MS for a in A):
        stop.append("sidecar p99 latency > %.0f ms in a run" % P99_MAX_MS)
    if any(a["ok"] and a["stale_kpm_steps"] for a in A):
        stop.append("sidecar stepped on stale KPM in a valid run")
    n_ok = sum(a["ok"] for a in A)
    if len(A) >= MIN_N and n_ok / len(A) < MIN_OK:
        stop.append("valid attempts %d/%d < %.0f %%" % (n_ok, len(A), 100 * MIN_OK))
    waits = sorted(w for a in A for w in a["waits"])
    q = lambda p: waits[min(len(waits) - 1, int(p * len(waits)))] if waits else None
    summ = {"attempts": len(A), "valid": n_ok, "readiness_timeouts": sum(a["readiness_timeout"] for a in A),
            "phases_checked": len(waits), "wait_p50_s": q(0.5), "wait_p99_s": q(0.99), "wait_max_s": waits[-1] if waits else None,
            "phases_waited_gt1s": sum(w > 1 for w in waits), "fallbacks": sum(a["fallbacks"] or 0 for a in A),
            "flagged_runs": [a["id"] for a in flagged],
            "residual": sum(bool(a["residual"]) for a in A), "stale_kpm_steps": sum(a["stale_kpm_steps"] for a in A),
            "stop": stop}
    return summ, A


def report(summ, A, camps):
    L = ["# v5 QA — %s\n" % ", ".join(pathlib.Path(c).name for c in camps),
         "| check | value |", "|---|---|"]
    L += ["| %s | %s |" % (k, v) for k, v in summ.items() if k != "stop"]
    L += ["", "**%s**" % ("STOP: " + "; ".join(summ["stop"]) if summ["stop"] else "PASS"), "",
          "| id | scenario | config | ok | readiness waits (s) | fallbacks | residual | stale KPM | why |", "|---|---|---|---|---|---|---|---|---|"]
    L += ["| %s | %s | %s | %d | %s | %s | %s | %d | %s |" % (a["id"], a["scenario"], a["config"], a["ok"],
          " ".join("%.1f" % w for w in a["waits"]), "%s%s" % (a["fallbacks"], " in " + ",".join(a["fallback_in_phase"]) if a.get("fallback_in_phase") else ""), "; ".join(a["residual"]), a["stale_kpm_steps"],
          a["why"].replace("|", "/")) for a in A]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("camps", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args()
    summ, A = qa(a.camps)
    txt = report(summ, A, a.camps)
    if a.out:
        pathlib.Path(a.out).write_text(txt)
    print(json.dumps(summ))
    return 1 if summ["stop"] else 0


if __name__ == "__main__":
    sys.exit(main())
