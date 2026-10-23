#!/usr/bin/env python3
"""v4 Phase 3/4 campaign runner (gated, resumable). Reads the design manifest and runs
each manifest "run" through the existing harness (run.run_once) so all collectors and the
causal raw logging are reused. After each run it records the live SUPI<->IP mapping and a
runtime assert (the attacker UE's profiler UL pps must rise during each attack phase; else
meta_run_ok=0 and the batch STOPS). At each checkpoint it builds + QA-audits the data so
far and STOPS on a stop-gate breach.

  python3 scripts/k8s/exp/v4traffic/campaign.py run --manifest <design.json> --lo 0 --hi 12 --tag batch1
  python3 scripts/k8s/exp/v4traffic/campaign.py run --reps 7 16 59 --tag rerun --prior <camp dirs>
  python3 scripts/k8s/exp/v4traffic/campaign.py run --variant manifest --manifest <v5 design.json> --lo 0 --hi 42 --tag pilot
--variant: detection-off (default, v4: defence off) | manifest (v5 live: each run's scenario and
defence configuration from the manifest) | <config> (v5: only the manifest runs of that config).
v5 runs reset the defence in every gap, apply the phase's KPM tamper / core outage, are checked by
integrity.check_run (v5 exemptions) and prof_assert (core-outage phases exempt); a failed run is kept
(meta_run_ok=0) and the batch stops after 2 failed runs in a row or a failed preflight.
Run via the repo's system python3 (needs numpy+yaml+pandas), not .venv-ml.
"""
import json, math, pathlib, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))                   # scripts/k8s/exp (run, lab, ...)
sys.path.insert(0, str(HERE))                          # v4traffic
sys.path.insert(0, str(ROOT / "scripts/ml"))           # build_dataset_v4, qa_v4

import run as harness
import lab
import build_dataset_v4 as B
import integrity

STOP_GATES = {"nuisance_auc_max": 0.6, "balance_tol": 0.05, "sym_tol": 0.05,
              "achieved_ok_min": 0.85, "size_overlap_min": 0.6}


def scn_for_run(run_phases, v5=False):
    """Turn one manifest run (list of phases) into a harness scenario (warmup + gaps). v5: the
    phase's tamper / core_outage pass through, the defence is reset at idle and every gap."""
    phases = [{"name": "idle", "duration": 15, **({"reset_defense": True} if v5 else {})}]
    for j, ph in enumerate(run_phases):
        p = {"name": "p%02d_%s" % (j, ph["family"]), "duration": ph["duration"],
             "attack": ph.get("attacker_ue") is not None, "flows": ph["flows"]}
        if ph.get("victim_mode"):
            p["victim_mode"] = ph["victim_mode"]
        if ph.get("congestion"):
            p["congestion"] = ph.get("congestion_cfg", {"rate": "4mbit"})
        if v5:
            p.update({k: ph[k] for k in ("tamper", "core_outage") if k in ph})
        phases.append(p)
        phases.append({"name": "gap%02d" % j, "duration": ph.get("gap", 10), **({"reset_defense": True} if v5 else {})})
    return {"name": "v4campaign", "ues": {"ue1": "attacker", "ue2": "benign"},
            "payload_bytes": 1200, "drain": {"quiet_kbps": 300, "timeout_s": 300},
            "tail_s": 12, "phases": phases}


