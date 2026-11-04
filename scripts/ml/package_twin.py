#!/usr/bin/env python3
"""Local package of the twin dataset: rows, per-window delivery, the raw files the builder reads for every kept run, manifest, datasheet, reports. Not uploaded. Usage: package_twin.py"""
import csv, gzip, json, pathlib, shutil, tarfile
ROOT = pathlib.Path(__file__).resolve().parents[2]
D = ROOT / "research/datasets/oran_flooding_twin"
kept = {}
for x in map(json.loads, open(D / "manifest/campaign_log.jsonl")):
    if x["event"] == "kept":
        kept[x["id"]] = x
rows = []
for k, v in sorted(kept.items()):
    run = pathlib.Path(v["run"])
    mac = {}
    for l in open(run / "ran/mac_stats.csv").read().splitlines()[1:]:
        f = l.split(","); mac.setdefault(f[2], []).append((float(f[0]), int(f[4]), int(f[5])))
    fl = json.loads((run / "traffic/flows.json").read_text())
    for f in fl:
        m = f.get("v4_meta") or {}
        if m.get("model") != "real_window":
            continue
        t = [r for r in mac.get(f["ue"], []) if f["replay_start_at"] <= r[0] <= f["replay_start_at"] + 76]
        over = any((g.get("v4_meta") or {}).get("model") == "flood_overlay" and g["phase"] == f["phase"] and g["ue"] == f["ue"] for g in fl)
        ul, dl = m["target_mean_bytes_s"] * 75, m["target_dl_mean_bytes_s"] * 75
        rows.append(dict(run=k, phase=f["phase"], ue=f["ue"], band=m["band"], window_index=m["window"]["index"], cell=m["window"]["cell"], has_other_flow=int(over), ul_target=round(ul), dl_target=round(dl), mac_ul=t[-1][1] - t[0][1] if t else "", mac_dl=t[-1][2] - t[0][2] if t else "", dl_ratio=round((t[-1][2] - t[0][2]) / dl, 3) if t and dl >= 5000 else ""))
with open(D / "windows.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, rows[0].keys()); w.writeheader(); w.writerows(rows)
low = [r for r in rows if r["dl_ratio"] != "" and r["dl_ratio"] < .7]
print("windows", len(rows), "DL under 70 % of the plan:", len(low))
tar = ROOT / "research/datasets/oran_flooding_twin_package.tar.gz"
with tarfile.open(tar, "w:gz") as t:
    for n in ("rows.parquet", "windows.csv", "DATASHEET.md", "manifest/design.json", "manifest/campaign_log.jsonl"):
        t.add(D / n, arcname="oran_flooding_twin/" + n)
    for k, v in sorted(kept.items()):
        run = pathlib.Path(v["run"])
        for n in ("raw/kpm.jsonl", "core/core_received.jsonl", "run.json", "traffic/flows.json", "ran/mac_stats.csv"):
            if (run / n).exists():
                t.add(run / n, arcname="oran_flooding_twin/raw/%s/%s" % (k, n))
    for n in ("out_campaign_report.txt", "out_campaign_validate.json", "out_heldout_check.txt", "out_heldout_gate.txt", "out_tamper_eval.txt", "out_tamper_cue_matched.txt", "out_label_lag.txt"):
        t.add(ROOT / "research/twinning" / n, arcname="oran_flooding_twin/reports/" + n)
print(tar.name, round(tar.stat().st_size / 2**20), "MiB")
