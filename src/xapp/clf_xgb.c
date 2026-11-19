/* Embedded XGBoost classifier (see clf_xgb.h). The model file is written by
   scripts/ml/export_clf.py; the tree walk follows XGBoost: go left when
   x < split (float), a missing value takes default_left, a leaf's value is
   its split_conditions entry. Ensemble logit = mean over seeds of
   (base_margin + sum of leaves) / temperature. */
#include "clf_xgb.h"
#include <json-c/json.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  int n;
  int *left, *right, *feat;
  float *thr;
  unsigned char *dleft;
} tree_t;

typedef struct {
  double temperature, base_margin;
  int n_trees;
  tree_t *trees;
} booster_t;

typedef struct {
  char rule[12];
  int k, n;               /* k of n (thr: 1 of 1); 0 for cusum */
  bool active;            /* a<k><n>: k of the last n ACTIVE seconds (silent seconds are skipped, not counted as misses) */
  bool mean;              /* mean<n><k> (2026-11-10): mean logit of the last n ACTIVE seconds, once at least k of them exist */
  double threshold, prior;
} rule_t;

/* alarm rules, as eval_block_rules.py RULES */
static const struct { const char *name; int k, n; bool active, mean; } RULES[] = {
  {"thr", 1, 1, false, false}, {"k23", 2, 3, false, false}, {"k35", 3, 5, false, false}, {"k610", 6, 10, false, false},
  {"k1220", 12, 20, false, false}, {"k2030", 20, 30, false, false},
  {"a2030", 20, 30, true, false}, {"a1220", 12, 20, true, false}, {"a1020", 10, 20, true, false},
  {"a510", 5, 10, true, false}, {"a612", 6, 12, true, false}, {"a815", 8, 15, true, false}, {"a816", 8, 16, true, false},
  {"a1015", 10, 15, true, false},
  {"mean66", 6, 6, true, true}, {"mean610", 6, 10, true, true}, {"mean812", 8, 12, true, true}, {"mean1010", 10, 10, true, true},
  {"mean2010", 10, 20, true, true}, {"mean3010", 10, 30, true, true},
};

static booster_t *B;
static int nB;
static rule_t soft, block;
static double delta_s = 0.2;
static int win_s = 10;
static int nf = 25;      /* inputs the model expects (features list of the model file) */
static bool ready;

static int set_rule(rule_t *r, json_object *o) {
  json_object *x = NULL;
  if (!o || !json_object_object_get_ex(o, "rule", &x)) return -1;
  snprintf(r->rule, sizeof(r->rule), "%s", json_object_get_string(x));
  r->threshold = json_object_object_get_ex(o, "threshold", &x) ? json_object_get_double(x) : 0;
  r->prior = json_object_object_get_ex(o, "prior", &x) ? json_object_get_double(x) : 0;
  r->active = r->mean = false;
  if (strcmp(r->rule, "cusum") == 0) { r->k = 0; r->n = 0; return 0; }
  for (size_t i = 0; i < sizeof(RULES) / sizeof(RULES[0]); i++)
    if (strcmp(r->rule, RULES[i].name) == 0) {
      r->k = RULES[i].k; r->n = RULES[i].n; r->active = RULES[i].active; r->mean = RULES[i].mean;
      return 0;
    }
  return -1;
}

static int load_tree(tree_t *t, json_object *o) {
  json_object *l, *r, *f, *s, *d;
  if (!json_object_object_get_ex(o, "left", &l) || !json_object_object_get_ex(o, "right", &r) ||
      !json_object_object_get_ex(o, "feat", &f) || !json_object_object_get_ex(o, "thr", &s) ||
      !json_object_object_get_ex(o, "default_left", &d))
    return -1;
  t->n = (int)json_object_array_length(l);
  t->left = malloc(sizeof(int) * t->n); t->right = malloc(sizeof(int) * t->n); t->feat = malloc(sizeof(int) * t->n);
  t->thr = malloc(sizeof(float) * t->n); t->dleft = malloc(t->n);
  for (int i = 0; i < t->n; i++) {
    t->left[i] = json_object_get_int(json_object_array_get_idx(l, i));
    t->right[i] = json_object_get_int(json_object_array_get_idx(r, i));
    t->feat[i] = json_object_get_int(json_object_array_get_idx(f, i));
    t->thr[i] = (float)json_object_get_double(json_object_array_get_idx(s, i));
    json_object *dv = json_object_array_get_idx(d, i);
    t->dleft[i] = json_object_is_type(dv, json_type_boolean) ? json_object_get_boolean(dv) : json_object_get_int(dv) != 0;
    if (t->left[i] >= t->n || t->right[i] >= t->n || (t->left[i] >= 0 && (t->feat[i] < 0 || t->feat[i] >= CLF_NF))) return -1;
  }
  return 0;
}

