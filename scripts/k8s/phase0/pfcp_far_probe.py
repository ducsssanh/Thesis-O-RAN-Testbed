#!/usr/bin/env python3
"""Phase 0 probe: send a PFCP Session Modification Request (Update FAR) to the UPF.

Stdlib only, so it runs inside the SMF pod's `capture` sidecar (shares the SMF
network namespace, has an N4 address). It bypasses SMF on purpose: the goal is
to prove UPF turns PFCP Update FAR into a BPF map change, before SMF is patched.
SMF is not told about the change, so always restore the FAR to FORW afterwards.

Usage:
  pfcp_far_probe.py --upf 172.30.24.20 --src 172.30.24.10 --seid 3 \
      --far 1 --far 2 --action drop|forw|none
"""
import argparse
import json
import random
import socket
import struct
import sys
import time

PFCP_SESSION_MODIFICATION_REQUEST = 52
PFCP_SESSION_MODIFICATION_RESPONSE = 53
IE_CAUSE = 19
IE_UPDATE_FAR = 10
IE_APPLY_ACTION = 44
IE_FAR_ID = 108
ACTIONS = {"drop": 0x01, "forw": 0x02}
CAUSES = {1: "Request accepted", 64: "Request rejected", 65: "Session context not found",
          66: "Mandatory IE missing", 69: "Mandatory IE incorrect",
          70: "Invalid length", 72: "Rule creation/modification failure"}


def ie(ie_type, payload):
    return struct.pack("!HH", ie_type, len(payload)) + payload


def update_far(far_id, action):
    # TS 29.244 Table 7.5.4.3-1: FAR ID (M) + Apply Action (C). action "none"
    # omits Apply Action to check the UPF keeps the current action.
    body = ie(IE_FAR_ID, struct.pack("!I", far_id))
    if action != "none":
        body += ie(IE_APPLY_ACTION, bytes([ACTIONS[action]]))
    return ie(IE_UPDATE_FAR, body)


def request(seid, seq, far_ids, action):
    body = b"".join(update_far(f, action) for f in far_ids)
    # Header with S=1: flags, type, length (after first 4 octets), SEID, seq(3), spare
    length = 8 + 4 + len(body)
    hdr = struct.pack("!BBHQ", 0x21, PFCP_SESSION_MODIFICATION_REQUEST, length, seid)
    return hdr + struct.pack("!I", seq << 8) + body


def parse_response(data):
    flags, mtype, length = struct.unpack("!BBH", data[:4])
    if mtype != PFCP_SESSION_MODIFICATION_RESPONSE:
        raise ValueError(f"unexpected message type {mtype}")
    off = 4
    seid = None
    if flags & 0x01:
        (seid,) = struct.unpack("!Q", data[off:off + 8])
        off += 8
    (seq_spare,) = struct.unpack("!I", data[off:off + 4])
    off += 4
    cause = None
    while off + 4 <= len(data):
        t, l = struct.unpack("!HH", data[off:off + 4])
        if t == IE_CAUSE and l >= 1:
            cause = data[off + 4]
        off += 4 + l
    return {"seid": seid, "seq": seq_spare >> 8, "cause": cause,
            "cause_text": CAUSES.get(cause, "unknown")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--upf", required=True, help="UPF N4 address")
    p.add_argument("--port", type=int, default=8805)
    p.add_argument("--src", default="0.0.0.0", help="local N4 address to bind")
    p.add_argument("--seid", type=lambda v: int(v, 0), required=True, help="UP F-SEID")
    p.add_argument("--far", type=int, action="append", required=True)
    p.add_argument("--action", choices=sorted(ACTIONS) + ["none"], required=True)
    p.add_argument("--timeout", type=float, default=3.0)
    a = p.parse_args()

    # High random sequence number: avoids colliding with SMF's transaction space.
    seq = random.randint(0x800000, 0xFFFFFF)
    msg = request(a.seid, seq, a.far, a.action)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((a.src, 0))
    s.settimeout(a.timeout)
    sent = time.time()
    s.sendto(msg, (a.upf, a.port))
    try:
        data, peer = s.recvfrom(4096)
    except socket.timeout:
        print(json.dumps({"ok": False, "error": "timeout", "seq": seq}))
        return 2
    result = parse_response(data)
    result.update(ok=result["cause"] == 1 and result["seq"] == seq, sent_seq=seq,
                  action=a.action, far_ids=a.far, up_seid=a.seid,
                  rtt_ms=round((time.time() - sent) * 1000, 3),
                  sent_at=sent, peer=f"{peer[0]}:{peer[1]}")
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
