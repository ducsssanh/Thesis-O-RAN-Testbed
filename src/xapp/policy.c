/* policy layer of the defense (see defense_internal.h): the escalation
   0-4 (table in policy_rules.h) from the classifier's labels,
   independent of which classifier produced them, the fusion of the two
   layers' evidence and the reputation DB */
#define _GNU_SOURCE /* strptime, timegm */
#include "defense_internal.h"
#include "policy_rules.h"
#include "../../../../src/util/time_now_us.h"
#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static uint64_t next_decision;

#define NEVER "9999-12-31T00:00:00"

static void save_reputation(const ue_t *u, int64_t now) {
  if (!db) return;
  sqlite3_stmt *q = NULL;
  char exp[40], upd[40], prob[40] = "";
  iso(u->expires_us, exp, sizeof(exp));
  iso(now, upd, sizeof(upd));
  if (u->probation_us > now) iso(u->probation_us, prob, sizeof(prob));
  if (sqlite3_prepare_v2(db, "INSERT INTO reputation(supi,level,score,expires_at,updated_at,peak,probation_until) VALUES(?,?,?,?,?,?,?) "
                             "ON CONFLICT(supi) DO UPDATE SET level=excluded.level,score=excluded.score,"
                             "expires_at=excluded.expires_at,updated_at=excluded.updated_at,peak=excluded.peak,"
                             "probation_until=excluded.probation_until", -1, &q, NULL) == SQLITE_OK) {
    sqlite3_bind_text(q, 1, u->supi, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(q, 2, u->level);
    sqlite3_bind_double(q, 3, u->score);
    sqlite3_bind_text(q, 4, u->level ? (u->expires_us ? exp : NEVER) : "", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(q, 5, upd, -1, SQLITE_TRANSIENT);
    sqlite3_bind_int(q, 6, u->peak);
    sqlite3_bind_text(q, 7, prob, -1, SQLITE_TRANSIENT);
    sqlite3_step(q);
  }
  sqlite3_finalize(q);
}

static void save_evidence(const ue_t *u, int64_t now, double severity, double trust, const features_t *f, const cls_result_t *r) {
  char ref[96], at[40];
  snprintf(ref, sizeof(ref), "kpm:node=%s/ue=%" PRIu64 "/t=%" PRId64, f->node, f->amf, f->collect_us / 1000);
  iso(now, at, sizeof(at));
  if (db) {
    sqlite3_stmt *q = NULL;
    if (sqlite3_prepare_v2(db, "INSERT INTO evidence(supi,at,layer,kind,severity,ref,trust) VALUES(?,?,?,?,?,?,?)", -1, &q, NULL) == SQLITE_OK) {
      sqlite3_bind_text(q, 1, u->supi, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 2, at, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 3, r->layer, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 4, r->kind, -1, SQLITE_TRANSIENT);
      sqlite3_bind_double(q, 5, severity);
      sqlite3_bind_text(q, 6, ref, -1, SQLITE_TRANSIENT);
      sqlite3_bind_double(q, 7, trust);
      sqlite3_step(q);
    }
    sqlite3_finalize(q);
  }
  json_object *o = event_base("evidence", u, now);
  json_object_object_add(o, "kind", json_object_new_string(r->kind));
  json_object_object_add(o, "layer", json_object_new_string(r->layer));
  json_object_object_add(o, "label", json_object_new_string(label_name(r->label)));
  json_object_object_add(o, "classifier", json_object_new_string(r->source));
  json_object_object_add(o, "classifier_score", json_object_new_double(r->score));
  json_object_object_add(o, "reason", json_object_new_string(r->reason));
  json_object_object_add(o, "severity", json_object_new_double(severity));
  json_object_object_add(o, "trust", json_object_new_double(trust));
  json_object_object_add(o, "score", json_object_new_double(u->score));
  json_object_object_add(o, "ref", json_object_new_string(ref));
  json_object_object_add(o, "collect_ms", json_object_new_int64(f->collect_us / 1000));
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
  json_object_object_add(o, "class", json_object_new_string(cfg.classes[u->cls].name));
  if (f->has_urr) {
    json_object_object_add(o, "urr_ul_kbps", json_object_new_double(f->urr_ul_kbps));
    json_object_object_add(o, "urr_dl_kbps", json_object_new_double(f->urr_dl_kbps));
  }
  json_object_object_add(o, "ran_hit_age_s", json_object_new_double(u->ran_hit_us ? (now - u->ran_hit_us) / 1e6 : -1));
  json_object_object_add(o, "core_hit_age_s", json_object_new_double(u->core_hit_us ? (now - u->core_hit_us) / 1e6 : -1));
  json_object_object_add(o, "repeats", json_object_new_int((int)u->repeats));
  event(o);
}

void policy_open_db(const char *path) {
  if (!path || sqlite3_open(path, &db) != SQLITE_OK) {
    fprintf(stderr, "[defense] cannot open %s: reputation not persisted\n", path ? path : "(null)");
    if (db) sqlite3_close(db);
    db = NULL;
    return;
  }
  exec_sql("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"
           "CREATE TABLE IF NOT EXISTS reputation(supi TEXT PRIMARY KEY,level INTEGER NOT NULL,score REAL NOT NULL,"
           "expires_at TEXT NOT NULL,updated_at TEXT NOT NULL);"
           "CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY,supi TEXT NOT NULL,at TEXT NOT NULL,layer TEXT NOT NULL,"
           "kind TEXT NOT NULL,severity REAL NOT NULL,ref TEXT NOT NULL,trust REAL NOT NULL);"
           "CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY,supi TEXT NOT NULL,at TEXT NOT NULL,layer TEXT NOT NULL,"
           "action TEXT NOT NULL,detail TEXT NOT NULL,status INTEGER NOT NULL,verified INTEGER NOT NULL);"
           "CREATE TABLE IF NOT EXISTS e2_trust(e2_node TEXT PRIMARY KEY,kpm_trust REAL NOT NULL DEFAULT 1.0,"
           "ctrl_trust REAL NOT NULL DEFAULT 1.0,last_mismatch TEXT,alarm INTEGER NOT NULL DEFAULT 0);"
           "CREATE TABLE IF NOT EXISTS policy(supi TEXT PRIMARY KEY,class TEXT NOT NULL,updated_at TEXT NOT NULL);");
  /* L1 columns on a DB created by an older xApp (fails harmlessly when present) */
  sqlite3_exec(db, "ALTER TABLE reputation ADD COLUMN peak INTEGER NOT NULL DEFAULT 0", NULL, NULL, NULL);
  sqlite3_exec(db, "ALTER TABLE reputation ADD COLUMN probation_until TEXT NOT NULL DEFAULT ''", NULL, NULL, NULL);
}

/* the gate flagged a UE's KPM (masked) or cleared it: stored and reported */
void policy_flag_ue(const char *supi, const char *node, double trust, bool masked, double c_t) {
  char now_iso[40];
  iso(time_now_us(), now_iso, sizeof(now_iso));
  if (db) {
    sqlite3_stmt *q = NULL;
    sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS ue_kpm_trust(supi TEXT PRIMARY KEY, e2_node TEXT, kpm_trust REAL, last_mismatch TEXT, alarm INTEGER)", NULL, NULL, NULL);
    if (sqlite3_prepare_v2(db, "INSERT INTO ue_kpm_trust(supi,e2_node,kpm_trust,last_mismatch,alarm) VALUES(?1,?2,?3,?4,?5) ON CONFLICT(supi) DO UPDATE SET "
                               "e2_node=?2,kpm_trust=?3,last_mismatch=?4,alarm=?5", -1, &q, NULL) == SQLITE_OK) {
      sqlite3_bind_text(q, 1, supi, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 2, node, -1, SQLITE_TRANSIENT);
      sqlite3_bind_double(q, 3, trust);
      sqlite3_bind_text(q, 4, now_iso, -1, SQLITE_TRANSIENT);
      sqlite3_bind_int(q, 5, masked);
      sqlite3_step(q);
    }
    sqlite3_finalize(q);
  }
  json_object *o = json_object_new_object();
  json_object_object_add(o, "type", json_object_new_string("kpm_gate"));
  json_object_object_add(o, "at", json_object_new_string(now_iso));
  json_object_object_add(o, "supi", json_object_new_string(supi));
  json_object_object_add(o, "e2_node", json_object_new_string(node));
  json_object_object_add(o, "kpm_trust", json_object_new_double(trust));
  json_object_object_add(o, "kpm_masked", json_object_new_boolean(masked));
  json_object_object_add(o, "c_t", json_object_new_double(c_t));
  event(o);
  printf("[defense] UE %s KPM %s (trust %.2f, c_t %.2f)\n", supi, masked ? "masked" : "trusted again", trust, c_t);
  fflush(stdout);
}

/* fair-use class of a SUPI: DB policy row, else config supiClass, else default */
static int resolve_class(const char *supi) {
  int cls = -1;
  if (db) {
    sqlite3_stmt *q = NULL;
    if (sqlite3_prepare_v2(db, "SELECT class FROM policy WHERE supi=?", -1, &q, NULL) == SQLITE_OK) {
      sqlite3_bind_text(q, 1, supi, -1, SQLITE_TRANSIENT);
      if (sqlite3_step(q) == SQLITE_ROW) cls = class_index((const char *)sqlite3_column_text(q, 0));
    }
    sqlite3_finalize(q);
  }
  for (int i = 0; cls < 0 && i < cfg.n_assign; i++)
    if (strcmp(cfg.assign[i].supi, supi) == 0) cls = cfg.assign[i].cls;
  return cls < 0 ? 0 : cls;
}

ue_t *ue_for(const char *supi, bool create) {
  ue_t *free_slot = NULL;
  for (int i = 0; i < MAX_UES; i++) {
    if (ues[i].used && strcmp(ues[i].supi, supi) == 0) return &ues[i];
    if (!ues[i].used && !free_slot) free_slot = &ues[i];
  }
  if (!create || !free_slot) return NULL;
  memset(free_slot, 0, sizeof(*free_slot));
  free_slot->used = true;
  snprintf(free_slot->supi, sizeof(free_slot->supi), "%s", supi);
  free_slot->cls = resolve_class(supi);
  return free_slot;
}

static void add_score(ue_t *u, int64_t now, double v) {
  if (u->score_us && cfg.half_life_s > 0) u->score *= pow(0.5, (now - u->score_us) / 1e6 / cfg.half_life_s);
  u->score += v;
  u->score_us = now;
}

void policy_set_level(ue_t *u, int level, int64_t now, const char *why) {
  int old = u->level;
  u->level = level;
  int exp = level > 0 ? cfg.expiry_s[level - 1] : 0;
  u->expires_us = exp > 0 ? now + (int64_t)exp * 1000000 : 0; /* level 4 in lab: until reset */
  if (level > u->peak) u->peak = level;
  if (old < 3 && level >= 3) u->release_pending = true;
  if (level < 3) u->release_pending = false;
  save_reputation(u, now);
  if (old != level) {
    json_object *o = event_base("level", u, now);
    json_object_object_add(o, "from", json_object_new_int(old));
    json_object_object_add(o, "why", json_object_new_string(why));
    json_object_object_add(o, "peak", json_object_new_int(u->peak));
    json_object_object_add(o, "pending", json_object_new_int(u->pending));
    event(o);
    printf("[defense] %s level %d -> %d (%s)\n", u->supi, old, level, why);
    fflush(stdout);
  }
}

static bool recent(int64_t at, int64_t now) {
  return at && now - at <= (int64_t)cfg.fusion_s * 1000000;
}

/* One classifier result. Both layers' window hits are timestamped (fusion);
   an attack label is evidence and moves the level by policy_next() (levels
   >= 3 only with both layers within fusion_s); a capped level completes
   when the second layer's evidence arrives. Returns the decision ID, 0 when
   nothing was decided. */
uint64_t policy_apply(ue_t *u, const features_t *f, const cls_result_t *r, int64_t now) {
  if (r->uncongested) uncongested++; /* heavy use of an idle cell: not a violation */
  if (r->ran_hit) u->ran_hit_us = now;
  if (r->core_hit) u->core_hit_us = now;
  /* KPM hidden (c_t well below the band, or this UE masked): core evidence
     stands alone, otherwise a gNB could keep an attacker out of block */
  const bool hidden = f->kpm_masked || (f->has_gate && f->c_t < cfg.gate_lo);
  const bool both = recent(u->core_hit_us, now) && (hidden || recent(u->ran_hit_us, now));
  const bool attack = r->label == LABEL_ATTACK;
  if (!attack && !(u->pending > u->level && both)) return 0;

  const bool in_prob = u->level == 0 && now < u->probation_us;
  policy_next_t n = policy_next(u->level, u->peak, in_prob, u->pending, both);
  /* the embedded model names its level (2 rate limit, 3 block); it is taken
     as is, above the ladder and the single-layer cap */
  const bool by_model = attack && r->want_level > n.level;
  if (by_model) {
    n.level = r->want_level > POLICY_MAX_LEVEL ? POLICY_MAX_LEVEL : r->want_level;
    n.pending = 0;
  }
  const bool escalates = n.level != u->level;
  if (attack) u->since_seq = f->seq; /* later decisions use later samples only */
  if (!escalates && u->level >= 1) {
    /* repeated label while the level is in force: refresh its expiry; with
       the "refresh" strategy evidence is recorded sparsely */
    u->pending = n.pending;
    if (!attack) return 0;
    if (!cfg.repeat_every && now - u->evidence_us < (int64_t)cfg.evidence_interval_s * 1000000) {
      u->repeats++;
      policy_set_level(u, u->level, now, r->kind);
      return 0;
    }
  }
  double trust = features_kpm_trust(u->supi);
  double sev = cfg.sev_rate + (in_prob ? cfg.sev_repeat : 0);
  add_score(u, now, sev * trust);
  u->decision_id = ++next_decision;
  cls_result_t ev = *r;
  if (!attack) { /* the second layer completed a capped escalation */
    snprintf(ev.kind, sizeof(ev.kind), "second_layer");
    snprintf(ev.layer, sizeof(ev.layer), "both");
  }
  save_evidence(u, now, sev, trust, f, &ev);
  u->evidence_us = now;
  u->repeats = 0;
  if (u->level == 0 && !in_prob) u->peak = 0; /* a new episode */
  u->pending = n.pending;
  policy_set_level(u, n.level, now, !attack ? "both_layers" : by_model ? "model_level" : escalates && in_prob ? "repeat_offense" : r->kind);
  return u->decision_id;
}

/* a level in force runs out to the one below; at 0 the probation starts */
void policy_expire(int64_t now) {
  for (int i = 0; i < MAX_UES; i++) {
    ue_t *u = &ues[i];
    if (!u->used || u->level == 0 || !u->expires_us || now < u->expires_us) continue;
    if (u->level == 1) u->probation_us = now + (int64_t)cfg.probation_s * 1000000;
    u->pending = 0;
    policy_set_level(u, u->level - 1, now, "expired");
  }
}

/* reputation survives an xApp restart: levels still in force come back and
   their quotas are applied again when the SUPI is next seen */
void policy_restore(void) {
  if (!db) return;
  sqlite3_stmt *q = NULL;
  char now_iso[40];
  iso(time_now_us(), now_iso, sizeof(now_iso));
  if (sqlite3_prepare_v2(db, "SELECT supi,level,score,expires_at,peak,probation_until FROM reputation "
                             "WHERE (level>0 AND expires_at>?1) OR probation_until>?1", -1, &q, NULL) == SQLITE_OK) {
    sqlite3_bind_text(q, 1, now_iso, -1, SQLITE_TRANSIENT);
    while (sqlite3_step(q) == SQLITE_ROW) {
      ue_t *u = ue_for((const char *)sqlite3_column_text(q, 0), true);
      if (!u) break;
      u->level = sqlite3_column_int(q, 1);
      u->score = sqlite3_column_double(q, 2);
      u->score_us = time_now_us();
      u->peak = sqlite3_column_int(q, 4);
      const char *exp = (const char *)sqlite3_column_text(q, 3), *prob = (const char *)sqlite3_column_text(q, 5);
      struct tm tm = {0};
      if (u->level && strcmp(exp, NEVER) != 0 && strptime(exp, "%Y-%m-%dT%H:%M:%S", &tm))
        u->expires_us = (int64_t)timegm(&tm) * 1000000;
      memset(&tm, 0, sizeof(tm));
      if (prob && *prob && strptime(prob, "%Y-%m-%dT%H:%M:%S", &tm)) u->probation_us = (int64_t)timegm(&tm) * 1000000;
      printf("[defense] restored %s at level %d (peak %d%s)\n", u->supi, u->level, u->peak, u->probation_us ? ", on probation" : "");
    }
  }
  sqlite3_finalize(q);
}