int clf_load(const char *path) {
  json_object *m = json_object_from_file(path), *x = NULL, *bs = NULL;
  if (!m) {
    fprintf(stderr, "[clf] cannot read %s\n", path);
    return -1;
  }
  int rc = -1;
  if (json_object_object_get_ex(m, "delta_s", &x)) delta_s = json_object_get_double(x);
  if (json_object_object_get_ex(m, "win_s", &x)) win_s = json_object_get_int(x);
  if (json_object_object_get_ex(m, "features", &x) && json_object_is_type(x, json_type_array)) nf = (int)json_object_array_length(x);
  if (nf != 25 && nf != 31) goto out;
  if (win_s < 1 || win_s > CLF_HIST) win_s = 10;
  json_object *so = NULL, *bo = NULL;
  json_object_object_get_ex(m, "soft", &so);
  json_object_object_get_ex(m, "block", &bo);
  if (set_rule(&soft, so) || set_rule(&block, bo) || soft.n > CLF_HIST || block.n > CLF_HIST) goto out;
  if (!json_object_object_get_ex(m, "boosters", &bs)) goto out;
  nB = (int)json_object_array_length(bs);
  B = calloc(nB, sizeof(booster_t));
  for (int b = 0; b < nB; b++) {
    json_object *o = json_object_array_get_idx(bs, b), *tr = NULL;
    B[b].temperature = json_object_object_get_ex(o, "temperature", &x) ? json_object_get_double(x) : 1.0;
    B[b].base_margin = json_object_object_get_ex(o, "base_margin", &x) ? json_object_get_double(x) : 0.0;
    if (!json_object_object_get_ex(o, "trees", &tr)) goto out;
    B[b].n_trees = (int)json_object_array_length(tr);
    B[b].trees = calloc(B[b].n_trees, sizeof(tree_t));
    for (int i = 0; i < B[b].n_trees; i++)
      if (load_tree(&B[b].trees[i], json_object_array_get_idx(tr, i))) goto out;
  }
  ready = nB > 0;
  rc = ready ? 0 : -1;
  printf("[clf] %s: %d boosters, soft %s > %.4f, block %s > %.4f, delta %.2f s, window %d s\n", path, nB, soft.rule, soft.threshold,
         block.rule, block.threshold, delta_s, win_s);
out:
  if (rc) fprintf(stderr, "[clf] bad model file %s\n", path);
  json_object_put(m);
  return rc;
}

bool clf_ready(void) { return ready; }
int clf_nf(void) { return nf; }
const char *clf_soft_rule(void) { return soft.rule; }
double clf_soft_threshold(void) { return soft.threshold; }
double clf_block_threshold(void) { return block.threshold; }
double clf_delta_s(void) { return delta_s; }

float clf_margin(const float *x) {
  double z = 0;
  for (int b = 0; b < nB; b++) {
    double m = B[b].base_margin;
    for (int i = 0; i < B[b].n_trees; i++) {
      const tree_t *t = &B[b].trees[i];
      int k = 0;
      while (t->left[k] >= 0) {
        const float v = x[t->feat[k]];
        k = isnan(v) ? (t->dleft[k] ? t->left[k] : t->right[k]) : (v < t->thr[k] ? t->left[k] : t->right[k]);
      }
      m += t->thr[k];
    }
    z += m / B[b].temperature;
  }
  return (float)(z / nB);
}

/* the i-th newest entry of a ring (0 = newest) */
#define AT(s, a, i) ((s)->a[((s)->head - 1 - (i) + 2 * CLF_HIST) % CLF_HIST])

static float np_sum(const float *a, int n);

static bool new_evidence(const rule_t *r, bool act, float z) {
  if (r->mean) return act;
  if (r->active) return act && z > r->threshold;
  return r->n == 0 || z > r->threshold; /* k of the last n seconds: this second a hit; CUSUM: as is */
}

static bool fire(const clf_state_t *s, const rule_t *r, double *cusum, float z, double *stat) {
  if (r->n == 0) { /* CUSUM on the logit */
    *cusum = fmax(0.0, *cusum + z - r->prior);
    *stat = *cusum;
    return *cusum > r->threshold;
  }
  int hits = 0;
  if (r->mean) { /* eval_block_rules.py "mean": np.mean of the float32 logits of the last n active seconds, oldest first */
    const int m = s->na < r->n ? s->na : r->n;
    if (m < r->k) { *stat = 0; return false; }
    float a[CLF_HIST];
    for (int j = 0; j < m; j++) a[j] = s->za[(s->heada - m + j + 2 * CLF_HIST) % CLF_HIST];
    const float mu = np_sum(a, m) / (float)m;
    *stat = mu;
    return mu > r->threshold;
  }
  if (r->active) {
    const int m = s->na < r->n ? s->na : r->n;
    for (int i = 0; i < m; i++) hits += s->za[(s->heada - 1 - i + 2 * CLF_HIST) % CLF_HIST] > r->threshold;
    *stat = hits;
    return hits >= r->k;
  }
  const int m = s->n < r->n ? s->n : r->n;
  for (int i = 0; i < m; i++) hits += AT(s, z, i) > r->threshold;
  *stat = hits;
  return hits >= r->k;
}

/* numpy's pairwise float32 sum (umath loops, n <= 128), so that the window
   inputs are bit-identical to train_clf.py win_summary() on float32 arrays */
