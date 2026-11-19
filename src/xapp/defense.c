/* Cross-domain defense in the xApp: configuration, the worker
   that runs the layers (defense_internal.h), KPM input, HTTP and lifecycle.
   See defense.h. */
#include "defense.h"
#include "defense_internal.h"
#include "policy_rules.h" /* POLICY_MAX_LEVEL */
#include "../../../../src/util/time_now_us.h"
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <math.h>
#include <time.h>

#define QUEUE_LEN 256

config_t cfg;
ue_t ues[MAX_UES];
sqlite3 *db;
pthread_mutex_t st_lock = PTHREAD_MUTEX_INITIALIZER;
unsigned long long unlabelled, uncongested, dropped;
static sample_t queue[QUEUE_LEN];
static size_t q_head, q_len;
static pthread_mutex_t q_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t q_cond = PTHREAD_COND_INITIALIZER;
static pthread_t worker;
static bool running;
static FILE *events;

/* KPM tamper at ingest (emulated compromised E2 node / untrusted
   KPM). A factor scales the UE's reported UL rate, throughput and PRB share
   (DL too with "dl"; PRB capped at 100 %) before the sample reaches the
   features; every tampered sample is logged with its raw values (ground
   truth, <run>_Tamper.jsonl). Network MITM over SCTP is out of scope. */
#define MAX_TAMPER 8
#define TAMPER_SERIES 256
typedef struct {
  bool used, by_amf, dl;
  char supi[96];
  uint64_t amf;
  double factor;
  int64_t since_us, until_us; /* until 0: until cleared */
  /* replay ("mimic", 2026-11-09): the UE's KPM replaced second by second by a
     recorded benign KPM trace (rate UL/DL, thp UL/DL, PRB UL/DL), so the reported
     KPM is benign KPM; second 0 = the first KPM second seen after the request */
  int n_series;
  float series[TAMPER_SERIES][6];
  int64_t first_s;
} tamper_t;
static tamper_t tampers[MAX_TAMPER];
static pthread_mutex_t t_lock = PTHREAD_MUTEX_INITIALIZER;
static FILE *tamper_log;

/* ---------- configuration ---------- */

static double num(json_object *o, const char *k, double def) {
  json_object *x = NULL;
  if (o && json_object_object_get_ex(o, k, &x) && (json_object_is_type(x, json_type_int) || json_object_is_type(x, json_type_double)))
    return json_object_get_double(x);
  return def;
}

/* {"sst": n, "sd": n | "hex"} */
static void snssai(json_object *o, int *sst, int64_t *sd) {
  json_object *x = NULL;
  *sst = (int)num(o, "sst", *sst);
  if (o && json_object_object_get_ex(o, "sd", &x)) {
    if (json_object_is_type(x, json_type_string)) *sd = strtoll(json_object_get_string(x), NULL, 16);
    else if (json_object_is_type(x, json_type_int)) *sd = json_object_get_int64(x);
  }
}

int class_index(const char *name) {
  for (int i = 0; i < cfg.n_classes; i++)
    if (strcmp(cfg.classes[i].name, name) == 0) return i;
  return -1;
}

/* fairUse {classes {name {ulRateKbps, dlRateKbps}}, supiClass {supi: name},
   congestion {enabled, ulCellPrbPct, dlCellPrbPct}}; "default" is class 0 */
static void load_fair_use(json_object *fu, json_object *d) {
  cfg.n_classes = 1;
  cfg.classes[0] = (fair_class_t){.name = "default", .ul_rate_kbps = num(d, "ulRateKbps", 3000), .dl_rate_kbps = num(d, "dlRateKbps", 15000)};
  json_object *cl = NULL, *sc = NULL, *cg = NULL;
  json_object_object_get_ex(fu, "classes", &cl);
  json_object_object_get_ex(fu, "supiClass", &sc);
  json_object_object_get_ex(fu, "congestion", &cg);
  if (cl && json_object_is_type(cl, json_type_object)) {
    json_object_object_foreach(cl, name, v) {
      int i = class_index(name);
      if (i < 0) {
        if (cfg.n_classes == MAX_CLASSES || strlen(name) >= sizeof(cfg.classes[0].name)) {
          fprintf(stderr, "[defense] fair-use class %s ignored\n", name);
          continue;
        }
        i = cfg.n_classes++;
        cfg.classes[i] = cfg.classes[0];
        snprintf(cfg.classes[i].name, sizeof(cfg.classes[i].name), "%s", name);
      }
      cfg.classes[i].ul_rate_kbps = num(v, "ulRateKbps", cfg.classes[i].ul_rate_kbps);
      cfg.classes[i].dl_rate_kbps = num(v, "dlRateKbps", cfg.classes[i].dl_rate_kbps);
    }
  }
  if (sc && json_object_is_type(sc, json_type_object)) {
    json_object_object_foreach(sc, supi, w) {
      int i = json_object_is_type(w, json_type_string) ? class_index(json_object_get_string(w)) : -1;
      if (i < 0 || cfg.n_assign == MAX_UES) {
        fprintf(stderr, "[defense] supiClass %s ignored (unknown class)\n", supi);
        continue;
      }
      snprintf(cfg.assign[cfg.n_assign].supi, sizeof(cfg.assign[0].supi), "%s", supi);
      cfg.assign[cfg.n_assign++].cls = i;
    }
  }
  json_object *x = NULL;
  cfg.congestion = cg && json_object_object_get_ex(cg, "enabled", &x) && json_object_get_boolean(x);
  cfg.cell_ul_prb_pct = num(cg, "ulCellPrbPct", 80);
  cfg.cell_dl_prb_pct = num(cg, "dlCellPrbPct", 60);
  cfg.other_ue_kbps = num(cg, "otherUeKbps", 100);
}

