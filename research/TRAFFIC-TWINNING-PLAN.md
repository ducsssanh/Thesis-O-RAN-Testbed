# Traffic twinning plan — grounding the testbed dataset in real traces

Status: 2026-10-31, draft rev 3 (rev 2: review against the generator code and the Madrid data — changes in §0; rev 3: validation statistics and threshold, §6.2–6.3). Execution plan for making the cross-domain dataset's **benign** traffic statistically
match real commercial traces, and for giving the **attack** traffic a defensible basis. Read with
`research/CROSS-DOMAIN-DEFENCE.md` (testbed, telemetry) and `research/DRL-DIRECTION.md` (what the dataset feeds).

The generator infrastructure already exists (`scripts/k8s/exp/traffic.py` + `scripts/k8s/exp/v4traffic/`): schedule
models (`schedules.py`: cbr, poisson, mmpp2, onoff_pareto, fgn, hawkes, pulsing), a shared packet-size prior
(`sizes.py`), a load-matching mixer (`mixer.py`), and hping3 / pacer / iperf / tcp_shortconn / dns_client backends.
**Twinning does not add a generator; it calibrates the parameters of these models to real data and adds a
validation gate.** It needs **small, listed code changes** to the existing modules (§4.C) — not a new generator.
Nothing in the measurement path changes (see §1).

---

## 0. Revision 2 (2026-10-29) — what changed and why

A review of rev 1 against `v4traffic/schedules.py`, `sizes.py`, `planbuilder.py` and the Madrid data found:

| # | problem in rev 1 | consequence if run as written | fix (section) |
|---|---|---|---|
| 1 | `r̄` drawn from the **active-second** rate, but `onoff_pareto` rescales the series so its **long-run mean** = `r̄` | ON seconds of the twin ≈ 1/duty ≈ 4× heavier than Madrid | `r̄` = Madrid **session mean rate**; active-second rate is the ON-level check (§4.A) |
| 2 | `onoff_pareto` superposes `K=4` sources by default | aggregate fills the OFF gaps; not one user | `K=1` for a per-UE twin (§4.A) |
| 3 | OFF gaps are **censored at 10 s** by the session rule (silence >10 s = new user); α_off fitted from the mean | biased α_off; the tail is an artefact | empirical resampling of ON/OFF, or truncated-Pareto MLE (§4.A) |
| 4 | ACF to lag 60 and per-UE Hurst asked of Madrid, but per-UE series are fragments (wallclock p50 1 s, p99 36 s); H≈0.7–0.9 was a **cell-level** figure from the Madrid repo, not measured by us | gate not computable on the real side | gate = KS on active-second rate / ON-run / OFF-gap + short-lag ACF; Hurst only cell-level, optional (§6) |
| 5 | 4/2 BS split assumed, but only **I-2650** per-UE parquet is on disk (`users_allBS.csv` = per-cell user counts only) | split not executable | decision D1 (§4.D) |
| 6 | Korean (benign) and §3.3 (attack) sizes differ, breaking v4's **shared size prior** (v4 overlap 0.84–1.00) | packet size becomes a class cue again | decision D2 (§4.D), confound accounting per evasion level (§5.3) |
| 7 | `sizes.py` smallest bin 64 B cannot give `E[size]` ≈ 51–58 B; `fgn` has no OFF and only H∈[0.7,0.9]; α bounds [1.2,1.8] | P1–P4 not expressible | code changes listed in §4.C |
| 8 | §5.1 said attack bytes *add to* benign; `planbuilder`/`mixer` keep **total = level** (background 20–60 %) | load-match would be lost | keep the mixer semantics (§5.1 reworded) |
| 9 | L3 has no real-anchored benign counterpart (no heavy-UL TCP app in Korean; Zoom is UDP) | L3 "near-indistinguishable" untested | add a heavy-UL TCP benign, documented as assumption (§5.3, §7) |
| 10 | normalisation by the median: per-UE series are mostly OFF → median 0 | division by zero | normalise by the mean of active seconds (§6.1) |
| 11 | KS `D(real,real)` computed on large n vs a small twin n | twin penalised by sampling noise | size-matched subsampling + bootstrap (§6.3) |
| 12 | profile mixing weights P1–P4 not stated | base rate undocumented | stated in §4.B |
| 13 | only UL twinned; benign DL undefined | DRL observation/teacher/reward see an unrealistic DL | benign DL twin (§4.E), DL validation (§6.2) |
| 14 | "session mean Mbit/s" in §3.1 averages active seconds only; 0-byte UL grants counted as active | `r̄` and band edges biased | `r̄` = bytes/wallclock (§4.A); active = bytes > 0 (§3.1 note) |

Net effect on schedule: ≈ +1.5–2 days (code changes §4.C, long validation runs §6.1).

---

## 1. What twinning changes, and what it does not

```
real datasets ──► calibrated generator params ──► UE sends packets ──► [ gNB → UPF ] ──► KPM / URR / profiler ──► (tamper / outage) ──► xApp
  (Madrid, KR-5G,            (this plan)              (testbed, unchanged)                  (unchanged)            (unchanged)
   5G-NIDD, IoT-23)
```

