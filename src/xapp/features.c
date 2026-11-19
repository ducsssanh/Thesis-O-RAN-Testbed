/* features layer of the defense (see defense_internal.h): cell load, the
   feature vector of a KPM sample, the window per SUPI and the dataset file */
#include "defense_internal.h"
#include "urr_receiver.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define CELL_WINDOW_US 1500000LL /* other UEs' latest sample counts towards the cell load */

/* latest PRB share of every UE per E2 node, for the cell load */
typedef struct {
  bool used;
  char node[32];
  uint64_t amf;
  int64_t collect_us;
  double prb_ul, prb_dl, rate_ul, rate_dl;
} cell_ue_t;

static cell_ue_t cell_ues[MAX_UES];
static FILE *dataset;

/* Per UE, the last seconds of KPM and core bytes. The two sides close their
   seconds about 20 ms apart, so bytes at a second boundary land in different
   seconds (research/twinning/ct_root_cause). Summing a few seconds cancels the
   inner boundaries; a real scaling of KPM stays in the sum. */
#define GATE_RING 8
/* KPM trust is per UE: tampering hides or frames one UE, and the other UEs of the gNB keep their own evidence */
static struct { char supi[96]; int64_t sec[GATE_RING]; double kpm[GATE_RING], core[GATE_RING]; double trust; bool masked; } gate_ues[MAX_UES];

static int gate_ue_slot(const char *supi) {
  for (int i = 0; i < MAX_UES; i++) {
    if (!gate_ues[i].supi[0]) {
      snprintf(gate_ues[i].supi, sizeof(gate_ues[i].supi), "%s", supi);
      gate_ues[i].trust = 1.0;
    }
    if (strcmp(gate_ues[i].supi, supi) == 0) return i;
  }
  return -1;
}

double features_kpm_trust(const char *supi) {
  const int i = gate_ue_slot(supi);
  return i < 0 ? 1.0 : gate_ues[i].trust;
}

bool features_kpm_masked(const char *supi) {
  const int i = gate_ue_slot(supi);
  return i >= 0 && gate_ues[i].masked;
}

static void gate_window(const char *supi, int64_t t, double kpm, double core, double *sum_kpm, double *sum_core, int *n) {
  const int u = gate_ue_slot(supi);
  *sum_kpm = kpm; *sum_core = core; *n = 1;
  if (u < 0) return;
  const int slot = (int)(t % GATE_RING);
  gate_ues[u].sec[slot] = t; gate_ues[u].kpm[slot] = kpm; gate_ues[u].core[slot] = core;
  *sum_kpm = 0; *sum_core = 0; *n = 0;
  for (int k = 0; k < cfg.gate_window_s; k++) {
    const int j = (int)((t - k) % GATE_RING);
    if (gate_ues[u].sec[j] != t - k) continue;
    *sum_kpm += gate_ues[u].kpm[j]; *sum_core += gate_ues[u].core[j]; (*n)++;
  }
}

/* Two signals. c_t, one second: soft, logged at once, no action. c_t_w, the same
   ratio over gate_window_s seconds: updates the trust of this UE, which masks its KPM. A second
   with no bytes on either side, or a sum below the byte floor, says nothing. */
static void gate_sample(features_t *f, const char *supi) {
  const profile_record_t *p = &f->prof;
  const double w = p->window_ms ? p->window_ms / 1000.0 : 1.0;
  const double kpm = f->rate_ul * 125.0; /* kbit/s -> bytes/s */
  double core = ((double)p->ul_bytes - cfg.gate_beta * (double)p->ul_pkts) / w;
  if (core < 0) core = 0;
  f->c_t = log((kpm + cfg.gate_eps_bytes) / (core + cfg.gate_eps_bytes));
  f->has_gate = true;
  double sum_kpm, sum_core;
  int n;
  gate_window(supi, (int64_t)p->time_unix, kpm, core, &sum_kpm, &sum_core, &n);
  const double eps = cfg.gate_eps_bytes * n;
  f->c_t_w = log((sum_kpm + eps) / (sum_core + eps));
  const int i = gate_ue_slot(supi);
  if (i < 0 || (kpm <= 0 && core <= 0) || (sum_kpm < eps && sum_core < eps)) return;
  const bool in_band = f->c_t_w >= cfg.gate_lo && f->c_t_w <= cfg.gate_hi;
  gate_ues[i].trust += cfg.gate_alpha * ((in_band ? 1.0 : 0.0) - gate_ues[i].trust);
  const bool masked = gate_ues[i].masked ? gate_ues[i].trust < cfg.gate_trust_min + 0.05 : gate_ues[i].trust < cfg.gate_trust_min;
  if (masked != gate_ues[i].masked) {
    gate_ues[i].masked = masked;
    policy_flag_ue(supi, f->node, gate_ues[i].trust, masked, f->c_t);
  }
}

