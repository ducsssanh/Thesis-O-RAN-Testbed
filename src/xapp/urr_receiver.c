#define _GNU_SOURCE /* strptime, timegm */
/* Lab-internal URR delivery endpoint in the KPM xApp process. */
#include "urr_receiver.h"
#include <microhttpd.h>
#include <json-c/json.h>
#include <sqlite3.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <errno.h>
#include <limits.h>
#include <openssl/pem.h>
#include <openssl/x509.h>

#define MAX_BODY (1u << 20)
typedef struct { char *body; size_t used; } request_t;
static struct MHD_Daemon *urr_daemon;
static sqlite3 *db;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static char *cert, *key;
static char export_path[PATH_MAX];
static urr_record_t last_report;
static int has_last_report;
static unsigned long long duplicate_count, error_count;
/* closed-loop information types other than URR, common envelope
   delivered at /v1/<kind>/events */
static const char *core_kinds[]={"test","session","profile","event"};
#define CORE_KINDS (sizeof(core_kinds)/sizeof(*core_kinds))
static unsigned long long core_received[CORE_KINDS],core_duplicates[CORE_KINDS],core_errors[CORE_KINDS];
static char core_export_path[PATH_MAX];
/* AMF UE NGAP ID -> SUPI, one entry per SUPI (a re-attach gets a new ID) */
#define MAX_UE_IDENTITIES 64
static struct { uint64_t amf_ue_ngap_id; char supi[96]; } identities[MAX_UE_IDENTITIES];
static size_t identity_count;

/* latest report of each SUPI and when it arrived (features of the defense) */
/* plus the last URR_RING reports, to align URR with KPM by measurement time */
#define URR_RING 16
static struct { urr_record_t r; int64_t received_us; urr_record_t ring[URR_RING]; int64_t ring_rx[URR_RING]; int ring_head; }
  per_supi[MAX_UE_IDENTITIES];
static size_t per_supi_count;

static void remember_usage(const urr_record_t *r){
  if(!r->supi[0])return;
  size_t slot=per_supi_count;
  for(size_t i=0;i<per_supi_count;i++)if(strcmp(per_supi[i].r.supi,r->supi)==0){slot=i;break;}
  bool known=slot<per_supi_count;
  if(slot==per_supi_count){if(per_supi_count==MAX_UE_IDENTITIES)return;per_supi_count++;}
  struct timespec ts;clock_gettime(CLOCK_REALTIME,&ts);
  const urr_record_t *prev=&per_supi[slot].r;
  uint64_t interval=1;
  if(known && prev->seid==r->seid && r->duration_seconds>prev->duration_seconds && r->duration_seconds-prev->duration_seconds<=60)
    interval=r->duration_seconds-prev->duration_seconds;
  per_supi[slot].r=*r;
  per_supi[slot].r.interval_seconds=interval;per_supi[slot].received_us=(int64_t)ts.tv_sec*1000000+ts.tv_nsec/1000;
  per_supi[slot].ring[per_supi[slot].ring_head]=per_supi[slot].r;
  per_supi[slot].ring_rx[per_supi[slot].ring_head]=per_supi[slot].received_us;
  per_supi[slot].ring_head=(per_supi[slot].ring_head+1)%URR_RING;
}

static void remember_identity_of(uint64_t amf_ue_ngap_id,const char *supi){
  if(!supi[0])return;
  size_t slot=identity_count;
  for(size_t i=0;i<identity_count;i++){
    if(strcmp(identities[i].supi,supi)==0)slot=i;
    else if(identities[i].amf_ue_ngap_id==amf_ue_ngap_id)identities[i].supi[0]='\0'; /* ID reused by AMF */
  }
  if(slot==identity_count){if(identity_count==MAX_UE_IDENTITIES)return;identity_count++;}
  identities[slot].amf_ue_ngap_id=amf_ue_ngap_id;
  snprintf(identities[slot].supi,sizeof(identities[slot].supi),"%s",supi);
}

static void remember_identity(const urr_record_t *r){
  if(r->has_ran_identity)remember_identity_of(r->amf_ue_ngap_id,r->supi);
}

/* current PDU session of each SUPI: from usage reports and
   oai-session records. PDU_SES_EST gives a provisional epoch (SEID unknown)
   until SESSION_BOUND or the first URR of the session gives the exact one;
   a late report of an older session does not move it back. */
static struct { char supi[96]; uint64_t seid; char epoch[33]; int64_t start; char source[8]; bool released; } sessions[MAX_UE_IDENTITIES];
static size_t session_count;
#define SESSION_TOLERANCE_S 3 /* producer epochTolerance */

static int64_t epoch_seconds(const char *e){
  struct tm t={0};
  if(!e || strlen(e)!=16 || !strptime(e,"%Y%m%dT%H%M%SZ",&t))return 0;
  return (int64_t)timegm(&t);
}