static void load_config(void) {
  cfg = (config_t){.enabled = false, .profile = "lab", .k = 2, .n = 3,
                   .max_prb_ratio = 10, .q_sst = 1, .q_sd = 0xBADBAD, .d_sst = 1, .d_sd = 0xFFFFFF, .b_sst = 1, .b_sd = 0, .block_prb_ratio = 1, .probation_s = 180, .expiry_s = {60, 180, 600, 0},
                   .upf_api = "http://oai-upf-security.oai-core.svc.cluster.local:8095", .upf_timeout_ms = 1000, .upf_sync_s = 10,
                   .upf_ttl_margin_s = 30, .upf_max_ttl_s = 86400, .ratelimit_factor = 1.0, .urr_max_age_s = 5, .core_max_age_s = 2, .fusion_s = 10,
                   .gate_beta = 57, .gate_eps_bytes = 1000, .gate_lo = -0.2, .gate_hi = 0.2, .gate_window_s = 3, .gate_alpha = 0.1, .gate_trust_min = 0.85,
                   .verify_s = 10, .release_every_s = 10, .release_on_block = true, .evidence_interval_s = 10,
                   .window = 10,
                   .model_path = "/opt/oai/models/clf_model.json", .actuate = true,
                   .esc_enabled = true, .esc_grace_s = 5, .esc_k = 8, .esc_n = 10, .esc_over_ratio = 0.25,
                   .esc_rel_ratio = 0, .esc_ref_s = 3, .esc_shadow = false,
                   .sev_rate = 2, .sev_repeat = 1, .half_life_s = 60};
  load_fair_use(NULL, NULL);
  const char *env = getenv("DEFENSE_CONFIG");
  json_object *c = env && *env ? json_tokener_parse(env) : NULL, *x = NULL;
  if (!c) {
    printf("[defense] no DEFENSE_CONFIG: detection disabled\n");
    return;
  }
  if (json_object_object_get_ex(c, "enabled", &x)) cfg.enabled = json_object_get_boolean(x);
  if (json_object_object_get_ex(c, "profile", &x) && json_object_is_type(x, json_type_string))
    snprintf(cfg.profile, sizeof(cfg.profile), "%s", json_object_get_string(x));
  json_object *d = NULL, *a = NULL, *f = NULL, *e = NULL, *s = NULL, *fu = NULL;
  json_object_object_get_ex(c, "detector", &d);
  json_object_object_get_ex(c, "fairUse", &fu);
  json_object_object_get_ex(c, "action", &a);
  json_object_object_get_ex(c, "confirm", &f);
  json_object_object_get_ex(c, "expiryS", &e);
  json_object_object_get_ex(c, "severity", &s);
  load_fair_use(fu, d);
  cfg.ul_prb_pct = num(d, "ulPrbPct", 0);
  cfg.dl_prb_pct = num(d, "dlPrbPct", 0);
  cfg.k = (int)num(d, "hits", cfg.k);
  cfg.n = (int)num(d, "samples", cfg.n);
  cfg.max_prb_ratio = (int)num(a, "maxPrbRatio", cfg.max_prb_ratio);
  if (a && json_object_object_get_ex(a, "mode", &x) && json_object_is_type(x, json_type_string))
    cfg.slice_mode = strcmp(json_object_get_string(x), "slice") == 0;
  json_object *qs = NULL, *ds = NULL;
  if (a) json_object_object_get_ex(a, "quarantineSlice", &qs);
  if (a) json_object_object_get_ex(a, "defaultSlice", &ds);
  snssai(qs, &cfg.q_sst, &cfg.q_sd);
  snssai(ds, &cfg.d_sst, &cfg.d_sd);
  /* limitSlice (levels 1-2) overrides quarantineSlice + maxPrbRatio; blockSlice (levels >= 3) */
  json_object *ls = NULL, *bs = NULL;
  if (a && json_object_object_get_ex(a, "limitSlice", &ls)) {
    snssai(ls, &cfg.q_sst, &cfg.q_sd);
    cfg.max_prb_ratio = (int)num(ls, "maxPrbRatio", cfg.max_prb_ratio);
  }
  if (a && json_object_object_get_ex(a, "blockSlice", &bs)) {
    snssai(bs, &cfg.b_sst, &cfg.b_sd);
    cfg.block_prb_ratio = (int)num(bs, "maxPrbRatio", cfg.block_prb_ratio);
  }
  cfg.probation_s = (int)num(f, "probationS", cfg.probation_s);
  json_object *cl = NULL;
  json_object_object_get_ex(c, "classifier", &cl);
  if (cl && json_object_object_get_ex(cl, "kind", &x) && json_object_is_type(x, json_type_string))
    cfg.xgb = strcmp(json_object_get_string(x), "xgb") == 0;
  if (cl && json_object_object_get_ex(cl, "model", &x) && json_object_is_type(x, json_type_string))
    snprintf(cfg.model_path, sizeof(cfg.model_path), "%s", json_object_get_string(x));
  if (json_object_object_get_ex(c, "actuate", &x)) cfg.actuate = json_object_get_boolean(x);
  json_object *es = NULL;
  json_object_object_get_ex(c, "escalation", &es);
  if (es && json_object_object_get_ex(es, "enabled", &x)) cfg.esc_enabled = json_object_get_boolean(x);
  cfg.esc_grace_s = (int)num(es, "graceS", cfg.esc_grace_s);
  cfg.esc_k = (int)num(es, "hits", cfg.esc_k);
  cfg.esc_n = (int)num(es, "samples", cfg.esc_n);
  cfg.esc_over_ratio = num(es, "overRatio", cfg.esc_over_ratio);
  cfg.esc_rel_ratio = num(es, "relRatio", cfg.esc_rel_ratio);
  cfg.esc_ref_s = (int)num(es, "refS", cfg.esc_ref_s);
  if (es && json_object_object_get_ex(es, "shadow", &x)) cfg.esc_shadow = json_object_get_boolean(x);
  if (cfg.esc_n < 1 || cfg.esc_n > 32) cfg.esc_n = 10;
  if (cfg.esc_k < 1 || cfg.esc_k > cfg.esc_n) cfg.esc_k = cfg.esc_n;
  if (cfg.esc_ref_s < 1 || cfg.esc_ref_s > 8) cfg.esc_ref_s = 3;
  if (cfg.esc_rel_ratio < 0) cfg.esc_rel_ratio = 0;
  cfg.window = (int)num(cl, "window", cfg.window);
  json_object *p = NULL;
  if (e && json_object_object_get_ex(e, cfg.profile, &p) && json_object_is_type(p, json_type_array))
    for (size_t i = 0; i < json_object_array_length(p) && i < 4; i++) cfg.expiry_s[i] = json_object_get_int(json_object_array_get_idx(p, i));
  /* core layer: UPF Security API and the core rule */
  json_object *co = NULL, *rp = NULL;
  json_object_object_get_ex(c, "core", &co);
  json_object_object_get_ex(c, "repeat", &rp);
  cfg.core = co && json_object_object_get_ex(co, "enabled", &x) && json_object_get_boolean(x);
  if (co && json_object_object_get_ex(co, "upfApi", &x) && json_object_is_type(x, json_type_string))
    snprintf(cfg.upf_api, sizeof(cfg.upf_api), "%s", json_object_get_string(x));
  cfg.upf_timeout_ms = (int)num(co, "timeoutMs", cfg.upf_timeout_ms);
  cfg.upf_sync_s = (int)num(co, "syncS", cfg.upf_sync_s);
  cfg.upf_ttl_margin_s = (int)num(co, "ttlMarginS", cfg.upf_ttl_margin_s);
  cfg.upf_max_ttl_s = (int)num(co, "maxTtlS", cfg.upf_max_ttl_s);
  cfg.ratelimit_factor = num(co, "ratelimitFactor", cfg.ratelimit_factor);
  cfg.limit_ul_kbps = num(co, "limitUlKbps", cfg.limit_ul_kbps);
  cfg.limit_dl_kbps = num(co, "limitDlKbps", cfg.limit_dl_kbps);
  cfg.urr_max_age_s = num(co, "urrMaxAgeS", cfg.urr_max_age_s);
  cfg.core_max_age_s = num(co, "coreMaxAgeS", cfg.core_max_age_s);
  json_object *gate = NULL;
  json_object_object_get_ex(c, "gate", &gate);
  cfg.gate_beta = num(gate, "betaBytes", cfg.gate_beta);
  cfg.gate_eps_bytes = num(gate, "epsBytes", cfg.gate_eps_bytes);
  cfg.gate_lo = num(gate, "lo", cfg.gate_lo);
  cfg.gate_hi = num(gate, "hi", cfg.gate_hi);
  cfg.gate_alpha = num(gate, "alpha", cfg.gate_alpha);
  cfg.gate_trust_min = num(gate, "trustMin", cfg.gate_trust_min);
  cfg.gate_window_s = (int)num(gate, "windowS", cfg.gate_window_s);
  if (cfg.gate_window_s < 1) cfg.gate_window_s = 1;
  if (cfg.gate_window_s > 8) cfg.gate_window_s = 8;
  cfg.fusion_s = (int)num(co, "fusionS", cfg.fusion_s);
  cfg.verify_s = (int)num(co, "verifyS", cfg.verify_s);
  cfg.release_every_s = (int)num(co, "releaseEveryS", cfg.release_every_s);
  if (co && json_object_object_get_ex(co, "releaseOnBlock", &x)) cfg.release_on_block = json_object_get_boolean(x);
  cfg.repeat_every = rp && json_object_object_get_ex(rp, "strategy", &x) && json_object_is_type(x, json_type_string) &&
                     strcmp(json_object_get_string(x), "every") == 0;
  cfg.evidence_interval_s = (int)num(rp, "evidenceIntervalS", cfg.evidence_interval_s);
  cfg.sev_rate = num(s, "kpmRate", cfg.sev_rate);
  cfg.sev_repeat = num(s, "repeat", cfg.sev_repeat);
  cfg.half_life_s = num(c, "scoreHalfLifeS", cfg.half_life_s);
  if (cfg.n < 1 || cfg.n > 32) cfg.n = 3;
  if (cfg.k < 1 || cfg.k > cfg.n) cfg.k = cfg.n;
  if (cfg.max_prb_ratio < 1 || cfg.max_prb_ratio > 99) cfg.max_prb_ratio = 10;
  if (cfg.block_prb_ratio < 1 || cfg.block_prb_ratio > 99) cfg.block_prb_ratio = 1;
  if (cfg.limit_ul_kbps < 0) cfg.limit_ul_kbps = 0;
  if (cfg.limit_dl_kbps < 0) cfg.limit_dl_kbps = 0;
  if (cfg.window < 1 || cfg.window > WINDOW_MAX) cfg.window = 10;
  json_object_put(c);
  printf("[defense] %s, profile %s: PDCP rate above the SUPI's fair-use class in %d of %d samples", cfg.enabled ? "enabled" : "disabled",
         cfg.profile, cfg.k, cfg.n);
  if (cfg.congestion)
    printf(" while cell PRB UL >= %.0f%% / DL >= %.0f%% with another UE >= %.0f kbps", cfg.cell_ul_prb_pct, cfg.cell_dl_prb_pct,
           cfg.other_ue_kbps);
  if (cfg.slice_mode) {
    printf(" -> quarantine RAN slice SST %d SD %06" PRIx64 " (shared PRB quota %d%%, default slice SST %d SD %06" PRIx64 ")",
           cfg.q_sst, cfg.q_sd, cfg.max_prb_ratio, cfg.d_sst, cfg.d_sd);
    if (cfg.b_sd)
      printf("; levels >= 3 -> block RAN slice SST %d SD %06" PRIx64 " (shared PRB quota %d%%)", cfg.b_sst, cfg.b_sd, cfg.block_prb_ratio);
  } else {
    printf(" -> PRB quota %d%%", cfg.max_prb_ratio);
  }
  printf("; again within %d s of the expiry -> next level (>= 3 needs KPM and URR within %d s); expiry %d/%d/%d/%d s\n",
         cfg.probation_s, cfg.fusion_s, cfg.expiry_s[0], cfg.expiry_s[1], cfg.expiry_s[2], cfg.expiry_s[3]);
  if (cfg.core && cfg.limit_ul_kbps > 0)
    printf("[defense] core layer: URR rule + UPF %s (1 monitor, 2 ratelimit UL %.0f / DL %.0f kbps for every UE, 3-4 block%s; sync %d s)\n",
           cfg.upf_api, cfg.limit_ul_kbps, cfg.limit_dl_kbps, cfg.release_on_block ? " + RRC release" : "", cfg.upf_sync_s);
  else if (cfg.core)
    printf("[defense] core layer: URR rule + UPF %s (1 monitor, 2 ratelimit x%.2f, 3-4 block + RRC release; sync %d s)\n", cfg.upf_api,
           cfg.ratelimit_factor, cfg.upf_sync_s);
  else
    printf("[defense] core layer off: RAN only, levels stop at 2\n");
  printf("[defense] repeated labels: %s (evidence every %d s)\n", cfg.repeat_every ? "every" : "refresh", cfg.evidence_interval_s);
  if (cfg.xgb)
    printf("[defense] classifier xgb (embedded, %s); escalation by response %s%s (grace %d s, %d of %d s above max(%.0f%% over the cap, "
           "relRatio %.2f x the first %d active s at level 2))\n",
           cfg.model_path, cfg.esc_enabled ? "on" : "off", cfg.esc_shadow ? ", shadow (logged only)" : "", cfg.esc_grace_s, cfg.esc_k,
           cfg.esc_n, cfg.esc_over_ratio * 100, cfg.esc_rel_ratio, cfg.esc_ref_s);
  printf("[defense] actions %s\n", cfg.actuate ? "sent to the RAN and the UPF" : "NOT sent (observe mode: decisions logged only)");
  printf("[defense] classifier %s (window %d)\n", cfg.xgb ? "xgb" : "rules", cfg.window);
  for (int i = 0; i < cfg.n_classes; i++)
    printf("[defense] fair-use class %s: UL %.0f kbps, DL %.0f kbps\n", cfg.classes[i].name, cfg.classes[i].ul_rate_kbps,
           cfg.classes[i].dl_rate_kbps);
}

