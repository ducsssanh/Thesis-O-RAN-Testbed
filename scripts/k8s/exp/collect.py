"""Export of every record of one run, cut by its time window from the
continuous files in the pods (KPM, URR at each hop, defense, RAN control,
UPF audit), plus UPF/xApp snapshots and the NF logs."""
import datetime
import gzip
import json
import re

from lab import UES, ex, kubectl, staged

NTP_UNIX = 2208988800
TAIL_BYTES = 60_000_000  # recent part of a continuous file; a run is minutes long


def iso_to_unix(s):
    s = s.rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = head + "." + frac[:6]
    return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp()


def tail(ns, deploy, container, path, nbytes=TAIL_BYTES):
    raw = ex(ns, deploy, container, "tail", "-c", str(nbytes), path, timeout=180, check=False)
    lines = raw.splitlines()
    return lines[1:] if len(raw) >= nbytes else lines  # first line may be cut


def head1(ns, deploy, container, path):
    return ex(ns, deploy, container, "head", "-1", path, check=False).rstrip("\n")


def cut_jsonl(lines, when, t0, t1):
    out = []
    for line in lines:
        try:
            t = when(json.loads(line))
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        if t is not None and t0 <= t <= t1:
            out.append(line)
    return "".join(x + "\n" for x in out)


def cut_csv(header, lines, col, t0, t1, scale=1000.0):
    names = header.split(",")
    i = names.index(col)
    out = [header]
    for line in lines:
        f = line.split(",")
        try:
            if t0 <= float(f[i]) / scale <= t1:
                out.append(line)
        except (ValueError, IndexError):
            continue
    return "\n".join(out) + "\n"


def run_dir_xapp():
    return "/artifacts/runs/%s/" % staged.run_id()


def export_ran(out, t0, t1):
    d = run_dir_xapp()
    x = ("near-rt-ric", "oai-lab-xapp", "xapp")
    h = head1(*x, d + "KPI_Metrics.csv")
    (out / "ran/kpm.csv").write_text(cut_csv(h, tail(*x, d + "KPI_Metrics.csv"), "Time (UNIX ms)", t0, t1))
    h = head1(*x, d + "KPI_Metrics_Cells.csv")
    (out / "ran/kpm_cells.csv").write_text(cut_csv(h, tail(*x, d + "KPI_Metrics_Cells.csv"), "Time (UNIX ms)", t0, t1))
    (out / "ran/rc_control.jsonl").write_text(
        cut_jsonl(tail(*x, d + "KPI_Metrics_RAN_Control.jsonl"), lambda o: o["sent_unix_ms"] / 1000, t0, t1))


def ue_rnti(ue_names):
    """{rnti hex: ue name} from the UE logs ("UE 0 RNTI 2580 stats ..."); the latest one per UE."""
    out = {}
    for n in ue_names:
        raw = kubectl("-n", "oai-ran", "logs", "deploy/" + UES[n][0], "-c", "nr-ue", "--tail=400", timeout=60, check=False)
        found = re.findall(r"UE 0 RNTI ([0-9a-f]{4}) stats", raw)
        if found:
            out[found[-1]] = n
    return out


def parse_mac_stats(raw, rnti_ue):
    """Raw nrMAC_stats.log samples (traffic.MacStats) -> CSV with one row per UE per sample; the counters
    are cumulative and restart at 0 when a UE gets a new RNTI. *_sdu_bytes = data bearers (LCID >= 3),
    the bytes of the MAC SDUs: no padding, BSR or retransmission. *_grants = first HARQ transmissions,
    which include the empty grants the gNB gives an idle UE."""
    rows, now, ues = ["stat_unix,rnti,ue,cu_ue_id,ul_sdu_bytes,dl_sdu_bytes,ul_grants,dl_grants"], None, {}

    def flush():
        for r, u in sorted(ues.items()):
            if {"ul", "dl", "ug", "dg"} <= set(u):
                rows.append("%s,%s,%s,%s,%d,%d,%d,%d" % (now, r, rnti_ue.get(r, ""), u.get("cu", ""), u["ul"], u["dl"], u["ug"], u["dg"]))

    for line in raw.splitlines():
        if line.startswith("@"):
            flush()
            now, ues = line[1:].strip(), {}
        elif m := re.match(r"UE RNTI ([0-9a-f]+) CU-UE-ID (\S+)", line):
            ues.setdefault(m[1], {})["cu"] = m[2]
        elif m := re.match(r"UE ([0-9a-f]+): ulsch_rounds (\d+)", line):
            ues.setdefault(m[1], {})["ug"] = int(m[2])
        elif m := re.match(r"UE ([0-9a-f]+): dlsch_rounds (\d+)", line):
            ues.setdefault(m[1], {})["dg"] = int(m[2])
        elif m := re.match(r"UE ([0-9a-f]+): LCID (\d+): TX +(\d+) RX +(\d+) bytes", line):
            u = ues.setdefault(m[1], {})
            u.setdefault("dl", 0)
            u.setdefault("ul", 0)
            if int(m[2]) >= 3:
                u["dl"] += int(m[3])
                u["ul"] += int(m[4])
    flush()
    return "\n".join(rows) + "\n"


