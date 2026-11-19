/* classifier layer of the defense (see defense_internal.h): the window of
   feature vectors of one SUPI in, a label out.
     "rules"   the fair-use rule: rate above the SUPI's class while the cell is
               busy, in k of the last n samples, measured by the RAN (KPM PDCP
               volume) and by the core (UPF profile of the SUPI); the label's
               layer is ran, core or both. Baseline, and the source of the
               per-layer hits the policy uses.
     "xgb"     the embedded model (clf_xgb.c), scored per KPM second at
               t + delta: gate, two alarm rules, escalation by response. */
#include "defense_internal.h"
#include "esc_rule.h"
#include "urr_receiver.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *label_name(label_t l) {
  return l == LABEL_BENIGN ? "benign" : l == LABEL_SUSPICIOUS ? "suspicious" : l == LABEL_ATTACK ? "attack" : "unknown";
}

static bool busy(const features_t *f, bool ul) {
  if (!cfg.congestion || f->kpm_masked) return true; /* the cell load comes from KPM */
  return ul ? f->cell_ul >= cfg.cell_ul_prb_pct && f->others_ul > 0 : f->cell_dl >= cfg.cell_dl_prb_pct && f->others_dl > 0;
}

/* RAN violation kind of one vector, NULL if none; *idle when above the class
   while the cell was not busy */
static const char *violation(const features_t *f, bool *idle) {
  *idle = false;
  /* KPM not trusted: this UE masked, or its UL above what the core
     counted (framing). Hiding needs no check here: it lowers the KPM rate */
  if (f->kpm_masked || (f->has_gate && f->c_t > cfg.gate_hi)) return NULL;
  bool busy_ul = busy(f, true), busy_dl = busy(f, false);
  bool rate_ul = f->limit_ul > 0 && f->rate_ul >= f->limit_ul, rate_dl = f->limit_dl > 0 && f->rate_dl >= f->limit_dl;
  bool over_ul = rate_ul || (cfg.ul_prb_pct > 0 && f->prb_ul >= cfg.ul_prb_pct);
  bool over_dl = rate_dl || (cfg.dl_prb_pct > 0 && f->prb_dl >= cfg.dl_prb_pct);
  *idle = false;
  if (over_ul && busy_ul) return rate_ul ? "kpm_rate_ul" : "kpm_prb_ul";
  if (over_dl && busy_dl) return rate_dl ? "kpm_rate_dl" : "kpm_prb_dl";
  *idle = over_ul || over_dl;
  return NULL;
}

/* core violation: the SUPI's rate at the UPF (profile of the same second)
   above its class, same busy-cell condition */
static const char *core_violation(const features_t *f) {
  if (!cfg.core || !features_core_ready(f)) return NULL;
  if (f->limit_ul > 0 && features_core_ul_kbps(f) >= f->limit_ul && busy(f, true)) return "core_rate_ul";
  if (f->limit_dl > 0 && features_core_dl_kbps(f) >= f->limit_dl && busy(f, false)) return "core_rate_dl";
  return NULL;
}

/* v1: per layer, the newest vector violates and k of the last n undecided
   ones do; ran_hit/core_hit count the whole window (fusion) */
static void rules(const window_t *w, cls_result_t *out) {
  *out = (cls_result_t){.label = LABEL_BENIGN, .layer = "ran", .source = "rules"};
  if (w->n == 0) return;
  bool idle;
  const features_t *last = w->v[w->n - 1];
  const features_t *last_core = NULL; /* the profile lags KPM: the newest vector that has it */
  for (int i = w->n - 1; i >= 0 && !last_core; i--)
    if (features_core_ready(w->v[i])) last_core = w->v[i];
  const char *kind = violation(last, &out->uncongested), *ckind = last_core ? core_violation(last_core) : NULL;
  int hits = 0, chits = 0, all = 0, call = 0, seen = 0, cseen = 0;
  for (int i = w->n - 1; i >= 0 && seen < cfg.n; i--, seen++) {
    bool v = violation(w->v[i], &idle) != NULL;
    all += v;
    if (w->v[i]->seq > w->since_seq) hits += v;
  }
  /* core: the last n vectors that have the profile of their second */
  for (int i = w->n - 1; i >= 0 && cseen < cfg.n; i--) {
    if (!features_core_ready(w->v[i])) continue;
    cseen++;
    bool c = core_violation(w->v[i]) != NULL;
    call += c;
    if (w->v[i]->seq > w->since_seq) chits += c;
  }
  out->ran_hit = all >= cfg.k;
  out->core_hit = call >= cfg.k;
  out->score = (double)(hits > chits ? hits : chits) / cfg.n;
  const bool ran = kind && hits >= cfg.k, core = ckind && chits >= cfg.k;
  if (!kind && !ckind) return;
  const bool by_ran = ran || (!core && kind); /* the layer that names the label */
  if (ran && core) snprintf(out->kind, sizeof(out->kind), "%s+core", kind);
  else snprintf(out->kind, sizeof(out->kind), "%s", by_ran ? kind : ckind);
  snprintf(out->layer, sizeof(out->layer), "%s", ran && core ? "both" : by_ran ? "ran" : "core");
  out->label = ran || core ? LABEL_ATTACK : LABEL_SUSPICIOUS;
  snprintf(out->reason, sizeof(out->reason), "KPM %d, core %d of the last %d samples above class %s", hits, chits, cfg.n,
           cfg.classes[last->cls].name);
}