/* ---------- shared helpers ---------- */

void iso(int64_t us, char *buf, size_t n) {
  time_t t = (time_t)(us / 1000000);
  struct tm tm;
  gmtime_r(&t, &tm);
  size_t len = strftime(buf, n, "%Y-%m-%dT%H:%M:%S", &tm);
  snprintf(buf + len, n - len, ".%03dZ", (int)(us / 1000 % 1000));
}

void event(json_object *o) {
  if (events) {
    fputs(json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN), events);
    fputc('\n', events);
    fflush(events);
  }
  json_object_put(o);
}

json_object *event_base(const char *type, const ue_t *u, int64_t now) {
  json_object *o = json_object_new_object();
  json_object_object_add(o, "at_ms", json_object_new_int64(now / 1000));
  json_object_object_add(o, "type", json_object_new_string(type));
  json_object_object_add(o, "supi", json_object_new_string(u->supi));
  json_object_object_add(o, "level", json_object_new_int(u->level));
  if (u->decision_id) json_object_object_add(o, "decision_id", json_object_new_uint64(u->decision_id));
  return o;
}

void exec_sql(const char *sql) {
  char *err = NULL;
  if (sqlite3_exec(db, sql, NULL, NULL, &err) != SQLITE_OK) {
    fprintf(stderr, "[defense] SQLite: %s\n", err ? err : "?");
    sqlite3_free(err);
  }
}

/* ---------- worker: features -> classifier -> policy -> actuators ---------- */

static void process(const sample_t *s, int64_t now) {
  features_t *f = NULL;
  ue_t *u = features_build(s, now, &f);
  if (!u) return;
  features_raw_write(u->supi, s, f, now);   /* raw KPM tap (source and arrival time) */
  if (!cfg.enabled) {
    features_log(u, f, NULL, 0);
    return;
  }
  features_fill_urr(u, now);
  if (cfg.xgb && clf_ready()) return; /* scored at t + delta by classifier_tick */
  window_t w;
  features_window(u, cfg.window > cfg.n ? cfg.window : cfg.n, &w);
  cls_result_t r;
  classifier_classify(&w, &r);
  uint64_t decision = policy_apply(u, f, &r, now);
  if (cfg.actuate) actuators_verify(u, f, now);
  features_log(u, f, &r, decision);
}

