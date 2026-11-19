#ifndef OAI_LAB_RAN_CONTROL_H
#define OAI_LAB_RAN_CONTROL_H
/* RAN actions of the xApp: E2SM-RC CONTROL towards the gNB for one
   UE, named by SUPI (resolved through the R1 identity table) or by AMF UE
   NGAP ID. Requests arrive on a loopback-only HTTP endpoint:
     POST /v1/ran/control {"supi"|"amf_ue_ngap_id", "action":"prb_quota",
                           "max_prb_ratio":0..100}   (100 removes the quota)
     POST /v1/ran/control {"supi"|"amf_ue_ngap_id", "action":"release"}
   With "sst" and "sd" (number, or hex string), prb_quota sets the PRB budget
   of that RAN slice (its members share it) and
     POST /v1/ran/control {"supi"|..., "action":"slice_handover", "sst", "sd"}
   moves the UE into that RAN slice (an S-NSSAI without a slice: the default
   one) keeping its PDU session.
   Every request is appended to a JSONL log. The same server answers the
   defense endpoints (defense.h). */
#include "../../../../src/xApp/e42_xapp_api.h"

/* Remember the E2SM UE ID of a UE seen in a KPM report (the RC header needs
   the full ID: AMF UE NGAP ID + GUAMI) */
void ran_control_note_ue(ue_id_e2sm_t const *ue_id);
int ran_control_start(const char *log_path);
/* Send one action (as the HTTP endpoint does); origin is logged ("http",
   "defense"). Returns an HTTP-style status; *out receives the result or
   {"error":...} and must be released with json_object_put. Blocks until
   the RIC acknowledges: never call it from the FlexRIC callback thread. */
struct json_object;
int ran_control_apply(const char *supi,uint64_t amf_ue_ngap_id,bool has_amf,const char *action,int64_t max_prb_ratio,
                      const char *origin,struct json_object **out);
/* As ran_control_apply with a target S-NSSAI (sst < 0: env SST or 1;
   sd < 0: none) for prb_quota and slice_handover */
int ran_control_slice(const char *supi,uint64_t amf_ue_ngap_id,bool has_amf,const char *action,int sst,int64_t sd,
                      int64_t max_prb_ratio,const char *origin,struct json_object **out);
void ran_control_stop(void);
#endif