void classifier_classify(const window_t *w, cls_result_t *out) { rules(w, out); }

json_object *classifier_state(void) {
  json_object *o = json_object_new_object();
  json_object_object_add(o, "kind", json_object_new_string(cfg.xgb ? "xgb" : "rules"));
  if (cfg.xgb) {
    json_object_object_add(o, "model", json_object_new_string(cfg.model_path));
    json_object_object_add(o, "model_ready", json_object_new_boolean(clf_ready()));
    json_object_object_add(o, "soft_rule", json_object_new_string(clf_soft_rule()));
    json_object_object_add(o, "soft_threshold", json_object_new_double(clf_soft_threshold()));
    json_object_object_add(o, "block_threshold", json_object_new_double(clf_block_threshold()));
  }
  json_object_object_add(o, "actuate", json_object_new_boolean(cfg.actuate));
  json_object_object_add(o, "window", json_object_new_int(cfg.window));
  return o;
}

/* ---------- embedded model (classifier.kind "xgb") ----------
   Scored per KPM second at t + delta_s (t = whole second of the KPM collect
   time), as the offline pipeline does: the UPF profile of that second counts
   only if it arrived by then. The 15 per-second inputs follow
   scripts/ml/episodes.py features() + clf_features.py + train_clf.py
   cur("f15"); KPM columns are zero while this UE's KPM is masked, profiler
   columns while the profile is late. The decision is the xApp's: the gate
   (trust, mask, framing guard), the model's two alarm rules, the escalation
   by response, then the policy ladder (policy_apply). */
static FILE *clf_log;

int clf_log_open(const char *path) {
  if (path && !(clf_log = fopen(path, "a"))) {
    fprintf(stderr, "[defense] cannot open %s\n", path);
    return -1;
  }
  return 0;
}

void clf_log_close(void) {
  if (clf_log) fclose(clf_log);
  clf_log = NULL;
}

static float clip(double v, double lo, double hi) { return (float)(v < lo ? lo : v > hi ? hi : v); }

/* the 15 per-second inputs of vector f (see above); *late: no profile of the second by t + delta */
static void clf_inputs(const ue_t *u, const features_t *f, float c[15], bool *late, double *trust, bool *masked) {
  const int64_t t_us = f->collect_us / 1000000 * 1000000;
  const double delta = clf_delta_s();
  /* arrival in whole ms, as the offline builder reads received_unix_ms */
  const int64_t rx_ms = (f->collect_us + llround(f->profile_age_s * 1e6)) / 1000;
  const double prof_age = f->has_profile && f->profile_offset_s == 0 ? rx_ms / 1000.0 - t_us / 1e6 : NAN;
  *late = isnan(prof_age) || prof_age > delta;
  *trust = features_kpm_trust(u->supi);
  *masked = features_kpm_masked(u->supi);
  const profile_record_t *p = &f->prof;
  const double w = p->window_ms ? p->window_ms / 1000.0 : 1.0;
  double ul_kbps = 0, dl_kbps = 0, ul_pps = 0, dl_pps = 0, ul_size = 0, dl_size = 0, ctw = 0;
  if (!*late) {
    ul_kbps = p->ul_bytes * 8 / 1000.0 / w; dl_kbps = p->dl_bytes * 8 / 1000.0 / w;
    ul_pps = p->ul_pkts / w; dl_pps = p->dl_pkts / w;
    ul_size = p->ul_pkts ? (double)p->ul_bytes / p->ul_pkts / 1500.0 : 0;
    dl_size = p->dl_pkts ? (double)p->dl_bytes / p->dl_pkts / 1500.0 : 0;
    ctw = f->has_gate ? f->c_t_w : 0;
  }
  const float c6 = (float)log1p(ul_kbps), c7 = (float)log1p(dl_kbps), c8 = (float)log1p(ul_pps), c9 = (float)log1p(dl_pps);
  const float c2 = *masked ? 0.f : (float)(f->prb_ul / 100.0), c3 = *masked ? 0.f : (float)(f->prb_dl / 100.0);
  c[0] = c6; c[1] = c7; c[2] = c8; c[3] = c9; c[4] = c2; c[5] = c3;
  c[6] = log1pf(c2 * 100.f / (1.f + expm1f(c6))); /* float32, as train_clf.py cur() on the float32 columns */
  c[7] = (float)ul_size; c[8] = (float)dl_size;
  c[9] = c7 - c6;
  c[10] = clip(ctw, -3, 3);
  c[11] = (float)*trust;
  c[12] = *masked ? 1.f : 0.f;
  c[13] = clip(f->at_us / 1e6 - (double)(t_us / 1000000), 0, 3); /* arrival_ts - t of the offline builder */
  c[14] = isnan(prof_age) ? 3.f : clip(prof_age, 0, 3);
}