static void *run(void *arg) {
  (void)arg;
  sample_t local[QUEUE_LEN];
  for (;;) {
    pthread_mutex_lock(&q_lock);
    if (q_len == 0 && running) {
      struct timespec ts;
      clock_gettime(CLOCK_REALTIME, &ts);
      /* 50 ms tick: the embedded model scores a second at t + delta */
      ts.tv_nsec += 50000000L;
      if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
      pthread_cond_timedwait(&q_cond, &q_lock, &ts);
    }
    if (!running) {
      pthread_mutex_unlock(&q_lock);
      return NULL;
    }
    size_t n = q_len;
    for (size_t i = 0; i < n; i++) local[i] = queue[(q_head + i) % QUEUE_LEN];
    q_head = (q_head + n) % QUEUE_LEN;
    q_len = 0;
    pthread_mutex_unlock(&q_lock);

    int64_t now = time_now_us();
    pthread_mutex_lock(&st_lock);
    for (size_t i = 0; i < n; i++) features_observe(&local[i]);
    for (size_t i = 0; i < n; i++) process(&local[i], now);
    classifier_tick(time_now_us());
    policy_expire(now);
    for (int i = 0; i < MAX_UES; i++)
      if (ues[i].used) features_flush(&ues[i], now, false);
    const bool act = cfg.actuate;
    pthread_mutex_unlock(&st_lock);
    if (act) { /* observe mode: levels are computed and logged, nothing is sent */
      actuators_reconcile(now);
      actuators_core_sync(now);
    }
  }
}

/* ---------- KPM input ---------- */

static void tamper_line(json_object *o) {
  if (tamper_log) {
    fputs(json_object_to_json_string_ext(o, JSON_C_TO_STRING_PLAIN), tamper_log);
    fputc('\n', tamper_log);
    fflush(tamper_log);
  }
  json_object_put(o);
}

static void tamper(sample_t *s) {
  s->raw_rate_ul = s->rate_ul;
  s->raw_rate_dl = s->rate_dl;
  s->raw_thp_ul = s->thp_ul;
  s->raw_thp_dl = s->thp_dl;
  s->raw_prb_ul = s->prb_ul;
  s->raw_prb_dl = s->prb_dl;
  char supi[96] = "";
  bool have_supi = urr_receiver_supi_for_ue(s->amf, supi, sizeof(supi));
  const int64_t now = time_now_us();
  pthread_mutex_lock(&t_lock);
  for (int i = 0; i < MAX_TAMPER; i++) {
    tamper_t *t = &tampers[i];
    if (!t->used) continue;
    if (t->until_us && now >= t->until_us) {
      t->used = false;
      json_object *o = json_object_new_object();
      json_object_object_add(o, "ts", json_object_new_double(now / 1e6));
      json_object_object_add(o, "type", json_object_new_string("expired"));
      json_object_object_add(o, "supi", json_object_new_string(t->supi));
      tamper_line(o);
      continue;
    }
    if (t->by_amf ? t->amf != s->amf : !have_supi || strcmp(t->supi, supi) != 0) continue;
    const double f = t->factor;
    if (t->n_series > 0) {
      const int64_t sec = s->collect_us / 1000000;
      if (!t->first_s) t->first_s = sec;
      const float *r = t->series[(sec - t->first_s) % t->n_series];
      s->tamper = 1.0;
      s->rate_ul = r[0]; s->rate_dl = r[1]; s->thp_ul = r[2]; s->thp_dl = r[3]; s->prb_ul = r[4]; s->prb_dl = r[5];
    } else {
      s->tamper = f;
      s->rate_ul *= f;
      s->thp_ul *= f;
      s->prb_ul = fmin(100.0, s->prb_ul * f);
      if (t->dl) {
        s->rate_dl *= f;
        s->thp_dl *= f;
        s->prb_dl = fmin(100.0, s->prb_dl * f);
      }
    }
    json_object *o = json_object_new_object(), *raw = json_object_new_object(), *tam = json_object_new_object();
    json_object_object_add(o, "ts", json_object_new_double(now / 1e6));
    json_object_object_add(o, "type", json_object_new_string("sample"));
    json_object_object_add(o, "source_ts", json_object_new_double(s->collect_us / 1e6));
    json_object_object_add(o, "supi", json_object_new_string(have_supi ? supi : ""));
    json_object_object_add(o, "amf_ue_ngap_id", json_object_new_uint64(s->amf));
    json_object_object_add(o, "factor", json_object_new_double(t->n_series ? 0 : f));
    json_object_object_add(o, "mode", json_object_new_string(t->n_series ? "replay" : "scale"));
    json_object_object_add(o, "dl", json_object_new_boolean(t->dl));
    const struct { const char *k; double a, b; } v[] = {{"rate_ul_kbps", s->raw_rate_ul, s->rate_ul}, {"thp_ul_kbps", s->raw_thp_ul, s->thp_ul},
        {"prb_ul_pct", s->raw_prb_ul, s->prb_ul}, {"rate_dl_kbps", s->raw_rate_dl, s->rate_dl}, {"thp_dl_kbps", s->raw_thp_dl, s->thp_dl},
        {"prb_dl_pct", s->raw_prb_dl, s->prb_dl}};
    for (size_t k = 0; k < sizeof(v) / sizeof(*v); k++) {
      json_object_object_add(raw, v[k].k, json_object_new_double(v[k].a));
      json_object_object_add(tam, v[k].k, json_object_new_double(v[k].b));
    }
    json_object_object_add(o, "raw", raw);
    json_object_object_add(o, "tampered", tam);
    tamper_line(o);
    break;
  }
  pthread_mutex_unlock(&t_lock);
}

static json_object *tamper_state(void) {
  json_object *a = json_object_new_array();
  const int64_t now = time_now_us();
  pthread_mutex_lock(&t_lock);
  for (int i = 0; i < MAX_TAMPER; i++) {
    const tamper_t *t = &tampers[i];
    if (!t->used || (t->until_us && now >= t->until_us)) continue;
    json_object *o = json_object_new_object();
    if (t->by_amf) json_object_object_add(o, "amf_ue_ngap_id", json_object_new_uint64(t->amf));
    else json_object_object_add(o, "supi", json_object_new_string(t->supi));
    json_object_object_add(o, "factor", json_object_new_double(t->factor));
    json_object_object_add(o, "dl", json_object_new_boolean(t->dl));
    json_object_object_add(o, "remaining_s", json_object_new_double(t->until_us ? (t->until_us - now) / 1e6 : -1));
    json_object_array_add(a, o);
  }
  pthread_mutex_unlock(&t_lock);
  return a;
}

/* {"supi"|"amf_ue_ngap_id", "factor", "until_s"?, "dl"?} sets (replaces) the
   UE's tamper; {"off": true[, "supi"|"amf_ue_ngap_id"]} clears one or all */
