#ifndef OAI_LAB_URR_RECEIVER_H
#define OAI_LAB_URR_RECEIVER_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct {
  uint64_t seid,ur_seqn,urr_id;
  bool has_urr_id;
  uint64_t ul_bytes,dl_bytes,total_bytes,ul_packets,dl_packets,total_packets,duration_seconds;
  char session_epoch[33],supi[96],dnn[96],observed_at[64],schema_version[24],run_id[96],enrichment_source[48];
  /* producer schema 1.2.0: RAN identity from the AMF UE table and
     PFCP End Time of the measurement (Unix s, 1 s resolution) */
  bool has_ran_identity;
  uint64_t amf_ue_ngap_id,end_time_unix;
  /* measurement period of this report (s), set by the receiver: OAI UPF's
     Duration Measurement counts from the session start while the volumes
     count since the previous report, so the period is the difference of two
     consecutive durations of the session (1 = PERIO when unknown) */
  uint64_t interval_seconds;
} urr_record_t;
int urr_receiver_start(void);
void urr_receiver_stop(void);
int urr_receiver_latest(urr_record_t *out);
/* SUPI of the UE whose E2SM-KPM UE ID (AMF UE NGAP ID) is given, learnt from
   the RAN identity of its URR reports; 1 if known */
int urr_receiver_supi_for_ue(uint64_t amf_ue_ngap_id,char *supi,size_t capacity);
/* reverse of the above: current AMF UE NGAP ID of a SUPI; 1 if known */
int urr_receiver_ue_for_supi(const char *supi,uint64_t *amf_ue_ngap_id);
/* latest report of a SUPI (usage since its previous report) and its arrival
   time (Unix us); 1 if any */
int urr_receiver_latest_for_supi(const char *supi,urr_record_t *out,int64_t *received_us);
/* the SUPI's report whose PFCP End Time is end_unix (one of the last 16); 1 if any */
int urr_receiver_supi_at(const char *supi,uint64_t end_unix,urr_record_t *out,int64_t *received_us);
/* UPF packet mix of one second (information type oai-upf-profile): counter
   differences over the window ending at time_unix */
typedef struct {
  char supi[96];
  uint64_t seid,time_unix,window_ms;
  uint64_t ul_pkts,ul_bytes,dl_pkts,dl_bytes;
  uint64_t ul_tcp,ul_tcp_syn,ul_udp,ul_icmp,ul_frag,ul_dns,ul_gtp_in_gtp;
  uint64_t dl_tcp,dl_tcp_syn,dl_udp,dl_icmp,dl_frag;
  double ul_dst_estimate;
  char observed_at[64];       /* the record's observed_at */
} profile_record_t;
/* the SUPI's profile whose window ends at t (one of the last 16); 1 if any */
int urr_receiver_profile_at(const char *supi,uint64_t t,profile_record_t *out,int64_t *received_us);
/* 1 once any profile of the SUPI arrived (the vector then waits for one) */
int urr_receiver_profile_active(const char *supi);
/* current (not released) PDU session of a SUPI: SEID (0 while only
   PDU_SES_EST is known), session epoch and where it came from (urr, est,
   bound); 1 if known */
int urr_receiver_session_of(const char *supi,uint64_t *seid,char *epoch,size_t capacity,char *source,size_t source_capacity);
#endif
