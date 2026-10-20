# Dataset v1 campaign design — O-RAN flooding (testbed)

Date: 2026-10-19. Design of the first real labelled dataset (not the probe).
Built with the existing harness (`scripts/k8s/exp/run.py`) + the flood/benign
generators added to `exp/traffic.py`; assembled by `scripts/ml/build_oran_dataset.py`.

## Scientific target & integrity constraints

Question: can the testbed's behavioural telemetry separate flooding from legitimate
high-load traffic **when the trivial cues are removed**? So the dataset is built so
that NO single trivial feature predicts the label:

1. **Load-matched** — benign and malicious span the SAME byte-rate band (500k & 1200k
   kbps), set via a target `rate` so URR/KPM volume overlaps. Volume alone must be
   insufficient.
2. **Packet-size diversity in BOTH classes** — benign has large-packet (UDP 1400 B,
   TCP MSS) AND small-packet (UDP 120 B) sessions; malicious has small-packet (64 B)
   AND large-packet (1400 B) floods. So `mean_bytes` overlaps and is not a shortcut.
3. **Protocol controls** — for every protocol an attack abuses, the benign class
   contains it at a normal rate: TCP bulk (control for SYN flood), low-rate ICMP ping
   (for ICMP flood), low-rate DNS query (for DNS flood). The detector must learn the
   abnormal RATE/pattern, not protocol presence.
4. **Independent sessions** — each scenario is run with `--reps 3`; every rep is a
   fresh run (drained at start), so reps are independent capture groups. Splits are by
   `(campaign, run)` / `(campaign, run, supi)`, never random windows.
5. **UE-ID ≠ label** — ue1 is benign in the benign scenarios and the attacker in the
   flood scenarios, so UE identity does not encode the label. ue2 is a steady benign
   background in every scenario (adds benign records and cell context).
6. **Detection OFF** in all scenarios so mitigation never shapes the traffic; the xApp
   still builds `features.jsonl`.

## Scenario matrix (each run `--reps 3`, detection-off)

| scenario | class | content (ue1) |
|---|---|---|
| `ds-benign-bulk` | benign | UDP large 1400 B @500k/1200k; TCP bulk (SYN control) |
| `ds-benign-light` | benign | UDP small 120 B @500k/1200k; ICMP ping; DNS query (protocol controls) |
| `ds-flood-udp` | malicious | udp_flood 64 B & 1400 B @500k/1200k |
| `ds-flood-proto` | malicious | syn / icmp / dns flood @500k/1200k |
| `ds-flood-special` | malicious | frag_flood (mtu 700) & fanout_udp (dst/24) @500k/1200k |
| `ds-mixed` | mixed | ue1 flood + ue2 legitimate bulk, concurrent, matched load |

## Generators (`exp/traffic.py`)

- `Flow` (iperf2): benign UDP (rate-paced, fixed packet size) or TCP bulk.
- `HpingFlow` (hping3 from the UE `keepalive` sidecar): families `udp_flood`,
  `syn_flood`, `icmp_flood`, `frag_flood` (`--mtu`), `dns_flood`, `fanout_udp`
  (`--rand-dest` over the DN /24), plus benign controls `icmp_ping`, `dns_query`.
  `malicious` sets the label only; `rate` or `pps`, with a 20000 pps safety cap.

## Known limitations (honest)

- **TCP over RFsim is loss-limited to ~330 kbps** regardless of window — RFsim UL loss
  collapses TCP congestion control. So the benign TCP control lands in the low band;
  it still provides a valid "TCP present, SYN rate ≈ 0, large packets" control, but it
  is not a high-load TCP sample. Benign high-load large-packet samples come from UDP.
- **Load matching is on offered byte-rate**; achieved is measured and reported per run
  (`flows.json` offered vs the DN counter / URR). Small-packet floods are pps-heavy;
  the frag/fanout achieved rates are recorded, not assumed.
- Single cell, RFsim radio, 2 UEs (ue1/ue2); no per-UE radio-condition variation yet
  (Phase M). ue3/ue4 available for later multi-UE scale-up.

## Assembly & checks

`build_oran_dataset.py --glob 'artifacts/experiments/*_v1' --out research/datasets/oran_flooding_v1`
produces `synchronized/records.csv` (online features only; decision outputs excluded
as leakage) and `reports/data_quality.md` with label/family counts, missingness, and
the benign-vs-malicious load-overlap table (must show overlap, or the matching failed).

## v1 build — results & validation (2026-10-19)

6 campaigns, 18 OK runs, **36 independent (campaign,run,supi) capture sessions**,
**6338 per-second records** (BENIGN 4718 / MALICIOUS 1620). Families: udp_flood 600,
fanout_udp 300, dns/icmp/syn/frag 180 each.

**The central claim holds on a dense, standard axis.** Benign and malicious occupy the
same KPM-throughput bands (0–100: 1506/194; 300–600: 2506/541; 600–1000: 166/422;
1000–2000: 451/448). Per-UE RAN PRB also overlaps near-totally (benign p50 25 / p90 45,
malicious p50 31 / p90 39). So neither volume nor PRB separates the classes — the
discriminative signal is behavioural (profiler protocol-mix / fan-out), e.g. syn→tcp_syn
up to 2409 (benign max 1), icmp up to 1532 (max 5), dns up to 1521 (max 21),
fanout→dst_estimate up to 266 (max 1).

