/* RAN actions of the KPM xApp: E2SM-RC CONTROL for one UE. */
#include "ran_control.h"
#include "urr_receiver.h"
#include "defense.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_struct.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_list.h"
#include "../../../../src/util/time_now_us.h"
#include <microhttpd.h>
#include <json-c/json.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <inttypes.h>
#include <assert.h>

#define MAX_BODY 4096
#define MAX_UES 64
/* a UE ID is used only while the gNB keeps reporting it in KPM */
#define UE_FRESH_US (10 * 1000000LL)
#define RC_RAN_FUNCTION 3
/* E2SM-RC v01.03 8.4.3.6 Slice-level PRB quota, RAN Parameter IDs */
enum { RRM_POLICY_RATIO_LIST = 1, RRM_POLICY_RATIO_GROUP, RRM_POLICY, RRM_POLICY_MEMBER_LIST, RRM_POLICY_MEMBER,
       PLMN_IDENTITY, S_NSSAI, SST, SD, MIN_PRB_RATIO, MAX_PRB_RATIO, DEDICATED_PRB_RATIO };

typedef struct { char *body; size_t used; } request_t;
static struct MHD_Daemon *daemon_;
static pthread_mutex_t ue_lock = PTHREAD_MUTEX_INITIALIZER;
/* one CONTROL at a time: the FlexRIC xApp API waits synchronously */
static pthread_mutex_t ctrl_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { ue_id_e2sm_t id; int64_t seen_us; bool used; } ues[MAX_UES];
static FILE *log_file;

void ran_control_note_ue(ue_id_e2sm_t const *ue_id){
  if(!ue_id || ue_id->type!=GNB_UE_ID_E2SM)return;
  pthread_mutex_lock(&ue_lock);
  int slot=-1,oldest=0;
  for(int i=0;i<MAX_UES;i++){
    if(ues[i].used && ues[i].id.gnb.amf_ue_ngap_id==ue_id->gnb.amf_ue_ngap_id){slot=i;break;}
    if(!ues[i].used){if(slot<0)slot=i;}
    else if(ues[i].seen_us<ues[oldest].seen_us)oldest=i;
  }
  if(slot<0)slot=oldest;
  if(ues[slot].used)free_ue_id_e2sm(&ues[slot].id);
  ues[slot].id=cp_ue_id_e2sm(ue_id);ues[slot].used=true;ues[slot].seen_us=time_now_us();
  pthread_mutex_unlock(&ue_lock);
}

static bool lookup_ue(uint64_t amf_ue_ngap_id,ue_id_e2sm_t *out){
  bool found=false;int64_t now=time_now_us();
  pthread_mutex_lock(&ue_lock);
  for(int i=0;i<MAX_UES && !found;i++)
    if(ues[i].used && ues[i].id.gnb.amf_ue_ngap_id==amf_ue_ngap_id && now-ues[i].seen_us<=UE_FRESH_US){*out=cp_ue_id_e2sm(&ues[i].id);found=true;}
  pthread_mutex_unlock(&ue_lock);
  return found;
}

