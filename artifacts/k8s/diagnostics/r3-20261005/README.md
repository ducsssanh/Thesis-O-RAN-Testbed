# Gate R3 — 05/10/2026

`scripts/k8s/phase0/r3_gate.py <out> 90`. Each run holds `result.json` (phases, checks), `KPI_Metrics.csv`, `defense.jsonl` (xApp defense events) and `defense-db.json` (DB rows for UE1).

| Run | xApp / gNB | Result | What it showed |
|---|---|---|---|
| run1 | C32 v1 (C31 "quota full" level 2) | FAIL | Benign 1 Mbit/s UE fills a 10 % quota (spare PRBs go to every active UE) and sticks at level 2; the OAI UE's 50 MB UL buffer keeps sending ~400 s under the quota |
| run2-aborted | repeat-offense level 2 | stopped | UE2 offered 4M but gets ~3.4: its buffer fills and drains at 5.6 Mbit/s, above even the `heavy` class |
| run3 | same, UE2 3M | FAIL | UE1 alone at 4M is "congested" (a lone UE gets ~98 % PRB); UE2 entering the flood at UL MCS 0 buffers and bursts. Flood path itself OK (repeat offense, reconnect, expiry) |
| run4-aborted | + congestion needs another active UE | stopped | Idle check passes; the inter-phase gap drops both UEs to MCS 0, UE2 bursts to 7.5 Mbit/s in benign |
| run5 | + gNB `ul_min_mcs = 16` | PASS 10/10 | First pass, default class UL 3000 kbps |
| run6 | same | FAIL | Slow cell (UL ~5.4 Mbit/s): flood fair share 2.7 < 3000, detection took 20 s, UE2 buffered and burst to 7.5 Mbit/s |
| **run7** | default class UL 2000 kbps | **PASS 10/10** | Gate result (plan section 14) |
| **run8** | same | **PASS 10/10** | Repeat; slow cell (UL ~3.8 Mbit/s), control harm to UE2 29 %, with defense 2.4 % |