- Twinning sits **entirely before the radio stack**. It only decides *what packets each UE emits and when*.
- KPM, URR and the eBPF profiler are still produced by the gNB and UPF exactly as before — not synthesised, not
  taken from any external dataset. The physical KPM↔URR invariant holds because both still measure the same packets.
- The KPM-tamper and core-outage injection stay where they are (after KPM is produced, before the xApp). Unchanged.
- The cross-domain idea and the DRL detector are unchanged.
- **One addition to the measurement path**: collect the gNB MAC UL-grant bytes per UE, used *only* to validate the
  twin against Madrid (§6). It is never fed to the xApp or the model.

---

## 2. Resources (downloaded under `data/external/`, analysis in `research/twinning/`)

| resource | what is REAL in it | what we extract | granularity |
|---|---|---|---|
| **Madrid LTE** `madrid/I-2650-raw-df-ms.parquet` (135.5 M TTI rows, 1 cell, ~1344 h) | per-RNTI PDCCH decode: TBS, PRB, MCS, `direction` (0=UL) | per-UE **UL rate distribution**, ON/OFF micro-structure, concurrency | 1 ms → aggregated to 1 s |
| **Korean 5G** `kr5g/*.csv` (11 apps, commercial SA phones, PCAPdroid) | per-packet time, src/dst, protocol, length (UL & DL) | per-app **packet-size & inter-arrival distribution, protocol mix, UL/DL ratio** | per packet |
| **5G-NIDD** `5gnidd/BS?_each_attack_csv/` (Argus flows over a real 5G testbed) | labelled flood flows after traversing a 5G stack | **attack behaviour at a flow meter** (proto mix, pkt size, per-flow rate) — validates the attack generator | per flow |
| **IoT-23 34-1** `iot23/34-1.pcap` (real Mirai capture, 126 MB) | real botnet flood packets | **observed** flood packet size / flags / per-second rate (external anchor only) | per packet |

Not used as training data (single-domain, no paired KPM/URR): 5G-NIDD and IoT-23 are **attack references** only;
Korean 5G is a **behaviour prior**; Madrid is the **load/timing** source. Only the testbed produces paired
cross-domain records.

---

## 3. Measured real values (the numbers the plan plugs in)

### 3.1 Madrid — per-UE uplink (reconstructed users: same RNTI, silence >10 s = new user)
`research/twinning/out_madrid.txt`

| quantity | p50 | p90 | p95 | p99 | mean |
|---|---|---|---|---|---|
| **active-second UL rate** (Mbit/s) | 0.027 | 0.219 | 0.355 | **1.290** | 0.105 |
| session active-seconds | 1 | 3 | 4 | 14 | — |
| session wallclock (s) | 1 | 11 | 17 | 36 | — |
| session mean rate (Mbit/s) | 0.029 | 0.149 | 0.219 | 0.394 | — |
| ON-run length (s) | 1 | 2 | 2 | 6 | 1.27 |
| OFF-gap within session (s) | 4 | 8 | 9 | 9 | 4.08 |
| concurrent users / s | 17 | 36 | 47 | 74 | 19.9 (max 141) |

Heavy-benign tail: **0.9 %** of sessions have mean UL in **[0.4, 1.2] Mbit/s** — the load-matched confound is real
but rare. Caveats: TBS is MAC (incl. retx+padding); RNTI reuse fragments long users, so *session duration* is weak,
but the *rate* and *ON/OFF micro-structure* are usable. Further caveats (rev 2): the OFF-gap distribution is
**censored at 10 s by construction** (the session rule), so its p99 = 9 s and mean are not a tail estimate; an
"active second" includes small control-related UL grants (BSR/SR-triggered), so the light band (P1) is largely
keep-alive traffic; per-UE series are short (wallclock p99 36 s), so long-lag temporal statistics cannot be
measured per UE. **Activity definition**: the table above counts a second as active when it had any UL grant,
including 0-byte grants (2.03 M of 13.8 M UL seconds on I-2650). Rev 2 uses bytes > 0 on both sides (§6.1); on
I-2650 this gives active-second UL p50 0.039 / p99 1.47 Mbit/s, sessions 6.1 M, concurrency p50 14
(`research/twinning/out_madrid_I-2650_v2.txt`). Step 1 of §8 recomputes all of §3.1 on the build set with this
definition. The sub-heavy band also has a session-mean distribution (above), which is the correct source for a
long-run mean `r̄` (§4.A).

### 3.1a Session rule: measure the inactivity timer and RNTI reuse (rev 3, 2026-10-31, before step 1 of §8)
The 10 s rule above is a convention copied from the IMDEA notebook, not a measurement. A C-RNTI belongs to one UE for
the whole RRC connection; it is freed only when the eNB releases the connection after the RRC inactivity timer
T_inact, and only then can it be given to another UE. So the cut must be placed at the measured T_inact, and whether
two consecutive episodes of one RNTI value can belong to different UEs depends on the operator's RNTI allocation
rule (how soon a freed value is handed out again). Both are measured on the **raw 1 ms data of the build cells only**
(`data/external/madrid/*-raw-df-ms.parquet`: timestamp, rnti, direction, mcs, prb, tbs per DCI).