**Packet size is not a shortcut.** mean_bytes overlaps both ways: benign has 1271 rows
at 0–100 B (small-UDP + control flows) and malicious has 298 rows at 1200 B+ (large-packet
udp_flood variant). It could be balanced further (more large floods / more small benign)
in a v2, but the trivial "small=attack / large=benign" rule is already defeated.

### v1 had two defects; both fixed in the canonical **v2** build

The first assembled build (`research/datasets/oran_flooding_v1`) had two problems that a
careful quality pass caught. The canonical dataset is now **v2**
(`research/datasets/oran_flooding_v2`, `--glob 'artifacts/experiments/*_v2'`), a uniform
re-run of all 6 campaigns after both were fixed.

**1. URR missing → was a leak; root-caused and fixed.** In v1, URR (PFCP usage-report EI)
was present only in `ds-benign-bulk` and absent in the other five campaigns, for *both*
classes — so pooled "URR present ⟹ benign" leaked the label via missingness. The true
cause was NOT the producer restart: the OAI **SMF container restarted**, wiping its
in-memory Nsmf_EventExposure subscriptions, but as a *container* restart (same pod, same
pod UID) the producer's pod-UID-keyed `subscribe()` skipped re-POSTing the `QOS_MON`
subscription (`src/urr-producer/internal/producer/server.go` ~540), so SMF sent no usage
reports. Fix (no restart, mapping untouched): POST the subscription straight to SMF
(`/nsmf_event-exposure/v1/subscriptions`, `eventSubs:[{event:QOS_MON}]`, notifUri = the
producer callback). In v2, URR is present **100% for both classes** and rejoins the
feature set X; the overlap claim is now shown on *two* standard volume layers (KPM
throughput AND the PFCP/URR core counter). The build's missingness leak audit is
data-driven and would re-flag URR automatically if it ever lost per-class parity again.
v3 code fix: key `subscribe()` on pod UID + container start time.

**2. frag_flood generator failed → excluded as an invalid condition.** hping3
`--udp -f --mtu` emits only a token fragment over the RFsim tunnel, so frag_flood
produced essentially no traffic (0% of its rows active; flow counters null). Those 180
rows were labelled MALICIOUS but were effectively idle — label noise. The assembler now
runs a **generator-failure gate**: a malicious family with < 10% active rows (profiler
pps > 5) is dropped as an invalid experimental control (NOT volume-based labelling of
individual rows) and reported. v2 keeps the 5 verified families (udp, syn, icmp, dns,
fanout_udp); a v3 would generate real IP fragmentation with nping/scapy.

### v2 canonical build — summary

6 campaigns, 18 OK runs, **36 independent sessions**, **6164 records** (BENIGN 4721 /
MALICIOUS 1443). All three telemetry layers (KPM + profiler + URR) live for both classes;
zero leak-risk features. Load overlaps on both KPM and URR volume axes; per-UE PRB
overlaps (benign p90 52 vs malicious 40 — malicious is not the higher-PRB class).
Separation is behavioural only: syn→tcp_syn 1348, icmp→icmp 1043, dns→dns 1067,
fanout→dst_estimate 266, each against a benign max of ~1–22.

### v3 canonical build — session-diversity enrichment (2026-10-19)

To grow independent-session diversity (the user's "Tăng session diversity" step), all 6
scenarios were re-run with **6 more reps** under tag `v3` (frag phases removed from
`ds-flood-special`, since frag_flood was already excluded). The canonical dataset is now
**v3** (`research/datasets/oran_flooding_v3`, built from `artifacts/experiments/*_v[23]`,
i.e. v2's 3 reps + v3's 6 reps per scenario — v2 is NOT re-run, just reused):

- **12 campaigns, 50 OK runs, 100 independent sessions, 16 812 records** (BENIGN 12 484 /
  MALICIOUS 4 328) — ≈2.8× the sessions and ≈2.7× the records of v2.
- 5 verified families (udp_flood 1804, fanout_udp 901, icmp_flood 542, syn_flood 541,
  dns_flood 540); frag_flood auto-excluded by the generator-failure gate (180 leftover v2
  rows, 0% active).
- **Leak audit: none** — `has_urr` and `has_prof` both 100% for both classes.
- Load overlaps on **both** KPM (`thp_ul_kbps`) and PFCP/URR (`urr_ul_kbps`) axes (heavy
  overlap in 300–600 and 600–1000 bands); packet-size (`prof_ul_mean_bytes`) overlaps both
  ways (benign and malicious each span 0–100 B and 1200 B+).
- **Known blemish (honest):** `ds-benign-bulk_v3` produced only 2/6 OK runs — the NGAP
  amf_ue_ngap_id→SUPI mapping went stale mid-scenario and the campaign guard only repaired
  it (producer+adapter restart + URR re-POST) at the *next* scenario. So benign-bulk is 5
  reps combined vs 9 for the other five scenarios; benign is the majority class, so class
  balance is unaffected. Re-running the 4 missing benign-bulk reps is optional.

v2 (`research/datasets/oran_flooding_v2`) is kept intact underneath v3.