static int tamper_http(json_object *in, json_object *o) {
  json_object *x = NULL;
  char supi[96] = "";
  uint64_t amf = 0;
  bool by_amf = false;
  if (json_object_object_get_ex(in, "supi", &x) && json_object_is_type(x, json_type_string))
    snprintf(supi, sizeof(supi), "%s", json_object_get_string(x));
  else if (json_object_object_get_ex(in, "amf_ue_ngap_id", &x) && json_object_is_type(x, json_type_int)) {
    amf = (uint64_t)json_object_get_int64(x);
    by_amf = true;
  }
  const bool off = json_object_object_get_ex(in, "off", &x) && json_object_get_boolean(x);
  const double factor = num(in, "factor", 0), until_s = num(in, "until_s", 0);
  const bool dl = json_object_object_get_ex(in, "dl", &x) && json_object_get_boolean(x);
  /* "series": [[rate_ul, rate_dl, thp_ul, thp_dl, prb_ul, prb_dl], ...] = replay mode */
  json_object *ser = NULL;
  const bool replay = json_object_object_get_ex(in, "series", &ser) && json_object_is_type(ser, json_type_array) &&
                      json_object_array_length(ser) > 0 && json_object_array_length(ser) <= TAMPER_SERIES;
  if (!off && ((!supi[0] && !by_amf) || (!replay && (!(factor > 0) || factor > 1000)))) {
    json_object_object_add(o, "error", json_object_new_string("supi|amf_ue_ngap_id and 0 < factor <= 1000 or series (<= 256 x 6), or off"));
    return 400;
  }
  const int64_t now = time_now_us();
  int cleared = 0;
  pthread_mutex_lock(&t_lock);
  for (int i = 0; i < MAX_TAMPER; i++) {
    tamper_t *t = &tampers[i];
    if (!t->used) continue;
    const bool same = by_amf ? t->by_amf && t->amf == amf : supi[0] && !t->by_amf && strcmp(t->supi, supi) == 0;
    if (same || (off && !supi[0] && !by_amf)) {
      t->used = false;
      cleared++;
    }
  }
  int code = 200;
  if (!off) {
    tamper_t *slot = NULL;
    for (int i = 0; i < MAX_TAMPER && !slot; i++)
      if (!tampers[i].used) slot = &tampers[i];
    if (!slot) {
      code = 409;
    } else {
      *slot = (tamper_t){.used = true, .by_amf = by_amf, .dl = dl, .amf = amf, .factor = factor, .since_us = now,
                         .until_us = until_s > 0 ? now + (int64_t)(until_s * 1e6) : 0};
      snprintf(slot->supi, sizeof(slot->supi), "%s", supi);
      if (replay) {
        slot->n_series = (int)json_object_array_length(ser);
        for (int k = 0; k < slot->n_series; k++) {
          json_object *row = json_object_array_get_idx(ser, k);
          for (int j = 0; j < 6; j++)
            slot->series[k][j] = row && json_object_is_type(row, json_type_array) && (int)json_object_array_length(row) > j
                                     ? (float)json_object_get_double(json_object_array_get_idx(row, j)) : 0.f;
        }
      }
    }
  }
  pthread_mutex_unlock(&t_lock);
  json_object *l = json_object_new_object();
  json_object_object_add(l, "ts", json_object_new_double(now / 1e6));
  json_object_object_add(l, "type", json_object_new_string(off ? "off" : "set"));
  json_object_object_add(l, "supi", json_object_new_string(supi));
  if (by_amf) json_object_object_add(l, "amf_ue_ngap_id", json_object_new_uint64(amf));
  json_object_object_add(l, "factor", json_object_new_double(off ? 1.0 : factor));
  json_object_object_add(l, "until_s", json_object_new_double(until_s));
  json_object_object_add(l, "dl", json_object_new_boolean(dl));
  json_object_object_add(l, "cleared", json_object_new_int(cleared));
  json_object_object_add(l, "status", json_object_new_int(code));
  tamper_line(l);
  printf("[defense] KPM tamper %s %s%s x%.3g (%d cleared)\n", off ? "off" : "set", supi[0] ? supi : by_amf ? "amf" : "all",
         dl ? " +dl" : "", off ? 1.0 : factor, cleared);
  json_object_object_add(o, "cleared", json_object_new_int(cleared));
  json_object_object_add(o, "tamper", tamper_state());
  if (code == 409) json_object_object_add(o, "error", json_object_new_string("tamper table full"));
  return code;
}

static bool name_is(byte_array_t ba, const char *s) {
  return ba.len == strlen(s) && memcmp(ba.buf, s, ba.len) == 0;
}

void defense_on_kpm(ue_id_e2sm_t const *ue_id, kpm_ind_msg_format_1_t const *msg, int64_t collect_us, const char *e2_node) {
  if (!running || !ue_id || ue_id->type != GNB_UE_ID_E2SM || !msg || msg->meas_data_lst_len == 0) return;
  sample_t s = {.amf = ue_id->gnb.amf_ue_ngap_id, .collect_us = collect_us};
  snprintf(s.node, sizeof(s.node), "%s", e2_node ? e2_node : "?");
  const meas_data_lst_t *data = &msg->meas_data_lst[0];
  const double period_s = msg->gran_period_ms && *msg->gran_period_ms ? *msg->gran_period_ms / 1000.0 : 1.0;
  size_t rec = 0;
  for (size_t i = 0; i < msg->meas_info_lst_len; i++) {
    const meas_info_format_1_lst_t *info = &msg->meas_info_lst[i];
    for (size_t z = 0; z < info->label_info_lst_len; z++, rec++) {
      if (rec >= data->meas_record_len || info->meas_type.type != NAME_MEAS_TYPE || z > 0) continue;
      const meas_record_lst_t *r = &data->meas_record_lst[rec];
      double v = r->value == INTEGER_MEAS_VALUE ? r->int_val : r->value == REAL_MEAS_VALUE ? r->real_val : 0;
      if (name_is(info->meas_type.name, "DRB.PdcpSduVolumeUL")) s.rate_ul = v * 1000.0 / period_s; /* Mb -> kbit/s */
      else if (name_is(info->meas_type.name, "DRB.PdcpSduVolumeDL")) s.rate_dl = v * 1000.0 / period_s;
      else if (name_is(info->meas_type.name, "DRB.UEThpUl")) s.thp_ul = v;
      else if (name_is(info->meas_type.name, "DRB.UEThpDl")) s.thp_dl = v;
      else if (name_is(info->meas_type.name, "RRU.PrbTotUl")) s.prb_ul = v;
      else if (name_is(info->meas_type.name, "RRU.PrbTotDl")) s.prb_dl = v;
    }
  }
  tamper(&s);
  pthread_mutex_lock(&q_lock);
  if (q_len == QUEUE_LEN) {
    dropped++;
  } else {
    queue[(q_head + q_len++) % QUEUE_LEN] = s;
    pthread_cond_signal(&q_cond);
  }
  pthread_mutex_unlock(&q_lock);
}

/* ---------- HTTP ---------- */