bool features_core_ready(const features_t *f) { return f->has_profile && f->profile_offset_s == 0; }

double features_core_ul_kbps(const features_t *f) {
  const double w = f->prof.window_ms ? f->prof.window_ms / 1000.0 : 1.0;
  return f->prof.ul_bytes * 8 / 1000.0 / w;
}

double features_core_dl_kbps(const features_t *f) {
  const double w = f->prof.window_ms ? f->prof.window_ms / 1000.0 : 1.0;
  return f->prof.dl_bytes * 8 / 1000.0 / w;
}

static void write_line(const ue_t *u, features_t *f);

int features_open(const char *path) {
  if (path && !(dataset = fopen(path, "a"))) {
    fprintf(stderr, "[defense] cannot open %s\n", path);
    return -1;
  }
  return 0;
}

void features_close(void) {
  if (dataset) fclose(dataset);
  dataset = NULL;
}

/* raw KPM tap: one JSON line per KPM indication, BEFORE any windowing/join,
   carrying source_ts (collect) and arrival_ts (now) for a causal offline build. */
static FILE *raw_kpm;

int features_raw_open(const char *path) {
  if (path && !(raw_kpm = fopen(path, "a"))) {
    fprintf(stderr, "[defense] cannot open %s\n", path);
    return -1;
  }
  return 0;
}

void features_raw_close(void) {
  if (raw_kpm) fclose(raw_kpm);
  raw_kpm = NULL;
}

void features_raw_write(const char *supi, const sample_t *s, const features_t *f, int64_t now_us) {
  if (!raw_kpm) return;
  json_object *o = json_object_new_object();
  json_object_object_add(o, "source_ts", json_object_new_double(s->collect_us / 1e6));
  json_object_object_add(o, "arrival_ts", json_object_new_double(now_us / 1e6));
  json_object_object_add(o, "supi", json_object_new_string(supi));
  json_object_object_add(o, "amf_ue_ngap_id", json_object_new_uint64(s->amf));
  json_object_object_add(o, "rate_ul_kbps", json_object_new_double(f->rate_ul));
  json_object_object_add(o, "rate_dl_kbps", json_object_new_double(f->rate_dl));
  json_object_object_add(o, "thp_ul_kbps", json_object_new_double(f->thp_ul));
  json_object_object_add(o, "thp_dl_kbps", json_object_new_double(f->thp_dl));
  json_object_object_add(o, "prb_ul_pct", json_object_new_double(f->prb_ul));
  json_object_object_add(o, "prb_dl_pct", json_object_new_double(f->prb_dl));
  json_object_object_add(o, "cell_prb_ul_pct", json_object_new_double(f->cell_ul));
  json_object_object_add(o, "cell_prb_dl_pct", json_object_new_double(f->cell_dl));
  if (s->tamper > 0) { /* tampered: the values above as the defense saw them, the reported ones too */
    json_object_object_add(o, "tamper_factor", json_object_new_double(s->tamper));
    json_object_object_add(o, "raw_rate_ul_kbps", json_object_new_double(s->raw_rate_ul));
    json_object_object_add(o, "raw_rate_dl_kbps", json_object_new_double(s->raw_rate_dl));
    json_object_object_add(o, "raw_thp_ul_kbps", json_object_new_double(s->raw_thp_ul));
    json_object_object_add(o, "raw_thp_dl_kbps", json_object_new_double(s->raw_thp_dl));
    json_object_object_add(o, "raw_prb_ul_pct", json_object_new_double(s->raw_prb_ul));
    json_object_object_add(o, "raw_prb_dl_pct", json_object_new_double(s->raw_prb_dl));
  }
  fputs(json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN), raw_kpm);
  fputc('\n', raw_kpm);
  fflush(raw_kpm);
  json_object_put(o);
}

