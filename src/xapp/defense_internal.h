#ifndef OAI_LAB_DEFENSE_INTERNAL_H
#define OAI_LAB_DEFENSE_INTERNAL_H
/* Layers of the defense in the xApp:
     features   one vector per SUPI and KPM sample (KPM, cell load, fair-use
                class, URR of the SUPI, state), a sliding window per SUPI and
                the dataset file
     classifier window -> {label, score, layer, kind}: the embedded model
                (clf_xgb.c) or the fair-use rule
     policy     evidence, score, levels, probation, expiry, reputation DB
     actuators  RAN actions (E2SM-RC) and core actions (UPF Security API)
                that bring the gNB and the UPF in line with the levels, and
                the verifier of their effect (KPM and URR)
   The classifier is the only layer that changes with the model. */
#include <json-c/json.h>
#include <sqlite3.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "urr_receiver.h" /* profile_record_t */
#include "clf_xgb.h"     /* embedded classifier state */

#define MAX_UES 64
#define MAX_CLASSES 8
#define WINDOW_MAX 32

/* fair-use class: the per-UE rate the subscriber is entitled to, a profile
   assigned per SUPI (used by the rule baseline) */
typedef struct {
  char name[16];
  double ul_rate_kbps, dl_rate_kbps;
} fair_class_t;

typedef struct {
  char supi[96];
  int cls;
} assign_t;

typedef struct {
  bool enabled;
  char profile[16];
  /* mean rate over the KPM period from DRB.PdcpSduVolume (DRB.UEThp is the
     rate while data is buffered, TS 28.552: a 2 Mbit/s UE reads 3.6 Mbit/s
     next to a flood); 0 disables a rule */
  fair_class_t classes[MAX_CLASSES]; /* [0] = default */
  int n_classes;
  assign_t assign[MAX_UES];  /* config supiClass; the DB policy table overrides */
  int n_assign;
  double ul_prb_pct, dl_prb_pct;
  /* a sample above the fair-use rate only counts while the cell is busy in
     that direction (sum of the UEs' PRB shares) and another UE sends in it:
     a UE alone in the cell gets ~all PRBs from the scheduler and harms nobody */
  bool congestion;
  double cell_ul_prb_pct, cell_dl_prb_pct, other_ue_kbps;
  int k, n;                   /* rules: k of the last n samples */
  /* classifier: the fair-use rule ("rules"), or "xgb": the embedded model
     (clf_xgb.c, file model_path) decides at t + delta_s per KPM second; the
     rules still give the per-layer hits */
  bool xgb;
  char model_path[256];
  /* actuate false: observe mode, every decision and level is computed and
     logged, no RAN or UPF action is sent (live detection test) */
  bool actuate;
  /* escalation by response: a UE rate-limited for grace_s
     that still offers UL above (1 + over_ratio) x its cap in k of the last
     n seconds (UPF profile, counted before the policy) goes to level 3 */
  bool esc_enabled;
  int esc_grace_s, esc_k, esc_n;
  double esc_over_ratio;
  /* relative threshold (2026-11-13, esc_rule.h): above max((1 + over_ratio) x cap, rel_ratio x the UE's own rate in
     its first ref_s active seconds at level 2); rel_ratio 0 = absolute rule. shadow: the rule runs and is logged
     (clf esc_would), the UE is not escalated (calibration runs) */
  double esc_rel_ratio;
  int esc_ref_s;
  bool esc_shadow;
  int window;                 /* feature vectors the rules look back over */
  int max_prb_ratio;          /* RAN action of levels 1-2 */
  /* action.mode "slice": levels 1-2 move the UE into a quarantine RAN slice
     whose members share max_prb_ratio (inter-slice handover in the gNB,
     PDU session kept), level 0 back to the default slice; "ue": a PRB
     quota on the UE itself */
  bool slice_mode;
  int q_sst, d_sst;
  int64_t q_sd, d_sd;
  /* end-to-end mitigation (2026-11-13): levels >= 3 move the UE into a
     second RAN slice, the block slice, with its own (lower) shared quota;
     b_sd 0 = levels >= 3 stay in the quarantine (limit) slice */
  int b_sst, block_prb_ratio;
  int64_t b_sd;
  /* level 2 = repeat offense: a violation within probation_s after the
     level-1 quota expired (PRB "quota full" cannot confirm: with spare PRBs
     the scheduler gives any active UE ~1/3 of the cell, so a benign UE also
     fills a 10 % quota) */
  int probation_s;
  int expiry_s[4];            /* levels 1-4 of the active profile; 0 = until reset */
  /* core layer: core rule of the fair-use classifier and the UPF
     actions of each level (1 monitor, 2 ratelimit at the class rate x
     ratelimit_factor, 3-4 block; 3 also releases the UE once, 4 at every
     attach). Levels >= 3 need KPM and URR evidence within fusion_s. */
  bool core;
  char upf_api[128];
  int upf_timeout_ms, upf_sync_s, upf_ttl_margin_s, upf_max_ttl_s;
  double ratelimit_factor, urr_max_age_s;
  /* level-2 UPF cap fixed for every UE (kbit/s), instead of the fair-use
     class rate x ratelimit_factor; 0 = class rate (2026-11-13: the class
     rate, 2 Mbit/s, is above every flood of the dataset) */
  double limit_ul_kbps, limit_dl_kbps;
  /* UPF profile of a KPM second: how long it is waited for and used (s) */
  double core_max_age_s;
  /* KPM trust gate: c_t = log((KPM + eps) / (max(B - beta*N, 0) + eps)) on UL
     bytes of one measurement second; honest while gate_lo <= c_t <= gate_hi.
     The profiler counts the whole frame, so beta is the per-packet headers
     above the IP PDU KPM counts. Trust of a UE: EWMA (gate_alpha) of its in-band
     share; its KPM is masked below gate_trust_min */
  double gate_beta, gate_eps_bytes, gate_lo, gate_hi, gate_alpha, gate_trust_min;
  int gate_window_s;          /* seconds summed for the trust update, 1..8 */
  int fusion_s, verify_s, release_every_s;
  /* levels 3-4 also release the UE (RRC); off: UPF block only (the OAI UE
     does not come back from a release within a run) */
  bool release_on_block;
  /* repeated attack labels while level >= 1: "refresh"
     refreshes the expiry and records evidence at most every
     evidence_interval_s (repeats counted); "every" records each label */
  bool repeat_every;
  int evidence_interval_s;
  double sev_rate, sev_repeat, half_life_s;
} config_t;

