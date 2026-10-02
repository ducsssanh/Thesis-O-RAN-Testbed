// SPDX-License-Identifier: LicenseRef-CSSL-1.0
uicc0 = {
 imsi = "__IMSI__";
 key = "__KEY__";
 opc = "__OPC__";
 pdu_sessions = ({ dnn = "{{ .Values.global.lab.slice.dnn }}"; nssai_sst = {{ .Values.global.lab.slice.sst }}; nssai_sd = 0x{{ .Values.global.lab.slice.sd }}; });
};
@include "channelmod_rfsimu.conf"
