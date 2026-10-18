"""Campaign report: one row per run (runs.csv), mean ± sd per variant
(summary.csv, summary.md) and a console table."""
import csv
import json
import statistics

import metrics as M


def _fmt(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return "%.3g" % v if abs(v) < 1000 else "%.0f" % v
    return str(v)


def _agg(vals):
    v = [x for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not v:
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None}
    return {"n": len(v), "mean": statistics.mean(v), "sd": statistics.stdev(v) if len(v) > 1 else 0.0, "min": min(v), "max": max(v)}


def flatten(m):
    row = dict(m["headline"])
    for ph, pm in m["phases"].items():
        for ue, e in pm.items():
            if not isinstance(e, dict):
                continue
            for k in ("offered_ul_mbps", "delivered_ul_mbps", "dn_ul_mbps", "loss_ul_pct", "kpm_ul_kbps", "urr_ul_kbps", "kpm_prb_ul_pct",
                      "offered_dl_mbps", "delivered_dl_mbps", "dn_dl_mbps", "loss_dl_pct", "kpm_dl_kbps", "urr_dl_kbps", "kpm_prb_dl_pct",
                      "max_level"):
                if e.get(k) is not None:
                    row["%s.%s.%s" % (ph, ue, k)] = e[k]
    return row


def build(campaign_dir, recompute=True):
    rows = []
    for run_dir in sorted((campaign_dir / "runs").glob("*/rep-*")):
        meta = run_dir / "run.json"
        if not meta.exists():
            continue
        run = json.loads(meta.read_text())
        if run.get("status") != "ok":
            rows.append({"variant": run.get("variant"), "rep": run.get("rep"), "status": run.get("status")})
            continue
        m = M.compute(run_dir) if recompute or not (run_dir / "metrics.json").exists() else json.loads((run_dir / "metrics.json").read_text())
        r = {"variant": run["variant"], "rep": run["rep"], "status": "ok"}
        r.update(flatten(m))
        rows.append(r)
    keys = ["variant", "rep", "status"] + sorted({k for r in rows for k in r} - {"variant", "rep", "status"})
    with (campaign_dir / "runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    variants = list(dict.fromkeys(r["variant"] for r in rows))
    ok = [r for r in rows if r.get("status") == "ok"]
    metrics_keys = [k for k in keys[3:]]
    summary = {v: {k: _agg([r.get(k) for r in ok if r["variant"] == v]) for k in metrics_keys} for v in variants}
    with (campaign_dir / "summary.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", *["%s_%s" % (v, s) for v in variants for s in ("n", "mean", "sd", "min", "max")]])
        for k in metrics_keys:
            w.writerow([k, *[summary[v][k][s] for v in variants for s in ("n", "mean", "sd", "min", "max")]])

    camp = json.loads((campaign_dir / "campaign.json").read_text())
    headline = camp["scenario"].get("report") or [k for k in metrics_keys if "." not in k]
    lines = ["# %s — %s" % (camp["scenario"]["name"], camp["id"]), "", camp["scenario"].get("description", "").strip(), "",
             "Runs: " + ", ".join("%s %d/%d ok" % (v, sum(1 for r in ok if r["variant"] == v), sum(1 for r in rows if r["variant"] == v))
                                  for v in variants), "",
             "| metric | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for k in headline:
        cells = []
        for v in variants:
            a = summary[v].get(k)
            cells.append("–" if not a or a["n"] == 0 else ("%s ± %s (n=%d)" % (_fmt(a["mean"]), _fmt(a["sd"]), a["n"])))
        lines.append("| %s | %s |" % (k, " | ".join(cells)))
    phases = [p["name"] for p in camp["scenario"]["phases"]]
    ues = list(camp["scenario"]["ues"])
    lines += ["", "Per phase (mean over runs), direction with offered traffic: offered / delivered / at DN (Mbit/s) · "
              "KPM / URR (kbit/s) · max level", ""]
    lines += ["| variant | phase | " + " | ".join(ues) + " |", "|---|---|" + "---|" * len(ues)]
    for v in variants:
        for ph in phases:
            cells = []
            for ue in ues:
                g = lambda k: summary[v].get("%s.%s.%s" % (ph, ue, k), {}).get("mean")
                d = "dl" if (g("offered_dl_mbps") or 0) > 0 and not (g("offered_ul_mbps") or 0) else "ul"
                cells.append("%s %s / %s / %s · %s / %s · L%s" % ((d.upper(),) + tuple(_fmt(g(k % d)) for k in
                             ("offered_%s_mbps", "delivered_%s_mbps", "dn_%s_mbps", "kpm_%s_kbps", "urr_%s_kbps")) + (_fmt(g("max_level")),)))
            lines.append("| %s | %s | %s |" % (v, ph, " | ".join(cells)))
    text = "\n".join(lines) + "\n"
    (campaign_dir / "summary.md").write_text(text)
    return text
