#!/usr/bin/env python3
"""Offline acceptance gates for real receiver/KPM/PFCP artifacts; no mock PASS."""
import csv, datetime, json, pathlib, subprocess, sys


def fields(pcap, expression, names):
    cmd = [
        "tshark",
        "-r",
        str(pcap),
        "-Y",
        expression,
        "-T",
        "fields",
        "-E",
        "separator=|",
        "-E",
        "occurrence=f",
    ]
    for name in names:
        cmd += ["-e", name]
    p = subprocess.run(cmd, text=True, capture_output=True, check=True)
    return [r.split("|") for r in p.stdout.splitlines() if r]


def iso(value):
    try:
        return datetime.datetime.fromtimestamp(
            float(value), datetime.timezone.utc
        ).isoformat()
    except ValueError:
        return value


def table(path, header, rows):
    with path.open("w") as f:
        w = csv.writer(f)
        w.writerow(header.split(","))
        w.writerows(rows)


def kpm_gate(path):
    with path.open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("No KPM samples")
    # Keep the research CSV schema intact, including dynamic measurement columns.
    node = next((k for k in rows[0] if k and k.startswith("E2 Node ID")), None)
    ue = next((k for k in rows[0] if k and k.startswith("UE ID")), None)
    if (
        not node
        or not ue
        or not any(
            r.get(node) and r.get(ue) and r[ue] not in ("0", "unknown") for r in rows
        )
    ):
        raise ValueError("KPM missing node/UE identity")
    ids = {r[node] for r in rows if r.get(node)}
    if len(ids) != 1:
        raise ValueError("Expected one E2 node")
    return {
        "samples": len(rows),
        "nodes": sorted(ids),
        "ueIds": sorted({r[ue] for r in rows if r.get(ue)}),
    }


def pfcp_gate(config, reports, transactions):
    if not config:
        raise ValueError(
            "Missing Create URR (volume threshold or measurement period) in this PCAP; inspect capture lifecycle and SMF configuration"
        )
    # URR comes from smf.upfs[].config.urr: a volume threshold and/or a
    # periodic trigger (column 10, seconds) must be configured
    thresholds = [int(r[i]) for r in config for i in (7, 8, 9) if r[i]]
    periods = [int(r[10]) for r in config if len(r) > 10 and r[10]]
    if not thresholds and not periods:
        raise ValueError("Missing actual URR threshold or measurement period")
    if not reports:
        raise ValueError(
            "Missing Usage Report. Actual threshold(s): "
            + str(thresholds)
            + " bytes, period(s): "
            + str(periods)
            + " s; increase duration beyond measured threshold and rerun; no PASS"
        )
    requests = [r for r in transactions if r[3] == "56"]
    accepted = [r for r in transactions if r[3] == "57" and r[5] == "1"]
    if not requests or any(
        not any(
            q[4] == r[4]
            and q[1] == r[2]
            and q[2] == r[1]
            and float(q[0]) >= float(r[0])
            for q in accepted
        )
        for r in requests
    ):
        raise ValueError("Usage Report has no matching accepted SMF response")
    ul = sum(int(r[9] or 0) for r in reports)
    dl = sum(int(r[10] or 0) for r in reports)
    if ul <= 0 or dl <= 0:
        raise ValueError("Usage Reports do not cover both UL and DL")
    for r in reports:
        if r[8] and r[9] and r[10] and int(r[8]) != int(r[9]) + int(r[10]):
            raise ValueError("Inconsistent total/UL/DL accounting in Usage Report")
    return {
        "thresholdBytes": thresholds,
        "measurementPeriodS": periods,
        "reportCount": len(reports),
        "ulBytes": ul,
        "dlBytes": dl,
        "acceptedResponses": len(accepted),
    }


