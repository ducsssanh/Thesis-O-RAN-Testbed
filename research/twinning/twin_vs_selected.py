#!/usr/bin/env python3
"""What the testbed adds, per band: each validation statistic for three sets of the SAME windows against the band's reference,
(1) the real windows as selected, (2) what the plan sends (packets + MAC overhead, so with the one-packet floor and the clip),
(3) what the gNB MAC measured. (1) shows window choice alone, (2) minus (1) the plan's floor and clip, (3) minus (2) the testbed.
Usage: twin_vs_selected.py <band> <campaign dir>...  Reads band windows from benign_windows.npz (build cells only)."""
import json, pathlib, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts/k8s/exp/v4traffic"))
import planbuilder as PB, sizes, validate_twin as V

band, dirs = sys.argv[1], sys.argv[2:]
z = np.load(pathlib.Path(__file__).parent / "benign_windows.npz")
Ur, Dr = z["ul_" + band], z["dl_" + band]
idx, Pu, Pd, Mu, Md = [], [], [], [], []
mac_bytes = lambda secs, o: [sum(x["pkts"]) + o * len(x["pkts"]) for x in secs]
for d in dirs:
    scn = json.loads((pathlib.Path(d) / "campaign.json").read_text())["scenario"]
    specs = {(p["name"], u): v["ul"] for p in scn["phases"] for u, v in p.get("flows", {}).items() if "ul" in v}
    for r in V.run_dirs([d]):
        u, dl, src, _ = V.twin_windows(r, band)
        Mu += u; Md += dl
        for fl in json.loads((r / "traffic/flows.json").read_text()):
            if fl.get("model") == "real_window":
                idx.append(fl["v4_meta"]["window"]["index"])
                plan, _ = PB.build_plan({**specs[fl["phase"], fl["ue"]], "seed": fl["v4_meta"]["seed"]}, 75, "x", "x", 1)
                Pu.append(mac_bytes(plan["seconds"], sizes.MAC_OVERHEAD["ul"])); Pd.append(mac_bytes(plan["dl_seconds"], sizes.MAC_OVERHEAD["dl"]))
idx = np.array(idx)
r, sp, ad = V.reference(V.Pool(Ur, Dr, 0, 0))
cmp_ = lambda p: V.compare(p.take(), r, band == "P4", sp, ad)
sel, plan, mac = cmp_(V.Pool(Ur[idx], Dr[idx], 0, 0)), cmp_(V.Pool(np.array(Pu), np.array(Pd), 30, 30)), cmp_(V.Pool(np.array(Mu), np.array(Md), 30, 30))
out = {k: {"selected": round(sel[k], 4), "planned": round(plan[k], 4), "measured": round(mac[k], 4)} for k in sel}
print(band, "windows", len(idx), "unique", len(set(idx.tolist())))
for k, v in out.items():
    print("  %-9s selected %.4f  planned %.4f  measured %.4f" % (k, v["selected"], v["planned"], v["measured"]))
(pathlib.Path(__file__).parent / ("out_selected_%s.json" % band)).write_text(json.dumps(out, indent=1) + "\n")