/* record a UE's PRB share (every sample of a batch first, so UEs reported in
   the same period see each other) */
void features_observe(const sample_t *s) {
  cell_ue_t *slot = NULL;
  for (int i = 0; i < MAX_UES; i++) {
    cell_ue_t *c = &cell_ues[i];
    if (c->used && c->amf == s->amf && strcmp(c->node, s->node) == 0) { slot = c; break; }
    if (!slot || !c->used || (slot->used && c->collect_us < slot->collect_us)) slot = c; /* free, else oldest */
  }
  *slot = (cell_ue_t){.used = true, .amf = s->amf, .collect_us = s->collect_us, .prb_ul = s->prb_ul, .prb_dl = s->prb_dl,
                      .rate_ul = s->rate_ul, .rate_dl = s->rate_dl};
  snprintf(slot->node, sizeof(slot->node), "%s", s->node);
}

static void cell_load(features_t *f) {
  for (int i = 0; i < MAX_UES; i++) {
    const cell_ue_t *c = &cell_ues[i];
    if (!c->used || strcmp(c->node, f->node) != 0 || llabs(c->collect_us - f->collect_us) > CELL_WINDOW_US) continue;
    f->cell_ul += c->prb_ul;
    f->cell_dl += c->prb_dl;
    if (c->amf == f->amf) continue;
    f->others_ul += c->rate_ul >= cfg.other_ue_kbps;
    f->others_dl += c->rate_dl >= cfg.other_ue_kbps;
  }
}

/* URR of the SUPI for the second the KPM sample measured (PFCP End Time =
   KPM collect time rounded): usage since the previous report (PERIO 1 s), as
   rates. URR arrives 1-2 s after KPM, so a vector usually gets it on a later
   pass (features_fill_urr). Until the report of that second arrives, a report
   one second off stands in (urr_offset_s), replaced once the right one is in. */
static void core_usage(features_t *f, const char *supi) {
  urr_record_t r;
  int64_t received_us = 0;
  const uint64_t t = (uint64_t)((f->collect_us + 500000) / 1000000);
  int off = 0;
  if (!urr_receiver_supi_at(supi, t, &r, &received_us)) {
    if (f->has_urr) return; /* keep the stand-in */
    if (urr_receiver_supi_at(supi, t - 1, &r, &received_us)) off = -1;
    else if (urr_receiver_supi_at(supi, t + 1, &r, &received_us)) off = 1;
    else return;
  }
  const double d = r.interval_seconds ? (double)r.interval_seconds : 1.0; /* not duration_seconds: cumulative in OAI */
  f->has_urr = true;
  f->urr_offset_s = off;
  f->urr_age_s = (received_us - f->collect_us) / 1e6; /* arrival lag behind the KPM sample */
  f->urr_ul_kbps = r.ul_bytes * 8 / 1000.0 / d;
  f->urr_dl_kbps = r.dl_bytes * 8 / 1000.0 / d;
  f->urr_ul_pps = r.ul_packets / d;
  f->urr_dl_pps = r.dl_packets / d;
  if (r.session_epoch[0]) {
    f->seid = r.seid;
    snprintf(f->session_epoch, sizeof(f->session_epoch), "%s", r.session_epoch);
    snprintf(f->session_source, sizeof(f->session_source), "urr");
  }
}

/* UPF packet mix of the same second, the same order as core_usage:
   exact second, else one second off as a stand-in */
static void core_profile(features_t *f, const char *supi) {
  profile_record_t p;
  int64_t received_us = 0;
  const uint64_t t = (uint64_t)((f->collect_us + 500000) / 1000000);
  int off = 0;
  if (!urr_receiver_profile_at(supi, t, &p, &received_us)) {
    if (f->has_profile) return;
    if (urr_receiver_profile_at(supi, t - 1, &p, &received_us)) off = -1;
    else if (urr_receiver_profile_at(supi, t + 1, &p, &received_us)) off = 1;
    else return;
  }
  f->has_profile = true;
  f->profile_offset_s = off;
  f->profile_age_s = (received_us - f->collect_us) / 1e6;
  f->prof = p;
  if (off == 0) gate_sample(f, supi);
}

