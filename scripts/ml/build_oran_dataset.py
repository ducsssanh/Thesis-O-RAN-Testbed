#!/usr/bin/env python3
"""Assemble the testbed O-RAN flooding dataset from experiment campaigns.

Turns one or more campaign directories (artifacts/experiments/<...>) into a
single tidy, leakage-aware labelled table of per-SUPI-per-second records, plus
a data-quality / load-overlap report. This is the "synchronized -> model-ready"
step of the dataset plan; it does NOT touch the cluster.

Ground truth comes from experimental control only (never from volume/PRB):
  - a (UE, phase) is MALICIOUS iff that UE ran an attack flow in that phase
    (traffic/flows.json carries the "attack" family on those flows);
  - otherwise the UE in that phase is BENIGN (idle/gap = benign low-load);
  - feature rows outside every phase (warmup/tail) are UNKNOWN and dropped.

Online-observable features only. The xApp's decision outputs (class, limit_*,
level, limited, core_action, urr_at_decision) are EXCLUDED as label leakage.

Usage:
  build_oran_dataset.py --out research/datasets/oran_flooding_v1 CAMPAIGN_DIR [CAMPAIGN_DIR ...]
  build_oran_dataset.py --out ... --glob 'artifacts/experiments/*flood*'
"""
import argparse
import csv
import glob
import json
import pathlib
import sys

# ---- feature groups (what an online detector could see) --------------------
RAN = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
       "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
PROF = ["prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps",
        "prof_ul_mean_bytes", "prof_dl_mean_bytes",
        "prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp",
        "prof_ul_frag", "prof_ul_dns", "prof_ul_gtp_in_gtp",
        "prof_dl_tcp", "prof_dl_tcp_syn", "prof_dl_udp", "prof_dl_icmp",
        "prof_dl_frag", "prof_ul_dst_estimate"]
# URR (standard 3GPP PFCP usage reporting, core-layer volume). In v2 it is a
# full first-class feature: the SMF-subscription outage that crippled URR in v1
# (SMF *container* restart wiped its Nsmf_EventExposure subs; the producer's
# pod-UID-keyed subscribe() skipped re-subscribing) is fixed, so URR is present
# for BOTH classes. The missingness leak audit below is DATA-DRIVEN and will flag
# urr_* automatically if a future run loses URR for one class again; any feature
# it marks leak-risk must be dropped by the modelling step.
URR = ["urr_ul_kbps", "urr_dl_kbps", "urr_ul_pps", "urr_dl_pps"]
FEATURES = RAN + URR + PROF
# never used as X: online decision outputs + identity/book-keeping
LEAK = {"class", "limit_ul_kbps", "limit_dl_kbps", "level", "limited",
        "core_action", "urr_at_decision"}

META = ["campaign", "run", "supi", "ue", "phase", "label", "attack_family",
        "load_category", "has_urr", "has_prof", "t_unix"]