def analyze(out):
    pcap = out / "pfcp.pcap"
    with (out / "phases.csv").open() as f:
        phases = list(csv.DictReader(f))
    if {p["direction"] for p in phases if p["status"] == "ok"} != {"ul", "dl"}:
        raise ValueError("Missing completed UL/DL traffic phases")
    traffic_start = min(int(p["start_unix_ms"]) for p in phases) / 1000
    traffic_end = max(int(p["end_unix_ms"]) for p in phases) / 1000
    msgs = fields(
        pcap,
        "pfcp",
        ["frame.time_epoch", "ip.src", "ip.dst", "pfcp.msg_type", "pfcp.seid"],
    )
    if not msgs or min(float(r[0]) for r in msgs) > traffic_start or max(float(r[0]) for r in msgs) < traffic_end - 10:
        raise ValueError("PFCP capture does not span this UL/DL experiment; start a fresh run and capture before UE")
    table(
        out / "pfcp_messages.csv",
        "frame_time_iso,frame_time_epoch_seconds,ip_src,ip_dst,pfcp_message_type,pfcp_seid",
        [[iso(r[0]), *r] for r in msgs],
    )
    cfg = fields(
        pcap,
        "pfcp.msg_type == 50 && pfcp.ie_type == 6 && (pfcp.volume_threshold.tovol || pfcp.volume_threshold.ulvol || pfcp.volume_threshold.dlvol || pfcp.measurement_period)",
        [
            "frame.time_epoch",
            "pfcp.msg_type",
            "pfcp.seid",
            "pfcp.urr_id",
            "pfcp.measurement_method_flags.volume",
            "pfcp.reporting_triggers_flags.volth",
            "pfcp.volume_threshold.tovol",
            "pfcp.volume_threshold.ulvol",
            "pfcp.volume_threshold.dlvol",
            "pfcp.measurement_period",
        ],
    )
    cfg = [[iso(r[0]), *r] for r in cfg]
    table(
        out / "pfcp_urr_config.csv",
        "frame_time_iso,frame_time_epoch_seconds,pfcp_message_type,pfcp_seid,urr_id,measurement_method_volume,trigger_volume_threshold,volume_threshold_bytes,uplink_volume_threshold_bytes,downlink_volume_threshold_bytes,measurement_period_seconds",
        cfg,
    )
    reports = fields(
        pcap,
        "pfcp.msg_type == 56 && pfcp.volume_measurement.tovol",
        [
            "frame.time_epoch",
            "pfcp.time_of_first_packet",
            "pfcp.time_of_last_packet",
            "ip.src",
            "ip.dst",
            "pfcp.msg_type",
            "pfcp.seid",
            "pfcp.urr_id",
            "pfcp.volume_measurement.tovol",
            "pfcp.volume_measurement.ulvol",
            "pfcp.volume_measurement.dlvol",
            "pfcp.usage_report_trigger_flags.volth",
            "pfcp.usage_report_trigger_flags.perio",
            "pfcp.usage_report_trigger.term",
        ],
    )
    reports = [r for r in reports if traffic_start <= float(r[0]) <= traffic_end + 15]
    table(
        out / "pfcp_urr.csv",
        "frame_time_iso,frame_time_epoch_seconds,first_packet_time_iso,last_packet_time_iso,ip_src,ip_dst,pfcp_message_type,pfcp_seid,urr_id,total_volume_bytes,uplink_volume_bytes,downlink_volume_bytes,trigger_volume_threshold,trigger_periodic,trigger_termination",
        [[iso(r[0]), *r] for r in reports],
    )
    transactions = fields(
        pcap,
        "pfcp.msg_type == 56 || pfcp.msg_type == 57",
        [
            "frame.time_epoch",
            "ip.src",
            "ip.dst",
            "pfcp.msg_type",
            "pfcp.seqno",
            "pfcp.cause",
        ],
    )
    table(
        out / "pfcp_report_responses.csv",
        "epoch,src,dst,type,sequence,cause",
        transactions,
    )
    result = {
        "status": "PASS",
        "scope": "one experiment; restart and lifecycle acceptance still required",
        "pfcp": pfcp_gate(cfg, reports, transactions),
        "kpm": kpm_gate(out / "KPI_Metrics.csv"),
    }
    if not fields(pcap, "pfcp.msg_type == 51 && pfcp.cause == 1", ["pfcp.seqno"]):
        raise ValueError("Missing accepted PFCP session establishment")
    for direction in ["ul", "dl"]:
        result[direction] = json.loads(
            (out / (direction + "-summary.json")).read_text()
        )
        if result[direction]["bytes"] <= 0 or result[direction]["lostPercent"] >= 100:
            raise ValueError("No received " + direction + " traffic")
    attach = json.loads((out / "xdp.json").read_text())
    entries = [
        e
        for item in (attach if isinstance(attach, list) else [attach])
        for e in item.get("xdp", [])
    ]
    for iface in ["n3", "n6"]:
        if not any(
            e.get("devname") == iface
            and e.get("mode") == "generic"
            and e.get("id", 0) > 0
            for e in entries
        ):
            raise ValueError("Missing SKB evidence on " + iface)
    return result


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1])
    status = 0
    try:
        result = analyze(out)
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        result = {"status": "FAIL", "reason": str(e)}
        status = 1
    (out / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    sys.exit(status)
