/* actuators layer of the defense (see defense_internal.h): RAN actions
   (E2SM-RC) and core actions (UPF Security API) that bring the gNB and the
   UPF in line with the levels, and the verifier of their effect:
     level  RAN                                    core (UPF, per SUPI)
     0      default slice, no quota                no policy
     1      quarantine slice (or PRB quota)        monitor
     2      quarantine slice                       ratelimit at the class rate
     3      quarantine slice + RRC Release once    block
     4      as 3 + RRC Release at every attach     block, TTL at the UPF's cap,
                                                   renewed while level 4 lasts
   A core policy expires at the UPF ttl_margin after the level would, so a
   dead xApp leaves nothing behind for long. The verifier checks the RAN
   limit with KPM PRB and with URR (the core view), and the UPF action with
   URR; a RAN limit the URR does not confirm lowers the gNB's ctrl_trust and
   adds the UPF ratelimit already at level 1. */
#include "defense_internal.h"
#include "http_client.h"
#include "ran_control.h"
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#define RETRY_US 2000000LL
#define UE_GONE_US 10000000LL

static sqlite3_int64 save_action(const ue_t *u, int64_t now, int ratio, int sst, int64_t sd, uint64_t amf, int code, json_object *res) {
  sqlite3_int64 id = 0;
  char at[40], detail[96];
  iso(now, at, sizeof(at));
  if (cfg.slice_mode)
    snprintf(detail, sizeof(detail), "max_prb_ratio=%d slice=%d/%06" PRIx64 " ue=%" PRIu64, ratio, sst, sd, amf);
  else
    snprintf(detail, sizeof(detail), "max_prb_ratio=%d ue=%" PRIu64, ratio, amf);
  if (db) {
    sqlite3_stmt *q = NULL;
    if (sqlite3_prepare_v2(db, "INSERT INTO actions(supi,at,layer,action,detail,status,verified) VALUES(?,?,'ran',?,?,?,0)", -1, &q, NULL) == SQLITE_OK) {
      sqlite3_bind_text(q, 1, u->supi, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 2, at, -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 3, cfg.slice_mode ? "slice_handover" : "prb_quota", -1, SQLITE_TRANSIENT);
      sqlite3_bind_text(q, 4, detail, -1, SQLITE_TRANSIENT);
      sqlite3_bind_int(q, 5, code);
      if (sqlite3_step(q) == SQLITE_DONE) id = sqlite3_last_insert_rowid(db);
    }
    sqlite3_finalize(q);
  }
  json_object *o = event_base("action", u, now);
  json_object_object_add(o, "layer", json_object_new_string("ran"));
  json_object_object_add(o, "action", json_object_new_string(cfg.slice_mode ? "slice_handover" : "prb_quota"));
  if (cfg.slice_mode) {
    char sl[32];
    snprintf(sl, sizeof(sl), "%d/%06" PRIx64, sst, sd);
    json_object_object_add(o, "slice", json_object_new_string(sl));
  }
  json_object_object_add(o, "max_prb_ratio", json_object_new_int(ratio));
  json_object_object_add(o, "amf_ue_ngap_id", json_object_new_uint64(amf));
  json_object_object_add(o, "http", json_object_new_int(code));
  if (res) json_object_object_add(o, "result", json_object_get(res));
  event(o);
  return id;
}

/* actions table row of any layer, written before the request is sent
   (status 0) and completed afterwards */
