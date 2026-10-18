# Ingest check — 20261006-005144_smoke

0/1 runs PASS

### runs/two-layer/rep-01 — FAIL

| check | result | detail |
|---|---|---|
| hops | PASS | `{"n4_reports":116,"missing":{"smf_raw":0,"producer":0,"adapter":0,"xapp":0},"xapp_duplicates":0}` |
| kpm | PASS | `{"per_supi":{"imsi-001010123456780":{"vectors":46,"per_s":0.999},"imsi-001010123456781":{"vectors":46,"per_s":0.999}}}` |
| coverage | PASS | `{"per_supi":{"imsi-001010123456780":{"same_s":0.978,"pm1_s":1.0},"imsi-001010123456781":{"same_s":1.0,"pm1_s":1.0}}}` |
| volume | FAIL | `{"per_supi":{"imsi-001010123456780":{"ul":{"median_err":-0.023,"n":27},"dl":{"median_err":-0.002,"n":18}},"imsi-001010123456781":{"ul":{"median_err":-0.011,"n":28},"dl":{"median_err":0.0,"n":18}}},"swapped":"no phase with the two UEs' rates >= 2x apart"}` |
| identity | PASS | `{"per_supi":{"imsi-001010123456780":{"compared":46,"mismatch":0},"imsi-001010123456781":{"compared":46,"mismatch":0}}}` |
| latency | PASS | `{"p50_s":2.0,"p95_s":3.0,"max_s":3.0,"n":118}` |
| idle | skipped | `{"phases":{}}` |
| reconnect | skipped | `{"events":[]}` |
| dataset | skipped | `{"skipped":"xApp image without the deferred dataset write (no urr_at_decision field)"}` |