static void remember_session(const char *supi,uint64_t seid,const char *epoch,const char *source,bool released){
  int64_t start=epoch_seconds(epoch);
  if(!supi[0] || !start)return;
  size_t slot=session_count;
  for(size_t i=0;i<session_count;i++)if(strcmp(sessions[i].supi,supi)==0){slot=i;break;}
  if(slot==session_count){if(session_count==MAX_UE_IDENTITIES)return;session_count++;snprintf(sessions[slot].supi,sizeof(sessions[slot].supi),"%s",supi);}
  else if(start<sessions[slot].start-SESSION_TOLERANCE_S)return; /* older session */
  bool same=sessions[slot].start && llabs(start-sessions[slot].start)<=SESSION_TOLERANCE_S;
  if(released){if(same || !seid)sessions[slot].released=true;return;}
  if(same && !seid && sessions[slot].seid)return; /* EST after the session is already bound */
  sessions[slot].start=start;sessions[slot].released=false;
  if(seid || !same)sessions[slot].seid=seid;
  snprintf(sessions[slot].epoch,sizeof(sessions[slot].epoch),"%s",epoch);
  snprintf(sessions[slot].source,sizeof(sessions[slot].source),"%s",source);
}


static char *read_file(const char *path) {
  FILE *f=fopen(path,"rb"); if(!f)return NULL;
  if(fseek(f,0,SEEK_END)!=0){fclose(f);return NULL;}
  long n=ftell(f); if(n<0 || n>1024*1024){fclose(f);return NULL;}
  rewind(f); char *p=calloc((size_t)n+1,1);
  if(!p || fread(p,1,(size_t)n,f)!=(size_t)n){free(p);fclose(f);return NULL;}
  fclose(f);return p;
}

static int valid_tls_identity(const char *certificate,const char *private_key){
  BIO *cert_bio=BIO_new_mem_buf(certificate,-1),*key_bio=BIO_new_mem_buf(private_key,-1);
  if(!cert_bio || !key_bio){BIO_free(cert_bio);BIO_free(key_bio);return 0;}
  X509 *cert_obj=PEM_read_bio_X509(cert_bio,NULL,NULL,NULL);
  EVP_PKEY *key_obj=PEM_read_bio_PrivateKey(key_bio,NULL,NULL,NULL);
  int valid=cert_obj && key_obj && X509_cmp_current_time(X509_get0_notBefore(cert_obj))<0 &&
      X509_cmp_current_time(X509_get0_notAfter(cert_obj))>0 && X509_check_private_key(cert_obj,key_obj)==1;
  X509_free(cert_obj);EVP_PKEY_free(key_obj);BIO_free(cert_bio);BIO_free(key_bio);
  return valid;
}

static enum MHD_Result reply(struct MHD_Connection *c,unsigned code,const char *body) {
  struct MHD_Response *r=MHD_create_response_from_buffer(strlen(body),(void*)body,MHD_RESPMEM_MUST_COPY);
  if(!r)return MHD_NO;
  MHD_add_response_header(r,"Content-Type","application/json");
  enum MHD_Result rc=MHD_queue_response(c,code,r); MHD_destroy_response(r); return rc;
}

static int uint_field(json_object *o,const char *name,uint64_t *v) {
  json_object *x=NULL;
  if(!json_object_object_get_ex(o,name,&x) || !json_object_is_type(x,json_type_int))return 0;
  const char *s=json_object_get_string(x); if(!s || *s=='-' || !*s)return 0;
  errno=0; char *end=NULL; unsigned long long n=strtoull(s,&end,10);
  if(errno || *end)return 0; *v=(uint64_t)n;return 1;
}

static int string_field(json_object *o,const char *name) {
  json_object *x=NULL;return json_object_object_get_ex(o,name,&x) && json_object_is_type(x,json_type_string) && json_object_get_string_len(x)>0;
}

static void copy_field(json_object *o,const char *name,char *dst,size_t capacity){
  json_object *x=NULL;if(json_object_object_get_ex(o,name,&x) && json_object_is_type(x,json_type_string))snprintf(dst,capacity,"%s",json_object_get_string(x));
}