static float np_sum(const float *a, int n) {
  if (n < 8) {
    float r = 0.f;
    for (int i = 0; i < n; i++) r += a[i];
    return r;
  }
  float r[8];
  for (int j = 0; j < 8; j++) r[j] = a[j];
  int i;
  for (i = 8; i < n - (n % 8); i += 8)
    for (int j = 0; j < 8; j++) r[j] += a[i + j];
  float res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
  for (; i < n; i++) res += a[i];
  return res;
}

static float np_mean(const float *a, int n) { return (float)((double)np_sum(a, n) / n); }

static float np_max(const float *a, int n) {
  float m = a[0];
  for (int i = 1; i < n; i++) if (a[i] > m) m = a[i];
  return m;
}

static float np_std(const float *a, int n) {
  const float m = (float)((double)np_sum(a, n) / n);
  float d[CLF_HIST];
  for (int i = 0; i < n; i++) { d[i] = a[i] - m; d[i] = d[i] * d[i]; }
  return sqrtf((float)((double)np_sum(d, n) / n));
}

void clf_step(clf_state_t *s, const float cur[15], clf_out_t *out) {
  memset(out, 0, sizeof(*out));
  memcpy(out->x, cur, 15 * sizeof(float));
  s->c6[s->head] = cur[0]; s->c8[s->head] = cur[2]; s->c2[s->head] = cur[4]; s->c7[s->head] = cur[1];
  s->head = (s->head + 1) % CLF_HIST;
  if (s->n < CLF_HIST) s->n++;
  /* win_summary(raw, W) of train_clf.py over the last W seconds, oldest first, float32 as numpy */
  const int W = s->n < win_s ? s->n : win_s;
  float k[CLF_HIST], p[CLF_HIST], r[CLF_HIST];
  int busy = 0, run = 0, best = 0;
  for (int j = 0; j < W; j++) {
    const int i = W - 1 - j;
    k[j] = expm1f(AT(s, c6, i)); p[j] = expm1f(AT(s, c8, i)); r[j] = AT(s, c2, i) * 100.f;
    const bool b = k[j] >= 8.f;
    busy += b;
    run = b ? 0 : run + 1;
    if (run > best) best = run;
  }
  const float m = np_mean(k, W), mk = np_max(k, W);
  float *w = out->x + 15;
  w[0] = log1pf(m); w[1] = log1pf(mk); w[2] = log1pf(np_mean(p, W)); w[3] = log1pf(np_max(p, W));
  w[4] = (float)((double)np_mean(r, W) / 100.0); w[5] = (float)((double)np_max(r, W) / 100.0);
  w[6] = (float)((double)busy / W);
  w[7] = m > 0 ? np_std(k, W) / m : 0.f; w[8] = m > 0 ? mk / m : 0.f; w[9] = (float)((double)best / win_s);
  if (nf == 31) { /* train_clf.py coupling(): UL-DL coupling over the last 10 s and 30 s, float32 as numpy */
    float *c = out->x + 25;
    for (int span = 0; span < 2; span++) {
      const int L = span == 0 ? 10 : 30, n = s->n < L ? s->n : L;
      float u[CLF_HIST], d[CLF_HIST], ui[CLF_HIST];
      int ni = 0;
      for (int j = 0; j < n; j++) {
        const int i = n - 1 - j;
        u[j] = expm1f(AT(s, c6, i)); d[j] = expm1f(AT(s, c7, i));
        if (d[j] < 1.f) ui[ni++] = u[j];
      }
      const float su = np_sum(u, n), sd = np_sum(d, n), sui = ni ? np_sum(ui, ni) : 0.f;
      if (span == 0) { c[0] = log1pf(np_mean(d, n)); c[1] = log1pf(np_max(d, n)); c[2] = log1pf(sd) - log1pf(su); c[4] = su > 0 ? sui / su : 0.f; }
      else { c[3] = log1pf(sd) - log1pf(su); c[5] = su > 0 ? sui / su : 0.f; }
    }
  }
  out->z = clf_margin(out->x);
  s->z[(s->head - 1 + CLF_HIST) % CLF_HIST] = out->z;
  const bool act = expm1f(cur[0]) >= 8.f; /* active second: core UL >= 8 kbit/s, as eval_block_rules.py active() */
  if (act) {
    s->za[s->heada] = out->z;
    s->heada = (s->heada + 1) % CLF_HIST;
    if (s->na < CLF_HIST) s->na++;
  }
  /* a k-of-n rule over active seconds keeps its statistic through silent seconds and remembers the attack seconds in
     its window while new benign seconds arrive. It fires only on new attack evidence: an active second that is itself
     above the threshold (a mean rule: an active second), so a UE that stopped attacking no longer refreshes the action
     TTL. The k-th hit is always such a second, so the first firing (eval_block_rules.py first()) is unchanged. */
  out->soft = fire(s, &soft, &s->cusum_soft, out->z, &out->soft_stat) && new_evidence(&soft, act, out->z);
  out->block = fire(s, &block, &s->cusum_block, out->z, &out->block_stat) && new_evidence(&block, act, out->z);
}