def export_defense(out, t0, t1):
    d = run_dir_xapp()
    x = ("near-rt-ric", "oai-lab-xapp", "xapp")
    (out / "defense/events.jsonl").write_text(cut_jsonl(tail(*x, d + "KPI_Metrics_Defense.jsonl"), lambda o: o["at_ms"] / 1000, t0, t1))
    (out / "defense/features.jsonl").write_text(cut_jsonl(tail(*x, d + "KPI_Metrics_Features.jsonl"), lambda o: o["at_ms"] / 1000, t0, t1))
    # v4: raw KPM (one record per indication, source_ts + arrival_ts) for the causal offline build
    (out / "raw").mkdir(exist_ok=True)
    (out / "raw/kpm.jsonl").write_text(cut_jsonl(tail(*x, d + "KPI_Metrics_RawKpm.jsonl"), lambda o: o["arrival_ts"], t0, t1))
    # v5 live: KPM tamper ground truth (xApp) and the model sidecar's per-step decisions
    (out / "defense/tamper.jsonl").write_text(cut_jsonl(tail(*x, d + "KPI_Metrics_Tamper.jsonl"), lambda o: o["ts"], t0, t1))
    # embedded classifier: per UE and second the 25 inputs, logit, alarms, label and level (classifier.kind xgb)
    (out / "defense/clf.jsonl").write_text(cut_jsonl(tail(*x, d + "KPI_Metrics_Clf.jsonl"), lambda o: o["scored_ms"] / 1000, t0, t1))
    (out / "defense/sidecar.jsonl").write_text(cut_jsonl(
        tail("near-rt-ric", "oai-lab-xapp", "sidecar", d + "KPI_Metrics_Sidecar.jsonl"), lambda o: o["ts"], t0, t1))
    q = ("import sqlite3,json,sys\nc=sqlite3.connect('file:/urr-state/defense.db?mode=ro',uri=True)\n"
         "print(json.dumps({t:[list(r) for r in c.execute('SELECT * FROM '+t+' WHERE at>=? AND at<=?',(sys.argv[1],sys.argv[2]))]"
         " for t in ('evidence','actions')}))\n")
    iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    (out / "defense/db_rows.json").write_text(ex(*x, "python3", "-c", q, iso(t0), iso(t1), check=False) or "{}")


def export_core(out, t0, t1):
    d = run_dir_xapp()
    (out / "core/urr_received.jsonl").write_text(cut_jsonl(
        tail("near-rt-ric", "oai-lab-xapp", "xapp", d + "urr-received.jsonl"), lambda o: iso_to_unix(o["report"]["observed_at"]), t0, t1))
    # closed-loop records (docs/CLOSED-LOOP-FRAMEWORK.md 3): xApp and producer side
    (out / "core/core_received.jsonl").write_text(cut_jsonl(
        tail("near-rt-ric", "oai-lab-xapp", "xapp", d + "core-received.jsonl"), lambda o: o["received_unix_ms"] / 1000, t0, t1))
    p = ("non-rt-ric", "urr-ei-producer", "artifacts")
    (out / "core/producer_normalized.jsonl").write_text(cut_jsonl(
        tail(*p, "/var/lib/urr-ei/normalized.jsonl"), lambda o: iso_to_unix(o["observed_at"]), t0, t1))
    (out / "core/producer_envelopes.jsonl").write_text(cut_jsonl(
        tail(*p, "/var/lib/urr-ei/envelopes.jsonl"), lambda o: iso_to_unix(o["observed_at"]), t0, t1))
    (out / "core/producer_smf_raw.jsonl").write_text(cut_jsonl(
        tail(*p, "/var/lib/urr-ei/smf-raw.jsonl"), lambda o: int(o["eventNotifs"][0]["timeStamp"]) - NTP_UNIX, t0, t1))
    a = ("near-rt-ric", "a1-ei-adapter", "artifacts")
    (out / "core/adapter_delivery.jsonl").write_text(cut_jsonl(
        tail(*a, "/var/lib/a1-ei/delivery-status.jsonl"), lambda o: iso_to_unix(o["last_attempt"]), t0, t1))
    (out / "core/upf_audit.jsonl").write_text(cut_jsonl(
        tail("oai-core", "oai-upf", "upf", "/upf-sec/audit.jsonl", 5_000_000), lambda o: o["ts_ms"] / 1000, t0, t1))


def export_logs(out, t0, ue_names):
    since = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    targets = [("near-rt-ric", "oai-lab-xapp", "xapp", "xapp"), ("near-rt-ric", "oai-flexric", None, "flexric"),
               ("oai-ran", "oai-gnb", "gnb", "gnb"), ("oai-core", "oai-upf", "upf", "upf"), ("oai-core", "oai-smf", "smf", "smf"),
               ("oai-core", "oai-amf", "amf", "amf")]
    targets += [("oai-ran", UES[n][0], "nr-ue", n) for n in ue_names]
    for ns, deploy, container, name in targets:
        args = ["-n", ns, "logs", "deploy/" + deploy, "--timestamps", "--since-time=" + since]
        if container:
            args += ["-c", container]
        raw = kubectl(*args, timeout=180, check=False)
        with gzip.open(out / ("logs/%s.log.gz" % name), "wt") as f:
            f.write(raw)


def snapshot(out, label):
    """Defense state, UPF policies/stats/sessions/info at the start or end."""
    from lab import defense_state, upf
    snap = {"defense_state": defense_state()}
    for path in ("/v1/info", "/v1/ues", "/v1/stats", "/v1/sessions"):
        snap["upf" + path.replace("/", "_")] = upf("GET", path)[1]
    (out / ("meta/snapshot_%s.json" % label)).write_text(json.dumps(snap, indent=1) + "\n")
    return snap


def link_stats():
    def one(ns, deploy, container, iface):
        try:
            item = json.loads(ex(ns, deploy, container, "ip", "-j", "-s", "link", "show", "dev", iface))[0]
            return {"rx": item.get("stats64", {}).get("rx"), "tx": item.get("stats64", {}).get("tx")}
        except Exception:
            return None
    return {"upf_n3": one("oai-core", "oai-upf", "upf", "n3"), "upf_n6": one("oai-core", "oai-upf", "upf", "n6"),
            "dn_n6": one("oai-core", "oai-lab-dn", "dn", "n6")}