static int valid_report(json_object *o,urr_record_t *record) {
  uint64_t seid=0,seq=0,n;
  if(!o || !json_object_is_type(o,json_type_object) || !uint_field(o,"seid",&seid) || !uint_field(o,"ur_seqn",&seq) || !seid || !seq)return 0;
  const char *strings[]={"schema_version","run_id","observed_at","supi","dnn","enrichment_source"};
  for(size_t i=0;i<sizeof(strings)/sizeof(*strings);i++)if(!string_field(o,strings[i]))return 0;
  const char *nums[]={"ul_bytes","dl_bytes","total_bytes","ul_packets","dl_packets","total_packets","duration_seconds"};
  for(size_t i=0;i<sizeof(nums)/sizeof(*nums);i++)if(!uint_field(o,nums[i],&n))return 0;
  json_object *id=NULL,*triggers=NULL,*snssai=NULL;
  if(!json_object_object_get_ex(o,"urr_id",&id) || !(json_object_is_type(id,json_type_null) || uint_field(o,"urr_id",&n)))return 0;
  if(!json_object_object_get_ex(o,"triggers",&triggers) || !json_object_is_type(triggers,json_type_array))return 0;
  for(size_t i=0;i<json_object_array_length(triggers);i++)if(!json_object_is_type(json_object_array_get_idx(triggers,i),json_type_string))return 0;
  if(!json_object_object_get_ex(o,"snssai",&snssai) || !json_object_is_type(snssai,json_type_object))return 0;
  if(!uint_field(snssai,"sst",&n) || !string_field(snssai,"sd"))return 0;
  /* session_epoch (producer schema 1.1.0) is optional: [0-9TZ]{1,32} */
  json_object *epoch=NULL;
  if(json_object_object_get_ex(o,"session_epoch",&epoch)){
    if(!json_object_is_type(epoch,json_type_string))return 0;
    const char *e=json_object_get_string(epoch);size_t len=strlen(e);
    if(len==0 || len>32 || strspn(e,"0123456789TZ")!=len)return 0;
  }
  /* ran_identity (producer schema 1.2.0) and end_time_unix are optional */
  json_object *ran=NULL;
  uint64_t amf_id=0,end_time=0;
  int has_ran=0;
  if(json_object_object_get_ex(o,"ran_identity",&ran) && !json_object_is_type(ran,json_type_null)){
    if(!json_object_is_type(ran,json_type_object) || !uint_field(ran,"amf_ue_ngap_id",&amf_id))return 0;
    has_ran=1;
  }
  json_object *et=NULL;
  if(json_object_object_get_ex(o,"end_time_unix",&et) && !uint_field(o,"end_time_unix",&end_time))return 0;
  memset(record,0,sizeof(*record));record->seid=seid;record->ur_seqn=seq;
  record->has_ran_identity=has_ran;record->amf_ue_ngap_id=amf_id;record->end_time_unix=end_time;
  if(epoch)copy_field(o,"session_epoch",record->session_epoch,sizeof(record->session_epoch));
  if(!json_object_is_type(id,json_type_null)){record->has_urr_id=true;uint_field(o,"urr_id",&record->urr_id);}
  uint_field(o,"ul_bytes",&record->ul_bytes);uint_field(o,"dl_bytes",&record->dl_bytes);uint_field(o,"total_bytes",&record->total_bytes);
  uint_field(o,"ul_packets",&record->ul_packets);uint_field(o,"dl_packets",&record->dl_packets);uint_field(o,"total_packets",&record->total_packets);
  uint_field(o,"duration_seconds",&record->duration_seconds);
  copy_field(o,"supi",record->supi,sizeof(record->supi));copy_field(o,"dnn",record->dnn,sizeof(record->dnn));
  copy_field(o,"observed_at",record->observed_at,sizeof(record->observed_at));
  copy_field(o,"schema_version",record->schema_version,sizeof(record->schema_version));
  copy_field(o,"run_id",record->run_id,sizeof(record->run_id));
  copy_field(o,"enrichment_source",record->enrichment_source,sizeof(record->enrichment_source));
  return 1;
}

static int export_jsonl(void) {
  char temp[PATH_MAX]; if(snprintf(temp,sizeof(temp),"%s.tmp",export_path)>=(int)sizeof(temp))return 0;
  FILE *f=fopen(temp,"wb");if(!f)return 0;
  sqlite3_stmt *q=NULL;
  if(sqlite3_prepare_v2(db,"SELECT event_id,job_id,report,received_at,run_id FROM urr WHERE run_id=? ORDER BY rowid",-1,&q,NULL)!=SQLITE_OK){fclose(f);return 0;}
  const char *run=getenv("RUN_ID");sqlite3_bind_text(q,1,run?run:"bootstrap",-1,SQLITE_TRANSIENT);
  int ok=1;
  while(sqlite3_step(q)==SQLITE_ROW){
    json_object *v=json_object_new_object();
    json_object_object_add(v,"event_id",json_object_new_string((const char*)sqlite3_column_text(q,0)));
    json_object_object_add(v,"job_id",json_object_new_string((const char*)sqlite3_column_text(q,1)));
    json_object *r=json_tokener_parse((const char*)sqlite3_column_text(q,2));
    json_object_object_add(v,"report",r);
    json_object_object_add(v,"received_at",json_object_new_string((const char*)sqlite3_column_text(q,3)));
    json_object_object_add(v,"xapp_run_id",json_object_new_string((const char*)sqlite3_column_text(q,4)));
    if(fputs(json_object_to_json_string_ext(v,JSON_C_TO_STRING_PLAIN),f)==EOF || fputc('\n',f)==EOF)ok=0;
    json_object_put(v); if(!ok)break;
  }
  sqlite3_finalize(q); if(fflush(f)!=0)ok=0; if(fclose(f)!=0)ok=0;
  if(ok && rename(temp,export_path)!=0)ok=0;
  if(!ok)remove(temp);return ok;
}

/* One stored report appended to the export (same line format as
   export_jsonl). Rewriting the whole export per report made ingest O(run
   size): about 1 s per report after a day of 1 s URR, slower than two UEs
   produce them, so the adapter queue grew without bound (found in R2). */
