#!/usr/bin/env python3
"""QA of v5 live attempts (the supervisor runs it after every chunk of ~50 runs).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/qa_v5.py CAMP_DIR [CAMP_DIR ...] [--out report.md]

Per attempt (every run dir, valid or not):
  run_ok        meta_run_ok and the reason of a failed attempt (error / integrity / profiler)
  readiness     wait before each traffic phase (s); a readiness timeout is a failed attempt
  fallbacks     xApp classifier fallbacks to the rules during the run (snapshot end - start)
  residual      anything left at the run start: UPF policies, an xApp level > 0, a KPM tamper
  stale KPM     sidecar steps whose KPM was older than 3 s (would enter the integrity rule as
                missing KPM; never seen in the pilot, must stay 0)
STOP (exit 1) when: a residual policy/level/tamper at a run start, a fallback in a valid run, a
stale-KPM step in a valid run, or fewer than MIN_OK of >= MIN_N attempts valid.
"""
import argparse, json, pathlib, sys

MIN_OK, MIN_N = 0.75, 10           # the valid-rate stop needs >= MIN_N attempts: a chunk cut short by the
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
    r["stale_kpm_steps"] = sum(1 for o in jsonl(rd / "defense/sidecar.jsonl")
                               if "row" in o and (o["row"].get("kpm_age_s") is None or o["row"]["kpm_age_s"] > 3.0))
    return r


def qa(camps):
    A = [attempt(rj.parent) for c in camps for rj in sorted(pathlib.Path(c).glob("runs/*/rep-*/run.json"))]
    stop = []
    if any(a["residual"] for a in A):
        stop.append("residual state at a run start")
    if any(a["ok"] and a["fallbacks"] for a in A):
        stop.append("classifier fallback in a valid run")
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
          " ".join("%.1f" % w for w in a["waits"]), a["fallbacks"], "; ".join(a["residual"]), a["stale_kpm_steps"],
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