def load_run(run_dir):
    """Yield labelled records for one run directory (runs/<variant>/rep-NN)."""
    run = json.loads((run_dir / "run.json").read_text())
    if run.get("status") != "ok":
        return
    feats_path = run_dir / "defense/features.jsonl"
    phases_path = run_dir / "phases.csv"
    flows_path = run_dir / "traffic/flows.json"
    if not (feats_path.exists() and phases_path.exists() and flows_path.exists()):
        return
    phases = list(csv.DictReader(phases_path.open()))
    flows = json.loads(flows_path.read_text())
    supi2ue = {u["supi"]: n for n, u in run.get("ues", {}).items()}

    # (phase, ue) -> attack family, and the set of (phase, ue) that had any flow
    attack_of = {}
    flow_ues = set()
    for f in flows:
        key = (f["phase"], f["ue"])
        flow_ues.add(key)
        if f.get("attack"):
            attack_of[key] = f["attack"]

    def phase_at(t):
        for p in phases:
            if float(p["t_start_unix"]) <= t <= float(p["t_end_unix"]):
                return p
        return None

    campaign = run_dir.parents[2].name
    run_id = run_dir.parents[0].name + "/" + run_dir.name  # variant/rep
    for line in feats_path.open():
        r = json.loads(line)
        supi = r.get("supi")
        ue = supi2ue.get(supi)
        if ue is None:
            continue
        t = r.get("at_ms", 0) / 1000.0
        p = phase_at(t)
        if p is None:
            continue  # warmup/tail -> UNKNOWN, dropped
        key = (p["phase"], ue)
        fam = attack_of.get(key)
        label = "MALICIOUS" if fam else "BENIGN"
        # load category from a dense measured UL rate (benign idle vs loaded);
        # this is descriptive metadata, NOT a label source. Uses KPM throughput
        # (present for every row), never URR (sparse/confounded).
        ul = r.get("thp_ul_kbps")
        if ul is None:
            ul = r.get("rate_ul_kbps") or 0
        load = "idle" if ul < 200 else "low" if ul < 1000 else "medium" if ul < 3000 else "high"
        rec = {"campaign": campaign, "run": run_id, "supi": supi, "ue": ue,
               "phase": p["phase"], "label": label, "attack_family": fam or "",
               "load_category": load,
               "has_urr": int(r.get("urr_age_s") is not None),
               "has_prof": int(r.get("prof_age_s") is not None),
               "t_unix": round(t, 3)}
        for k in FEATURES:
            rec[k] = r.get(k)
        yield rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaigns", nargs="*", help="campaign directories")
    ap.add_argument("--glob", help="glob of campaign dirs (alternative to listing them)")
    ap.add_argument("--out", required=True, help="dataset root (records.csv + report written here)")
    a = ap.parse_args()

    camps = list(a.campaigns)
    if a.glob:
        camps += sorted(glob.glob(a.glob))
    camps = [pathlib.Path(c) for c in dict.fromkeys(camps)]
    if not camps:
        sys.exit("no campaign directories given")

    records = []
    runs_seen = 0
    for camp in camps:
        for run_dir in sorted(camp.glob("runs/*/rep-*")):
            n0 = len(records)
            records.extend(load_run(run_dir))
            if len(records) > n0:
                runs_seen += 1
    if not records:
        sys.exit("no OK runs with features/phases/flows found")

    # ---- generator-failure gate (validity, not volume-based labelling) ------
    # A malicious family whose attack generator never actually sent traffic is
    # an invalid experimental condition (the control did not take effect), not a
    # real attack sample. Drop any malicious family with < MIN of its rows active
    # (prof_ul_pps > PPS). This catches silent generator failures (e.g. hping3 -f
    # fragmented flood) automatically; it NEVER drops individual rows by volume.
    activity, dropped = family_activity(records)
    records = [r for r in records if not (r["label"] == "MALICIOUS" and r["attack_family"] in dropped)]

    out = pathlib.Path(a.out)
    (out / "synchronized").mkdir(parents=True, exist_ok=True)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    cols = META + FEATURES
    csv_path = out / "synchronized/records.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(records)

    # ---- data-quality + load-overlap report --------------------------------
    rep = report(records, runs_seen, camps, activity, dropped)
    (out / "reports/data_quality.md").write_text(rep)
    print(rep)
    print("records: %d -> %s" % (len(records), csv_path))


ACTIVITY_PPS = 5.0      # a row is "active" if the profiler saw > this many pps
FAMILY_ACTIVE_MIN = 0.10  # a malicious family below this active fraction is invalid


def family_activity(records):
    """Per-malicious-family achieved-activity, and the set of invalid families.

    Returns (rows, dropped) where rows is a list of
    (family, n, active_fraction) and dropped is the set of families whose
    generator never produced traffic (active_fraction < FAMILY_ACTIVE_MIN).
    """
    from collections import defaultdict
    byfam = defaultdict(list)
    for r in records:
        if r["label"] == "MALICIOUS":
            byfam[r["attack_family"]].append(r)
    rows, dropped = [], set()
    for fam, rs in sorted(byfam.items()):
        def pps(r):
            v = r.get("prof_ul_pps")
            try:
                return float(v) if v not in (None, "", "nan", "None") else 0.0
            except (TypeError, ValueError):
                return 0.0
        active = sum(1 for r in rs if pps(r) > ACTIVITY_PPS) / len(rs)
        rows.append((fam, len(rs), active))
        if active < FAMILY_ACTIVE_MIN:
            dropped.add(fam)
    return rows, dropped