/* one KPM report of one UE, as queued by the FlexRIC callback */
typedef struct {
  uint64_t amf;
  int64_t collect_us;
  double rate_ul, rate_dl, thp_ul, thp_dl, prb_ul, prb_dl;
  char node[32];
  /* KPM tamper (emulated compromised E2 node): factor applied at
     ingest (0 = untouched) and the values as reported before it */
  double tamper;
  double raw_rate_ul, raw_rate_dl, raw_thp_ul, raw_thp_dl, raw_prb_ul, raw_prb_dl;
} sample_t;

typedef enum { LABEL_UNKNOWN = 0, LABEL_BENIGN, LABEL_SUSPICIOUS, LABEL_ATTACK } label_t;

/* feature vector: a KPM sample of a SUPI with its context (the classifier's
   input and one line of the dataset) */
typedef struct {
  uint64_t seq;               /* per SUPI, increasing */
  int64_t at_us, collect_us;
  uint64_t amf;
  char node[32];
  double rate_ul, rate_dl, thp_ul, thp_dl, prb_ul, prb_dl; /* kbit/s, % */
  double cell_ul, cell_dl;    /* summed PRB share of the cell */
  int others_ul, others_dl;   /* other UEs of the cell sending >= other_ue_kbps */
  int cls;                    /* fair-use class index */
  double limit_ul, limit_dl;  /* its rates, kbit/s */
  bool has_urr;               /* URR report of the same second (PFCP End Time ~ collect time) */
  int urr_offset_s;           /* 0, or -1/+1 while a report one second off stands in */
  double urr_age_s, urr_ul_kbps, urr_dl_kbps, urr_ul_pps, urr_dl_pps;
  /* UPF packet mix of the same second (oai-upf-profile), filled like URR */
  bool has_profile;
  int profile_offset_s;
  double profile_age_s;
  profile_record_t prof;
  /* KPM trust gate, from the profile of the same second only */
  bool has_gate;
  double c_t, c_t_w;          /* one second (soft signal); gate_window_s seconds (updates trust) */
  double kpm_trust;           /* of this UE, when the vector was built */
  bool kpm_masked;            /* this UE's KPM is not used (below gate_trust_min) */
  uint64_t seid;              /* PDU session: from the URR of the second, else the session table */
  char session_epoch[33], session_source[8];
  int level;
  bool limited;               /* in the quarantine slice / under a quota */
  char core_action[12];       /* UPF policy in force: none|monitor|ratelimit|block */
  /* dataset line, written once the URR of the second has arrived or
     urr_max_age_s has passed (features_flush) */
  bool decided, logged;
  bool urr_at_decision;       /* the URR was there when the vector was classified */
  bool has_result;            /* classifier ran (detection enabled) */
  label_t label;
  double score;
  char source[12], kind[32];
  uint64_t decision_id;
  bool clf_done;              /* scored by the embedded model */
} features_t;

typedef struct {
  const features_t *v[WINDOW_MAX]; /* oldest first */
  int n;
  uint64_t since_seq;         /* vectors up to this one were already decided on */
} window_t;

typedef struct {
  label_t label;
  double score;               /* 0..1 */
  char layer[8];              /* ran | core | both */
  char kind[32];              /* evidence kind, e.g. kpm_rate_ul */
  char reason[96];
  char source[12];            /* rules | xgb */
  bool uncongested;           /* above the class while the cell was not busy */
  /* rules over the whole window (since_seq ignored): fusion input of the
     policy, per layer */
  bool ran_hit, core_hit;
  /* level the embedded model asks for (2 rate limit, 3 block), 0 none; taken
     by the policy as is */
  int want_level;
} cls_result_t;