static ran_parameter_value_t *int_value(int64_t v){
  ran_parameter_value_t *p=calloc(1,sizeof(*p));assert(p!=NULL);p->type=INTEGER_RAN_PARAMETER_VALUE;p->int_ran=v;return p;
}
static ran_parameter_value_t *octets_value(const uint8_t *b,size_t n){
  ran_parameter_value_t *p=calloc(1,sizeof(*p));assert(p!=NULL);p->type=OCTET_STRING_RAN_PARAMETER_VALUE;
  p->octet_str_ran.len=n;p->octet_str_ran.buf=calloc(n,1);assert(p->octet_str_ran.buf!=NULL);memcpy(p->octet_str_ran.buf,b,n);return p;
}
static void element(seq_ran_param_t *p,uint32_t id,ran_parameter_value_t *v){
  p->ran_param_id=id;p->ran_param_val.type=ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;p->ran_param_val.flag_false=v;
}
static seq_ran_param_t *structure(seq_ran_param_t *p,uint32_t id,size_t n){
  p->ran_param_id=id;p->ran_param_val.type=STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  p->ran_param_val.strct=calloc(1,sizeof(ran_param_struct_t));assert(p->ran_param_val.strct!=NULL);
  p->ran_param_val.strct->sz_ran_param_struct=n;p->ran_param_val.strct->ran_param_struct=calloc(n,sizeof(seq_ran_param_t));
  assert(p->ran_param_val.strct->ran_param_struct!=NULL);return p->ran_param_val.strct->ran_param_struct;
}
/* LIST with one item (a STRUCTURE of n parameters); returns its parameters */
static seq_ran_param_t *list1(seq_ran_param_t *p,uint32_t id,size_t n){
  p->ran_param_id=id;p->ran_param_val.type=LIST_RAN_PARAMETER_VAL_TYPE;
  p->ran_param_val.lst=calloc(1,sizeof(ran_param_list_t));assert(p->ran_param_val.lst!=NULL);
  ran_param_list_t *l=p->ran_param_val.lst;l->sz_lst_ran_param=1;l->lst_ran_param=calloc(1,sizeof(lst_ran_param_t));assert(l->lst_ran_param!=NULL);
  l->lst_ran_param[0].ran_param_struct.sz_ran_param_struct=n;
  l->lst_ran_param[0].ran_param_struct.ran_param_struct=calloc(n,sizeof(seq_ran_param_t));
  assert(l->lst_ran_param[0].ran_param_struct.ran_param_struct!=NULL);return l->lst_ran_param[0].ran_param_struct.ran_param_struct;
}

/* PLMN Identity, TS 38.413 9.3.3.5 (BCD, filler 0xF for a 2-digit MNC) */
static void plmn_octets(e2sm_plmn_t const *p,uint8_t out[3]){
  int mcc1=p->mcc/100,mcc2=p->mcc/10%10,mcc3=p->mcc%10;
  int mnc1,mnc2,mnc3;
  if(p->mnc_digit_len==3){mnc1=p->mnc/100;mnc2=p->mnc/10%10;mnc3=p->mnc%10;}
  else{mnc1=p->mnc/10;mnc2=p->mnc%10;mnc3=0xF;}
  out[0]=(uint8_t)(mcc2<<4|mcc1);out[1]=(uint8_t)(mnc3<<4|mcc3);out[2]=(uint8_t)(mnc2<<4|mnc1);
}

static void sd_octets(uint32_t sd,uint8_t out[3]){out[0]=(uint8_t)(sd>>16);out[1]=(uint8_t)(sd>>8);out[2]=(uint8_t)sd;}

/* 8.4.3.6: one RRM Policy Ratio Group whose member is the UE's PLMN and
   slice; with an SD (sd >= 0) the gNB sets the PRB budget of that RAN slice,
   without one the quota of the UE in the header (R2) */
static void fill_prb_quota(e2sm_rc_ctrl_msg_frmt_1_t *msg,ue_id_e2sm_t const *ue,uint8_t sst,int64_t sd,int max_ratio){
  msg->sz_ran_param=1;msg->ran_param=calloc(1,sizeof(seq_ran_param_t));assert(msg->ran_param!=NULL);
  seq_ran_param_t *group=list1(&msg->ran_param[0],RRM_POLICY_RATIO_LIST,1);
  seq_ran_param_t *g=structure(&group[0],RRM_POLICY_RATIO_GROUP,4);
  seq_ran_param_t *policy=structure(&g[0],RRM_POLICY,1);
  seq_ran_param_t *member_item=list1(&policy[0],RRM_POLICY_MEMBER_LIST,1);
  seq_ran_param_t *member=structure(&member_item[0],RRM_POLICY_MEMBER,2);
  uint8_t plmn[3];plmn_octets(&ue->gnb.guami.plmn_id,plmn);
  element(&member[0],PLMN_IDENTITY,octets_value(plmn,3));
  seq_ran_param_t *snssai=structure(&member[1],S_NSSAI,sd>=0?2:1);
  element(&snssai[0],SST,octets_value(&sst,1));
  if(sd>=0){uint8_t d[3];sd_octets((uint32_t)sd,d);element(&snssai[1],SD,octets_value(d,3));}
  element(&g[1],MIN_PRB_RATIO,int_value(0));
  element(&g[2],MAX_PRB_RATIO,int_value(max_ratio));
  element(&g[3],DEDICATED_PRB_RATIO,int_value(0));
}