/* escalation by response: at level 2 for grace_s, offered UL (profile, counted before
   the UPF policy) above the threshold in k of the last n ACTIVE seconds
   (core UL >= 8 kbit/s) -> the UE does not back off -> level 3. Threshold
   (esc_rule.h, 2026-11-13): max((1 + over_ratio) x cap, rel_ratio x the UE's
   median offered UL in its first ref_s active seconds at level 2): a UE that
   backs off from a high rate is not judged against the cap alone. Shadow
   mode: u->esc_would is set and logged, the UE is not escalated. */
static bool escalate(ue_t *u, const features_t *f, bool late, int64_t now) {
  u->esc_would = false;
  if (u->level != 2) {
    u->limited_since_us = 0;
    u->esc_n = u->esc_head = u->esc_ref_n = 0;
    u->esc_thr = 0;
    u->esc_offered = -1;
    return false;
  }
  if (!u->limited_since_us) u->limited_since_us = now;
  double cap_ul, cap_dl;
  core_want(u, &cap_ul, &cap_dl);
  u->esc_offered = late ? -1 : features_core_ul_kbps(f);
  /* the rule is computed also when disabled (grace = never) so the log keeps the reference and the threshold */
  const double grace = cfg.esc_enabled ? cfg.esc_grace_s : 1e18;
  u->esc_would = esc_step(u->esc_hist, &u->esc_n, &u->esc_head, u->esc_ref, &u->esc_ref_n, cfg.esc_ref_s, cap_ul, cfg.esc_over_ratio,
                          cfg.esc_rel_ratio, cfg.esc_k, cfg.esc_n, (now - u->limited_since_us) / 1e6, grace, u->esc_offered, &u->esc_thr);
  return u->esc_would && !cfg.esc_shadow;
}

