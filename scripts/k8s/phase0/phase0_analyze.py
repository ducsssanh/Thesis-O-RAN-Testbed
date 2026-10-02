#!/usr/bin/env python3
"""Summarise a Phase 0 run: per-second iperf receiver throughput vs DROP/FORW marks."""
import csv, json, pathlib, sys

out = pathlib.Path(sys.argv[1])
t = dict(l.split("=") for l in (out / "timeline.txt").read_text().split())
t = {k: float(v) for k, v in t.items()}
drop_s, forw_s = t["drop_sent"] - t["t0"], t["forw_sent"] - t["t0"]
res = {"drop_offset_s": round(drop_s, 2), "forw_offset_s": round(forw_s, 2)}
for d in ("ul", "dl"):
    rows = [r for r in csv.reader((out / f"{d}-receiver.csv").read_text().splitlines())
            if len(r) >= 9 and "-" in r[6]]
    per = []
    for r in rows:
        a, b = (float(x) for x in r[6].split("-"))
        if b - a > 1.5:  # final summary row
            continue
        per.append((a, int(r[8])))
    phase = {"before": [], "blocked": [], "after": []}
    for a, bps in per:
        # 1 s guard around each mark: iperf interval start ~= client start (t0 + ~0.2 s)
        if a + 1 <= drop_s:
            phase["before"].append(bps)
        elif drop_s + 1 <= a and a + 1 <= forw_s:
            phase["blocked"].append(bps)
        elif a >= forw_s + 1:
            phase["after"].append(bps)
    res[d] = {k: {"n": len(v), "mean_kbps": round(sum(v) / len(v) / 1e3, 1) if v else None,
                  "max_kbps": round(max(v) / 1e3, 1) if v else None}
              for k, v in phase.items()}
    res[d]["series_kbps"] = [(round(a), round(b / 1e3)) for a, b in per]
print(json.dumps(res, indent=1))