/* Slice Handover (Style 2 extension of the gNB): the target S-NSSAI */
static void fill_slice_handover(e2sm_rc_ctrl_msg_frmt_1_t *msg,uint8_t sst,uint32_t sd){
  msg->sz_ran_param=1;msg->ran_param=calloc(1,sizeof(seq_ran_param_t));assert(msg->ran_param!=NULL);
  seq_ran_param_t *snssai=structure(&msg->ran_param[0],S_NSSAI,2);
  uint8_t d[3];sd_octets(sd,d);
  element(&snssai[0],SST,octets_value(&sst,1));
  element(&snssai[1],SD,octets_value(d,3));
}

/* CONTROL style and action IDs the E2 node advertises under these names */
static bool find_ctrl(e2sm_rc_func_def_t const *rc,const char *style_name,const char *act_name,uint32_t *style,uint16_t *act){
  if(!rc->ctrl)return false;
  for(size_t i=0;i<rc->ctrl->sz_seq_ctrl_style;i++){
    seq_ctrl_style_t const *s=&rc->ctrl->seq_ctrl_style[i];
    if(s->name.len!=strlen(style_name) || memcmp(s->name.buf,style_name,s->name.len)!=0)continue;
    for(size_t j=0;j<s->sz_seq_ctrl_act;j++)
      if(s->seq_ctrl_act[j].name.len==strlen(act_name) && memcmp(s->seq_ctrl_act[j].name.buf,act_name,s->seq_ctrl_act[j].name.len)==0){
        *style=s->style_type;*act=s->seq_ctrl_act[j].id;return true;
      }
  }
  return false;
}

static enum MHD_Result reply(struct MHD_Connection *c,unsigned code,json_object *o){
  const char *body=json_object_to_json_string_ext(o,JSON_C_TO_STRING_PLAIN);
  struct MHD_Response *r=MHD_create_response_from_buffer(strlen(body),(void*)body,MHD_RESPMEM_MUST_COPY);
  json_object_put(o);if(!r)return MHD_NO;
  MHD_add_response_header(r,"Content-Type","application/json");
  enum MHD_Result rc=MHD_queue_response(c,code,r);MHD_destroy_response(r);return rc;
}
static enum MHD_Result fail(struct MHD_Connection *c,unsigned code,const char *why){
  json_object *o=json_object_new_object();json_object_object_add(o,"error",json_object_new_string(why));return reply(c,code,o);
}

static void log_line(json_object *o){
  if(!log_file)return;
  fputs(json_object_to_json_string_ext(o,JSON_C_TO_STRING_PLAIN),log_file);fputc('\n',log_file);fflush(log_file);
}

static json_object *error_object(const char *why){
  json_object *o=json_object_new_object();json_object_object_add(o,"error",json_object_new_string(why));return o;
}

int ran_control_apply(const char *supi_in,uint64_t amf,bool has_amf,const char *action,int64_t ratio,const char *origin,json_object **out){
  return ran_control_slice(supi_in,amf,has_amf,action,-1,-1,ratio,origin,out);
}

