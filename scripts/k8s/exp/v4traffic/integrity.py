#!/usr/bin/env python3
"""Run-integrity guards for v4 runs (shared by campaign.py, qa_v4.py and the retro audit).

A run is INTEGRAL only if all four hold:
  1. every phase lasted within +-DUR_TOL of its plan (idle=15 s, pNN=duration, gapNN=gap),
  2. no KPM / URR / profiler gap > GAP_S inside any phase (per SUPI, edges included),
  3. the host did not suspend/resume (kernel `PM: suspend entry/exit`) during the run window,
  4. every generator flow logged >= ROWS_MIN x planned-duration per-second rows
     (traffic/<phase>_<ue>_<dir>.csv) — catches a backend that stalls mid-phase
     (e.g. pre-fix iperf2 waiting ~3 s per block for a silent victim's FIN ack).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/integrity.py RUN_DIR [RUN_DIR ...]
"""
import csv, json, pathlib, re, subprocess, sys, datetime

ROOT = pathlib.Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "research/datasets/oran_flooding_v4/manifest/design.json"
DUR_TOL = 0.20
GAP_S = 3.0
ROWS_MIN = 0.90
_FLOW_CSV = re.compile(r"^(p\d\d_.+)_(ue\d+)_(ul|dl)\.csv$")


def planned(rep, manifest=MANIFEST):
    """{phase name: planned seconds} for manifest run `rep` (1-based), as scn_for_run builds it."""
    run = json.loads(pathlib.Path(manifest).read_text())["runs"][rep - 1]
    d = {"idle": 15}
    for j, ph in enumerate(run):
        d["p%02d_%s" % (j, ph["family"])] = ph["duration"]
        d["gap%02d" % j] = ph.get("gap", 10)
    return d


def _jsonl(p):
    try:
        with open(p) as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass
    except OSError:
        return


def _iso(s):
    s = s.rstrip("Z")
    if "." in s:
        head, frac = s.split(".")
        s = head + "." + frac[:6]
    return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp()


def streams(rd):
    """{stream: {supi: sorted source_ts}} from the run's raw files."""
    out = {"kpm": {}, "urr": {}, "prof": {}}
    for r in _jsonl(rd / "raw/kpm.jsonl"):
        if "supi" in r and "source_ts" in r:
            out["kpm"].setdefault(r["supi"], []).append(r["source_ts"])
    for o in _jsonl(rd / "core/urr_received.jsonl"):
        r = o.get("report") or {}
        if "supi" in r and "observed_at" in r:
            out["urr"].setdefault(r["supi"], []).append(_iso(r["observed_at"]))
    for o in _jsonl(rd / "core/core_received.jsonl"):
        r = o.get("report") or {}
        if o.get("kind") == "profile" and "supi" in r and "observed_at" in r:
            out["prof"].setdefault(r["supi"], []).append(_iso(r["observed_at"]))
    return {k: {s: sorted(v) for s, v in d.items()} for k, d in out.items()}


def flow_rows(rd, plan):
    """[(csv name, phase, rows, planned s)] for every generator flow CSV of the run. Only rows
    with a known sent volume count (an iperf block that timed out logs an empty `bytes`)."""
    out = []
    for f in sorted((pathlib.Path(rd) / "traffic").glob("p*_ue*_*.csv")):
        m = _FLOW_CSV.match(f.name)
        if not m or m.group(1) not in plan:
            continue
        with open(f, newline="") as fh:
            n = sum(1 for r in csv.DictReader(fh) if (r.get("bytes") or "").strip())
        out.append((f.name, m.group(1), n, plan[m.group(1)]))
    return out


