#!/usr/bin/env python3
"""UE identity check (2026-11-10): per run, KPM rows (xApp raw tap, SUPI from AMF UE NGAP ID) vs UPF profile rows (SUPI + ran_identity from the AMF UE table):
SUPIs within run.json, one AMF ID never on two SUPIs, KPM and profile agree on the AMF ID of each SUPI. Usage: check_ue_identity.py (from repo root)"""
import json, pathlib, sys, collections
root = pathlib.Path("artifacts/experiments")
stats = collections.Counter(); bad = []
for k in sorted(root.glob("*/runs/*/*/raw/kpm.jsonl")):
    r = k.parent.parent
    if not (r / "run.json").exists() or not (r / "core/core_received.jsonl").exists():
        stats["missing_files"] += 1; continue
    m = json.loads((r / "run.json").read_text())
    want = {v.get("supi") for v in (m.get("ues") or {}).values()}
    ks = collections.defaultdict(set); ka = collections.defaultdict(set); nk = 0
    for l in open(k):
        try: o = json.loads(l)
        except Exception: continue
        if "supi" not in o: continue
        nk += 1; ks[o["supi"]].add(o.get("amf_ue_ngap_id")); ka[o.get("amf_ue_ngap_id")].add(o["supi"])
    ps = collections.defaultdict(set); np_ = 0; nori = 0
    for l in open(r / "core/core_received.jsonl"):
        if '"profile"' not in l: continue
        try: o = json.loads(l)
        except Exception: continue
        rep = o.get("report") or {}
        if o.get("kind") != "profile" or "supi" not in rep: continue
        np_ += 1
        ri = rep.get("ran_identity")
        if not ri: nori += 1; continue
        ps[rep["supi"]].add(ri.get("amf_ue_ngap_id"))
    stats["runs"] += 1; stats["kpm_rows"] += nk; stats["prof_rows"] += np_; stats["prof_no_ran_identity"] += nori
    issues = []
    if set(ks) - want: issues.append("kpm supi not in run.json")
    if any(len(v) > 1 for v in ka.values()): issues.append("one amf id -> 2 supi in KPM")
    for s in ks:
        if ps.get(s) and not (ks[s] & ps[s]): issues.append("kpm/prof amf mismatch " + s)
    if any(len(v) > 1 for v in ks.values()): stats["runs_reattach"] += 1
    if issues: bad.append((str(r), issues)); stats["runs_with_issue"] += 1
print(dict(stats))
for b in bad[:15]: print(b)