int ran_control_slice(const char *supi_in,uint64_t amf,bool has_amf,const char *action,int sst_in,int64_t sd,int64_t ratio,
                      const char *origin,json_object **out){
  bool quota=strcmp(action,"prb_quota")==0,release=strcmp(action,"release")==0,handover=strcmp(action,"slice_handover")==0;
  char supi[96]="";if(supi_in)snprintf(supi,sizeof(supi),"%s",supi_in);
  *out=NULL;
  if(!quota && !release && !handover){*out=error_object("action must be prb_quota, slice_handover or release");return 400;}
  if(quota && (ratio<0 || ratio>100)){*out=error_object("max_prb_ratio must be an integer 0..100");return 400;}
  if(sd>0xFFFFFF || sst_in>255 || (handover && (sst_in<0 || sd<0))){*out=error_object("slice_handover needs sst 0..255 and sd 0..0xFFFFFF");return 400;}
  const char *env_sst=getenv("SST");
  const uint8_t sst=(uint8_t)(sst_in>=0?sst_in:env_sst && *env_sst?(int)strtoul(env_sst,NULL,0):1);
  if(supi[0] && !has_amf){has_amf=urr_receiver_ue_for_supi(supi,&amf);if(!has_amf){*out=error_object("SUPI has no RAN identity yet");return 404;}}
  if(!has_amf){*out=error_object("supi or amf_ue_ngap_id required");return 400;}
  if(!supi[0])urr_receiver_supi_for_ue(amf,supi,sizeof(supi));
  ue_id_e2sm_t ue={0};
  if(!lookup_ue(amf,&ue)){*out=error_object("UE not in recent KPM reports");return 404;}

  const char *style_name=release?"Radio Access Control":"Radio Resource Allocation Control";
  const char *act_name=quota?"Slice-level PRB quota":handover?"Slice Handover":"RRC Connection Release";
  e2_node_arr_xapp_t nodes=e2_nodes_xapp_api();
  e2_node_connected_xapp_t *node=NULL;
  uint32_t style=0;uint16_t act=0;
  for(size_t i=0;i<nodes.len && !node;i++)
    for(size_t k=0;k<nodes.n[i].len_rf;k++)
      if(nodes.n[i].rf[k].id==RC_RAN_FUNCTION && nodes.n[i].rf[k].defn.type==RC_RAN_FUNC_DEF_E &&
         find_ctrl(&nodes.n[i].rf[k].defn.rc,style_name,act_name,&style,&act)){node=&nodes.n[i];break;}
  if(!node){free_e2_node_arr_xapp(&nodes);free_ue_id_e2sm(&ue);*out=error_object("no E2 node offers this E2SM-RC control action");return 501;}

  rc_ctrl_req_data_t req_data={0};
  req_data.hdr.format=FORMAT_1_E2SM_RC_CTRL_HDR;
  req_data.hdr.frmt_1.ric_style_type=style;req_data.hdr.frmt_1.ctrl_act_id=act;
  req_data.hdr.frmt_1.ue_id=cp_ue_id_e2sm(&ue);
  req_data.msg.format=FORMAT_1_E2SM_RC_CTRL_MSG;
  if(quota)fill_prb_quota(&req_data.msg.frmt_1,&ue,sst,sd,(int)ratio);
  if(handover)fill_slice_handover(&req_data.msg.frmt_1,sst,(uint32_t)sd);
  int64_t sent_us=time_now_us();
  pthread_mutex_lock(&ctrl_lock);
  sm_ans_xapp_t ans=control_sm_xapp_api(&node->id,RC_RAN_FUNCTION,&req_data);
  pthread_mutex_unlock(&ctrl_lock);
  int64_t acked_us=time_now_us();
  free_rc_ctrl_req_data(&req_data);free_ue_id_e2sm(&ue);free_e2_node_arr_xapp(&nodes);

  json_object *o=json_object_new_object();
  json_object_object_add(o,"status",json_object_new_string(ans.success?"acknowledged":"failed"));
  json_object_object_add(o,"action",json_object_new_string(action));
  if(quota)json_object_object_add(o,"max_prb_ratio",json_object_new_int64(ratio));
  if(sd>=0){json_object_object_add(o,"sst",json_object_new_int(sst));json_object_object_add(o,"sd",json_object_new_int64(sd));}
  json_object_object_add(o,"supi",json_object_new_string(supi));
  json_object_object_add(o,"amf_ue_ngap_id",json_object_new_uint64(amf));
  json_object_object_add(o,"ric_style_type",json_object_new_int((int)style));
  json_object_object_add(o,"ctrl_act_id",json_object_new_int(act));
  json_object_object_add(o,"origin",json_object_new_string(origin));
  json_object_object_add(o,"sent_unix_ms",json_object_new_int64(sent_us/1000));
  json_object_object_add(o,"ack_latency_ms",json_object_new_double((acked_us-sent_us)/1000.0));
  log_line(o);
  printf("[xApp] RAN control (%s) %s %s (AMF UE NGAP ID %" PRIu64 ") style %u action %u: %s\n",origin,action,supi,amf,style,act,ans.success?"acknowledged":"failed");
  fflush(stdout);
  *out=o;
  return ans.success?200:502;
}