def suspend_intervals(t0, t1):
    """Kernel suspend intervals [(entry, exit)] touching [t0, t1]; exit=None if not yet resumed.
    Returns (intervals, error)."""
    since = datetime.datetime.fromtimestamp(t0 - 6 * 3600).strftime("%Y-%m-%d %H:%M:%S")
    try:
        r = subprocess.run(["journalctl", "-k", "--no-pager", "-q", "-o", "short-unix", "--since", since,
                            "-g", "PM: suspend (entry|exit)"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], "journalctl failed: %s" % e
    if r.returncode not in (0, 1):                                  # 1 = no match
        return [], "journalctl rc=%d: %s" % (r.returncode, r.stderr.strip()[:120])
    ev, cur = [], None
    for line in r.stdout.splitlines():
        try:
            ts = float(line.split()[0])
        except (ValueError, IndexError):
            continue
        if "suspend entry" in line:
            cur = ts
        elif "suspend exit" in line and cur is not None:
            ev.append((cur, ts))
            cur = None
    if cur is not None:
        ev.append((cur, None))
    return [(a, b) for a, b in ev if a <= t1 and (b is None or b >= t0)], None


def check_run(rd, rep=None, manifest=MANIFEST):
    """Return (ok, reasons, details) for one run dir."""
    rd = pathlib.Path(rd)
    rep = rep or int(rd.name.split("-")[1])
    meta = json.loads((rd / "run.json").read_text())
    reasons, det = [], {}
    if "t_start" not in meta or "t_end" not in meta:              # run failed before any phase
        return False, ["run has no timing (status=%s)" % meta.get("status")], \
            {"max_dur_dev": None, "max_dur_dev_phase": None, "max_stream_gap_s": None, "suspend": []}
    # 1. phase duration vs plan
    plan = planned(rep, manifest)
    worst = (0.0, None)
    for ph in meta.get("phases") or []:
        n = ph["name"]
        if n not in plan:
            continue
        act = ph["t_end"] - ph["t_start"]
        dev = abs(act - plan[n]) / plan[n]
        if dev > worst[0]:
            worst = (dev, n)
        if dev > DUR_TOL:
            reasons.append("phase %s lasted %.1fs vs plan %ds (%+.0f%%)" % (n, act, plan[n], 100 * (act - plan[n]) / plan[n]))
    det["max_dur_dev"], det["max_dur_dev_phase"] = round(worst[0], 3), worst[1]
    # 2. stream gaps inside each phase
    st = streams(rd)
    supis = sorted({s for d in st.values() for s in d} & {m["supi"] for m in (meta.get("ues") or {}).values()})
    maxgap = 0.0
    for ph in meta.get("phases") or []:
        if ph["name"] not in plan:
            continue
        for name, per in st.items():
            for supi in supis:
                ts = [t for t in per.get(supi, []) if ph["t_start"] <= t <= ph["t_end"]]
                edges = [ph["t_start"]] + ts + [ph["t_end"]]
                g = max(b - a for a, b in zip(edges, edges[1:]))
                maxgap = max(maxgap, g)
                if g > GAP_S:
                    reasons.append("%s gap %.1fs in %s (%s)" % (name, g, ph["name"], supi[-4:]))
    det["max_stream_gap_s"] = round(maxgap, 2)
    # 4. per-flow row coverage (a stalled generator logs fewer 1 s rows than the phase lasted)
    worst = (None, None)
    for name, _, n, dur in flow_rows(rd, plan):
        frac = n / dur
        if worst[0] is None or frac < worst[0]:
            worst = (frac, name)
        if frac < ROWS_MIN:
            reasons.append("flow %s logged %d rows vs %ds phase (%.0f%% < %.0f%%)" % (name, n, dur, 100 * frac, 100 * ROWS_MIN))
    det["min_flow_rows_frac"] = None if worst[0] is None else round(worst[0], 3)
    det["min_flow_rows_flow"] = worst[1]
    # 3. host suspend overlapping the run
    iv, err = suspend_intervals(meta["t_start"], meta["t_end"])
    det["suspend"] = iv
    if err:
        reasons.append("suspend scan unavailable: " + err)
    for a, b in iv:
        reasons.append("host suspend %.0f..%s overlaps run" % (a, "?" if b is None else "%.0f" % b))
    return (not reasons), reasons, det


if __name__ == "__main__":
    bad = 0
    for p in sys.argv[1:]:
        ok, rs, det = check_run(p)
        bad += not ok
        print("%s ok=%d %s %s" % (p, ok, json.dumps(det), "; ".join(rs[:4])))
    sys.exit(1 if bad else 0)