int defense_http(const char *url, const char *body, struct json_object **out) {
  json_object *o = json_object_new_object();
  *out = o;
  if (strcmp(url, "/v1/defense/state") == 0 && !body) {
    pthread_mutex_lock(&st_lock);
    json_object_object_add(o, "enabled", json_object_new_boolean(cfg.enabled));
    json_object_object_add(o, "profile", json_object_new_string(cfg.profile));
    json_object_object_add(o, "max_prb_ratio", json_object_new_int(cfg.max_prb_ratio));
    json_object_object_add(o, "action_mode", json_object_new_string(cfg.slice_mode ? "slice" : "ue"));
    {
      char sd[16];
      json_object *sl = json_object_new_object(), *lim = json_object_new_object(), *blk = json_object_new_object();
      snprintf(sd, sizeof(sd), "%06" PRIx64, cfg.q_sd);
      json_object_object_add(lim, "sst", json_object_new_int(cfg.q_sst));
      json_object_object_add(lim, "sd", json_object_new_string(sd));
      json_object_object_add(lim, "max_prb_ratio", json_object_new_int(cfg.max_prb_ratio));
      snprintf(sd, sizeof(sd), "%06" PRIx64, cfg.b_sd);
      json_object_object_add(blk, "sst", json_object_new_int(cfg.b_sst));
      json_object_object_add(blk, "sd", json_object_new_string(sd));
      json_object_object_add(blk, "max_prb_ratio", json_object_new_int(cfg.block_prb_ratio));
      json_object_object_add(sl, "limit", lim);
      json_object_object_add(sl, "block", blk);
      json_object_object_add(sl, "limit_ul_kbps", json_object_new_double(cfg.limit_ul_kbps));
      json_object_object_add(sl, "limit_dl_kbps", json_object_new_double(cfg.limit_dl_kbps));
      json_object_object_add(o, "mitigation", sl);
    }
    json_object_object_add(o, "unlabelled_samples", json_object_new_uint64(unlabelled));
    json_object_object_add(o, "dropped_samples", json_object_new_uint64(dropped));
    json_object_object_add(o, "uncongested_samples", json_object_new_uint64(uncongested));
    json_object *fu = json_object_new_object(), *cls = json_object_new_object(), *cg = json_object_new_object();
    for (int i = 0; i < cfg.n_classes; i++) {
      json_object *c = json_object_new_object();
      json_object_object_add(c, "ul_rate_kbps", json_object_new_double(cfg.classes[i].ul_rate_kbps));
      json_object_object_add(c, "dl_rate_kbps", json_object_new_double(cfg.classes[i].dl_rate_kbps));
      json_object_object_add(cls, cfg.classes[i].name, c);
    }
    json_object_object_add(cg, "enabled", json_object_new_boolean(cfg.congestion));
    json_object_object_add(cg, "ul_cell_prb_pct", json_object_new_double(cfg.cell_ul_prb_pct));
    json_object_object_add(cg, "dl_cell_prb_pct", json_object_new_double(cfg.cell_dl_prb_pct));
    json_object_object_add(cg, "other_ue_kbps", json_object_new_double(cfg.other_ue_kbps));
    json_object_object_add(fu, "classes", cls);
    json_object_object_add(fu, "congestion", cg);
    json_object_object_add(o, "fair_use", fu);
    json_object_object_add(o, "classifier", classifier_state());
    json_object_object_add(o, "core", actuators_core_state());
    json_object *tm = json_object_new_object(), *ex = json_object_new_array();
    for (int i = 0; i < 4; i++) json_object_array_add(ex, json_object_new_int(cfg.expiry_s[i]));
    json_object_object_add(tm, "expiry_s", ex);
    json_object_object_add(tm, "probation_s", json_object_new_int(cfg.probation_s));
    json_object_object_add(tm, "fusion_s", json_object_new_int(cfg.fusion_s));
    json_object_object_add(tm, "release_on_block", json_object_new_boolean(cfg.release_on_block));
    json_object_object_add(o, "timing", tm);
    json_object_object_add(o, "tamper", tamper_state());
    json_object *arr = json_object_new_array();
    int64_t now = time_now_us();
    for (int i = 0; i < MAX_UES; i++) {
      ue_t *u = &ues[i];
      if (!u->used) continue;
      json_object *e = json_object_new_object();
      json_object_object_add(e, "supi", json_object_new_string(u->supi));
      json_object_object_add(e, "level", json_object_new_int(u->level));
      json_object_object_add(e, "class", json_object_new_string(cfg.classes[u->cls].name));
      json_object_object_add(e, "score", json_object_new_double(u->score));
      json_object_object_add(e, "expires_in_s", json_object_new_double(u->level ? (u->expires_us - now) / 1e6 : 0));
      json_object_object_add(e, "amf_ue_ngap_id", json_object_new_uint64(u->amf));
      json_object_object_add(e, "applied_ratio", json_object_new_int(u->applied_ratio));
      json_object_object_add(e, "synced_amf_ue_ngap_id", json_object_new_uint64(u->synced_amf));
      json_object_object_add(e, "verified", json_object_new_boolean(u->verified));
      json_object_object_add(e, "probation_s", json_object_new_double(u->probation_us > now ? (u->probation_us - now) / 1e6 : 0));
      json_object_object_add(e, "rate_ul_kbps", json_object_new_double(u->rate_ul));
      json_object_object_add(e, "rate_dl_kbps", json_object_new_double(u->rate_dl));
      json_object_object_add(e, "decision_id", json_object_new_uint64(u->decision_id));
      json_object_object_add(e, "peak", json_object_new_int(u->peak));
      json_object_object_add(e, "pending", json_object_new_int(u->pending));
      json_object_object_add(e, "ran_hit_age_s", json_object_new_double(u->ran_hit_us ? (now - u->ran_hit_us) / 1e6 : -1));
      json_object_object_add(e, "core_hit_age_s", json_object_new_double(u->core_hit_us ? (now - u->core_hit_us) / 1e6 : -1));
      double ul, dl;
      json_object_object_add(e, "core_want", json_object_new_string(core_want(u, &ul, &dl)));
      json_object_object_add(e, "core_applied", json_object_new_string(u->core_applied[0] ? u->core_applied : "unknown"));
      json_object_object_add(e, "core_verified", json_object_new_boolean(u->core_verified));
      json_object_object_add(e, "core_assist", json_object_new_boolean(u->core_assist));
      json_object_object_add(e, "released_amf_ue_ngap_id", json_object_new_uint64(u->released_amf));
      json_object_array_add(arr, e);
    }
    pthread_mutex_unlock(&st_lock);
    json_object_object_add(o, "ues", arr);
    return 200;
  }
  json_object *in = body ? json_tokener_parse(body) : NULL, *x = NULL;
  int code = 404;
  if (strcmp(url, "/v1/defense/enabled") == 0 && in && json_object_object_get_ex(in, "enabled", &x) && json_object_is_type(x, json_type_boolean)) {
    pthread_mutex_lock(&st_lock);
    cfg.enabled = json_object_get_boolean(x);
    /* samples taken while disabled do not count towards a decision */
    for (int i = 0; i < MAX_UES; i++) ues[i].since_seq = ues[i].seq;
    pthread_mutex_unlock(&st_lock);
    json_object_object_add(o, "enabled", json_object_new_boolean(cfg.enabled));
    printf("[defense] detection %s by request\n", cfg.enabled ? "enabled" : "disabled");
    code = 200;
  } else if (strcmp(url, "/v1/defense/reset") == 0 && in && json_object_object_get_ex(in, "supi", &x) && json_object_is_type(x, json_type_string)) {
    pthread_mutex_lock(&st_lock);
    ue_t *u = ue_for(json_object_get_string(x), false);
    if (u) {
      u->score = 0;
      u->since_seq = u->seq;
      u->probation_us = 0;
      u->peak = u->pending = 0;
      u->core_assist = false;
      /* embedded model: alarm-rule history restarts too (a new episode, as offline); vectors already scored stay scored */
      const uint64_t scored = u->clf.last_seq;
      memset(&u->clf, 0, sizeof(u->clf));
      u->clf.last_seq = scored;
      u->limited_since_us = 0;
      u->esc_n = u->esc_head = u->esc_ref_n = 0;
      u->esc_would = false;
      policy_set_level(u, 0, time_now_us(), "admin reset");
      code = 200;
    }
    pthread_mutex_unlock(&st_lock);
    json_object_object_add(o, "reset", json_object_new_boolean(code == 200));
  } else if (strcmp(url, "/v1/defense/force") == 0 && in && json_object_object_get_ex(in, "supi", &x) && json_object_is_type(x, json_type_string)) {
    /* {"supi", "level", "ttl_s"?}: calibration runs only (2026-11-13): put a UE at a level without any decision, e.g. a
       benign UE at level 2 to see whether escalation by response wrongly blocks it; the level runs out after ttl_s
       (default: the level's expiry) and then steps down as usual. Logged with the reason "forced". */
    json_object *lv = NULL, *tt = NULL;
    const int level = json_object_object_get_ex(in, "level", &lv) ? json_object_get_int(lv) : -1;
    pthread_mutex_lock(&st_lock);
    ue_t *u = level >= 0 && level <= POLICY_MAX_LEVEL ? ue_for(json_object_get_string(x), false) : NULL;
    if (u) {
      const int64_t now = time_now_us();
      policy_set_level(u, level, now, "forced");
      if (level > u->peak) u->peak = level;
      if (level > 0 && json_object_object_get_ex(in, "ttl_s", &tt) && json_object_get_int(tt) > 0)
        u->expires_us = now + (int64_t)json_object_get_int(tt) * 1000000;
      code = 200;
      json_object_object_add(o, "level", json_object_new_int(u->level));
    } else {
      code = level < 0 || level > POLICY_MAX_LEVEL ? 400 : 404;
    }
    pthread_mutex_unlock(&st_lock);
    json_object_object_add(o, "forced", json_object_new_boolean(code == 200));
  } else if (strcmp(url, "/v1/defense/mode") == 0 && in && json_object_object_get_ex(in, "mode", &x) && json_object_is_type(x, json_type_string)
             && (strcmp(json_object_get_string(x), "slice") == 0 || strcmp(json_object_get_string(x), "ue") == 0)) {
    /* {"mode": "slice"|"ue"}: RAN action of levels 1-2 (experiments compare
       both); every UE is synced again with the new action */
    pthread_mutex_lock(&st_lock);
    cfg.slice_mode = strcmp(json_object_get_string(x), "slice") == 0;
    for (int i = 0; i < MAX_UES; i++) ues[i].synced_amf = 0;
    pthread_mutex_unlock(&st_lock);
    json_object_object_add(o, "mode", json_object_new_string(cfg.slice_mode ? "slice" : "ue"));
    printf("[defense] action mode %s by request\n", cfg.slice_mode ? "slice" : "ue");
    code = 200;
  } else if (strcmp(url, "/v1/defense/timing") == 0 && in) {
    /* {"expiryS": [l1, l2, l3, l4], "probationS"?, "fusionS"?, "releaseOnBlock"?}: experiments
       with a shorter ladder (not persisted; the next restart reads the config) */
    json_object *y = NULL;
    pthread_mutex_lock(&st_lock);
    if (json_object_object_get_ex(in, "expiryS", &y) && json_object_is_type(y, json_type_array))
      for (size_t i = 0; i < json_object_array_length(y) && i < 4; i++) cfg.expiry_s[i] = json_object_get_int(json_object_array_get_idx(y, i));
    cfg.probation_s = (int)num(in, "probationS", cfg.probation_s);
    cfg.fusion_s = (int)num(in, "fusionS", cfg.fusion_s);
    if (json_object_object_get_ex(in, "releaseOnBlock", &y) && json_object_is_type(y, json_type_boolean))
      cfg.release_on_block = json_object_get_boolean(y);
    json_object *ex = json_object_new_array();
    for (int i = 0; i < 4; i++) json_object_array_add(ex, json_object_new_int(cfg.expiry_s[i]));
    json_object_object_add(o, "expiry_s", ex);
    json_object_object_add(o, "probation_s", json_object_new_int(cfg.probation_s));
    json_object_object_add(o, "fusion_s", json_object_new_int(cfg.fusion_s));
    json_object_object_add(o, "release_on_block", json_object_new_boolean(cfg.release_on_block));
    printf("[defense] timing by request: expiry %d/%d/%d/%d s, probation %d s, fusion %d s\n", cfg.expiry_s[0], cfg.expiry_s[1],
           cfg.expiry_s[2], cfg.expiry_s[3], cfg.probation_s, cfg.fusion_s);
    pthread_mutex_unlock(&st_lock);
    code = 200;
  } else if (strcmp(url, "/v1/defense/actuate") == 0 && in && json_object_object_get_ex(in, "actuate", &x) &&
             json_object_is_type(x, json_type_boolean)) {
    /* {"actuate": bool}: false = observe mode (live detection test) */
    pthread_mutex_lock(&st_lock);
    cfg.actuate = json_object_get_boolean(x);
    pthread_mutex_unlock(&st_lock);
    json_object_object_add(o, "actuate", json_object_new_boolean(cfg.actuate));
    printf("[defense] actions %s by request\n", cfg.actuate ? "on" : "off (observe)");
    code = 200;
  } else if (strcmp(url, "/v1/defense/escalation") == 0 && in) {
    /* {"enabled"?, "graceS"?, "hits"?, "samples"?, "overRatio"?, "relRatio"?, "refS"?, "shadow"?} */
    json_object *y = NULL;
    pthread_mutex_lock(&st_lock);
    if (json_object_object_get_ex(in, "enabled", &y) && json_object_is_type(y, json_type_boolean)) cfg.esc_enabled = json_object_get_boolean(y);
    cfg.esc_grace_s = (int)num(in, "graceS", cfg.esc_grace_s);
    cfg.esc_n = (int)num(in, "samples", cfg.esc_n);
    cfg.esc_k = (int)num(in, "hits", cfg.esc_k);
    cfg.esc_over_ratio = num(in, "overRatio", cfg.esc_over_ratio);
    cfg.esc_rel_ratio = num(in, "relRatio", cfg.esc_rel_ratio);
    cfg.esc_ref_s = (int)num(in, "refS", cfg.esc_ref_s);
    if (json_object_object_get_ex(in, "shadow", &y) && json_object_is_type(y, json_type_boolean)) cfg.esc_shadow = json_object_get_boolean(y);
    if (cfg.esc_n < 1 || cfg.esc_n > 32) cfg.esc_n = 10;
    if (cfg.esc_k < 1 || cfg.esc_k > cfg.esc_n) cfg.esc_k = cfg.esc_n;
    if (cfg.esc_ref_s < 1 || cfg.esc_ref_s > 8) cfg.esc_ref_s = 3;
    if (cfg.esc_rel_ratio < 0) cfg.esc_rel_ratio = 0;
    json_object_object_add(o, "enabled", json_object_new_boolean(cfg.esc_enabled));
    json_object_object_add(o, "graceS", json_object_new_int(cfg.esc_grace_s));
    json_object_object_add(o, "hits", json_object_new_int(cfg.esc_k));
    json_object_object_add(o, "samples", json_object_new_int(cfg.esc_n));
    json_object_object_add(o, "overRatio", json_object_new_double(cfg.esc_over_ratio));
    json_object_object_add(o, "relRatio", json_object_new_double(cfg.esc_rel_ratio));
    json_object_object_add(o, "refS", json_object_new_int(cfg.esc_ref_s));
    json_object_object_add(o, "shadow", json_object_new_boolean(cfg.esc_shadow));
    printf("[defense] escalation by response %s%s: grace %d s, %d of %d, over %.2f, relRatio %.2f, refS %d (by request)\n",
           cfg.esc_enabled ? "on" : "off", cfg.esc_shadow ? " (shadow)" : "", cfg.esc_grace_s, cfg.esc_k, cfg.esc_n, cfg.esc_over_ratio,
           cfg.esc_rel_ratio, cfg.esc_ref_s);
    pthread_mutex_unlock(&st_lock);
    code = 200;
  } else if (strcmp(url, "/v1/defense/core") == 0 && in && json_object_object_get_ex(in, "enabled", &x) &&
             json_object_is_type(x, json_type_boolean)) {
    /* {"enabled": bool}: core layer on/off at run time (experiments compare
       RAN-only with both layers); off removes the UPF policies this xApp set
       and stops the URR rule, so levels stop at 2 */
    pthread_mutex_lock(&st_lock);
    cfg.core = json_object_get_boolean(x);
    for (int i = 0; i < MAX_UES; i++) {
      ues[i].pending = 0;
      ues[i].core_hit_us = 0;
      ues[i].core_assist = false;
    }
    json_object_object_add(o, "core", json_object_new_boolean(cfg.core));
    pthread_mutex_unlock(&st_lock);
    printf("[defense] core layer %s by request\n", cfg.core ? "enabled" : "disabled");
    code = 200;
  } else if (strcmp(url, "/v1/defense/classifier") == 0 && in && json_object_object_get_ex(in, "kind", &x) && json_object_is_type(x, json_type_string)
             && (strcmp(json_object_get_string(x), "rules") == 0 || strcmp(json_object_get_string(x), "xgb") == 0)) {
    /* {"kind": "rules"|"xgb"} */
    pthread_mutex_lock(&st_lock);
    cfg.xgb = strcmp(json_object_get_string(x), "xgb") == 0;
    if (cfg.xgb && !clf_ready()) clf_load(cfg.model_path);
    json_object_object_add(o, "classifier", classifier_state());
    pthread_mutex_unlock(&st_lock);
    printf("[defense] classifier %s by request\n", cfg.xgb ? "xgb" : "rules");
    code = 200;
  } else if (strcmp(url, "/v1/defense/tamper") == 0 && in) {
    code = tamper_http(in, o);
  } else if (strcmp(url, "/v1/defense/policy") == 0 && in && json_object_object_get_ex(in, "supi", &x) && json_object_is_type(x, json_type_string)) {
    /* {"supi", "class"}: persistent fair-use class of a SUPI (admin) */
    json_object *c = NULL;
    const char *supi = json_object_get_string(x);
    pthread_mutex_lock(&st_lock);
    int cls = json_object_object_get_ex(in, "class", &c) && json_object_is_type(c, json_type_string) ? class_index(json_object_get_string(c)) : -1;
    if (cls < 0) {
      json_object_object_add(o, "error", json_object_new_string("unknown class"));
      code = 400;
    } else if (!db) {
      json_object_object_add(o, "error", json_object_new_string("no reputation DB"));
      code = 503;
    } else {
      sqlite3_stmt *q = NULL;
      char at[40];
      iso(time_now_us(), at, sizeof(at));
      if (sqlite3_prepare_v2(db, "INSERT INTO policy(supi,class,updated_at) VALUES(?,?,?) ON CONFLICT(supi) DO UPDATE SET "
                                 "class=excluded.class,updated_at=excluded.updated_at", -1, &q, NULL) == SQLITE_OK) {
        sqlite3_bind_text(q, 1, supi, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(q, 2, cfg.classes[cls].name, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(q, 3, at, -1, SQLITE_TRANSIENT);
        code = sqlite3_step(q) == SQLITE_DONE ? 200 : 500;
      }
      sqlite3_finalize(q);
      ue_t *u = ue_for(supi, true);
      if (u && code == 200) {
        u->cls = cls;
        u->since_seq = u->seq;
      }
      json_object_object_add(o, "supi", json_object_new_string(supi));
      json_object_object_add(o, "class", json_object_new_string(cfg.classes[cls].name));
      printf("[defense] %s fair-use class %s by request\n", supi, cfg.classes[cls].name);
    }
    pthread_mutex_unlock(&st_lock);
  } else {
    json_object_object_add(o, "error", json_object_new_string("GET /v1/defense/state, POST /v1/defense/enabled|reset|force|policy|mode|classifier|timing|core|tamper|actuate|escalation"));
    code = body ? 400 : 404;
  }
  if (in) json_object_put(in);
  return code;
}

/* ---------- lifecycle ---------- */

int defense_start(const char *db_path, const char *event_log_path) {
  load_config();
  policy_open_db(db_path);
  if (event_log_path && !(events = fopen(event_log_path, "a")))
    fprintf(stderr, "[defense] cannot open %s\n", event_log_path);
  /* dataset next to the event log: <run>/KPI_Metrics_Features.jsonl */
  if (event_log_path) {
    char path[512];
    const char *suffix = strstr(event_log_path, "_Defense.jsonl");
    if (suffix) snprintf(path, sizeof(path), "%.*s_Features.jsonl", (int)(suffix - event_log_path), event_log_path);
    else snprintf(path, sizeof(path), "%s.features.jsonl", event_log_path);
    features_open(path);
    char rawp[512];
    if (suffix) snprintf(rawp, sizeof(rawp), "%.*s_RawKpm.jsonl", (int)(suffix - event_log_path), event_log_path);
    else snprintf(rawp, sizeof(rawp), "%s.rawkpm.jsonl", event_log_path);
    features_raw_open(rawp);
    char tp[512];
    if (suffix) snprintf(tp, sizeof(tp), "%.*s_Tamper.jsonl", (int)(suffix - event_log_path), event_log_path);
    else snprintf(tp, sizeof(tp), "%s.tamper.jsonl", event_log_path);
    if (!(tamper_log = fopen(tp, "a"))) fprintf(stderr, "[defense] cannot open %s\n", tp);
    char cp[512];
    if (suffix) snprintf(cp, sizeof(cp), "%.*s_Clf.jsonl", (int)(suffix - event_log_path), event_log_path);
    else snprintf(cp, sizeof(cp), "%s.clf.jsonl", event_log_path);
    clf_log_open(cp);
  }
  if (cfg.xgb && clf_load(cfg.model_path) != 0) fprintf(stderr, "[defense] embedded model not loaded: rules decide\n");
  policy_restore();
  running = true;
  return pthread_create(&worker, NULL, run, NULL) == 0 ? 0 : -1;
}

void defense_stop(void) {
  pthread_mutex_lock(&q_lock);
  bool was = running;
  running = false;
  pthread_cond_signal(&q_cond);
  pthread_mutex_unlock(&q_lock);
  if (was) pthread_join(worker, NULL);
  for (int i = 0; i < MAX_UES; i++)
    if (ues[i].used) features_flush(&ues[i], time_now_us(), true);
  if (events) fclose(events);
  events = NULL;
  features_close();
  features_raw_close();
  clf_log_close();
  pthread_mutex_lock(&t_lock);
  if (tamper_log) fclose(tamper_log);
  tamper_log = NULL;
  pthread_mutex_unlock(&t_lock);
  if (db) sqlite3_close(db);
  db = NULL;
}
