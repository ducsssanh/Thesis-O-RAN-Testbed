#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image=${1:?pass xApp image tag}
tmp=$(mktemp -d)
container=
cleanup() { if [[ -n "$container" ]]; then docker rm -f "$container" >/dev/null 2>&1 || true; fi; rm -rf "$tmp"; }
trap cleanup EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost \
  -addext 'subjectAltName=DNS:localhost' -keyout "$tmp/tls.key" -out "$tmp/tls.crt" >/dev/null 2>&1
cat >"$tmp/event.json" <<'JSON'
{"event_id":"job:9007199254740993:2","job_id":"job","report":{"schema_version":"1.0.0","run_id":"test","observed_at":"2026-09-30T00:00:00Z","smf_timestamp":"0","supi":"imsi-test","seid":9007199254740993,"urr_id":null,"ur_seqn":2,"triggers":["VOLTH"],"ul_bytes":10,"dl_bytes":20,"total_bytes":30,"ul_packets":1,"dl_packets":2,"total_packets":3,"duration_seconds":1,"dnn":"nist-dnn","snssai":{"sst":1,"sd":"FFFFFF"},"enrichment_source":"lab-config"}}
JSON
start() {
  container=$(docker run -d --rm -p 127.0.0.1::8443 -v "$tmp:/test" -v "$root/tests/k8s/urr_receiver_smoke.c:/test-main.c:ro" "$image" \
    sh -c 'gcc -I/source/flexric/examples/xApp/c/monitor /test-main.c /source/flexric/examples/xApp/c/monitor/urr_receiver.c -lmicrohttpd -ljson-c -lsqlite3 -lcrypto -lpthread -o /test/receiver && URR_DB_PATH=/test/urr.db URR_EXPORT_PATH=/test/urr-received.jsonl URR_TLS_CERT=/test/tls.crt URR_TLS_KEY=/test/tls.key RUN_ID=test /test/receiver')
  port=$(docker port "$container" 8443/tcp | awk -F: 'NR==1 {print $NF}')
  for _ in {1..30}; do if curl -fsS --max-time 5 --resolve "localhost:$port:127.0.0.1" --cacert "$tmp/tls.crt" "https://localhost:$port/readyz" >/dev/null 2>&1; then return; fi; sleep 1; done
  docker logs "$container"
  exit 1
}
post() { curl -sS --max-time 5 --resolve "localhost:$port:127.0.0.1" --cacert "$tmp/tls.crt" -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' --data-binary @"$1" "https://localhost:$port/v1/urr/events"; }
start
[[ $(post "$tmp/event.json") == 201 ]]
[[ $(post "$tmp/event.json") == 200 ]]
sed 's/"total_bytes":30/"total_bytes":31/' "$tmp/event.json" >"$tmp/conflict.json"
[[ $(post "$tmp/conflict.json") == 409 ]]
# Same SEID/UR-SEQN in another session epoch is a new report, not a conflict
sed -e 's/"event_id":"job:9007199254740993:2"/"event_id":"job:9007199254740993:20261001T120000Z:2"/' \
    -e 's/"seid":9007199254740993,/"seid":9007199254740993,"session_epoch":"20261001T120000Z",/' \
    -e 's/"total_bytes":30/"total_bytes":32/' "$tmp/event.json" >"$tmp/epoch.json"
[[ $(post "$tmp/epoch.json") == 201 ]]
[[ $(post "$tmp/epoch.json") == 200 ]]
sed 's/"event_id":"job:9007199254740993:20261001T120000Z:2"/"event_id":"job:9007199254740993:2"/' "$tmp/epoch.json" >"$tmp/epoch-id.json"
[[ $(post "$tmp/epoch-id.json") == 400 ]]
sed 's/"session_epoch":"20261001T120000Z"/"session_epoch":"x:y"/' "$tmp/epoch.json" >"$tmp/epoch-bad.json"
[[ $(post "$tmp/epoch-bad.json") == 400 ]]
echo '{"bad":true}' >"$tmp/invalid.json"
[[ $(post "$tmp/invalid.json") == 400 ]]
docker rm -f "$container" >/dev/null
container=
start
[[ $(post "$tmp/event.json") == 200 ]]
python3 - "$tmp/urr-received.jsonl" <<'PY'
import json,sys
rows=[json.loads(x) for x in open(sys.argv[1])]
assert len(rows)==2,rows
assert rows[0]['report']['seid']==9007199254740993
assert rows[1]['report']['session_epoch']=='20261001T120000Z',rows[1]
assert rows[0]['report']['urr_id'] is None
PY
docker rm -f "$container" >/dev/null
container=
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$tmp/wrong.key" >/dev/null 2>&1
if docker run --rm -v "$tmp:/test" "$image" sh -c \
  'URR_DB_PATH=/test/urr.db URR_EXPORT_PATH=/test/urr-received.jsonl URR_TLS_CERT=/test/tls.crt URR_TLS_KEY=/test/wrong.key RUN_ID=test /test/receiver'; then
  echo 'receiver accepted a mismatched TLS key' >&2
  exit 1
fi
echo 'xApp receiver smoke PASS'