typedef struct {
  bool used;
  char supi[96];
  int level;
  int cls;                    /* fair-use class index */
  double score;
  int64_t score_us, expires_us, last_seen_us, next_try_us;
  int64_t probation_us;       /* repeat offense before this -> level 2 */
  double rate_ul, rate_dl;    /* latest sample (drain checks) */
  uint64_t amf;               /* UE ID of the latest KPM report */
  int applied_ratio;          /* quota in force at the gNB for synced_amf (0 none) */
  int64_t applied_sd;         /* RAN slice (SD) the UE was handed over to (slice mode) */
  uint64_t synced_amf;        /* UE ID whose gNB quota this xApp has set (0: unknown,
                                 e.g. after an xApp restart) */
  sqlite3_int64 last_action;  /* row of the latest quota action */
  bool verified;
  uint64_t decision_id;       /* latest decision on this SUPI */
  char node[32];              /* E2 node of the latest KPM report */
  /* escalation (policy_rules.h) */
  int peak;                   /* highest level of the current episode */
  int pending;                /* level capped by single-layer evidence */
  int64_t ran_hit_us, core_hit_us; /* latest window with k of n hits, per layer */
  int64_t evidence_us;        /* latest evidence row (repeat strategy) */
  unsigned repeats;           /* attack labels not recorded since then */
  /* core actuator: what the UPF holds for this SUPI (as far as we know) */
  char core_applied[12];      /* none|monitor|ratelimit|block */
  double core_rate_kbps;
  int64_t core_expires_us, core_since_us, core_next_try_us;
  bool core_verified, ran_core_checked, core_assist;
  bool release_pending;       /* entered level 3: one RRC release due (a level restored
                                 from the DB does not release again) */
  uint64_t released_amf;      /* UE ID released by the defense (levels 3-4) */
  int64_t released_us;
  int64_t ran_applied_us;     /* RAN limit set on synced_amf (URR verification) */
  /* embedded classifier and escalation by response */
  clf_state_t clf;
  int64_t limited_since_us;   /* level 2 entered (0: not at 2) */
  unsigned char esc_hist[32]; /* per second at level 2: offered UL above the cap */
  int esc_n, esc_head;
  double esc_ref[8];          /* first active seconds at level 2 (esc_rule.h ESC_REF_MAX) */
  int esc_ref_n;
  double esc_thr;             /* threshold of the last second (log) */
  double esc_offered;         /* offered UL of the last second the rule saw (-1: late) (log) */
  bool esc_would;             /* the rule fired this second (also in shadow mode) */
  uint64_t esc_seq;
  /* feature window */
  features_t win[WINDOW_MAX];
  int win_len, win_head;
  uint64_t seq, since_seq;
} ue_t;

extern config_t cfg;
extern ue_t ues[MAX_UES];
extern sqlite3 *db;
extern pthread_mutex_t st_lock;    /* cfg, ues, the counters below */
extern unsigned long long unlabelled, uncongested, dropped;

/* defense.c */
void iso(int64_t us, char *buf, size_t n);
void event(json_object *o);
json_object *event_base(const char *type, const ue_t *u, int64_t now);
void exec_sql(const char *sql);
int class_index(const char *name);

/* features.c */
int features_open(const char *path);
void features_close(void);
int features_raw_open(const char *path);
void features_raw_close(void);
void features_raw_write(const char *supi, const sample_t *s, const features_t *f, int64_t now_us);
void features_observe(const sample_t *s);
ue_t *features_build(const sample_t *s, int64_t now, features_t **out);
void features_window(const ue_t *u, int n, window_t *w);
void features_fill_urr(ue_t *u, int64_t now);
const features_t *features_latest_urr(const ue_t *u);
const features_t *features_latest_profile(const ue_t *u);
bool features_core_ready(const features_t *f);
double features_core_ul_kbps(const features_t *f);
double features_core_dl_kbps(const features_t *f);
double features_kpm_trust(const char *supi);
bool features_kpm_masked(const char *supi);
void features_log(const ue_t *u, features_t *f, const cls_result_t *r, uint64_t decision_id);
void features_flush(ue_t *u, int64_t now, bool all);
json_object *features_json(const features_t *f, const char *supi);

/* classifier.c (and the embedded model's tick) */
void classifier_tick(int64_t now);
int clf_log_open(const char *path);
void clf_log_close(void);
void classifier_classify(const window_t *w, cls_result_t *out);
json_object *classifier_state(void);
const char *label_name(label_t l);

/* policy.c */
ue_t *ue_for(const char *supi, bool create);
uint64_t policy_apply(ue_t *u, const features_t *f, const cls_result_t *r, int64_t now);
void policy_expire(int64_t now);
void policy_flag_ue(const char *supi, const char *node, double trust, bool masked, double c_t);
void policy_set_level(ue_t *u, int level, int64_t now, const char *why);
void policy_open_db(const char *path);
void policy_restore(void);

/* actuators.c */
void actuators_verify(ue_t *u, const features_t *f, int64_t now);
void actuators_reconcile(int64_t now);
void actuators_core_sync(int64_t now);
json_object *actuators_core_state(void);
const char *core_want(const ue_t *u, double *ul_kbps, double *dl_kbps);
#endif