Quick check already done (per-second table, I-2650, UL or DL activity): the gap histogram decays smoothly from 1 to
40 s, and so does the gap before "release-like" seconds (one small DL-only grant followed by > 60 s of silence). No
peak at any timer value is visible at 1 s resolution, so the measurement needs the ms data.

| # | measurement (raw ms, build cells) | how | gives |
|---|---|---|---|
| 0 | remove decoder false positives | drop RNTI values seen in fewer than k grants within a short window and never again (spurious PDCCH decodes) | clean episodes |
| 1 | end-of-connection signature | for each RNTI episode, the time from the last UL grant / last data grant to the final DL grant(s) before a long silence; at ms resolution the release message should form a sharp peak | **T_inact** (and its spread) |
| 2 | RNTI allocation rule | value of each newly appearing RNTI against time (sequential/incremental, random, or lowest-free) | the reassignment rule |
| 3 | RNTI reuse interval | for each RNTI value, time from a detected release to its next appearance | the minimum time before a value can belong to another UE |
| 4 | start-of-connection signature | first grants of an episode (random access → contention resolution pattern) | confirms that an episode is a new connection |

**Decision rule.** Cut a session at a silence > T_inact (+ a small margin for the release delay). A shorter gap is
the same UE by construction (the connection was not released). A longer gap is a new connection; it is the same
physical UE only if the reuse interval allows it, and the sniffer cannot link it either way. If the reuse interval is
much longer than T_inact (expected for sequential allocation), two adjacent episodes of one RNTI value never belong
to different UEs within that interval, and the cut only splits one user's activity into connections. Activity counts
UL **or** DL (a UE that only downloads keeps its connection). Record T_inact, the allocation rule and the reuse
interval in §3.1; rerun the profile with the measured value; keep a sensitivity check at T_inact ± 5 s.

**Literature cross-check.** Attanasio et al. (Computer Networks 219, 2022, doi:10.1016/j.comnet.2022.109428; and the
ACM MSWiM 2021 version, doi:10.1145/3479239.3485685) study RNTI allocation and management with the same kind of
sniffer traces from the same group; read them before step 1 and compare their timer and allocation findings with the
measurement above. If they disagree, the measurement on our cells wins and the difference is reported.

### 3.2 Korean 5G — per-app behaviour prior (`research/twinning/out_kr5g.txt`)

| app | UL Mbit/s | UL pkt p50 (B) | UL pkt/s | protocol | character |
|---|---|---|---|---|---|
| Zoom | 0.84 | 877 | 136 | UDP | symmetric, continuous — **load-matched to attacks** |
| GeForce Now | 0.15 | 106 | 61 | UDP | cloud game, DL 12 Mbit/s |
| Battleground | 0.018 | 68 | 28 | UDP | game, small steady |
| Teamfight Tactics | 0.010 | 51 | 20 | UDP | game, small |
| Netflix | 0.005 | 40 (ACK) | 10 | TCP | streaming, UL = ACKs |
| YouTube Live | 0.007 | 59 | 3 | QUIC | DL-heavy, bursty (26 % active-s) |
| Roblox | 0.005 | 58 | 5 | RakNet/UDP | small, sparse |

(MS Teams capture: UE-side detection failed, excluded.)

### 3.3 Attack references (`research/twinning/out_5gnidd_bs1.txt`, `iot23/ddos_per_sec.txt`)

5G-NIDD, per attack flow (tool in brackets): SYN flood [hping3] IP len **54 B**; UDP flood [hping3] **42 B**;
ICMP flood [hping3] **42 B**; HTTP flood [Goldeneye] TCP, pkt p50 66 B; Slowrate [Slowloris/Torshammer] pkt 68–74 B.
IoT-23 Mirai (observed in pcap): two attack bursts of 32 s and 23 s, **940–1843 pkt/s**, packet sizes 60 B and
1078 B, to TCP/80. These bound the *shape* of the floods; they do not set the testbed rate (§5.2).

---

## 4. Benign twinning pipeline (calibrate existing models to §3.1–§3.2)

Goal: replace the hand-picked benign levels (`400k/500k/1200k`, `pkt:1400`) in
`experiments/scenarios/ds-benign-*.yaml` with parameters drawn from real distributions, keeping the SAME generator.

### A. Build the benign profile library (offline, one-off)
`research/twinning/` scripts already produce the distributions. Define **K=4 profiles** by clustering Madrid session
mean-rate × Korean app behaviour:

Bands are defined on the Madrid **session mean rate** (§3.1: p50 0.029 / p90 0.149 / p95 0.219 / p99 0.394
Mbit/s; the heavy tail [0.4, 1.2] is the 0.9 % confound band). Exact band edges are recomputed on the build set (D1).

| profile | rate source (Madrid session mean) | behaviour source (Korean) | model + params |
|---|---|---|---|
| P1 light-sparse | ≤ p50 | Roblox/YouTube-Live | `onoff_k1`, app size prior (Roblox) |
| P2 light-steady | p50–p90 | Battleground/TFT | `onoff_k1` (or `poisson` × duty), app size prior (BG/TFT) |
| P3 medium | p90–p99 | GeForce Now | `onoff_k1` with `mmpp2` inside ON, app size prior (GFN) |
| P4 heavy | > p99 (confound band [0.4, 1.2]) | Zoom | `onoff_k1` with near-CBR inside ON, app size prior (Zoom) |