def _kexec(ns, deploy, container, *cmd, timeout=20):
    import subprocess
    p = subprocess.run(["kubectl", "--context", "oai-lab", "-n", ns, "exec", f"deploy/{deploy}",
                        "-c", container, "--", *cmd], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def pfcp_associated():
    """True if the SMF<->UPF PFCP N4 association is LIVE right now. Authoritative and
    rotation-proof: the UPF security API lists the PFCP sessions it currently holds, which
    can only exist over a live N4 association (the startup 'Added PFCP association' log line
    rotates out of a long-lived SMF log, so grepping for it gives false negatives)."""
    try:
        s, body = lab.upf("GET", "/v1/sessions")
    except Exception:
        return False
    return s == 200 and len((body or {}).get("sessions", [])) >= 1


def urr_fresh(ue_supi=None, max_age=3.0):
    """URR pipeline liveness: the urr-ei-producer must be writing smf-raw.jsonl NOW and
    the recent records must cover BOTH PDU sessions (SEID 1 and 2). URR is Periodic
    Reporting (time-triggered 1 s), so this holds even when UEs are idle; a stale file or
    a missing SEID means the SMF->producer Nsmf_EventExposure subscription broke (e.g.
    after an SMF restart). Checked at the producer because the xApp exposes no raw URR age.
    Returns (ok, detail)."""
    import subprocess
    pod = subprocess.run(["kubectl", "--context", "oai-lab", "-n", "non-rt-ric", "get", "pod",
                          "-o", "name"], capture_output=True, text=True, timeout=20).stdout
    pod = next((l for l in pod.splitlines() if "urr-ei-producer" in l), "")
    if not pod:
        return False, "no urr-ei-producer pod"
    script = ("now=$(date +%s); f=/var/lib/urr-ei/smf-raw.jsonl; "
              "age=$(( now - $(stat -c %Y $f) )); echo AGE $age; "
              "tail -40 $f | grep -o '\"SEID\":[0-9]*' | sort -u")
    r = subprocess.run(["kubectl", "--context", "oai-lab", "-n", "non-rt-ric", "exec", pod,
                        "-c", "artifacts", "--", "sh", "-c", script], capture_output=True, text=True, timeout=25)
    out = r.stdout
    age = None
    seids = set()
    for line in out.splitlines():
        if line.startswith("AGE"):
            try:
                age = int(line.split()[1])
            except (ValueError, IndexError):
                pass
        elif '"SEID":' in line:
            seids.add(line.split(":")[1])
    if age is None:
        return False, "cannot read producer smf-raw.jsonl"
    if age > max_age:
        return False, f"producer URR stale (age {age}s > {max_age}s)"
    if len(seids) < 2:
        return False, f"URR missing a session (SEIDs seen: {sorted(seids)})"
    return True, f"fresh (age {age}s, SEIDs {sorted(seids)})"


def extra_preflight(ue_supi):
    """Campaign-level per-run asserts beyond run_once's tunnels+SUPIs: PFCP association
    present and fresh URR for both SUPIs. Returns (ok, reasons)."""
    reasons = []
    if not pfcp_associated():
        reasons.append("no PFCP association SMF<->UPF")
    ok, detail = urr_fresh(ue_supi)
    if not ok:
        reasons.append("stale/absent URR: " + detail)
    return (len(reasons) == 0), reasons


def record_mapping(run_dir):
    """Live SUPI<->IP from the UPF sessions, written beside the run (not hard-coded)."""
    s, body = lab.upf("GET", "/v1/sessions")
    mp = {}
    if s == 200:
        for x in body.get("sessions", []):
            mp[x.get("supi")] = x.get("ue_ip") or x.get("ip")
    if not all(mp.values()) or not mp:                 # UPF API has no IP: pair SMF "PAA" -> "PDU_SES_EST ... SUPI"
        log = lab.kubectl("-n", "oai-core", "logs", "deploy/oai-smf", "-c", "smf", check=False) or ""
        paa = None
        for line in log.splitlines():
            if "PAA, Ipv4 Address:" in line:
                paa = line.rsplit(":", 1)[1].strip()
            elif "PDU_SES_EST (Event Exposure), SUPI" in line and paa:
                mp[line.split("SUPI", 1)[1].split(",")[0].strip()] = paa
                paa = None
    (run_dir / "meta" / "supi_ip_mapping.json").write_text(json.dumps(mp, indent=1) + "\n")
    return mp


def prof_assert(run_dir, skip=()):
    """Runtime check: in every attack phase, the ATTACKER UE's profiler UL pps must exceed
    an idle floor. Returns (ok, reasons). Reads the run's raw profiler + schedule.
    skip: phase names exempt (v5 core outage: no profiler by design)."""
    ue_supi, phases = B.load_schedule(run_dir)
    prof = {r["supi"]: [] for r in B.load_prof(run_dir)}
    for r in B.load_prof(run_dir):
        prof[r["supi"]].append((r["source_ts"], r.get("prof_ul_pps", 0.0)))
    reasons = []
    for ph in phases:
        if ph["name"] in skip:
            continue
        atks = [(ue, info) for ue, info in ph["ues"].items() if info["label"] == "MALICIOUS"]
        for ue, info in atks:
            supi = ue_supi.get(ue)
            vals = [p for (t, p) in prof.get(supi, []) if ph["start"] + 3 <= t <= ph["end"]]
            peak = max(vals) if vals else 0.0
            if peak < 20:                              # flood/benign both well above 20 pps live
                reasons.append(f"{ph['name']}/{ue}: attacker prof_ul_pps peak {peak:.0f} < 20")
    return (len(reasons) == 0), reasons


def checkpoint_qa(data_dir, run_dirs):
    """Build + audit the data collected so far; return (pass, metrics, breaches)."""
    import subprocess
    py = str(ROOT / ".venv-ml/bin/python")
    subprocess.run([py, "-I", str(ROOT / "scripts/ml/build_dataset_v4.py"), "--out", str(data_dir),
                    *[str(r) for r in run_dirs]], check=True)
    import pandas as pd
    sys.path.insert(0, str(ROOT / "scripts/ml"))
    import qa_v4
    df = pd.read_parquet(data_dir / "rows.parquet")
    nb = df[df.label.isin(["BENIGN", "MALICIOUS"])]
    m = {}
    m["pmal_ue"] = {u: round(float((g.label == "MALICIOUS").mean()), 3) for u, g in nb.groupby("meta_ue")}
    du = nb[nb.meta_backend.isin(("pacer", "hping", "iperf"))]
    m["pmal_backend"] = {b: round(float((g.label == "MALICIOUS").mean()), 3) for b, g in du.groupby("meta_backend")}
    # achieved at the CELL level (backend x role x load), ±10% on the median per-phase ratio
    # — robust to single-phase variance of bursty schedules. Plus a load-MATCHING symmetry
    # gate: per load level the malicious vs benign median achieved_ratio must track (±0.05).
    m["cell_achieved_pass_rate"], m["cell_achieved_fail"], m["load_symmetry"] = None, [], {}
    if "meta_achieved_ratio" in nb:
        ph = nb.dropna(subset=["meta_achieved_ratio"]).groupby(["meta_run_id", "meta_phase", "meta_ue"]).agg(
            backend=("meta_backend", "first"), label=("label", "first"),
            load=("meta_load_mbps", "first"), ratio=("meta_achieved_ratio", "first")).reset_index()
        cg = ph.groupby(["backend", "label", "load"])["ratio"]
        cells, counts = cg.median(), cg.size()
        eval_cells = cells[counts >= 3]                 # small-sample guard: a 2-phase cell
        m["cells_evaluable"] = int(len(eval_cells))     # median is too noisy to gate on
        passed = eval_cells.sub(1.0).abs() <= 0.10
        m["cell_achieved_pass_rate"] = round(float(passed.mean()), 3) if len(passed) else None
        m["cell_achieved_fail"] = [f"{b}/{lab}/{ld:g}={r:.2f}(n{counts[(b,lab,ld)]})"
                                   for (b, lab, ld), r in eval_cells.items() if abs(r - 1) > 0.10]
        for ld, g in ph.groupby("load"):
            mm, bb = g[g.label == "MALICIOUS"]["ratio"].median(), g[g.label == "BENIGN"]["ratio"].median()
            if pd.notna(mm) and pd.notna(bb):
                m["load_symmetry"][f"{ld:g}"] = round(abs(mm - bb), 3)
    nb_sk = qa_v4.nuisance_baseline(df) if qa_v4._SK else {"innocent": None}
    m["nuisance_auc"] = nb_sk.get("innocent")
    # per-cell size overlap for the size-matched pairs
    ov = {}
    for pair, g in nb.groupby("meta_pair"):
        if "~" not in str(pair):
            continue
        per = [qa_v4._ovl(gg[gg.label == "BENIGN"]["prof_ul_mean_bytes"], gg[gg.label == "MALICIOUS"]["prof_ul_mean_bytes"], 12)
               for _, gg in g.groupby(["meta_run_id", "meta_phase"]) if gg.label.nunique() == 2]
        per = [x for x in per if x is not None]
        if per:
            ov[str(pair)] = round(float(pd.Series(per).median()), 3)
    m["size_overlap_per_pair"] = ov
    # balance is INDEPENDENCE from the set's base rate (not an absolute 0.5): the benign-benign
    # offset makes the base rate ~0.44, so compare each level to the base rate it sits in.
    base = round(float((nb.label == "MALICIOUS").mean()), 3)
    base_du = round(float((du.label == "MALICIOUS").mean()), 3) if len(du) else base
    m["base_rate"], m["base_rate_dual_use"] = base, base_du
    tol = STOP_GATES["balance_tol"]
    breaches = []
    for u, p in m["pmal_ue"].items():
        if abs(p - base) > tol:
            breaches.append(f"P(mal|ue={u})={p} vs base {base} (|Δ|>{tol})")
    for b, p in m["pmal_backend"].items():
        if abs(p - base_du) > tol:
            breaches.append(f"P(mal|backend={b})={p} vs dual-use base {base_du} (|Δ|>{tol})")
    # only enforce cell-achieved once enough cells have >=3 phases to judge (at the first
    # 8-run checkpoint most cells have 2 phases -> informational; it bites at the 42-run one).
    if m.get("cells_evaluable", 0) >= 8 and m.get("cell_achieved_pass_rate") is not None \
            and m["cell_achieved_pass_rate"] < STOP_GATES["achieved_ok_min"]:
        breaches.append(f"cell_achieved_pass_rate={m['cell_achieved_pass_rate']} < {STOP_GATES['achieved_ok_min']} (cells off: {m['cell_achieved_fail']})")
    for ld, d in m["load_symmetry"].items():                # load-matching protection
        if d > STOP_GATES["sym_tol"]:
            breaches.append(f"load {ld}: |median(ratio|MAL)-median(ratio|BEN)|={d} > {STOP_GATES['sym_tol']}")
    if m.get("nuisance_auc") is not None and m["nuisance_auc"] > STOP_GATES["nuisance_auc_max"]:
        breaches.append(f"nuisance_auc={m['nuisance_auc']} > 0.6")
    # size-matched pairs only (udp/pulsing/mimicry/fanout/dns small share the prior)
    SIZE_MATCHED = ("udp_flood~udp_bidir", "pulsing_udp~onoff_pareto",
                    "mimicry_udp~udp_nofeedback", "fanout_udp~fanout_benign")
    for pair in SIZE_MATCHED:
        if pair in ov and ov[pair] < STOP_GATES["size_overlap_min"]:
            breaches.append(f"size overlap {pair}={ov[pair]} < 0.6")
    return (len(breaches) == 0), m, breaches


def prior_run_dirs(prior_camps, lo):
    """meta_run_ok=1 run dirs of earlier batches for manifest runs [0, lo), so a checkpoint
    audits the whole PREFIX (the design balances prefixes, not slices). Newest valid attempt (t_start) wins."""
    best, best_t = {}, {}
    for c in prior_camps:
        for rd in sorted((pathlib.Path(c) / "runs" / "detection-off").glob("rep-*")):
            rep = int(rd.name.split("-")[1])
            try:
                m = json.loads((rd / "run.json").read_text())
                ok, t0 = m.get("meta_run_ok") == 1, m.get("t_start") or 0
            except (OSError, ValueError):
                ok, t0 = False, 0
            if ok and rep <= lo and t0 >= best_t.get(rep, 0):      # newest valid attempt by t_start
                best[rep], best_t[rep] = rd, t0
    missing = [r for r in range(1, lo + 1) if r not in best]
    if missing:
        raise SystemExit("prior batches lack ok runs for reps %s" % missing)
    return [best[r] for r in sorted(best)]


def newest_valid_dirs(camps, n_runs):
    """--reps mode: newest meta_run_ok=1 attempt (by t_start) for EVERY manifest run 1..n_runs
    across `camps` (prior batches + the current one) -> the full prefix for the final checkpoint."""
    best = {}
    for c in camps:
        for rd in sorted((pathlib.Path(c) / "runs" / "detection-off").glob("rep-*")):
            try:
                m = json.loads((rd / "run.json").read_text())
            except (OSError, ValueError):
                continue
            rep, t0 = int(rd.name.split("-")[1]), m.get("t_start") or 0
            if m.get("meta_run_ok") == 1 and rep <= n_runs and t0 >= best.get(rep, (0, None))[0]:
                best[rep] = (t0, rd)
    missing = [r for r in range(1, n_runs + 1) if r not in best]
    return [best[r][1] for r in sorted(best)], missing


def run_v5(man, manifest_path, order, tag, only=None):
    """v5 live runs (manifest entries with scenario, config, defence, phases)."""
    camp = harness.OUT_DIR / (time.strftime("%Y%m%d-%H%M%S") + "_v5live_" + tag)
    camp.mkdir(parents=True, exist_ok=True)
    runs = man["runs"]
    order = [i for i in order if only is None or runs[i]["config"] == only]
    (camp / "campaign.json").write_text(json.dumps({"manifest": str(manifest_path), "runs": [i + 1 for i in order],
                                                    "variant": only or "manifest"}, indent=1) + "\n")
    harness.log("campaign %s: %d v5 runs" % (camp.name, len(order)))
    ue_supi = {n: lab.UES[n][2] for n in ("ue1", "ue2")}
    fails, done = 0, []
    for i in order:
        e = runs[i]
        pok, preasons = extra_preflight(ue_supi)
        if not pok:
            harness.log("STOP before run %d: preflight: %s" % (i + 1, "; ".join(preasons)))
            return {"stopped": i + 1, "reason": "preflight", "reasons": preasons, "done": done}
        scn = scn_for_run(e["phases"], v5=True)
        scn["name"] = "v5live"
        variant = {"name": e["config"], "defense": e["defense"]}
        ok = harness.run_once(scn, variant, i + 1, camp)
        rd = camp / "runs" / e["config"] / ("rep-%02d" % (i + 1))
        mp = record_mapping(rd)
        outage = {"p%02d_%s" % (j, ph["family"]) for j, ph in enumerate(e["phases"]) if ph.get("core_outage")}
        pok, reasons = prof_assert(rd, outage)
        meta = json.loads((rd / "run.json").read_text())
        iok, ireasons, idet = integrity.check_run(rd, i + 1, manifest_path)
        meta.update({"attempt_id": "%s_rep-%02d@%d" % (camp.name, i + 1, int(meta.get("t_start") or 0)),
                     "manifest_id": e["id"], "manifest_rep": e["rep"], "scenario": e["scenario"], "config": e["config"],
                     "meta_run_ok": int(bool(ok) and pok and iok), "prof_assert": {"ok": pok, "reasons": reasons[:8]},
                     "integrity": {"ok": iok, "reasons": ireasons[:8], **idet}, "supi_ip_mapping": mp})
        (rd / "run.json").write_text(json.dumps(meta, indent=1) + "\n")
        harness.log("   run %d (%s / %s / rep %d) meta_run_ok=%d%s%s" % (
            i + 1, e["scenario"], e["config"], e["rep"], meta["meta_run_ok"], "" if pok else " PROF: " + "; ".join(reasons[:3]),
            "" if iok else " INTEGRITY: " + "; ".join(ireasons[:3])))
        done.append(i + 1)
        fails = 0 if meta["meta_run_ok"] else fails + 1
        if fails >= 2:
            harness.log("STOP: 2 failed runs in a row")
            return {"stopped": i + 1, "reason": "run_not_ok", "done": done}
    return {"done": done, "camp": str(camp)}


def run_campaign(manifest_path, lo, hi, tag, prior=(), reps=None, variant="detection-off"):
    man = json.loads(pathlib.Path(manifest_path).read_text())
    if variant != "detection-off":
        if not isinstance(man["runs"][0], dict):
            raise SystemExit("--variant %s needs a v5 manifest" % variant)
        order = [r - 1 for r in reps] if reps else list(range(lo, min(hi, len(man["runs"]))))
        return run_v5(man, manifest_path, order, tag, None if variant == "manifest" else variant)
    runs = man["runs"]
    hi = min(hi, len(runs))
    camp = harness.OUT_DIR / (time.strftime("%Y%m%d-%H%M%S") + "_v4campaign_" + tag)
    camp.mkdir(parents=True, exist_ok=True)
    if reps:                                           # non-contiguous reruns: one checkpoint at the end
        order = [r - 1 for r in reps]
        (camp / "campaign.json").write_text(json.dumps({"manifest": str(manifest_path), "reps": list(reps),
                                                        "prior": [str(p) for p in prior]}, indent=1) + "\n")
        harness.log("campaign %s: reps %s of %d" % (camp.name, list(reps), len(runs)))
        prior_dirs = []
    else:
        order = list(range(lo, hi))
        (camp / "campaign.json").write_text(json.dumps({"manifest": str(manifest_path), "range": [lo, hi]}, indent=1) + "\n")
        harness.log("campaign %s: runs [%d,%d) of %d" % (camp.name, lo, hi, len(runs)))
        prior_dirs = prior_run_dirs(prior, lo) if prior else []
    if prior_dirs:
        harness.log("checkpoints include %d prior runs from %s" % (len(prior_dirs), ", ".join(map(str, prior))))
    run_dirs, checkpoints = [], set(man.get("checkpoints") or [])
    variant = {"name": "detection-off", "defense": {"enabled": False, "core": False}}
    ue_supi = {n: lab.UES[n][2] for n in ("ue1", "ue2")}
    for k, i in enumerate(order):
        pok, preasons = extra_preflight(ue_supi)       # PFCP assoc + fresh URR for both SUPIs
        if not pok:
            harness.log("STOP before run %d: preflight: %s" % (i + 1, "; ".join(preasons)))
            return {"stopped": i + 1, "reason": "preflight", "reasons": preasons}
        scn = scn_for_run(runs[i])
        ok = harness.run_once(scn, variant, i + 1, camp)
        rd = camp / "runs" / "detection-off" / ("rep-%02d" % (i + 1))
        run_dirs.append(rd)
        mp = record_mapping(rd)
        pok, reasons = prof_assert(rd)
        meta = json.loads((rd / "run.json").read_text())
        iok, ireasons, idet = integrity.check_run(rd, i + 1, manifest_path)   # duration / gaps / host suspend
        meta["attempt_id"] = "%s_rep-%02d@%d" % (camp.name, i + 1, int(meta.get("t_start") or 0))
        meta["meta_run_ok"] = int(bool(ok) and pok and iok)
        meta["prof_assert"] = {"ok": pok, "reasons": reasons[:8]}
        meta["integrity"] = {"ok": iok, "reasons": ireasons[:8], **idet}
        meta["supi_ip_mapping"] = mp
        (rd / "run.json").write_text(json.dumps(meta, indent=1) + "\n")
        harness.log("   run %d meta_run_ok=%d%s" % (i + 1, meta["meta_run_ok"], ("" if pok else " PROF-ASSERT FAIL: " + "; ".join(reasons[:3])) + ("" if iok else " INTEGRITY FAIL: " + "; ".join(ireasons[:3]))))
        if not meta["meta_run_ok"]:
            harness.log("STOP: run %d failed (ok=%s prof=%s integrity=%s)" % (i + 1, ok, pok, iok))
            return {"stopped": i + 1, "reason": "run_not_ok", "reasons": reasons + ireasons}
        if reps:
            if k + 1 < len(order):
                continue
            sel, missing = newest_valid_dirs(list(prior) + [camp], len(runs))
            if missing:
                harness.log("STOP: final checkpoint lacks ok runs for reps %s" % missing)
                return {"stopped": i + 1, "reason": "prefix_incomplete", "missing": missing}
            harness.log("final checkpoint over the full prefix 1..%d (%d newest valid attempts)" % (len(runs), len(sel)))
            passed, m, breaches = checkpoint_qa(camp / "dataset_sofar", sel)
            harness.log("CHECKPOINT @%d(full): %s" % (len(runs), json.dumps(m)))
        elif (i + 1) in checkpoints or (i + 1) == hi:
            passed, m, breaches = checkpoint_qa(camp / "dataset_sofar", prior_dirs + run_dirs)
            harness.log("CHECKPOINT @%d: %s" % (i + 1, json.dumps(m)))
        else:
            continue
        if not passed:
            harness.log("STOP: stop-gate breach: " + "; ".join(breaches))
            return {"stopped": i + 1, "reason": "stop_gate", "breaches": breaches, "metrics": m}
    return {"done": reps or hi, "run_dirs": [str(r) for r in run_dirs]}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="v4 campaign runner (gated)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--manifest", default="research/datasets/oran_flooding_v4/manifest/design.json")
    r.add_argument("--lo", type=int, default=0)
    r.add_argument("--hi", type=int, default=12)
    r.add_argument("--tag", default="batch")
    r.add_argument("--prior", nargs="*", default=[], help="earlier batch camp dirs (runs [0,lo)) for prefix checkpoints")
    r.add_argument("--variant", default="detection-off",
                   help="detection-off (v4) | manifest (v5: per-run config) | a v5 config name")
    r.add_argument("--reps", nargs="+", type=int, default=None,
                   help="non-contiguous manifest runs (1-based) to (re)run instead of [lo,hi); one checkpoint at the "
                        "end over the full prefix 1..N (newest valid attempt per run across --prior + this batch)")
    a = ap.parse_args()
    res = run_campaign(a.manifest, a.lo, a.hi, a.tag, a.prior, a.reps, a.variant)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
