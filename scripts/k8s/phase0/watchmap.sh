#!/bin/bash
# Print rules_match_pdr_map keys (seid,pdr_id) every ~0.2 s whenever they change.
# Usage: watchmap.sh [seconds=60] [map-id]   (map id from: bpftool.sh map show | grep rules_match_pdr)
# One privileged container polls the map (avoids ~1 s docker start per sample). Read-only.
D=$(cd "$(dirname "$0")" && pwd)
ID=${2:-$("$D/bpftool.sh" map show 2>/dev/null | grep 'name rules_match_pdr' | cut -d: -f1)}
BPFTOOL=${BPFTOOL:-$(ls /usr/lib/linux-tools-*/bpftool | tail -1)}
exec docker run --rm --privileged --pid=host -v /:/host:ro ubuntu:22.04 bash -c '
B="/host/lib64/ld-linux-x86-64.so.2 --library-path /host/lib/x86_64-linux-gnu /host'"$BPFTOOL"'"
prev=""; end=$((SECONDS+'"${1:-60}"'))
while [ $SECONDS -lt $end ]; do
  cur=$($B -j map dump id '"$ID"' | tr "," "\n" | grep -o "\"seid\":[0-9]*\|\"pdr_id\":[0-9]*" | paste -d, - - | sort | tr "\n" " ")
  [ "$cur" != "$prev" ] && echo "$(date -u +%H:%M:%S.%N | cut -c1-12) $cur" && prev=$cur
  sleep 0.2
done'
