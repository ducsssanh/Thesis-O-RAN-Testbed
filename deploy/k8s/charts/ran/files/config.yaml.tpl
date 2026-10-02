amf:
  amf_name: amf
  emergency_support: false
  plmn_support_list:
  - mcc: {{ .Values.global.lab.plmn.mcc | quote }}
    mnc: {{ .Values.global.lab.plmn.mnc | quote }}
    tac: {{ .Values.global.lab.tac }}
    nssai:
    - &id001
      sst: {{ .Values.global.lab.slice.sst }}
      sd: {{ .Values.global.lab.slice.sd | quote }}
  relative_capacity: 30
  served_guami_list:
  - amf_pointer: '00'
    amf_region_id: '01'
    amf_set_id: '000'
    mcc: {{ .Values.global.lab.plmn.mcc | quote }}
    mnc: {{ .Values.global.lab.plmn.mnc | quote }}
  statistics_timer_interval: 20
  support_features_options:
    enable_nssf: false
    enable_simple_scenario: false
    enable_smf_selection: true
  supported_encryption_algorithms:
  - NEA0
  - NEA1
  - NEA2
  supported_integrity_algorithms:
  - NIA1
  - NIA2
database:
  connection_timeout: 300
  database_name: oai_db
  generate_random: false
  host: oai-lab-db.oai-core.svc.cluster.local
  password: __DB_PASSWORD__
  type: mysql
  user: oai
dnns:
- dnn: {{ .Values.global.lab.slice.dnn | quote }}
  ipv4_subnet: {{ .Values.global.lab.ueSubnet | quote }}
  pdu_session_type: IPV4
http_version: 1
log_level:
  general: debug
nfs:
  amf:
    host: oai-amf.oai-core.svc.cluster.local
    n2:
      interface_name: n2
      port: 38412
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
  ausf:
    host: oai-ausf.oai-core.svc.cluster.local
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
  nrf:
    host: oai-nrf.oai-core.svc.cluster.local
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
  smf:
    host: oai-smf.oai-core.svc.cluster.local
    n4:
      interface_name: n4
      port: 8805
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
  udm:
    host: oai-udm.oai-core.svc.cluster.local
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
  udr:
    host: oai-udr.oai-core.svc.cluster.local
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
  upf:
    host: oai-upf.oai-core.svc.cluster.local
    n3:
      interface_name: n3
      port: 2152
    n4:
      interface_name: n4
      port: 8805
    n6:
      interface_name: n6
    sbi:
      api_version: v1
      interface_name: eth0
      port: 80
register_nf:
  general: true
smf:
  ims:
    pcscf_ipv4: 127.0.0.1
  local_subscription_infos:
  - dnn: {{ .Values.global.lab.slice.dnn | quote }}
    single_nssai: *id001
    qos_profile:
      5qi: 9
  smf_info:
    sNssaiSmfInfoList:
    - sNssai: *id001
      dnnSmfInfoList:
      - dnn: {{ .Values.global.lab.slice.dnn | quote }}
  support_features:
    use_local_pcc_rules: true
    use_local_subscription_info: true
  ue_dns:
    primary_ipv4: 172.21.3.100
    secondary_ipv4: 8.8.8.8
  ue_mtu: 1500
  upfs:
  - host: {{ .Values.global.lab.networks.n4.addresses.upf | quote }}
    config:
      enable_usage_reporting: {{ .Values.global.lab.usageReporting }}
snssais:
- *id001
upf:
  remote_n6_gw: {{ .Values.global.lab.networks.n6.addresses.dn | quote }}
  smfs:
  - host: {{ .Values.global.lab.networks.n4.addresses.smf | quote }}
  support_features:
    enable_bpf_datapath: true
    enable_urr: {{ .Values.global.lab.usageReporting }}
    enable_snat: false
    xdp_mode: {{ .Values.global.lab.xdpMode | quote }}
  upf_info:
    sNssaiUpfInfoList:
    - sNssai: *id001
      dnnUpfInfoList:
      - dnn: {{ .Values.global.lab.slice.dnn | quote }}