/* Feature vector of a sample, appended to the window of its SUPI; NULL when
   the UE ID has no SUPI yet (counted in unlabelled) */
ue_t *features_build(const sample_t *s, int64_t now, features_t **out) {
  char supi[96] = "";
  if (!urr_receiver_supi_for_ue(s->amf, supi, sizeof(supi))) {
    unlabelled++;
    return NULL;
  }
  ue_t *u = ue_for(supi, true);
  if (!u) return NULL;
  u->amf = s->amf;
  u->last_seen_us = now;
  u->rate_ul = s->rate_ul;
  u->rate_dl = s->rate_dl;
  snprintf(u->node, sizeof(u->node), "%s", s->node);

  features_t *f = &u->win[u->win_head];
  if (u->win_len == WINDOW_MAX && f->decided && !f->logged) write_line(u, f); /* overdue: window full */
  u->win_head = (u->win_head + 1) % WINDOW_MAX;
  if (u->win_len < WINDOW_MAX) u->win_len++;
  *f = (features_t){.seq = ++u->seq, .at_us = now, .collect_us = s->collect_us, .amf = s->amf, .rate_ul = s->rate_ul,
                    .rate_dl = s->rate_dl, .thp_ul = s->thp_ul, .thp_dl = s->thp_dl, .prb_ul = s->prb_ul, .prb_dl = s->prb_dl,
                    .cls = u->cls, .limit_ul = cfg.classes[u->cls].ul_rate_kbps, .limit_dl = cfg.classes[u->cls].dl_rate_kbps,
                    .level = u->level, .limited = u->applied_ratio > 0 && u->synced_amf == s->amf};
  snprintf(f->node, sizeof(f->node), "%s", s->node);
  const int gate = gate_ue_slot(supi);
  f->kpm_trust = gate < 0 ? 1.0 : gate_ues[gate].trust;
  f->kpm_masked = gate >= 0 && gate_ues[gate].masked;
  snprintf(f->core_action, sizeof(f->core_action), "%s", u->core_applied[0] ? u->core_applied : "none");
  cell_load(f);
  urr_receiver_session_of(supi, &f->seid, f->session_epoch, sizeof(f->session_epoch), f->session_source, sizeof(f->session_source));
  core_usage(f, supi);
  core_profile(f, supi);
  *out = f;
  return u;
}

/* give the recent vectors of a SUPI the URR that has arrived since */
void features_fill_urr(ue_t *u, int64_t now) {
  for (int i = 0; i < u->win_len; i++) {
    features_t *f = &u->win[i];
    const int64_t age = now - f->collect_us;
    if (age <= (int64_t)(cfg.urr_max_age_s * 1e6) && (!f->has_urr || f->urr_offset_s)) core_usage(f, u->supi);
    if (age <= (int64_t)(cfg.core_max_age_s * 1e6) && (!f->has_profile || f->profile_offset_s)) core_profile(f, u->supi);
  }
}

/* newest vector of a SUPI that has URR (NULL if none) */
const features_t *features_latest_urr(const ue_t *u) {
  const features_t *best = NULL;
  for (int i = 0; i < u->win_len; i++)
    if (u->win[i].has_urr && (!best || u->win[i].seq > best->seq)) best = &u->win[i];
  return best;
}

/* newest vector of a SUPI with the UPF profile of its own second (NULL if none) */
const features_t *features_latest_profile(const ue_t *u) {
  const features_t *best = NULL;
  for (int i = 0; i < u->win_len; i++)
    if (features_core_ready(&u->win[i]) && (!best || u->win[i].seq > best->seq)) best = &u->win[i];
  return best;
}

/* the latest n vectors of a SUPI, oldest first */
void features_window(const ue_t *u, int n, window_t *w) {
  if (n > u->win_len) n = u->win_len;
  if (n > WINDOW_MAX) n = WINDOW_MAX;
  w->n = n;
  w->since_seq = u->since_seq;
  for (int i = 0; i < n; i++) w->v[i] = &u->win[(u->win_head - n + i + 2 * WINDOW_MAX) % WINDOW_MAX];
}