static void clf_line(const ue_t *u, const features_t *f, const clf_out_t *o, const cls_result_t *r, bool late, double trust,
                     bool masked, bool esc, uint64_t decision, int64_t now) {
  if (!clf_log) return;
  json_object *j = json_object_new_object(), *x = json_object_new_array();
  json_object_object_add(j, "supi", json_object_new_string(u->supi));
  json_object_object_add(j, "seq", json_object_new_uint64(f->seq));
  json_object_object_add(j, "t", json_object_new_int64(f->collect_us / 1000000));
  json_object_object_add(j, "collect_ms", json_object_new_int64(f->collect_us / 1000));
  json_object_object_add(j, "scored_ms", json_object_new_int64(now / 1000));
  for (int i = 0; i < CLF_NF; i++) json_object_array_add(x, json_object_new_double(o->x[i]));
  json_object_object_add(j, "x", x);
  json_object_object_add(j, "z", json_object_new_double(o->z));
  json_object_object_add(j, "soft", json_object_new_boolean(o->soft));
  json_object_object_add(j, "block", json_object_new_boolean(o->block));
  json_object_object_add(j, "soft_stat", json_object_new_double(o->soft_stat));
  json_object_object_add(j, "block_stat", json_object_new_double(o->block_stat));
  json_object_object_add(j, "late", json_object_new_boolean(late));
  json_object_object_add(j, "trust", json_object_new_double(trust));
  json_object_object_add(j, "masked", json_object_new_boolean(masked));
  if (f->has_gate) json_object_object_add(j, "c_t_w", json_object_new_double(f->c_t_w));
  json_object_object_add(j, "esc", json_object_new_boolean(esc));
  if (u->level == 2 || u->esc_would) { /* relative escalation (esc_rule.h): reference, threshold, rule result (also in shadow mode) */
    json_object_object_add(j, "esc_would", json_object_new_boolean(u->esc_would));
    json_object_object_add(j, "esc_ref", json_object_new_double(esc_ref_median(u->esc_ref, u->esc_ref_n)));
    json_object_object_add(j, "esc_ref_n", json_object_new_int(u->esc_ref_n));
    json_object_object_add(j, "esc_thr", json_object_new_double(u->esc_thr));
    json_object_object_add(j, "esc_offered", json_object_new_double(u->esc_offered));
    json_object_object_add(j, "esc_since_ms", json_object_new_int64(u->limited_since_us ? (now - u->limited_since_us) / 1000 : -1));
  }
  json_object_object_add(j, "label", json_object_new_string(label_name(r->label)));
  json_object_object_add(j, "kind", json_object_new_string(r->kind));
  json_object_object_add(j, "want_level", json_object_new_int(r->want_level));
  json_object_object_add(j, "level", json_object_new_int(u->level));
  json_object_object_add(j, "actuate", json_object_new_boolean(cfg.actuate));
  if (decision) json_object_object_add(j, "decision_id", json_object_new_uint64(decision));
  fputs(json_object_to_json_string_ext(j, JSON_C_TO_STRING_PLAIN), clf_log);
  fputc('\n', clf_log);
  fflush(clf_log);
  json_object_put(j);
}

/* called by the worker (st_lock held) every tick: score the vectors whose
   second is due, oldest first */
void classifier_tick(int64_t now) {
  if (!cfg.enabled || !cfg.xgb || !clf_ready()) return;
  const int64_t delta_us = (int64_t)(clf_delta_s() * 1e6);
  for (int i = 0; i < MAX_UES; i++) {
    ue_t *u = &ues[i];
    if (!u->used) continue;
    features_fill_urr(u, now);
    for (int k = 0; k < u->win_len; k++) {
      features_t *f = &u->win[(u->win_head - u->win_len + k + 2 * WINDOW_MAX) % WINDOW_MAX];
      if (f->clf_done || f->seq <= u->clf.last_seq) continue;
      if (now < f->collect_us / 1000000 * 1000000 + delta_us) break; /* not due yet; keep the order */
      float c[15];
      bool late, masked;
      double trust;
      clf_inputs(u, f, c, &late, &trust, &masked);
      clf_out_t o;
      clf_step(&u->clf, c, &o);
      window_t w;
      features_window(u, cfg.n, &w);
      cls_result_t r;
      rules(&w, &r); /* fusion hits and the idle-cell count only */
      r.label = LABEL_BENIGN;
      r.kind[0] = r.reason[0] = '\0';
      r.want_level = 0;
      r.score = 1.0 / (1.0 + exp(-o.z));
      snprintf(r.source, sizeof(r.source), "xgb");
      snprintf(r.layer, sizeof(r.layer), "both");
      /* gate guard: KPM of this UE untrusted and above what the core counts
         (framing): no action on the UE, the gNB is flagged (policy_flag_ue) */
      const bool framed = masked && f->has_gate && f->c_t_w > cfg.gate_hi;
      const bool esc = escalate(u, f, late, now);
      if (framed && (o.soft || o.block)) {
        r.label = LABEL_SUSPICIOUS;
        snprintf(r.kind, sizeof(r.kind), "framed_kpm");
      } else if (o.block || esc) {
        r.label = LABEL_ATTACK;
        r.want_level = 3;
        snprintf(r.kind, sizeof(r.kind), "%s", o.block ? "model_block" : "esc_response");
      } else if (o.soft) {
        r.label = LABEL_ATTACK;
        r.want_level = 2;
        snprintf(r.kind, sizeof(r.kind), "model_soft");
      }
      snprintf(r.reason, sizeof(r.reason), "z %.2f, %s %.0f, k2030 %.0f%s", o.z, clf_soft_rule(), o.soft_stat, o.block_stat,
               masked ? ", KPM masked" : "");
      const uint64_t decision = policy_apply(u, f, &r, now);
      if (cfg.actuate) actuators_verify(u, f, now);
      features_log(u, f, &r, decision);
      clf_line(u, f, &o, &r, late, trust, masked, esc, decision, now);
      f->clf_done = true;
      u->clf.last_seq = f->seq;
    }
  }
}
