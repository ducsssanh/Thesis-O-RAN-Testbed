#!/bin/bash
# Phase 0: PFCP Update FAR DROP/FORW sent straight to the UPF (bypassing SMF),
# with concurrent UL/DL iperf and BPF map snapshots. See docs/TWO-LAYER-DEFENSE-PLAN.md (Phase 0).
# Usage: run.sh <out-dir> [up-seid] [ue-ip]
set -u
D=$(cd "$(dirname "$0")" && pwd); OUT="$1"; SEID=${2:-3}; UE=${3:-10.1.0.3}
K="kubectl --context ${KCTX:-oai-lab}"; mkdir -p "$OUT"
SMF=$($K -n oai-core get pod -o name | grep oai-smf | head -1)
UEPOD=deploy/oai-nr-ue; DNPOD=deploy/oai-lab-dn; DN=172.30.26.10; DUR=45
UPF_N4=172.30.24.20; SMF_N4=172.30.24.10
MAPID=$("$D/bpftool.sh" map show 2>/dev/null | grep 'name rules_match_pdr' | cut -d: -f1)
dumpmap(){ "$D/bpftool.sh" -j map dump id "$MAPID" > "$OUT/map-$1.raw.json"; python3 "$D/mapview.py" "$OUT/map-$1.raw.json" > "$OUT/map-$1.json"; }
probe(){ $K -n oai-core exec -i "$SMF" -c capture -- python3 - --upf $UPF_N4 --src $SMF_N4 \
  --seid "$SEID" --far 1 --far 2 --action "$1" < "$D/pfcp_far_probe.py"; }
# The harness installs this route at session start; a UE pod restart loses it.
$K -n oai-ran exec $UEPOD -c nr-ue -- ip route replace 172.30.26.0/24 dev oaitun_ue1 src "$UE"
$K -n oai-core exec "$SMF" -c capture -- sh -c "rm -f /tmp/p0.pcap; timeout 70 tshark -q -i n4 -f 'udp port 8805' -w /tmp/p0.pcap >/dev/null 2>&1 &"
$K -n oai-core exec $DNPOD -c dn -- sh -c "timeout 70 iperf -s -u -p 5101 -i 1 -y C > /tmp/p0-ul.csv 2>&1 < /dev/null &"
$K -n oai-ran exec $UEPOD -c nr-ue -- sh -c "timeout 70 iperf -s -u -p 5102 -i 1 -y C > /tmp/p0-dl.csv 2>&1 < /dev/null &"
sleep 3; dumpmap before
echo "t0=$(date +%s.%N)" > "$OUT/timeline.txt"
$K -n oai-ran exec $UEPOD -c nr-ue -- iperf -c $DN -B "$UE" -u -b 1M -l 1200 -t $DUR -p 5101 > "$OUT/ul-client.txt" 2>&1 &
$K -n oai-core exec $DNPOD -c dn -- iperf -c "$UE" -u -b 1M -l 1200 -t $DUR -p 5102 > "$OUT/dl-client.txt" 2>&1 &
sleep 12; echo "drop_sent=$(date +%s.%N)" >> "$OUT/timeline.txt"; probe drop | tee "$OUT/probe-drop.json"; dumpmap drop
sleep 15; echo "forw_sent=$(date +%s.%N)" >> "$OUT/timeline.txt"; probe forw | tee "$OUT/probe-forw.json"; dumpmap forw
wait; sleep 4
$K -n oai-core exec $DNPOD -c dn -- cat /tmp/p0-ul.csv > "$OUT/ul-receiver.csv"
$K -n oai-ran exec $UEPOD -c nr-ue -- cat /tmp/p0-dl.csv > "$OUT/dl-receiver.csv"
sleep 20; $K -n oai-core exec "$SMF" -c capture -- cat /tmp/p0.pcap > "$OUT/n4.pcap"
$K -n oai-core logs deploy/oai-upf --since=3m > "$OUT/upf.log" 2>&1
python3 "$D/phase0_analyze.py" "$OUT" > "$OUT/summary.json" && cat "$OUT/summary.json"