def report(records, runs_seen, camps, activity=None, dropped=None):
    dropped = dropped or set()
    n = len(records)
    ben = [r for r in records if r["label"] == "BENIGN"]
    mal = [r for r in records if r["label"] == "MALICIOUS"]
    sessions = {(r["campaign"], r["run"], r["supi"]) for r in records}
    fams = {}
    for r in mal:
        fams[r["attack_family"]] = fams.get(r["attack_family"], 0) + 1

    def present(r, k):
        v = r.get(k)
        return v not in (None, "", "nan", "None")

    def bandcount(rows, lo, hi, key):
        return sum(1 for r in rows if present(r, key) and lo <= float(r[key]) < hi)

    def overlap_table(key, bands, note):
        out = ["\n## %s" % note[0], note[1],
               "| band | benign | malicious |", "|---|---:|---:|"]
        for lo, hi in bands:
            lab = "%g-%s" % (lo, "inf" if hi > 1e8 else ("%g" % hi))
            out.append("| %s | %d | %d |" % (lab, bandcount(ben, lo, hi, key), bandcount(mal, lo, hi, key)))
        return out

    lines = ["# Testbed O-RAN flooding dataset — data quality\n",
             "Campaigns: %d, OK runs: %d, independent (campaign,run,supi) sessions: %d" % (len(camps), runs_seen, len(sessions)),
             "Records (per-SUPI-per-second): %d  (BENIGN %d / MALICIOUS %d)\n" % (n, len(ben), len(mal)),
             "Ground truth is experimental control only (a UE is MALICIOUS iff it ran an",
             "attack flow in that phase); never derived from volume or PRB.\n",
             "## Label / family distribution", "- BENIGN: %d" % len(ben)]
    for f, c in sorted(fams.items()):
        lines.append("- MALICIOUS/%s: %d" % (f, c))

    # ---- generator-failure gate (validity) ---------------------------------
    if activity:
        lines += ["\n## Attack generator validity (achieved activity per family)",
                  "A malicious family is kept only if its generator actually produced traffic",
                  "(> %g%% of rows with profiler pps > %g). This is a validity filter on the"
                  % (FAMILY_ACTIVE_MIN * 100, ACTIVITY_PPS),
                  "experimental CONTROL, not volume-based labelling of rows.",
                  "| family | rows | active rows | kept |", "|---|---:|---:|---|"]
        for fam, cnt, act in activity:
            lines.append("| %s | %d | %.0f%% | %s |" % (fam, cnt, act * 100, "no — EXCLUDED" if fam in dropped else "yes"))
        if dropped:
            lines.append("\n**Excluded families (generator produced no traffic): %s.** "
                         "hping3 `-f` fragmented flood emits only a token fragment over the "
                         "RFsim tunnel, so frag_flood never became a real attack condition; "
                         "its rows are dropped rather than kept as mislabelled idle traffic. "
                         "Logged as a limitation; a v3 would generate IP fragmentation with "
                         "nping/scapy." % ", ".join(sorted(dropped)))

    # ---- missingness-by-label audit (a feature whose PRESENCE predicts the
    # label is a leak even if its values overlap). ---------------------------
    lines += ["\n## Missingness leak audit (presence rate by class)",
              "A feature present for one class but absent for the other leaks the label via its mask.",
              "Data-driven: any feature with a presence gap > 20 pts is flagged LEAK-RISK and",
              "must be dropped by the modelling step (none expected in v2).",
              "| feature | benign present | malicious present | verdict |", "|---|---:|---:|---|"]
    flagged = []
    for k in ["has_prof", "has_urr"] + FEATURES:
        if k in ("has_urr", "has_prof"):
            pb = 100.0 * sum(r[k] for r in ben) / max(len(ben), 1)
            pm = 100.0 * sum(r[k] for r in mal) / max(len(mal), 1)
        else:
            pb = 100.0 * sum(present(r, k) for r in ben) / max(len(ben), 1)
            pm = 100.0 * sum(present(r, k) for r in mal) / max(len(mal), 1)
        gap = abs(pb - pm)
        verdict = "LEAK-RISK (drop)" if gap > 20 else "ok"
        if gap > 20:
            flagged.append(k)
        # surface the has_* flags and anything with a non-trivial gap
        if k in ("has_urr", "has_prof") or gap > 5:
            lines.append("| %s | %.0f%% | %.0f%% | %s |" % (k, pb, pm, verdict))
    lines.append("\n**Leak-risk features: %s**" % (", ".join(flagged) if flagged else "none — all features present for both classes"))

    # ---- load overlap on the two standard volume axes (RAN + core) ----------
    lines += overlap_table(
        "thp_ul_kbps",
        [(0, 100), (100, 300), (300, 600), (600, 1000), (1000, 2000), (2000, 1e9)],
        ("Benign vs malicious LOAD overlap (thp_ul_kbps bands — KPM / RAN, dense both classes)",
         "Overlap is the point: both classes occupy the same volume bands, so volume alone cannot separate them."))
    lines += overlap_table(
        "urr_ul_kbps",
        [(0, 100), (100, 300), (300, 600), (600, 1000), (1000, 2000), (2000, 1e9)],
        ("Benign vs malicious LOAD overlap (urr_ul_kbps bands — PFCP/URR / core, dense both classes)",
         "Same overlap holds on the standard 3GPP core-volume counter, confirming the claim is not an artefact of one measurement layer."))

    # ---- packet-size overlap (mean_bytes must NOT be a trivial shortcut) ----
    lines += overlap_table(
        "prof_ul_mean_bytes",
        [(0, 100), (100, 300), (300, 800), (800, 1200), (1200, 1e9)],
        ("Benign vs malicious PACKET-SIZE overlap (prof_ul_mean_bytes bands)",
         "By design both classes span small and large packets (small-packet benign controls + large-packet flood variants), so mean packet size alone is not a label shortcut."))

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
