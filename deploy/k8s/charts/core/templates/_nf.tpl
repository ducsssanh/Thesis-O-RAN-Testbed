{{- define "lab.nf" -}}
{{- $lab := .Values.global.lab -}}
{{- $nf := trimPrefix "oai-" .Chart.Name -}}
{{- $w := index $lab.workloads $nf -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Chart.Name }}
  labels: {oai-lab/component: {{ $nf | quote }}}
spec:
  replicas: {{ $lab.replicas | default 0 }}
  strategy: {type: Recreate}
  selector:
    matchLabels:
      {{- include (printf "%s.selectorLabels" .Chart.Name) . | nindent 6 }}
  template:
    metadata:
      labels:
        oai-lab/component: {{ $nf | quote }}
        {{- include (printf "%s.selectorLabels" .Chart.Name) . | nindent 8 }}
      annotations:
        {{- /* defense.xapp only configures the xApp and defense.upfSecurity only the UPF
               (its env below): changing them must not restart the other NFs */}}
        {{- $cfg := omit $lab "defense" }}
        {{- if hasKey $lab "defense" }}{{- $_ := set $cfg "defense" (omit $lab.defense "xapp" "upfSecurity") }}{{- end }}
        oai-lab/config-checksum: {{ toJson $cfg | sha256sum | quote }}
        k8s.v1.cni.cncf.io/networks: {{ include "lab.attachments" (dict "lab" $lab "nf" $nf) | quote }}
    spec:
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      initContainers:
        - name: prepare
          image: {{ $lab.toolsImage | quote }}
          command: [python3, /opt/lab/runtime.py, prepare, {{ $nf | quote }}]
          env:
            - name: POD_IP
              valueFrom: {fieldRef: {fieldPath: status.podIP}}
            {{- if eq $nf "nr-ue" }}
            {{- range $key := list "IMSI" "KEY" "OPC" }}
            - name: {{ $key }}
              valueFrom: {secretKeyRef: {name: {{ $lab.secretName }}, key: {{ $key }}}}
            {{- end }}
            {{- else if not (has $nf (list "gnb" "flexric")) }}
            - name: DB_PASSWORD
              valueFrom: {secretKeyRef: {name: {{ $lab.secretName }}, key: DB_PASSWORD}}
            {{- end }}
          securityContext:
            privileged: {{ eq $nf "upf" }}
            capabilities: {add: [NET_ADMIN], drop: [ALL]}
          volumeMounts:
            - {name: config, mountPath: /input, readOnly: true}
            - {name: runtime, mountPath: /config}
        {{- if eq $nf "smf" }}
        - name: trust-lab-ca
          image: {{ $w.image | quote }}
          command: [sh, -ec, 'cat /etc/ssl/certs/ca-certificates.crt /etc/oai-lab-ca/ca.crt > /trust/ca-certificates.crt']
          securityContext: {runAsUser: 0, allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts:
            - {name: lab-ca, mountPath: /etc/oai-lab-ca, readOnly: true}
            - {name: trust-bundle, mountPath: /trust}
        {{- end }}
      containers:
        - name: {{ $nf }}
          image: {{ $w.image | quote }}
          imagePullPolicy: IfNotPresent
          {{- if has $nf (list "gnb" "nr-ue" "flexric") }}
          command: [/opt/lab/radio-entrypoint.sh, {{ $nf | quote }}]
          {{- else }}
          command: [{{ printf "/openair-%s/bin/oai_%s" $nf $nf | quote }}, -c, /config/config.yaml, -o]
          {{- end }}
          securityContext:
            privileged: {{ eq $nf "upf" }}
            capabilities:
              drop: [ALL]
              add: [NET_ADMIN, NET_RAW{{ if has $nf (list "gnb" "nr-ue") }}, SYS_NICE, IPC_LOCK{{ end }}]
          {{- if eq $nf "smf" }}
          env: [{name: SSL_CERT_FILE, value: /etc/ssl/certs/ca-certificates.crt}]
          {{- end }}
          {{- $sec := (($lab.defense | default dict).upfSecurity | default dict) }}
          {{- if and (eq $nf "upf") $sec.enabled }}
          env:
            - {name: UPF_SEC_ENABLED, value: "true"}
            - {name: UPF_SEC_PORT, value: {{ $sec.port | default 8095 | quote }}}
            - {name: UPF_SEC_DB_PATH, value: {{ $sec.dbPath | default "/upf-sec/sec_policy.db" | quote }}}
            - {name: UPF_SEC_AUDIT_PATH, value: {{ $sec.auditPath | default "/upf-sec/audit.jsonl" | quote }}}
            - {name: UPF_SEC_MAX_TTL_S, value: {{ $sec.maxTtlS | default 86400 | quote }}}
            - {name: UPF_SEC_MAX_CMDS_PER_S, value: {{ $sec.maxCmdsPerS | default 10 | quote }}}
            - {name: UPF_SEC_MAX_BLOCKED_RATIO, value: {{ $sec.maxBlockedRatio | default 0.5 | quote }}}
            - {name: UPF_SEC_MAX_POLICIES, value: {{ $sec.maxPolicies | default 16384 | quote }}}
            - {name: UPF_SEC_RATELIMIT_BURST_MS, value: {{ $sec.ratelimitBurstMs | default 100 | quote }}}
            - {name: UPF_SEC_SWEEP_S, value: {{ $sec.sweepS | default 5 | quote }}}
            - {name: UPF_SEC_PROFILE, value: {{ (hasKey $sec "profile" | ternary $sec.profile true) | quote }}}
            - {name: UPF_SEC_TELEMETRY_RING, value: {{ $sec.telemetryRing | default 7200 | quote }}}
            - {name: UPF_SEC_DROP_SPOOFED, value: {{ (hasKey $sec "dropSpoofed" | ternary $sec.dropSpoofed true) | quote }}}
            - {name: UPF_SEC_DROP_GTP_IN_GTP, value: {{ (hasKey $sec "dropGtpInGtp" | ternary $sec.dropGtpInGtp true) | quote }}}
            - {name: UPF_SEC_DROP_UNKNOWN_UL, value: {{ (hasKey $sec "dropUnknownUl" | ternary $sec.dropUnknownUl true) | quote }}}
            {{- $reflex := ($sec.reflex | default dict) }}
            - {name: UPF_SEC_REFLEX_MODE, value: {{ $reflex.mode | default "off" | quote }}}
            - {name: UPF_SEC_REFLEX_QUOTA_UL_BYTES, value: {{ $reflex.quotaUlBytes | default 3125000 | quote }}}
            - {name: UPF_SEC_REFLEX_RATE_UL_KBPS, value: {{ $reflex.rateUlKbps | default 2000 | quote }}}
            - {name: UPF_SEC_REFLEX_TTL_S, value: {{ $reflex.ttlS | default 10 | quote }}}
            - {name: UPF_SEC_REFLEX_TTL_MAX_S, value: {{ $reflex.ttlMaxS | default 60 | quote }}}
            - {name: UPF_SEC_REFLEX_MAX_SHARE, value: {{ $reflex.maxShare | default 0.2 | quote }}}
          ports:
            - {name: sec-api, containerPort: {{ $sec.port | default 8095 }}, protocol: TCP}
          {{- end }}
          resources:
            requests: {{ toJson $w.requests }}
            limits: {{ toJson $w.limits }}
          startupProbe:
            exec: {command: [sh, -c, {{ if has $nf (list "gnb" "nr-ue" "flexric") }}"kill -0 1"{{ else if eq $nf "upf" }}"awk '$2 ~ /:2265$/ {ok=1} END {exit !ok}' /proc/net/udp /proc/net/udp6"{{ else }}"awk '$2 ~ /:0050$/ && $4 == \"0A\" {ok=1} END {exit !ok}' /proc/net/tcp /proc/net/tcp6"{{ end }}]}
            failureThreshold: 90
            periodSeconds: 2
          readinessProbe:
            exec: {command: [sh, -c, {{ if has $nf (list "gnb" "nr-ue" "flexric") }}"kill -0 1"{{ else if eq $nf "upf" }}"awk '$2 ~ /:2265$/ {ok=1} END {exit !ok}' /proc/net/udp /proc/net/udp6"{{ else }}"awk '$2 ~ /:0050$/ && $4 == \"0A\" {ok=1} END {exit !ok}' /proc/net/tcp /proc/net/tcp6"{{ end }}]}
            periodSeconds: 5
          volumeMounts:
            - {name: runtime, mountPath: /config, readOnly: true}
            {{- if eq $nf "smf" }}
            - {name: lab-ca, mountPath: /etc/oai-lab-ca, readOnly: true}
            - {name: trust-bundle, mountPath: /etc/ssl/certs/ca-certificates.crt, subPath: ca-certificates.crt, readOnly: true}
            {{- end }}
            {{- if eq $nf "nr-ue" }}
            - {name: tun, mountPath: /dev/net/tun}
            {{- end }}
            {{- if and (eq $nf "upf") $sec.enabled }}
            - {name: upf-security, mountPath: /upf-sec}
            {{- end }}
        {{- if eq $nf "smf" }}
        - name: capture
          image: {{ $lab.toolsImage | quote }}
          command: [python3, /opt/lab/runtime.py, capture]
          securityContext: {capabilities: {add: [NET_RAW, NET_ADMIN, CHOWN, SETUID, SETGID, KILL], drop: [ALL]}}  # KILL: stop tcpdump after it drops to its own uid
          resources: {requests: {cpu: 25m, memory: 64Mi}, limits: {cpu: 250m, memory: 256Mi}}
          volumeMounts:
            - {name: artifacts, mountPath: /artifacts}
        {{- end }}
      volumes:
        - name: config
          configMap: {name: oai-lab-config}
        - name: runtime
          emptyDir: {medium: Memory}
        {{- if eq $nf "nr-ue" }}
        - name: tun
          hostPath: {path: /dev/net/tun, type: CharDevice}
        {{- end }}
        {{- if and (eq $nf "upf") $sec.enabled }}
        - name: upf-security
          persistentVolumeClaim: {claimName: oai-lab-upf-security}
        {{- end }}
        {{- if eq $nf "smf" }}
        - name: lab-ca
          secret: {secretName: oai-lab-ca, items: [{key: ca.crt, path: ca.crt}]}
        - name: trust-bundle
          emptyDir: {medium: Memory}
        - name: artifacts
          persistentVolumeClaim: {claimName: oai-lab-artifacts}
        {{- end }}
{{- end -}}

{{- define "lab.attachments" -}}
{{- $nets := list -}}
{{- range $name, $net := .lab.networks -}}
{{- if hasKey $net.addresses $.nf -}}
{{- $nets = append $nets (dict "name" (printf "oai-%s-%s" $.nf $name) "interface" $name) -}}
{{- end -}}
{{- end -}}
{{- toJson $nets -}}
{{- end -}}