static enum MHD_Result control(struct MHD_Connection *c,request_t *req){
  json_object *in=json_tokener_parse(req->body),*x=NULL;
  if(!in || !json_object_is_type(in,json_type_object)){if(in)json_object_put(in);return fail(c,400,"body must be a JSON object");}
  char action[24]="";
  if(json_object_object_get_ex(in,"action",&x) && json_object_is_type(x,json_type_string))snprintf(action,sizeof(action),"%s",json_object_get_string(x));
  int64_t ratio=-1;
  if(json_object_object_get_ex(in,"max_prb_ratio",&x) && json_object_is_type(x,json_type_int))ratio=json_object_get_int64(x);
  int sst=-1;int64_t sd=-1;
  if(json_object_object_get_ex(in,"sst",&x) && json_object_is_type(x,json_type_int))sst=(int)json_object_get_int64(x);
  if(json_object_object_get_ex(in,"sd",&x)){
    if(json_object_is_type(x,json_type_int))sd=json_object_get_int64(x);
    else if(json_object_is_type(x,json_type_string))sd=(int64_t)strtoll(json_object_get_string(x),NULL,16);
  }
  char supi[96]="";uint64_t amf=0;bool has_amf=false;
  if(json_object_object_get_ex(in,"supi",&x) && json_object_is_type(x,json_type_string))snprintf(supi,sizeof(supi),"%s",json_object_get_string(x));
  if(json_object_object_get_ex(in,"amf_ue_ngap_id",&x) && json_object_is_type(x,json_type_int) && json_object_get_int64(x)>=0){amf=(uint64_t)json_object_get_int64(x);has_amf=true;}
  json_object_put(in);
  json_object *o=NULL;
  int code=ran_control_slice(supi,amf,has_amf,action,sst,sd,ratio,"http",&o);
  return reply(c,(unsigned)code,o);
}

static enum MHD_Result handle(void *cls,struct MHD_Connection *c,const char *url,const char *method,const char *version,
                              const char *upload,size_t *size,void **context){
  (void)cls;(void)version;
  if(strncmp(url,"/v1/defense/",12)==0 && strcmp(method,"GET")==0){
    json_object *o=NULL;int code=defense_http(url,NULL,&o);return reply(c,(unsigned)code,o);
  }
  bool ran=strcmp(url,"/v1/ran/control")==0,def=strncmp(url,"/v1/defense/",12)==0;
  if((!ran && !def) || strcmp(method,"POST")!=0)return fail(c,404,"POST /v1/ran/control, GET|POST /v1/defense/...");
  if(*context==NULL){request_t *r=calloc(1,sizeof(*r));if(!r)return MHD_NO;r->body=calloc(MAX_BODY+1,1);if(!r->body){free(r);return MHD_NO;}*context=r;return MHD_YES;}
  request_t *r=*context;
  if(*size){if(r->used+*size>MAX_BODY)return fail(c,413,"body too large");memcpy(r->body+r->used,upload,*size);r->used+=*size;*size=0;return MHD_YES;}
  if(def){json_object *o=NULL;int code=defense_http(url,r->body,&o);return reply(c,(unsigned)code,o);}
  return control(c,r);
}

static void completed(void *cls,struct MHD_Connection *c,void **context,enum MHD_RequestTerminationCode reason){
  (void)cls;(void)c;(void)reason;request_t *r=*context;if(r){free(r->body);free(r);}*context=NULL;
}

int ran_control_start(const char *log_path){
  const char *p=getenv("RAN_CONTROL_PORT");long port=p && *p?strtol(p,NULL,10):8090;
  if(port<=0 || port>65535)return -1;
  if(log_path && !(log_file=fopen(log_path,"a")))fprintf(stderr,"[xApp] RAN control log %s: %s\n",log_path,strerror(errno));
  /* loopback only: actions are requested from inside the pod */
  struct sockaddr_in addr={.sin_family=AF_INET,.sin_port=htons((uint16_t)port)};
  addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  daemon_=MHD_start_daemon(MHD_USE_INTERNAL_POLLING_THREAD,(uint16_t)port,NULL,NULL,&handle,NULL,
                           MHD_OPTION_SOCK_ADDR,(struct sockaddr*)&addr,MHD_OPTION_NOTIFY_COMPLETED,&completed,NULL,MHD_OPTION_END);
  if(daemon_)printf("[xApp] RAN control on 127.0.0.1:%ld\n",port);
  return daemon_?0:-1;
}

void ran_control_stop(void){
  if(daemon_){MHD_stop_daemon(daemon_);daemon_=NULL;}
  if(log_file){fclose(log_file);log_file=NULL;}
}