json_object *features_json(const features_t *f, const char *supi) {
  json_object *o = json_object_new_object();
  json_object_object_add(o, "supi", json_object_new_string(supi));
  json_object_object_add(o, "seq", json_object_new_uint64(f->seq));
  json_object_object_add(o, "at_ms", json_object_new_int64(f->at_us / 1000));
  json_object_object_add(o, "collect_ms", json_object_new_int64(f->collect_us / 1000));
  json_object_object_add(o, "amf_ue_ngap_id", json_object_new_uint64(f->amf));
  json_object_object_add(o, "e2_node", json_object_new_string(f->node));
  json_object_object_add(o, "rate_ul_kbps", json_object_new_double(f->rate_ul));
  json_object_object_add(o, "rate_dl_kbps", json_object_new_double(f->rate_dl));
  json_object_object_add(o, "thp_ul_kbps", json_object_new_double(f->thp_ul));
  json_object_object_add(o, "thp_dl_kbps", json_object_new_double(f->thp_dl));
  json_object_object_add(o, "prb_ul_pct", json_object_new_double(f->prb_ul));
  json_object_object_add(o, "prb_dl_pct", json_object_new_double(f->prb_dl));
  json_object_object_add(o, "cell_prb_ul_pct", json_object_new_double(f->cell_ul));
  json_object_object_add(o, "cell_prb_dl_pct", json_object_new_double(f->cell_dl));
  json_object_object_add(o, "others_ul", json_object_new_int(f->others_ul));
  json_object_object_add(o, "others_dl", json_object_new_int(f->others_dl));
  json_object_object_add(o, "class", json_object_new_string(cfg.classes[f->cls].name));
  json_object_object_add(o, "limit_ul_kbps", json_object_new_double(f->limit_ul));
  json_object_object_add(o, "limit_dl_kbps", json_object_new_double(f->limit_dl));
  if (f->has_urr) {
    json_object_object_add(o, "urr_age_s", json_object_new_double(f->urr_age_s));
    json_object_object_add(o, "urr_offset_s", json_object_new_int(f->urr_offset_s));
    json_object_object_add(o, "urr_ul_kbps", json_object_new_double(f->urr_ul_kbps));
    json_object_object_add(o, "urr_dl_kbps", json_object_new_double(f->urr_dl_kbps));
    json_object_object_add(o, "urr_ul_pps", json_object_new_double(f->urr_ul_pps));
    json_object_object_add(o, "urr_dl_pps", json_object_new_double(f->urr_dl_pps));
  }
  if (f->has_profile) {
    const profile_record_t *p = &f->prof;
    const double w = p->window_ms ? p->window_ms / 1000.0 : 1.0;
    json_object_object_add(o, "prof_age_s", json_object_new_double(f->profile_age_s));
    json_object_object_add(o, "prof_offset_s", json_object_new_int(f->profile_offset_s));
    json_object_object_add(o, "prof_ul_kbps", json_object_new_double(p->ul_bytes * 8 / 1000.0 / w));
    json_object_object_add(o, "prof_dl_kbps", json_object_new_double(p->dl_bytes * 8 / 1000.0 / w));
    json_object_object_add(o, "prof_ul_pps", json_object_new_double(p->ul_pkts / w));
    json_object_object_add(o, "prof_dl_pps", json_object_new_double(p->dl_pkts / w));
    json_object_object_add(o, "prof_ul_mean_bytes", json_object_new_double(p->ul_pkts ? (double)p->ul_bytes / p->ul_pkts : 0));
    json_object_object_add(o, "prof_dl_mean_bytes", json_object_new_double(p->dl_pkts ? (double)p->dl_bytes / p->dl_pkts : 0));
    struct { const char *k; uint64_t v; } c[] = {{"prof_ul_tcp", p->ul_tcp}, {"prof_ul_tcp_syn", p->ul_tcp_syn}, {"prof_ul_udp", p->ul_udp},
        {"prof_ul_icmp", p->ul_icmp}, {"prof_ul_frag", p->ul_frag}, {"prof_ul_dns", p->ul_dns}, {"prof_ul_gtp_in_gtp", p->ul_gtp_in_gtp},
        {"prof_dl_tcp", p->dl_tcp}, {"prof_dl_tcp_syn", p->dl_tcp_syn}, {"prof_dl_udp", p->dl_udp}, {"prof_dl_icmp", p->dl_icmp},
        {"prof_dl_frag", p->dl_frag}};
    for (size_t i = 0; i < sizeof(c) / sizeof(*c); i++) json_object_object_add(o, c[i].k, json_object_new_uint64(c[i].v));
    json_object_object_add(o, "prof_ul_dst_estimate", json_object_new_double(p->ul_dst_estimate));
  }
  if (f->has_gate) {
    json_object_object_add(o, "c_t", json_object_new_double(f->c_t));
    json_object_object_add(o, "c_t_w", json_object_new_double(f->c_t_w));
  }
  json_object_object_add(o, "kpm_trust", json_object_new_double(f->kpm_trust));
  json_object_object_add(o, "kpm_masked", json_object_new_boolean(f->kpm_masked));
  if (f->session_epoch[0]) {
    json_object_object_add(o, "seid", json_object_new_uint64(f->seid));
    json_object_object_add(o, "session_epoch", json_object_new_string(f->session_epoch));
    json_object_object_add(o, "session_source", json_object_new_string(f->session_source));
  }
  json_object_object_add(o, "level", json_object_new_int(f->level));
  json_object_object_add(o, "limited", json_object_new_boolean(f->limited));
  json_object_object_add(o, "core_action", json_object_new_string(f->core_action));
  return o;
}

