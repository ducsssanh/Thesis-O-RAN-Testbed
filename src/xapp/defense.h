#ifndef OAI_LAB_DEFENSE_H
#define OAI_LAB_DEFENSE_H
/* Cross-domain defense in the xApp: features from KPM (RAN) and the UPF
   telemetry (core) per SUPI, a classifier (embedded model or fair-use rule), a
   reputation DB keyed by SUPI (SQLite) and the escalation:
     level 1  suspicion                          -> quarantine RAN slice, UPF monitor
     level 2  repeat offense after level 1       -> slice, UPF ratelimit
     level 3  repeat after 2, KPM and URR agree  -> slice + RRC release, UPF block
     level 4  repeat after 3, KPM and URR agree  -> release at every attach, UPF block
   One layer alone stops at 2. A level expires to the one below; level 0
   removes the RAN limit and the UPF policy. A SUPI that re-attaches under a
   new UE ID gets its RAN limit again; the UPF applies its policy from the
   first packet of the new session.
   Configuration: JSON in DEFENSE_CONFIG (chart global.lab.defense.xapp);
   absent or "enabled": false disables detection; "core.enabled": false
   keeps the RAN-only behaviour. */
#include "../../../../src/xApp/e42_xapp_api.h"
#include <stdint.h>

int defense_start(const char *db_path, const char *event_log_path);
void defense_stop(void);
/* One per-UE KPM report (called from the FlexRIC callback thread; only
   queues the sample) */
void defense_on_kpm(ue_id_e2sm_t const *ue_id, kpm_ind_msg_format_1_t const *msg, int64_t collect_us, const char *e2_node);
/* GET /v1/defense/state; POST /v1/defense/enabled {"enabled":bool};
   POST /v1/defense/reset {"supi"} (admin: level 0, quota removed);
   POST /v1/defense/policy {"supi","class"}; POST /v1/defense/mode {"mode"};
   POST /v1/defense/timing {"expiryS":[4],"probationS","fusionS"} (experiments);
   POST /v1/defense/core {"enabled":bool} (RAN-only vs both layers) */
struct json_object;
int defense_http(const char *url, const char *body, struct json_object **out);
#endif
