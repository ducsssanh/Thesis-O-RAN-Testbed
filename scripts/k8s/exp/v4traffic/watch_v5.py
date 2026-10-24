#!/usr/bin/env python3
"""Live view of a running v5 campaign (read-only: never changes the testbed or the campaign).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/watch_v5.py [--tag main] [--every 3]

Shows: progress (valid / selected manifest runs, failed attempts, ETA), the running attempt
(manifest id, scenario, config, elapsed, approximate phase from the plan), and per UE what the
defence sees now: KPM UL rate, xApp level, active tamper, sidecar label / kpm_trust / core_trust /
integrity alarm. One kubectl exec per refresh (both HTTP GETs in one call), progress every 30 s.
"""
import argparse, json, pathlib, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import lab
import supervise_v5 as S

MAN = S.ROOT / "research/datasets/oran_flooding_v5_live/manifest/design.json"
RUN_S = {False: 384.0, True: 217.0}           # pilot start-to-start per run (4-phase / icmp_control)


def running(tag):
    """(manifest id, run start unix) of the attempt in progress, else None."""
    best = None
    for rj in S.EXP.glob("*_v5live_%s_s*/runs/*/rep-*/run.json" % tag):
        try:
            if json.loads(rj.read_text()).get("status") != "running":
                continue
        except (OSError, ValueError):
            continue
        t = rj.parent.stat().st_ctime
        if best is None or t > best[1]:
            best = (int(rj.parent.name.split("-")[1]), t)
    return best


def phase_at(e, el):
    """Approximate phase from the plan (idle 15 s, phases, gaps; + ~20 s setup before idle)."""
    t = el - 20
    if t < 0:
        return "setup (drain, defence config)"
    seq = [("idle", 15)] + [x for j, ph in enumerate(e["phases"])
                            for x in (("p%02d_%s%s%s" % (j, ph["family"], " atk=" + ph["attacker_ue"],
                                                         " tamper %s x%g" % (ph["tamper"]["ue"], ph["tamper"]["factor"]) if ph.get("tamper") else "")
                                       + (" CORE OUTAGE" if ph.get("core_outage") else ""), ph["duration"]),
                                      ("gap%02d" % j, ph.get("gap", 15)))]
    for name, d in seq:
        if t < d:
            return "%s (%d/%d s)" % (name, t, d)
        t -= d
    return "tail / collecting logs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="main")
    ap.add_argument("--every", type=float, default=3.0)
    ap.add_argument("--config-reps", default="rules-v1=1,3")
    a = ap.parse_args()
    M = json.loads(MAN.read_text())
    ids = S.config_reps(list(range(1, len(M["runs"]) + 1)), M, a.config_reps)
    prog, t_prog = "", 0
    while True:
        if time.time() - t_prog > 30:
            at = S.attempts(MAN, a.tag)
            ok = [i for i in ids if at.get(i, (0, False))[1]]
            fails = sum(n - int(v) for n, v in at.values())
            left = [i for i in ids if i not in ok]
            eta = sum(RUN_S[M["runs"][i - 1]["scenario"] == "icmp_control"] for i in left) * 1.11 / 3600
            prog = "valid %d/%d (%.0f %%)  failed attempts %d  left %d runs  ETA ~%.1f h (incl. ~11 %% re-runs)" % (
                len(ok), len(ids), 100 * len(ok) / len(ids), fails, len(left), eta)
            t_prog = time.time()
        cur = running(a.tag)
        try:
            (s1, st), (s2, sc) = lab.http_many([["GET", "http://127.0.0.1:8090/v1/defense/state", None],
                                                ["GET", "http://127.0.0.1:8091/state", None]])
        except Exception as ex:
            st, sc = {}, {"error": str(ex)[:100]}
        L = [time.strftime("%H:%M:%S") + "  " + prog, ""]
        if cur:
            e = M["runs"][cur[0] - 1]
            el = time.time() - cur[1]
            L += ["run %d  rep %d  %s / %s  elapsed %d s" % (e["id"], e["rep"], e["scenario"], e["config"], el),
                  "phase ~ " + phase_at(e, el)]
        else:
            L.append("no attempt running (between runs, recovery or QA)")
        tam = {t.get("supi"): t.get("factor") for t in (st.get("tamper") or [])}
        su = (sc or {}).get("ues") or {}
        L += ["", "%-6s %10s %6s %8s | %-10s %5s %5s %6s" % ("UE", "KPM UL", "level", "tamper", "sidecar", "kt", "ct", "integ")]
        for u in st.get("ues") or []:
            n = next((k for k, v in lab.UES.items() if v[2] == u["supi"]), u["supi"][-4:])
            d = su.get(u["supi"]) or {}
            L.append("%-6s %7.0f kb %6d %8s | %-10s %5.2f %5.0f %6s" % (
                n, u.get("rate_ul_kbps") or 0, u.get("level") or 0, "x%g" % tam[u["supi"]] if u["supi"] in tam else "-",
                d.get("label", "-"), d.get("kt", float("nan")), d.get("ct", float("nan")), "ALARM" if d.get("integrity") else "-"))
        L += ["", "classifier %s  sidecar mode %s  fallbacks %s" % (
            (st.get("classifier") or {}).get("kind"), (sc or {}).get("mode"), (st.get("classifier") or {}).get("fallbacks"))]
        print("\033[2J\033[H" + "\n".join(L), flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