/* the classifier output and the decision of a vector (0: none); its dataset
   line waits for the URR of the same second (features_flush) */
void features_log(const ue_t *u, features_t *f, const cls_result_t *r, uint64_t decision_id) {
  (void)u;
  f->decided = true;
  f->urr_at_decision = f->has_urr;
  f->has_result = r != NULL;
  if (r) {
    f->label = r->label;
    f->score = r->score;
    snprintf(f->source, sizeof(f->source), "%s", r->source);
    snprintf(f->kind, sizeof(f->kind), "%s", r->kind);
  }
  f->decision_id = decision_id;
}

static void write_line(const ue_t *u, features_t *f) {
  f->logged = true;
  if (!dataset) return;
  json_object *o = features_json(f, u->supi);
  json_object_object_add(o, "urr_at_decision", json_object_new_boolean(f->urr_at_decision));
  if (f->has_result) {
    json_object_object_add(o, "label", json_object_new_string(label_name(f->label)));
    json_object_object_add(o, "score", json_object_new_double(f->score));
    json_object_object_add(o, "source", json_object_new_string(f->source));
    if (f->kind[0]) json_object_object_add(o, "kind", json_object_new_string(f->kind));
  }
  if (f->decision_id) json_object_object_add(o, "decision_id", json_object_new_uint64(f->decision_id));
  fputs(json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN), dataset);
  fputc('\n', dataset);
  json_object_put(o);
}

/* write the decided vectors of a SUPI whose URR has arrived or is overdue
   (all: every decided vector, at shutdown), oldest first */
void features_flush(ue_t *u, int64_t now, bool all) {
  features_fill_urr(u, now);
  bool wrote = false;
  for (int i = 0; i < u->win_len; i++) {
    features_t *f = &u->win[(u->win_head - u->win_len + i + 2 * WINDOW_MAX) % WINDOW_MAX];
    if (!f->decided || f->logged) continue;
    const int64_t age = now - f->collect_us;
    if (!all && ((age <= (int64_t)(cfg.urr_max_age_s * 1e6) && (!f->has_urr || f->urr_offset_s)) ||
                 (age <= (int64_t)(cfg.core_max_age_s * 1e6) && (!f->has_profile || f->profile_offset_s) && urr_receiver_profile_active(u->supi))))
      break; /* wait for the URR and the UPF profile of the second; keep the order */
    write_line(u, f);
    wrote = true;
  }
  if (wrote && dataset) fflush(dataset);
}