**Formulas (what value → which generator knob):**
- **Long-run mean `r̄`** = sampled from the Madrid **session mean rate** restricted to the band (empirical
  inverse-CDF): `r̄ = F⁻¹(U)`, `U ~ Uniform(band)`. Definition: session bytes × 8 / session **wallclock** (OFF
  seconds included). Note: the "session mean Mbit/s" printed by rev-1 `madrid_profile.py` (and in §3.1) is the mean
  over **active** seconds only, so it is not `r̄`; step 1 of §8 recomputes it as bytes/wallclock and the band edges
  in §4.A are re-derived from that. The generator's `rbar` is a long-run mean (`onoff_pareto`
  rescales `rate.mean()` to `rbar`), so the active-second rate must **not** be used here (rev-1 error).
- **ON level** follows: `r_on = r̄ / duty`, `duty = E[ON]/(E[ON]+E[OFF])`. The Madrid active-second rate in the band
  is then a **check** of `r_on` (KS in §6.2), not an input.
- **ON/OFF**: one source per UE (`K=1`). Durations are **resampled from the Madrid empirical ON-run and OFF-gap
  distributions** of the band (build set), not a mean-matched Pareto. Reason: OFF gaps are censored at 10 s (§3.1)
  and ON runs are near-degenerate at 1 s, so a mean-matched α is biased (rev 1 gave α_on≈4.7, α_off≈1.32 — both
  outside the module's [1.2, 1.8]). Alternative if a parametric form is wanted for the thesis text: truncated-Pareto
  MLE with the 10 s truncation explicit. OFF gaps longer than 10 s cannot be estimated from Madrid; the twin caps them
  at 10 s and records this as a limitation (§9).
- **Inside-ON process**: P1/P2 Poisson packets; P3 `mmpp2` (GFN bursts); P4 near-CBR (Zoom continuous). `fgn` is no
  longer used for P4: it produces a continuous rate with no OFF, unlike any Madrid UE, and its H would have no
  per-UE real anchor (§0 #4).
- **Packet size**: per-app UL size distribution from Korean (empirical, not only p50), via the new app-prior mode of
  `sizes.py` (§4.C); `λ = r_on / E[size]` inside ON.
- **Hurst**: not a per-UE input. Optionally reported at cell level only (§6.2).
- Concurrency: the testbed runs 2 UEs, not 20. We do **not** reproduce 17 concurrent users; we reproduce one
  *subject* UE (the profile under test) + one *background* UE, and record that the real cell holds ~17 (p50) so the
  single-cell PRB context is documented, not matched (limitation §9).

### B. Wire profiles into scenarios
- Add `v4` flow specs to `ds-benign-*.yaml` with `{backend, model, level_mbps, size_prior, seed}` from the table.
- `planbuilder.build_plan` already turns a spec into a per-second plan; `runner.run_backend` already logs achieved
  per-second bytes. No code change, only spec values.
- Keep `reps` as independent seeds so each rep is a fresh draw from the distribution.
- **Profile mixing weights** (stated, since they set the base rate): the benign dataset **oversamples P4** on
  purpose — the confound band is 0.9 % of real sessions but is where the detection problem lives. Default
  P1/P2/P3/P4 = 0.25/0.25/0.20/0.30, recorded in the manifest and the datasheet together with the real Madrid
  frequencies (≈ 0.50/0.40/0.09/0.01), so results can be re-weighted to the real mix.
- `planbuilder` needs a small change to read `benign_profiles.json` (§4.C); the spec values alone are not enough.

### C. Code changes required (small; no new generator)
| module | change | why |
|---|---|---|
| `schedules.py` | new `onoff_k1(rbar, T, rng, on_samples, off_samples, inner, mean_size)` — one source, ON/OFF durations resampled from empirical arrays, inner process `poisson`/`mmpp2`/`cbr`, long-run mean rescaled to `rbar` | §0 #1–#3; existing `onoff_pareto` (K≥1, α∈[1.2,1.8]) is kept unchanged for v4 reproducibility |
| `sizes.py` | new app-prior mode: empirical size distribution per app (sizes may go below the 64 B bin), selected by profile; the shared Dirichlet prior stays the default for v4 | §0 #7 |
| `planbuilder.py` | resolve `profile: P1..P4` from `benign_profiles.json` / `attack_shapes.json` into model + size prior + `rbar`; record the draw in `flows.json` meta | provenance per flow |
| `test_schedules.py` | tests: `onoff_k1` mean = `rbar`, realised duty ≈ empirical duty, OFF ≤ cap | regression |
| run harness | per-UE gNB MAC UL- **and DL**-grant bytes per second (validation only, §6.1) | measure at the Madrid layer |
| DN-side sender | run the pacer on the DN toward the UE with a per-second plan (benign DL twin, §4.E) | iperf `dl` is constant-rate only |

### D. Decisions before step 1 of §8 — **taken 2026-10-29: D1-a, D2 as recommended**
Madrid per-UE files on the IMDEA share (2026-10-29): `I-796`, `I-1815`, `I-2650`, `II-816` (2 parts), `II-1835`
(2 parts), `II-2650` — 6 cells, ≈ 42 GB raw, downloaded to `data/external/madrid/`. **Held out (decided
2026-10-29, before any profiling): `I-796` and `II-2650`** — used only for the single final check (§6.3). Build set:
`I-1815`, `I-2650`, `II-816`, `II-1835`. (`I-2650` statistics in §3.1 were computed before the split; it stays in
the build set, so no held-out data has been looked at.)
- **D1 — validation split.** Only I-2650 per-UE data is on disk. Options: (a) download the other 5 per-UE parquets
  from IMDEA (~1 GB each; disk has ~14 GB free → reduce each to per-(rnti,s) and delete the raw before the next;
  `data/external/` is not raw testbed data, so this does not conflict with the no-delete rule) and use the 4/2 BS
  split; (b) time split within I-2650 (e.g. first 4 weeks build / last 2 weeks test) — same cell, weaker claim.
  **Recommended: (a)**; fall back to (b) only if the share is unreachable, and state it in §9.
- **D2 — packet-size confound.** Real benign sizes (Korean) differ from flood sizes (§3.3), so size becomes a class
  cue again, unlike v4's shared prior. **Recommended:** accept it as the realistic condition at L1, and remove it at
  L2/L3 by giving the attack the benign profile's size distribution (§5.3). The datasheet reports, per evasion
  level, the size overlap between classes (as v4 did) so the confound is measured, not hidden.

### E. Benign DL twin (added 2026-10-29, needed for DRL)
Rev 1 twinned only UE→DN. DRL needs DL to be realistic too (`research/DRL-DIRECTION.md`): the observation carries
KPM/URR **UL and DL** (§3.2 there), the core-side teacher uses "UL without matching DL" as an attack-effect signal,
and the reward's "benign bytes lost" is mostly DL (users mostly receive). An unrealistic benign DL would give the
policy a shortcut and mis-price wrong blocks.
- **Real sources**: Madrid per-UE per-second **DL bytes** (the reduction now keeps UL and DL, §8 step 1) — gives the
  **joint** UL↔DL behaviour of real users (DL/UL ratio per second, DL activity when UL is OFF, lag between UL and
  DL bursts); Korean per-app DL rate and DL/UL ratio (§3.2, e.g. GeForce Now DL ≈ 12 Mbit/s) — gives the app shape.
- **Per profile**: DL long-run mean `r̄_DL = ρ · r̄_UL`, `ρ` sampled from the Madrid per-session DL/UL byte ratio
  of the band; DL ON/OFF resampled from Madrid DL activity runs (same `onoff_k1`, separate draw, so UL and DL are
  not artificially locked together); inside-ON process and size from the Korean app's DL.
- **Generator**: DL is sent DN→UE. Today only the iperf `dl` direction exists (`traffic.py`, constant rate); a
  DN-side scheduled sender (the pacer run on the DN with a per-second plan) is needed — listed in §4.C.
- **Attack side**: unchanged — the attacker UE's benign background also gets its DL twin; the flood itself has
  whatever DL the victim produces (victim mode, existing). So "UL without matching DL" is measured against a
  realistic benign DL, not against zero.
- **Validation** (§6.2): add KS on the per-second DL/UL ratio over seconds where both are active, and KS on the
  normalised DL active-second rate.

### B3/B4. Run + validate (see §6).

---

## 5. Attack construction (the part with no benign basis — give it a defensible one)

### 5.1 Mechanism (how the attack is realised)
- The attacker UE is a **compromised-but-in-use device**: it runs its benign profile (§4) **and** a bot process
  concurrently (matches real IoT bots). Load accounting follows the existing `planbuilder`/`mixer` semantics:
  the benign background takes 20–60 % of the phase `level` and the attack fills the rest, so the **attacker UE's
  total = `level`** = the benign counterpart's load (rev 1 wrongly said the attack *adds to* benign, which would make
  the attacker heavier by the background share and break the load match). In the manifest, `role=attack` is the only ground-truth label; the benign flow on the same UE keeps `role=benign`.
- Vectors use the existing hping3 backends (`traffic.py` KINDS: `udp_flood, syn_flood, icmp_flood, frag_flood,
  dns_flood, fanout_udp`). **No Mirai binary and no Mirai source is used**; hping3 reproduces the publicly known
  packet shape. Testbed egress is blocked during campaigns; the victim is a local DN/MEC server.
- Target: a victim server on the DN reached over N6 (`fanout_udp` sweeps DN aliases for the Crossfire-style variant).

### 5.2 Parameter vector θ and how each is anchored
θ = (vector, rate `r`, temporal model, onset, duration, ramp, evasion level, react).

| param | value / rule | basis |
|---|---|---|
| vector | one of the 6 KINDS | MITRE ATT&CK T1498/T1499; shapes validated in §6 |
| **rate `r`** | `r = F⁻¹(q)` of the Madrid active-second UL rate: q95→0.35, q99→1.29 Mbit/s; sweep q∈{0.90, 0.95, 0.99} | §3.1 — "load-matched to the heaviest 1–5 % of real users" is now a measured statement, not a guess (the existing 0.4–1.2 Mbit/s band = p95–p99) |
| onset | uniform over the phase pre-roll (randomised change point) | adaptive-attacker / unknown change point |
| duration | the phase length (30–60 s) | experiment design |
| ramp | {step, linear-10 s} | tests slow ramp evasion |
| pkt size (per vector) | SYN 54–60 B, UDP 42–64 B, ICMP 42 B; large-pkt variant 1400 B | §3.3 (5G-NIDD / IoT-23) |
| **evasion level** | L1/L2/L3 (below) | the detection-boundary result |
| **react** | {none, stop-on-throttle, resume-after-release, probe-threshold} | for TTL-based mitigation & DRL (DRL §2.8) |

### 5.3 Evasion levels (defines the detection-boundary curve)
- **L1 load-match only**: `r` at the chosen percentile, default flood packet shape. Distinguishable by behaviour
  (SYN share, pkt size, destinations) at the UPF profiler.
- **L2 + timing-match**: wrap the flood in ON/OFF drawn from the Madrid benign ON/OFF (§3.1, same `onoff_k1`
  resampling as the benign twin), so the 1 s rate series looks benign. Under D2 the attack also takes the paired
  benign profile's **size distribution**, so the remaining cue is protocol mix, not size.
- **L3 + behaviour-match**: HTTP flood with a full TCP handshake to a responsive server, benign-like packet sizes.
  Its benign counterpart must be **TCP with heavy UL** at the same load; the Korean set has none (Netflix UL is ACKs,
  Zoom is UDP), so L3 is paired with a heavy-UL TCP benign (bulk upload / sync, existing `tcp`/iperf backends), timed
  by the P4 ON/OFF — documented as an **assumption** in §7. Pairing L3 with Zoom would leave protocol as a cue and
  the "near-indistinguishable" claim untested.
  Per-UE, L3 is expected to be near-indistinguishable (allowed — report it).
- Per evasion level the datasheet reports which cues remain by construction (size overlap, protocol mix, timing),
  so the delay-vs-false-alarm curve can be read against them.

### 5.3a How the evasion levels are used in training vs testing (decided 2026-10-29)
- L1/L2/L3 are our construction (§7), so training and testing on all three only shows the model learned our three
  definitions. **Primary protocol: train on L1 + L2, test on L3 held out** (an attacker smarter than anything seen in
  training; DRL-DIRECTION question 4). Also report train-all / test-all (different runs) as an upper bound.
- Leave-one-level-out (3 folds) is optional if time allows.
- For DRL the dataset builds the replay environment: levels are **episode types**; a curriculum L1 → L2 is allowed
  inside the training set; L3 episodes and the `react` variants on L3 stay out of training. The open lever is **multi-UE
  correlation**: many L3 UEs starting together toward one destination remain visible in the profiler's
  destination-count across UEs (DRL §2.7).

### 5.4 Crossfire-style harm without a full botnet
Testbed has 2 UEs; do **not** shrink RFsim capacity (it would break the benign twin). Instead:
- argue harm by computation: `N · r` vs the N6/UPF capacity (N = modelled botnet size);
- if a demonstration of congestion is needed, add an explicit bottleneck `tc tbf` on the N6 path to the victim with
  a benign TCP flow sharing it (this is also the only place "shrew/low-rate" is well-defined — otherwise call it
  `pulsing/RoQ`, since v5 showed RFsim does not congest at 0.4–1.2 Mbit/s).

---

## 6. Validation gate (why the twin is "realistic")

### 6.1 Measure at the same point
- Benign twin is validated against Madrid using the **gNB MAC UL-grant bytes per UE** (new collection), not KPM
  `DRB.UEThpUl` or URR — those are different layers and would fail KS on overhead alone.
- Compare only **normalised shape**: divide each per-second series by the **mean of its active (non-zero) seconds**,
  then compare. Not the median: per-UE series are mostly OFF, so the median is 0 (rev-1 error). Never compare
  absolute rate (scheduler/capacity differ).
- Same "active second" and "session" definitions on both sides: active = UL grant bytes > 0 in that second; the
  twin's MAC series is cut into sessions with the same 10 s silence rule as Madrid, so both sides are truncated alike (OFF ≤ 10 s).
- Validation runs are **dedicated long benign runs** (≥ 10 min per profile, several seeds), not the 30–60 s dataset
  phases, so each statistic has enough samples.

### 6.2 Statistics per band (rev 3, 2026-10-31)
Only statistics measurable on the fragmented Madrid per-UE data (§3.1 caveats). All on the normalised series (§6.1).

| # | statistic | checks |
|---|---|---|
| 1 | KS `D` on the active-second UL rate | level distribution |
| 2 | KS `D` on the active-second DL rate (§4.E) | DL level distribution |
| 3 | KS `D` on the per-second DL/UL byte ratio (seconds with both directions active) | UL↔DL coupling |
| 4 | KS `D` on the ON-run length | burst timing |
| 5 | KS `D` on the OFF-gap length — distribution **conditional on OFF ≤ 10 s** (gaps > 10 s are session boundaries, not observed; truncated, not censored at 10) | silence timing |
| 6 | `d_ACF = Σ_{lag=1..10}(ρ_twin(lag) − ρ_real(lag))²`, sessions with wallclock ≥ 15 s on both sides | order in time |
| 7 | `|ρ_S,twin − ρ_S,real|`, ρ_S = Spearman between ON-run length and mean rate in that run | the one joint dependence the 1-D tests miss |
| 8 | **P4 only**: Anderson–Darling k-sample statistic (`scipy.stats.anderson_ksamp`, midrank; statistic only — its p-value is capped to [0.001, 0.25]) | tail of the heavy band |
| 9 | **P4 only**: `|q99_twin − q99_real|` of the normalised UL rate; dropped if P4 has < a few hundred validation samples (q99 too noisy) | tail of the heavy band |

Family size k = 7 per band (9 for P4), 30 over all bands. ON/OFF keep KS rather than TVD: ties are handled by the
bootstrap bar (§6.3), and a smaller k keeps power. Per test, `D` is read as: *at some threshold x, the shares of
samples ≤ x differ by D; everywhere else by less.*

*Optional, cell level only*: Hurst of the summed UL of the cell vs Madrid cell-level H — context, not gated.

### 6.3 Threshold: cluster bootstrap + max-statistic (rev 3, 2026-10-31)
- Use the statistics' **magnitudes**, never p-values (Madrid n is huge, p ≈ 0 always). Bonati et al. state only "K-S
  distance below a user-defined threshold" and report no D or sample size, so no number of ours is set beside theirs;
  the difference claimed is a data-derived, family-wise bar.
- **Null = real vs real at the twin's size.** The twin (n samples in a band) is compared with the full real data of the
  band, so the null draws n samples from build cell A and compares them with **all** of build cell B. Pairs within the
  same group (I or II) are preferred, since the groups differ (UL share ≈ 30–40 % vs ≈ 90 %); τ is reported per pair.
- **Cluster bootstrap.** Seconds of one user are not independent, so resampling single seconds makes the bar too tight.
  Draw whole **RNTIs** (the closest thing to a user; RNTI reuse merges users, which is conservative) with replacement
  until n seconds are reached; truncate the last cluster to exactly n. On the twin side the cluster is one draw
  (run, UE, phase).
- **Max-statistic (family-wise bar).** k tests at α each would fail a perfect twin with probability up to
  1 − 0.95^k (≈ 56 % for k = 16, if independent). Per bootstrap replicate m:
  1. compute all k statistics on the same resample (keeps their correlation);
  2. turn each into its percentile within its own bootstrap distribution;
  3. `T_m = max_i percentile_i`.
  With M = 1000 replicates, `τ* = Q_0.95(T_m)`. The twin passes iff every statistic's percentile ≤ τ*.
  Less conservative than Bonferroni (`1 − α/k`), because correlated tests are not counted as independent.
- **Family scope.** In the tuning loop: per band (one band is tuned at a time). In the held-out check: all bands
  together (k = 30), because the claim is about the whole twin.
- **Diagnosis on failure.** Report the test with the highest percentile; for KS tests `scipy.stats.ks_2samp(twin,
  real)` gives `statistic_location` and `statistic_sign` (SciPy ≥ 1.10; `.venv-ml` has 1.18.1): sign = +1 → the twin's
  CDF is higher at x → the twin is lighter there → raise load (−1: the reverse). One point only: a body/tail mismatch
  shows in tests 8–9. Tuning knobs: inside-ON process, app size prior, the band's ON/OFF source lists.
- **Split to avoid fitting the test**: 4 build cells for profiles and the tuning loop; the 2 held-out cells
  (I-796, II-2650) are used **once**, for the final check, and that result is reported as it is. The tuning loop
  "until it passes" can pass by luck; the single held-out check is what guards against that.
- Report: family pass/fail, every test's percentile, τ*, n per band, τ per cell pair. Family-wise control lowers
  the power of each test, so per-test results are always shown too.

### 6.4 Attack-side validation (separate claim)
- Validate the hping3 flood *shape* against 5G-NIDD / IoT-23: KS on packet-size and, for flows that cross a 5G
  stack, on the per-flow proto/size seen at the UPF — i.e. "the flood's observable features survive the 5G stack",
  not "the testbed scheduler reproduces 5G-NIDD's jitter".
- This is a *shape* check of our hping3 configuration, **not** a claim that attack frequency is realistic. The
  headline attack claim is robustness across the L1/L2/L3 boundary under an adaptive attacker (Kerckhoffs), reported
  as a delay-vs-false-alarm curve per evasion level.

---

## 7. Parameter provenance (what is real / assumed / synthetic)

| element | real (measured) | assumption (documented) | synthetic (generated) |
|---|---|---|---|
| benign long-run rate per UE | Madrid session-mean UL dist (per band) | LTE→RFsim scaling choice | per-second rate series |
| benign ON level | Madrid active-second UL dist (used as check) | `r_on = r̄ / duty` | — |
| benign packet size | Korean per-app UL size distribution | app↔profile mapping | per-packet sizes |
| benign ON/OFF | Madrid ON-run / OFF-gap (empirical, resampled) | OFF censored at 10 s (both sides) | ON/OFF schedule |
| benign burstiness | short-lag ACF of Madrid per-UE series | inside-ON process per profile | — |
| cell-level Hurst | Madrid repo figure (cell aggregate; not re-measured) | context only, not gated | — |
| profile mix | Madrid band frequencies (recorded) | P4 oversampled on purpose | — |
| benign DL rate / ratio | Madrid per-UE DL bytes; Korean per-app DL | `r̄_DL = ρ·r̄_UL`, ρ from Madrid band | DN→UE per-second series |
| benign DL ON/OFF | Madrid DL activity runs | drawn independently of UL ON/OFF | DL schedule |
| concurrency | Madrid ~17/s (recorded) | not reproduced (2 UEs) | — |
| L3 benign counterpart | — | heavy-UL TCP benign (no real per-app anchor) | upload/sync flow |
| attack packet shape | 5G-NIDD + IoT-23 | hping3 == Mirai shape | flood packets |
| attack rate | anchored to Madrid percentiles | — | — |
| attack onset/duration/ramp | — | adaptive-attacker space | randomised |
| evasion L1/L2/L3 | behaviour from benign real | levels are our construction | — |
| KPM/URR/profiler | testbed physics | — | — |

---

## 8. End-to-end execution steps

0. **Decisions D1, D2** (§4.D); under D1-a download + reduce the other 5 Madrid BS one at a time (disk). *~0.5 day.*
1. **Madrid per-UE profiles** — first measure T_inact, the RNTI allocation rule and the reuse interval on the raw ms data of the build cells (§3.1a) and set the session cut from them; extend `madrid_reduce.py`/`madrid_profile.py` to the build set; emit
   `benign_profiles.json` per band: session-mean inverse-CDF (`r̄`), active-second dist (check), empirical ON-run and
   OFF-gap arrays, band frequency, short-lag ACF reference, and the DL side (DL/UL ratio ρ, DL ON/OFF, §4.E).
   Reduction: `research/twinning/madrid_reduce.py` (rev 2: streams, keeps UL **and** DL per (rnti, s), zstd;
   ≈ 0.25–0.3 GB per cell). Malformed head/tail rows (NaN or out-of-range epoch) are dropped and counted:
   I-796 22, II-2650 3, II-816 1, I-1815 0, I-2650 0. Spans: I-2650 1344 h, I-1815 1880 h, I-796 302 h, II-2650
   469 h, II-816 434 h, II-1835 380 h (0 dropped). Active second = bytes > 0 (§6.1); rev 1 counted 0-byte grants as active (§3.1 note).
   *~1 day.*
2. **Korean size/IAT priors** — `inspect_kr5g.py` → per-app empirical UL size distribution and proto mix into the
   same JSON. *~0.5 day.*
3. **Attack references** — finalise flood shapes (`out_5gnidd_bs1.txt`, IoT-23 pcap stats) into `attack_shapes.json`;
   confirm the hping3 configuration matches (§6.4). *~0.5 day.*
4. **Code changes** (§4.C): `onoff_k1`, app size prior, `planbuilder` profile resolution, tests. v4 paths untouched
   (`check_reproducible.py` must still pass on a v4 design). *~1 day.*
5. **Wire into scenarios** — new `ds-benign-twin.yaml` + `ds-flood-twin.yaml` using `profile:` specs; add θ fields
   (evasion level, react), the L3 heavy-UL TCP benign counterpart, the P1–P4 mix. *~0.5–1 day.*
6. **MAC-stats collection** — add per-UE gNB UL-grant bytes to the run harness (validation only). *~1 day.*
7. **Run + validate** — dedicated long benign runs per profile on the build set, tune to pass §6.2–6.3 (size-matched
   bar); then the single held-out check. *~1.5–2 days.*
8. **Generate the twinned dataset** — benign-twin + load-matched attack (L1–L3, react variants) + the existing
   tamper/outage injection; this replaces the v4/v5 benign basis with a grounded one. *~2 days.*

Everything downstream (the DRL replay environment, baselines) consumes this dataset unchanged.

## 9. Limitations (state them, do not paper over)
- Madrid is **LTE**, not 5G NR; we twin *user demand* (rate/timing), which is largely RAT-independent, while the gNB
  scheduler and capacity are the testbed's own. No public 5G per-UE commercial trace exists (checked 2026-10-28).
- TBS includes retransmissions/padding; RNTI reuse fragments long sessions → session *duration* is unreliable (rate
  and micro-ON/OFF are not).
- Korean app↔Madrid profile mapping is a modelling choice.
- Only 2 UEs: cell concurrency and Crossfire harm are argued, not reproduced in RFsim.
- OFF gaps longer than 10 s and session durations cannot be estimated from Madrid (session rule + RNTI reuse); the
  twin is validated only up to that horizon, and per-UE long-range dependence (Hurst) is not claimed.
- If D1-b is taken, the held-out set is a later period of the same cell, not another cell.
- The benign mix oversamples P4 (§4.B); results are also reported re-weighted to the Madrid band frequencies.
- The L3 benign counterpart (heavy-UL TCP) has no per-app real anchor.
- Attack *frequency/prevalence* is never claimed realistic; only the attack *shape* (vs real malware/5G floods) and
  detector *robustness* across evasion levels are.