static sqlite3_int64 action_row(const char *supi, int64_t now, const char *layer, const char *action, const char *detail) {
  sqlite3_int64 id = 0;
  if (!db) return 0;
  char at[40];
  iso(now, at, sizeof(at));
  sqlite3_stmt *q = NULL;
  if (sqlite3_prepare_v2(db, "INSERT INTO actions(supi,at,layer,action,detail,status,verified) VALUES(?,?,?,?,?,0,0)", -1, &q, NULL) == SQLITE_OK) {
    sqlite3_bind_text(q, 1, supi, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(q, 2, at, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(q, 3, layer, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(q, 4, action, -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(q, 5, detail, -1, SQLITE_TRANSIENT);
    if (sqlite3_step(q) == SQLITE_DONE) id = sqlite3_last_insert_rowid(db);
  }
  sqlite3_finalize(q);
  return id;
}

static void action_done(sqlite3_int64 id, int status) {
  if (!db || !id) return;
  char sql[96];
  snprintf(sql, sizeof(sql), "UPDATE actions SET status=%d WHERE id=%lld", status, (long long)id);
  exec_sql(sql);
}

static void action_verified(sqlite3_int64 id) {
  if (!db || !id) return;
  char sql[96];
  snprintf(sql, sizeof(sql), "UPDATE actions SET verified=1 WHERE id=%lld", (long long)id);
  exec_sql(sql);
}

/* ---------- core (UPF Security API) ---------- */

static char boot_id[64], core_error[128];
static int64_t core_synced_us;
static unsigned long long core_requests, core_failures;
static sqlite3_int64 core_rows[MAX_UES]; /* latest core action row per UE slot */

const char *core_want(const ue_t *u, double *ul_kbps, double *dl_kbps) {
  *ul_kbps = *dl_kbps = 0;
  if (!cfg.core || !cfg.enabled || u->level == 0) return "none";
  if (u->level >= 3) return "block";
  if (u->level == 2 || u->core_assist) {
    *ul_kbps = cfg.limit_ul_kbps > 0 ? cfg.limit_ul_kbps : cfg.classes[u->cls].ul_rate_kbps * cfg.ratelimit_factor;
    *dl_kbps = cfg.limit_dl_kbps > 0 ? cfg.limit_dl_kbps : cfg.classes[u->cls].dl_rate_kbps * cfg.ratelimit_factor;
    return "ratelimit";
  }
  return "monitor";
}

/* one request to the UPF API; returns the HTTP status (0: no answer) and
   the parsed body in *out (may be NULL) */
static int upf(const char *method, const char *path, json_object *body, json_object **out) {
  char url[256], err[128] = "";
  snprintf(url, sizeof(url), "%s%s", cfg.upf_api, path);
  int status = 0;
  char *resp = http_call(method, url, body ? json_object_to_json_string_ext(body, JSON_C_TO_STRING_PLAIN) : NULL, cfg.upf_timeout_ms,
                         &status, err, sizeof(err));
  pthread_mutex_lock(&st_lock);
  core_requests++;
  if (!resp || (status != 200 && status != 404)) {
    core_failures++;
    snprintf(core_error, sizeof(core_error), "%s %s: %s", method, path, resp ? resp : err);
  }
  pthread_mutex_unlock(&st_lock);
  if (out) *out = resp ? json_tokener_parse(resp) : NULL;
  free(resp);
  return resp || status ? status : 0;
}

static void core_event(const ue_t *u, int64_t now, const char *action, double ul, double dl, int ttl, int status, json_object *res) {
  json_object *o = event_base("action", u, now);
  json_object_object_add(o, "layer", json_object_new_string("core"));
  json_object_object_add(o, "action", json_object_new_string(action));
  if (!strcmp(action, "ratelimit")) {
    json_object_object_add(o, "rate_ul_kbps", json_object_new_double(ul));
    json_object_object_add(o, "rate_dl_kbps", json_object_new_double(dl));
  }
  if (ttl) json_object_object_add(o, "ttl_s", json_object_new_int(ttl));
  json_object_object_add(o, "http", json_object_new_int(status));
  if (res) {
    json_object *x = NULL;
    if (json_object_object_get_ex(res, "error", &x)) json_object_object_add(o, "error", json_object_get(x));
    if (json_object_object_get_ex(res, "enforced", &x)) json_object_object_add(o, "enforced", json_object_get(x));
    if (json_object_object_get_ex(res, "epoch", &x)) json_object_object_add(o, "upf_epoch", json_object_get(x));
  }
  event(o);
}

/* bring the UPF in line with one UE's level (called without st_lock) */
static void core_reconcile_ue(int slot, int64_t now) {
  pthread_mutex_lock(&st_lock);
  ue_t *u = &ues[slot];
  if (!u->used || now < u->core_next_try_us) {
    pthread_mutex_unlock(&st_lock);
    return;
  }
  double ul, dl;
  const char *want = core_want(u, &ul, &dl);
  const char *have = u->core_applied[0] ? u->core_applied : "unknown";
  /* where the UPF policy should end: margin after the level, or the UPF's
     TTL cap for a level without expiry (renewed at half) */
  int64_t target = strcmp(want, "none") == 0 ? 0
                 : u->expires_us ? u->expires_us + (int64_t)cfg.upf_ttl_margin_s * 1000000 : 0;
  bool need = strcmp(want, have) != 0 || (!strcmp(want, "ratelimit") && u->core_rate_kbps != ul);
  if (!need && strcmp(want, "none") != 0) {
    if (target) need = llabs(target - u->core_expires_us) > 5000000LL;
    else need = u->core_expires_us - now < (int64_t)cfg.upf_max_ttl_s * 500000LL;
  }
  if (!need) {
    pthread_mutex_unlock(&st_lock);
    return;
  }
  char supi[96], path[160], action[12];
  snprintf(supi, sizeof(supi), "%s", u->supi);
  snprintf(action, sizeof(action), "%s", want);
  snprintf(path, sizeof(path), "/v1/ues/%s", supi);
  int ttl = 0;
  if (strcmp(want, "none") != 0) {
    ttl = target ? (int)((target - now) / 1000000 + 1) : cfg.upf_max_ttl_s;
    if (ttl > cfg.upf_max_ttl_s) ttl = cfg.upf_max_ttl_s;
    if (ttl < 1) ttl = 1;
  }
  const int level = u->level;
  pthread_mutex_unlock(&st_lock);

  /* the decision is stored before it is sent */
  char detail[96];
  snprintf(detail, sizeof(detail), "ttl_s=%d rate_ul_kbps=%.0f rate_dl_kbps=%.0f level=%d", ttl, ul, dl, level);
  sqlite3_int64 row = action_row(supi, now, "core", strcmp(action, "none") ? action : "delete", detail);
  json_object *res = NULL;
  int status;
  if (strcmp(action, "none") == 0) {
    status = upf("DELETE", path, NULL, &res);
    if (status == 404) status = 200; /* nothing there: in line */
  } else {
    json_object *b = json_object_new_object();
    json_object_object_add(b, "action", json_object_new_string(action));
    json_object_object_add(b, "ttl_s", json_object_new_int(ttl));
    json_object_object_add(b, "level", json_object_new_int(level));
    if (!strcmp(action, "ratelimit")) {
      json_object_object_add(b, "rate_ul_kbps", json_object_new_int64((int64_t)ul));
      json_object_object_add(b, "rate_dl_kbps", json_object_new_int64((int64_t)dl));
    }
    status = upf("PUT", path, b, &res);
    json_object_put(b);
  }
  action_done(row, status);

  pthread_mutex_lock(&st_lock);
  if (u->used && strcmp(u->supi, supi) == 0) {
    if (status == 200) {
      snprintf(u->core_applied, sizeof(u->core_applied), "%s", action);
      u->core_rate_kbps = ul;
      u->core_expires_us = ttl ? now + (int64_t)ttl * 1000000 : 0;
      if (strcmp(action, "none") != 0 && (strcmp(have, action) != 0 || !u->core_since_us)) {
        u->core_since_us = now;
        u->core_verified = !strcmp(action, "monitor"); /* nothing to check */
        core_rows[slot] = row;
      }
      if (!strcmp(action, "none")) u->core_since_us = 0;
    } else {
      u->core_next_try_us = now + RETRY_US;
    }
    core_event(u, now, action, ul, dl, ttl, status, res);
  }
  pthread_mutex_unlock(&st_lock);
  if (res) json_object_put(res);
}

/* periodic check against the UPF: a restarted UPF (boot_id) or a policy that
   differs from ours is pushed again; a policy for a SUPI at level 0 is
   removed (the xApp is the only brain) */
void actuators_core_sync(int64_t now) {
  pthread_mutex_lock(&st_lock);
  const bool due = cfg.core && cfg.enabled && now - core_synced_us >= (int64_t)cfg.upf_sync_s * 1000000;
  pthread_mutex_unlock(&st_lock);
  if (!due) return;
  json_object *info = NULL, *list = NULL, *x = NULL, *arr = NULL;
  int si = upf("GET", "/v1/info", NULL, &info);
  int sl = si == 200 ? upf("GET", "/v1/ues", NULL, &list) : 0;
  pthread_mutex_lock(&st_lock);
  core_synced_us = now;
  if (si == 200 && info && json_object_object_get_ex(info, "boot_id", &x)) {
    const char *b = json_object_get_string(x);
    if (boot_id[0] && strcmp(boot_id, b) != 0) {
      printf("[defense] UPF restarted (boot_id %s -> %s): policies pushed again\n", boot_id, b);
      for (int i = 0; i < MAX_UES; i++) ues[i].core_applied[0] = '\0';
    }
    snprintf(boot_id, sizeof(boot_id), "%s", b);
  }
  char stale[MAX_UES][96];
  int n_stale = 0;
  if (sl == 200 && list && json_object_object_get_ex(list, "policies", &arr) && json_object_is_type(arr, json_type_array)) {
    for (int i = 0; i < MAX_UES; i++) {
      ue_t *u = &ues[i];
      if (!u->used || !u->core_applied[0] || !strcmp(u->core_applied, "none")) continue;
      bool found = false;
      for (size_t j = 0; j < json_object_array_length(arr); j++) {
        json_object *p = json_object_array_get_idx(arr, j), *s = NULL, *a = NULL, *act = NULL;
        if (json_object_object_get_ex(p, "supi", &s) && !strcmp(json_object_get_string(s), u->supi) &&
            json_object_object_get_ex(p, "action", &a) && !strcmp(json_object_get_string(a), u->core_applied) &&
            json_object_object_get_ex(p, "active", &act) && json_object_get_boolean(act))
          found = true;
      }
      if (!found) u->core_applied[0] = '\0'; /* unknown: push again */
    }
    for (size_t j = 0; j < json_object_array_length(arr) && n_stale < MAX_UES; j++) {
      json_object *p = json_object_array_get_idx(arr, j), *s = NULL;
      if (!json_object_object_get_ex(p, "supi", &s)) continue;
      ue_t *u = ue_for(json_object_get_string(s), false);
      double ul, dl;
      if (!u || !strcmp(core_want(u, &ul, &dl), "none")) snprintf(stale[n_stale++], 96, "%s", json_object_get_string(s));
    }
  }
  pthread_mutex_unlock(&st_lock);
  for (int i = 0; i < n_stale; i++) {
    char path[160];
    snprintf(path, sizeof(path), "/v1/ues/%s", stale[i]);
    sqlite3_int64 row = action_row(stale[i], now, "core", "delete", "stale policy at the UPF");
    action_done(row, upf("DELETE", path, NULL, NULL));
    printf("[defense] removed stale UPF policy of %s\n", stale[i]);
  }
  if (info) json_object_put(info);
  if (list) json_object_put(list);
}

json_object *actuators_core_state(void) {
  json_object *o = json_object_new_object();
  json_object_object_add(o, "enabled", json_object_new_boolean(cfg.core));
  json_object_object_add(o, "upf_api", json_object_new_string(cfg.upf_api));
  json_object_object_add(o, "upf_boot_id", json_object_new_string(boot_id));
  json_object_object_add(o, "requests", json_object_new_uint64(core_requests));
  json_object_object_add(o, "failures", json_object_new_uint64(core_failures));
  json_object_object_add(o, "last_error", json_object_new_string(core_error));
  return o;
}

/* ---------- verifier ---------- */

static void lower_ctrl_trust(const char *node) {
  if (!db || !node[0]) return;
  sqlite3_stmt *q = NULL;
  if (sqlite3_prepare_v2(db, "INSERT INTO e2_trust(e2_node,ctrl_trust) VALUES(?,0.5) ON CONFLICT(e2_node) DO UPDATE SET "
                             "ctrl_trust=ctrl_trust*0.5", -1, &q, NULL) == SQLITE_OK) {
    sqlite3_bind_text(q, 1, node, -1, SQLITE_TRANSIENT);
    sqlite3_step(q);
  }
  sqlite3_finalize(q);
}

static void verdict(ue_t *u, const features_t *f, int64_t now, const char *layer, const char *what, bool ok) {
  json_object *o = event_base(ok ? "verified" : "unverified", u, now);
  json_object_object_add(o, "layer", json_object_new_string(layer));
  json_object_object_add(o, "check", json_object_new_string(what));
  json_object_object_add(o, "collect_ms", json_object_new_int64(f->collect_us / 1000));
  json_object_object_add(o, "prb_ul_pct", json_object_new_double(f->prb_ul));
  json_object_object_add(o, "prb_dl_pct", json_object_new_double(f->prb_dl));
  if (f->has_urr) {
    json_object_object_add(o, "urr_ul_kbps", json_object_new_double(f->urr_ul_kbps));
    json_object_object_add(o, "urr_dl_kbps", json_object_new_double(f->urr_dl_kbps));
    json_object_object_add(o, "urr_age_s", json_object_new_double(f->urr_age_s));
  }
  event(o);
  printf("[defense] %s %s %s: %s\n", u->supi, layer, what, ok ? "verified" : "NOT verified");
  fflush(stdout);
}

void actuators_verify(ue_t *u, const features_t *f, int64_t now) {
  const bool limited = u->applied_ratio > 0 && u->synced_amf == f->amf;
  /* RAN limit, by KPM: the UE's PRB share obeys it */
  if (limited && !u->verified && f->prb_ul <= u->applied_ratio + 3 && f->prb_dl <= u->applied_ratio + 3) {
    u->verified = true;
    action_verified(u->last_action);
    verdict(u, f, now, "ran", "prb_share", true);
  }
  if (!cfg.core) return;
  /* UPF action verdicts use the newest vector that has URR (it counts after
     the policy; the profile counts before it), measured >= 1 s after the action */
  const features_t *g = features_latest_urr(u);
  const int64_t urr_at = g ? g->collect_us : 0;
  const int64_t verify_us = (int64_t)cfg.verify_s * 1000000;
  if (g) f = g;
  /* RAN limit, by the UPF profile (the core view): the SUPI's rate falls below
     its class. A verdict needs a profile measured after the action; none yet
     (UE released) -> keep waiting */
  const features_t *p = features_latest_profile(u);
  if (limited && u->level <= 2 && !u->ran_core_checked && u->ran_applied_us && p && p->collect_us > u->ran_applied_us + 1000000) {
    if (features_core_ul_kbps(p) < p->limit_ul && features_core_dl_kbps(p) < p->limit_dl) {
      u->ran_core_checked = true;
      verdict(u, p, now, "ran", "core_below_class", true);
    } else if (now - u->ran_applied_us > verify_us) {
      /* the gNB did not do what it acknowledged (or KPM lies): trust it
         less and let the UPF limit the SUPI already at this level */
      u->ran_core_checked = true;
      u->core_assist = true;
      lower_ctrl_trust(u->node);
      verdict(u, p, now, "ran", "core_below_class", false);
    }
  }
  /* UPF action, by URR: block -> no traffic counted, ratelimit -> at most
     the rate (+25 %); monitor needs no check */
  const bool check_core = u->core_since_us && !u->core_verified &&
                          (strcmp(u->core_applied, "block") == 0 || strcmp(u->core_applied, "ratelimit") == 0);
  if (check_core) {
    const bool block = strcmp(u->core_applied, "block") == 0;
    const double cap = block ? 1.0 : u->core_rate_kbps * 1.25;
    const bool after = g && urr_at > u->core_since_us + 1000000;
    if (after && f->urr_ul_kbps <= cap) {
      u->core_verified = true;
      int slot = (int)(u - ues);
      action_verified(core_rows[slot]);
      verdict(u, f, now, "core", block ? "urr_zero" : "urr_at_rate", true);
    } else if (after && now - u->core_since_us > verify_us) {
      u->core_verified = true; /* reported once */
      verdict(u, f, now, "core", block ? "urr_zero" : "urr_at_rate", false);
    }
  }
}

/* RRC Release: once when the SUPI enters level 3, and at level 4 at every
   attach (rate-limited) */
static bool release_due(const ue_t *u, int64_t now) {
  if (!cfg.release_on_block) return false;
  if (!cfg.enabled || u->level < 3 || !u->amf || now - u->last_seen_us > UE_GONE_US) return false;
  if (u->release_pending) return true;
  return u->level == 4 && u->released_amf != u->amf && now - u->released_us >= (int64_t)cfg.release_every_s * 1000000;
}

/* Bring the gNB and the UPF in line with the levels: RAN limited while
   level >= 1, on the UE ID the SUPI currently has (a re-attach gets it
   again); release at levels 3-4; the UPF policy of the level */
void actuators_reconcile(int64_t now) {
  for (int i = 0; i < MAX_UES; i++) {
    pthread_mutex_lock(&st_lock);
    ue_t *u = &ues[i];
    if (!u->used) {
      pthread_mutex_unlock(&st_lock);
      continue;
    }
    /* core off: still remove what this xApp put at the UPF */
    const bool core_on = cfg.core || (u->core_applied[0] && strcmp(u->core_applied, "none") != 0);
    if (now < u->next_try_us) {
      pthread_mutex_unlock(&st_lock);
      if (core_on) core_reconcile_ue(i, now);
      continue;
    }
    bool present = u->amf && now - u->last_seen_us <= UE_GONE_US;
    /* levels 1-2: limit slice; levels >= 3: block slice (when configured) */
    const bool blk = u->level >= 3 && cfg.slice_mode && cfg.b_sd;
    int want = u->level >= 1 && cfg.enabled ? (blk ? cfg.block_prb_ratio : cfg.max_prb_ratio) : 0;
    const int want_sst = blk ? cfg.b_sst : cfg.q_sst;
    const int64_t want_sd = blk ? cfg.b_sd : cfg.q_sd;
    /* set the limit explicitly once per UE ID: one left by an earlier xApp
       instance is unknown to this one */
    bool needed = present && (u->synced_amf != u->amf || u->applied_ratio != want || (want && cfg.slice_mode && u->applied_sd != want_sd));
    bool release = !needed && release_due(u, now);
    char supi[96];
    snprintf(supi, sizeof(supi), "%s", u->supi);
    uint64_t amf = u->amf;
    const bool slice = cfg.slice_mode;
    pthread_mutex_unlock(&st_lock);

    if (release) {
      json_object *res = NULL;
      sqlite3_int64 row = action_row(supi, now, "ran", "release", "rrc_release");
      int code = ran_control_apply(supi, amf, true, "release", 0, "defense", &res);
      action_done(row, code);
      pthread_mutex_lock(&st_lock);
      if (u->used && strcmp(u->supi, supi) == 0) {
        if (code == 200) {
          u->released_amf = amf;
          u->released_us = now;
          u->release_pending = false;
        } else {
          u->next_try_us = now + RETRY_US;
        }
        json_object *o = event_base("action", u, now);
        json_object_object_add(o, "layer", json_object_new_string("ran"));
        json_object_object_add(o, "action", json_object_new_string("release"));
        json_object_object_add(o, "amf_ue_ngap_id", json_object_new_uint64(amf));
        json_object_object_add(o, "http", json_object_new_int(code));
        if (res) json_object_object_add(o, "result", json_object_get(res));
        event(o);
        printf("[defense] %s RRC release of UE %" PRIu64 " (level %d): HTTP %d\n", supi, amf, u->level, code);
        fflush(stdout);
      }
      pthread_mutex_unlock(&st_lock);
      json_object_put(res);
    }
    if (needed) {
      json_object *res = NULL;
      int code;
      if (!slice && want) {
        code = ran_control_apply(supi, amf, true, "prb_quota", want, "defense", &res);
      } else if (want) {
        /* (re)define the quarantine slice first: a restarted gNB has none */
        code = ran_control_slice(supi, amf, true, "prb_quota", want_sst, want_sd, want, "defense", &res);
        if (code == 200) {
          json_object_put(res);
          res = NULL;
          code = ran_control_slice(supi, amf, true, "slice_handover", want_sst, want_sd, -1, "defense", &res);
        }
      } else {
        /* back to the default slice, and no UE quota left by an earlier
           instance or the other mode */
        code = ran_control_slice(supi, amf, true, "slice_handover", cfg.d_sst, cfg.d_sd, -1, "defense", &res);
        if (code == 200) {
          json_object_put(res);
          res = NULL;
          code = ran_control_apply(supi, amf, true, "prb_quota", 100, "defense", &res);
        }
      }

      pthread_mutex_lock(&st_lock);
      if (u->used && strcmp(u->supi, supi) == 0) {
        if (code == 200) {
          u->applied_ratio = want;
          u->applied_sd = want && slice ? want_sd : 0;
          u->synced_amf = amf;
          u->verified = false;
          u->ran_applied_us = want ? now : 0;
          u->ran_core_checked = false;
          if (!want) u->core_assist = false;
        } else {
          u->next_try_us = now + RETRY_US;
        }
        sqlite3_int64 id = save_action(u, now, want ? want : 100, want ? want_sst : cfg.d_sst, want ? want_sd : cfg.d_sd, amf, code, res);
        if (want) u->last_action = id;
      }
      pthread_mutex_unlock(&st_lock);
      json_object_put(res);
    }
    if (core_on) core_reconcile_ue(i, now);
  }
}