static int append_jsonl(const char *id,const char *job,const char *raw,const char *when,int64_t when_ms,const char *run){
  FILE *f=fopen(export_path,"ab");if(!f)return 0;
  json_object *v=json_object_new_object();
  json_object_object_add(v,"event_id",json_object_new_string(id));
  json_object_object_add(v,"job_id",json_object_new_string(job));
  json_object_object_add(v,"report",json_tokener_parse(raw));
  json_object_object_add(v,"received_at",json_object_new_string(when));
  json_object_object_add(v,"received_unix_ms",json_object_new_int64(when_ms)); /* ms arrival for the causal join */
  json_object_object_add(v,"xapp_run_id",json_object_new_string(run));
  int ok=fputs(json_object_to_json_string_ext(v,JSON_C_TO_STRING_PLAIN),f)!=EOF && fputc('\n',f)!=EOF;
  json_object_put(v);if(fclose(f)!=0)ok=0;return ok;
}

static enum MHD_Result ingest(struct MHD_Connection *c,request_t *req){
  json_tokener *tok=json_tokener_new();
  json_object *o=json_tokener_parse_ex(tok,req->body,(int)req->used);
  int parsed=json_tokener_get_error(tok)==json_tokener_success;
  json_tokener_free(tok);
  json_object *eid=NULL,*jid=NULL,*report=NULL;
  urr_record_t record;
  if(!parsed || !o || !json_object_object_get_ex(o,"event_id",&eid) || !json_object_is_type(eid,json_type_string) ||
     !json_object_object_get_ex(o,"job_id",&jid) || !json_object_is_type(jid,json_type_string) ||
     !json_object_object_get_ex(o,"report",&report) || !valid_report(report,&record)){
    pthread_mutex_lock(&lock);error_count++;pthread_mutex_unlock(&lock);
    if(o)json_object_put(o);return reply(c,400,"{\"error\":\"invalid URR envelope\"}");
  }
  const char *id=json_object_get_string(eid),*job=json_object_get_string(jid);
  if(!*id || !*job || strlen(id)>255 || strlen(job)>128 || strncmp(id,job,strlen(job))!=0 || id[strlen(job)]!=':'){
    pthread_mutex_lock(&lock);error_count++;pthread_mutex_unlock(&lock);
    json_object_put(o);return reply(c,400,"{\"error\":\"invalid event ID\"}");
  }
  const char *raw=json_object_to_json_string_ext(report,JSON_C_TO_STRING_PLAIN);
  char expected[128];
  if(record.session_epoch[0])snprintf(expected,sizeof(expected),"%llu:%s:%llu",(unsigned long long)record.seid,record.session_epoch,(unsigned long long)record.ur_seqn);
  else snprintf(expected,sizeof(expected),"%llu:%llu",(unsigned long long)record.seid,(unsigned long long)record.ur_seqn);
  if(strcmp(id+strlen(job)+1,expected)!=0){pthread_mutex_lock(&lock);error_count++;pthread_mutex_unlock(&lock);json_object_put(o);return reply(c,400,"{\"error\":\"event ID mismatch\"}");}
  pthread_mutex_lock(&lock);
  sqlite3_stmt *q=NULL;int status=500;
  if(sqlite3_prepare_v2(db,"SELECT report FROM urr WHERE event_id=?",-1,&q,NULL)==SQLITE_OK){
    sqlite3_bind_text(q,1,id,-1,SQLITE_TRANSIENT);
    if(sqlite3_step(q)==SQLITE_ROW){
      json_object *old=json_tokener_parse((const char*)sqlite3_column_text(q,0));
      status=old && json_object_equal(old,report)?200:409;
      if(status==200)duplicate_count++;else error_count++;
      if(old)json_object_put(old);
    }else status=201;
  }
  sqlite3_finalize(q);
  if(status==201){
    const char *run=getenv("RUN_ID");if(!run)run="bootstrap";
    char when[40];time_t now=time(NULL);struct tm t;gmtime_r(&now,&t);strftime(when,sizeof(when),"%Y-%m-%dT%H:%M:%SZ",&t);
    struct timespec rts;clock_gettime(CLOCK_REALTIME,&rts);int64_t when_ms=(int64_t)rts.tv_sec*1000+rts.tv_nsec/1000000;
    if(sqlite3_prepare_v2(db,"INSERT INTO urr(event_id,job_id,report,received_at,run_id) VALUES(?,?,?,?,?)",-1,&q,NULL)==SQLITE_OK){
      sqlite3_bind_text(q,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(q,2,job,-1,SQLITE_TRANSIENT);
      sqlite3_bind_text(q,3,raw,-1,SQLITE_TRANSIENT);sqlite3_bind_text(q,4,when,-1,SQLITE_TRANSIENT);sqlite3_bind_text(q,5,run,-1,SQLITE_TRANSIENT);
      if(sqlite3_step(q)!=SQLITE_DONE)status=500;
    }else status=500;
    sqlite3_finalize(q);
    if(status==201){last_report=record;has_last_report=1;remember_identity(&record);remember_usage(&record);
      if(record.session_epoch[0])remember_session(record.supi,record.seid,record.session_epoch,"urr",false);
      (void)append_jsonl(id,job,raw,when,when_ms,run);}
    else error_count++;
  }
  pthread_mutex_unlock(&lock);json_object_put(o);
  if(status==201)return reply(c,201,"{\"status\":\"stored\"}");
  if(status==200)return reply(c,200,"{\"status\":\"duplicate\"}");
  if(status==409)return reply(c,409,"{\"error\":\"conflicting payload\"}");
  return reply(c,500,"{\"error\":\"storage failure\"}");
}

/* oai-upf-profile records: the last PROFILE_RING seconds of each SUPI */
#define PROFILE_RING 16
static struct { char supi[96]; profile_record_t ring[PROFILE_RING]; int64_t rx[PROFILE_RING]; int head; } profiles[MAX_UE_IDENTITIES];
static size_t profile_count;

static void apply_profile(json_object *o,int64_t received_us){
  profile_record_t p;memset(&p,0,sizeof(p));
  json_object *b=NULL,*x=NULL;
  copy_field(o,"supi",p.supi,sizeof(p.supi));
  if(!p.supi[0] || !uint_field(o,"time_unix",&p.time_unix) || !json_object_object_get_ex(o,"body",&b) || !json_object_is_type(b,json_type_object))return;
  uint_field(o,"seid",&p.seid);uint_field(o,"window_ms",&p.window_ms);
  json_object *ran=NULL;uint64_t amf=0;
  if(json_object_object_get_ex(o,"ran_identity",&ran) && json_object_is_type(ran,json_type_object) && uint_field(ran,"amf_ue_ngap_id",&amf))
    remember_identity_of(amf,p.supi);
  copy_field(o,"observed_at",p.observed_at,sizeof(p.observed_at));
  struct { const char *k; uint64_t *v; } f[]={{"ul_pkts",&p.ul_pkts},{"ul_bytes",&p.ul_bytes},{"dl_pkts",&p.dl_pkts},{"dl_bytes",&p.dl_bytes},
    {"ul_tcp",&p.ul_tcp},{"ul_tcp_syn",&p.ul_tcp_syn},{"ul_udp",&p.ul_udp},{"ul_icmp",&p.ul_icmp},{"ul_frag",&p.ul_frag},{"ul_dns",&p.ul_dns},
    {"ul_gtp_in_gtp",&p.ul_gtp_in_gtp},{"dl_tcp",&p.dl_tcp},{"dl_tcp_syn",&p.dl_tcp_syn},{"dl_udp",&p.dl_udp},{"dl_icmp",&p.dl_icmp},{"dl_frag",&p.dl_frag}};
  for(size_t i=0;i<sizeof(f)/sizeof(*f);i++)uint_field(b,f[i].k,f[i].v);
  if(json_object_object_get_ex(b,"ul_dst_estimate",&x))p.ul_dst_estimate=json_object_get_double(x);
  size_t slot=profile_count;
  for(size_t i=0;i<profile_count;i++)if(strcmp(profiles[i].supi,p.supi)==0){slot=i;break;}
  if(slot==profile_count){if(profile_count==MAX_UE_IDENTITIES)return;profile_count++;snprintf(profiles[slot].supi,sizeof(profiles[slot].supi),"%s",p.supi);}
  profiles[slot].ring[profiles[slot].head]=p;profiles[slot].rx[profiles[slot].head]=received_us;
  profiles[slot].head=(profiles[slot].head+1)%PROFILE_RING;
}

/* oai-session record: RAN identity of the SUPI (re-attach labelled before
   the next usage report) and the session table */
static void apply_session(json_object *o){
  char supi[96]="",epoch[33]="",event[24]="";
  uint64_t seid=0,amf=0;
  copy_field(o,"supi",supi,sizeof(supi));copy_field(o,"session_epoch",epoch,sizeof(epoch));
  uint_field(o,"seid",&seid);
  json_object *ran=NULL,*body=NULL;
  if(json_object_object_get_ex(o,"ran_identity",&ran) && json_object_is_type(ran,json_type_object) && uint_field(ran,"amf_ue_ngap_id",&amf))
    remember_identity_of(amf,supi);
  if(json_object_object_get_ex(o,"body",&body))copy_field(body,"event",event,sizeof(event));
  if(strcmp(event,"PDU_SES_EST")==0)remember_session(supi,0,epoch,"est",false);
  else if(strcmp(event,"SESSION_BOUND")==0)remember_session(supi,seid,epoch,"bound",false);
  else if(strcmp(event,"PDU_SES_REL")==0)remember_session(supi,seid,epoch,"rel",true);
}

/* One envelope record: type, source, source_epoch, seq, supi, time_unix and
   a body; its event ID must be <job>:<source>:<source_epoch>:<seq>. Stored in
   core_events (deduplicated like URR) and appended to core-received.jsonl
   with the arrival time in ms, for the latency of the path. */
static int valid_envelope(json_object *o,char *key,size_t capacity){
  uint64_t seq=0,t=0;json_object *body=NULL;
  if(!o || !json_object_is_type(o,json_type_object) || !uint_field(o,"seq",&seq) || !seq || !uint_field(o,"time_unix",&t) || !t)return 0;
  const char *strings[]={"type","source","source_epoch","supi"};
  for(size_t i=0;i<sizeof(strings)/sizeof(*strings);i++)if(!string_field(o,strings[i]))return 0;
  if(!json_object_object_get_ex(o,"body",&body))return 0;
  json_object *src=NULL,*ep=NULL;json_object_object_get_ex(o,"source",&src);json_object_object_get_ex(o,"source_epoch",&ep);
  return snprintf(key,capacity,"%s:%s:%llu",json_object_get_string(src),json_object_get_string(ep),(unsigned long long)seq)<(int)capacity;
}

static enum MHD_Result ingest_core(struct MHD_Connection *c,request_t *req,size_t kind){
  json_tokener *tok=json_tokener_new();
  json_object *o=json_tokener_parse_ex(tok,req->body,(int)req->used);
  int parsed=json_tokener_get_error(tok)==json_tokener_success;
  json_tokener_free(tok);
  json_object *eid=NULL,*jid=NULL,*report=NULL;char key[256];
  if(!parsed || !o || !json_object_object_get_ex(o,"event_id",&eid) || !json_object_is_type(eid,json_type_string) ||
     !json_object_object_get_ex(o,"job_id",&jid) || !json_object_is_type(jid,json_type_string) ||
     !json_object_object_get_ex(o,"report",&report) || !valid_envelope(report,key,sizeof(key))){
    pthread_mutex_lock(&lock);core_errors[kind]++;pthread_mutex_unlock(&lock);
    if(o)json_object_put(o);return reply(c,400,"{\"error\":\"invalid envelope\"}");
  }
  const char *id=json_object_get_string(eid),*job=json_object_get_string(jid);
  size_t jl=strlen(job);
  if(!jl || jl>128 || strlen(id)>255 || strncmp(id,job,jl)!=0 || id[jl]!=':' || strcmp(id+jl+1,key)!=0){
    pthread_mutex_lock(&lock);core_errors[kind]++;pthread_mutex_unlock(&lock);
    json_object_put(o);return reply(c,400,"{\"error\":\"event ID mismatch\"}");
  }
  const char *raw=json_object_to_json_string_ext(report,JSON_C_TO_STRING_PLAIN);
  pthread_mutex_lock(&lock);
  sqlite3_stmt *q=NULL;int status=500;
  if(sqlite3_prepare_v2(db,"SELECT report FROM core_events WHERE event_id=?",-1,&q,NULL)==SQLITE_OK){
    sqlite3_bind_text(q,1,id,-1,SQLITE_TRANSIENT);
    if(sqlite3_step(q)==SQLITE_ROW){
      json_object *old=json_tokener_parse((const char*)sqlite3_column_text(q,0));
      status=old && json_object_equal(old,report)?200:409;
      if(old)json_object_put(old);
    }else status=201;
  }
  sqlite3_finalize(q);
  if(status==201){
    const char *run=getenv("RUN_ID");if(!run)run="bootstrap";
    struct timespec ts;clock_gettime(CLOCK_REALTIME,&ts);struct tm t;gmtime_r(&ts.tv_sec,&t);
    char when[48],sec[32];strftime(sec,sizeof(sec),"%Y-%m-%dT%H:%M:%S",&t);
    snprintf(when,sizeof(when),"%s.%03ldZ",sec,ts.tv_nsec/1000000);
    if(sqlite3_prepare_v2(db,"INSERT INTO core_events(event_id,kind,job_id,report,received_at,run_id) VALUES(?,?,?,?,?,?)",-1,&q,NULL)==SQLITE_OK){
      sqlite3_bind_text(q,1,id,-1,SQLITE_TRANSIENT);sqlite3_bind_text(q,2,core_kinds[kind],-1,SQLITE_STATIC);
      sqlite3_bind_text(q,3,job,-1,SQLITE_TRANSIENT);sqlite3_bind_text(q,4,raw,-1,SQLITE_TRANSIENT);
      sqlite3_bind_text(q,5,when,-1,SQLITE_TRANSIENT);sqlite3_bind_text(q,6,run,-1,SQLITE_TRANSIENT);
      if(sqlite3_step(q)!=SQLITE_DONE)status=500;
    }else status=500;
    sqlite3_finalize(q);
    if(status==201){
      FILE *f=fopen(core_export_path,"ab");
      if(f){
        json_object *v=json_object_new_object();
        json_object_object_add(v,"event_id",json_object_new_string(id));
        json_object_object_add(v,"kind",json_object_new_string(core_kinds[kind]));
        json_object_object_add(v,"report",json_object_get(report));
        json_object_object_add(v,"received_at",json_object_new_string(when));
        json_object_object_add(v,"received_unix_ms",json_object_new_int64((int64_t)ts.tv_sec*1000+ts.tv_nsec/1000000));
        json_object_object_add(v,"xapp_run_id",json_object_new_string(run));
        fputs(json_object_to_json_string_ext(v,JSON_C_TO_STRING_PLAIN),f);fputc('\n',f);
        json_object_put(v);fclose(f);
      }
      core_received[kind]++;
      if(strcmp(core_kinds[kind],"session")==0)apply_session(report);
      else if(strcmp(core_kinds[kind],"profile")==0)apply_profile(report,(int64_t)ts.tv_sec*1000000+ts.tv_nsec/1000);
    }
  }
  if(status==200)core_duplicates[kind]++;
  else if(status!=201)core_errors[kind]++;
  pthread_mutex_unlock(&lock);json_object_put(o);
  if(status==201)return reply(c,201,"{\"status\":\"stored\"}");
  if(status==200)return reply(c,200,"{\"status\":\"duplicate\"}");
  if(status==409)return reply(c,409,"{\"error\":\"conflicting payload\"}");
  return reply(c,500,"{\"error\":\"storage failure\"}");
}

/* index of the closed-loop kind of a /v1/<kind>/events URL, -1 if none */
static int core_kind_of(const char *url){
  for(size_t i=0;i<CORE_KINDS;i++){
    char path[64];snprintf(path,sizeof(path),"/v1/%s/events",core_kinds[i]);
    if(strcmp(url,path)==0)return (int)i;
  }
  return -1;
}

static enum MHD_Result handle(void *cls,struct MHD_Connection *c,const char *url,const char *method,const char *version,
                              const char *upload,size_t *size,void **context){
  (void)cls;(void)version;
  if(strcmp(method,"GET")==0){
    if(strcmp(url,"/healthz")==0 || strcmp(url,"/readyz")==0)return reply(c,200,"{\"status\":\"ok\"}");
    if(strcmp(url,"/v1/urr/status")==0){
      pthread_mutex_lock(&lock);sqlite3_stmt *q=NULL;int count=0;
      if(sqlite3_prepare_v2(db,"SELECT COUNT(*) FROM urr",-1,&q,NULL)==SQLITE_OK && sqlite3_step(q)==SQLITE_ROW)count=sqlite3_column_int(q,0);
      sqlite3_finalize(q);
      char latest[256]="";
      if(sqlite3_prepare_v2(db,"SELECT event_id FROM urr ORDER BY rowid DESC LIMIT 1",-1,&q,NULL)==SQLITE_OK && sqlite3_step(q)==SQLITE_ROW){
        const char *p=(const char*)sqlite3_column_text(q,0);if(p)snprintf(latest,sizeof(latest),"%s",p);
      }
      sqlite3_finalize(q);
      unsigned long long duplicates=duplicate_count,errors=error_count;
      pthread_mutex_unlock(&lock);
      json_object *status=json_object_new_object();
      json_object_object_add(status,"received",json_object_new_int(count));
      json_object_object_add(status,"duplicates",json_object_new_uint64(duplicates));
      json_object_object_add(status,"errors",json_object_new_uint64(errors));
      json_object_object_add(status,"last_event_id",json_object_new_string(latest));
      enum MHD_Result rc=reply(c,200,json_object_to_json_string(status));json_object_put(status);return rc;
    }
    if(strcmp(url,"/v1/core/status")==0){
      json_object *status=json_object_new_object();
      pthread_mutex_lock(&lock);
      for(size_t i=0;i<CORE_KINDS;i++){
        json_object *k=json_object_new_object();
        json_object_object_add(k,"received",json_object_new_uint64(core_received[i]));
        json_object_object_add(k,"duplicates",json_object_new_uint64(core_duplicates[i]));
        json_object_object_add(k,"errors",json_object_new_uint64(core_errors[i]));
        json_object_object_add(status,core_kinds[i],k);
      }
      pthread_mutex_unlock(&lock);
      enum MHD_Result rc=reply(c,200,json_object_to_json_string(status));json_object_put(status);return rc;
    }
    return reply(c,404,"{}");
  }
  int kind=core_kind_of(url);
  if((strcmp(url,"/v1/urr/events")!=0 && kind<0) || strcmp(method,"POST")!=0)return reply(c,404,"{}");
  if(*context==NULL){request_t *r=calloc(1,sizeof(*r));if(!r)return MHD_NO;r->body=calloc(MAX_BODY+1,1);if(!r->body){free(r);return MHD_NO;}*context=r;return MHD_YES;}
  request_t *r=*context;
  if(*size){if(r->used+*size>MAX_BODY)return reply(c,413,"{\"error\":\"body too large\"}");memcpy(r->body+r->used,upload,*size);r->used+=*size;*size=0;return MHD_YES;}
  return kind>=0?ingest_core(c,r,(size_t)kind):ingest(c,r);
}

static void completed(void *cls,struct MHD_Connection *c,void **context,enum MHD_RequestTerminationCode reason){
  (void)cls;(void)c;(void)reason;request_t *r=*context;if(r){free(r->body);free(r);}*context=NULL;
}

int urr_receiver_start(void){
  const char *path=getenv("URR_DB_PATH");if(!path)path="/artifacts/urr-state/urr.db";
  const char *out=getenv("URR_EXPORT_PATH");if(!out)out="/artifacts/urr-received.jsonl";
  if(snprintf(export_path,sizeof(export_path),"%s",out)>=(int)sizeof(export_path))return -1;
  if(sqlite3_open(path,&db)!=SQLITE_OK)return -1;
  if(sqlite3_exec(db,"PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS urr(event_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,report TEXT NOT NULL,received_at TEXT NOT NULL,run_id TEXT NOT NULL);"
                  "CREATE TABLE IF NOT EXISTS core_events(event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,job_id TEXT NOT NULL,report TEXT NOT NULL,received_at TEXT NOT NULL,run_id TEXT NOT NULL);",NULL,NULL,NULL)!=SQLITE_OK)return -1;
  /* closed-loop records next to the URR export unless CORE_EXPORT_PATH */
  const char *core_out=getenv("CORE_EXPORT_PATH");
  if(core_out){if(snprintf(core_export_path,sizeof(core_export_path),"%s",core_out)>=(int)sizeof(core_export_path))return -1;}
  else{
    const char *slash=strrchr(export_path,'/');int dir=slash?(int)(slash-export_path)+1:0;
    if(snprintf(core_export_path,sizeof(core_export_path),"%.*score-received.jsonl",dir,export_path)>=(int)sizeof(core_export_path))return -1;
  }
  sqlite3_stmt *last=NULL;
  if(sqlite3_prepare_v2(db,"SELECT report FROM urr ORDER BY rowid DESC LIMIT 1",-1,&last,NULL)==SQLITE_OK && sqlite3_step(last)==SQLITE_ROW){
    json_object *r=json_tokener_parse((const char*)sqlite3_column_text(last,0));
    if(r){has_last_report=valid_report(r,&last_report);json_object_put(r);}
  }
  sqlite3_finalize(last);
  (void)export_jsonl();
  cert=read_file(getenv("URR_TLS_CERT")?getenv("URR_TLS_CERT"):"/tls/tls.crt");
  key=read_file(getenv("URR_TLS_KEY")?getenv("URR_TLS_KEY"):"/tls/tls.key");
  if(!cert || !key || !valid_tls_identity(cert,key))return -1;
  urr_daemon=MHD_start_daemon(MHD_USE_INTERNAL_POLLING_THREAD|MHD_USE_TLS,8443,NULL,NULL,&handle,NULL,
                          MHD_OPTION_HTTPS_MEM_KEY,key,MHD_OPTION_HTTPS_MEM_CERT,cert,
                          MHD_OPTION_NOTIFY_COMPLETED,&completed,NULL,MHD_OPTION_END);
  return urr_daemon?0:-1;
}

void urr_receiver_stop(void){
  if(urr_daemon){MHD_stop_daemon(urr_daemon);urr_daemon=NULL;}
  if(db){sqlite3_close(db);db=NULL;}
  free(cert);free(key);cert=key=NULL;
}

int urr_receiver_supi_for_ue(uint64_t amf_ue_ngap_id,char *supi,size_t capacity){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<identity_count && !found;i++)
    if(identities[i].supi[0] && identities[i].amf_ue_ngap_id==amf_ue_ngap_id){
      snprintf(supi,capacity,"%s",identities[i].supi);found=1;
    }
  pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_ue_for_supi(const char *supi,uint64_t *amf_ue_ngap_id){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<identity_count && !found;i++)
    if(identities[i].supi[0] && strcmp(identities[i].supi,supi)==0){*amf_ue_ngap_id=identities[i].amf_ue_ngap_id;found=1;}
  pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_latest(urr_record_t *out){
  if(!out)return 0;
  pthread_mutex_lock(&lock);int found=has_last_report;if(found)*out=last_report;pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_supi_at(const char *supi,uint64_t end_unix,urr_record_t *out,int64_t *received_us){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<per_supi_count && !found;i++){
    if(strcmp(per_supi[i].r.supi,supi)!=0)continue;
    for(int k=0;k<URR_RING && !found;k++)
      if(per_supi[i].ring[k].end_time_unix==end_unix && per_supi[i].ring[k].supi[0]){
        *out=per_supi[i].ring[k];if(received_us)*received_us=per_supi[i].ring_rx[k];found=1;}
    break;
  }
  pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_profile_at(const char *supi,uint64_t t,profile_record_t *out,int64_t *received_us){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<profile_count && !found;i++){
    if(strcmp(profiles[i].supi,supi)!=0)continue;
    for(int k=0;k<PROFILE_RING && !found;k++)
      if(profiles[i].ring[k].time_unix==t && profiles[i].ring[k].supi[0]){*out=profiles[i].ring[k];if(received_us)*received_us=profiles[i].rx[k];found=1;}
    break;
  }
  pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_profile_active(const char *supi){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<profile_count && !found;i++)found=strcmp(profiles[i].supi,supi)==0;
  pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_session_of(const char *supi,uint64_t *seid,char *epoch,size_t capacity,char *source,size_t source_capacity){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<session_count && !found;i++)
    if(strcmp(sessions[i].supi,supi)==0 && !sessions[i].released){
      *seid=sessions[i].seid;snprintf(epoch,capacity,"%s",sessions[i].epoch);
      if(source)snprintf(source,source_capacity,"%s",sessions[i].source);found=1;}
  pthread_mutex_unlock(&lock);
  return found;
}

int urr_receiver_latest_for_supi(const char *supi,urr_record_t *out,int64_t *received_us){
  int found=0;
  pthread_mutex_lock(&lock);
  for(size_t i=0;i<per_supi_count && !found;i++)
    if(strcmp(per_supi[i].r.supi,supi)==0){*out=per_supi[i].r;if(received_us)*received_us=per_supi[i].received_us;found=1;}
  pthread_mutex_unlock(&lock);
  return found;
}
