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
        oai-lab/config-checksum: {{ toJson $lab | sha256sum | quote }}
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
          env: [{name: SSL_CERT_FILE, value: /etc/oai-lab-ca/ca.crt}]
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
            {{- end }}
            {{- if eq $nf "nr-ue" }}
            - {name: tun, mountPath: /dev/net/tun}
            {{- end }}
        {{- if and (eq $nf "nr-ue") (gt (int $lab.defense.ueKeepaliveS) 0) }}
        # Benign background traffic, like any phone's keep-alives: one UDP
        # datagram to the DN discard port through the UE tunnel, so an idle
        # but attached UE is not taken for a lost one by the session TTL (T2)
        - name: keepalive
          image: {{ $lab.toolsImage | quote }}
          command:
            - python3
            - -c
            - |
              import socket, sys, time
              dn, period = sys.argv[1], float(sys.argv[2])
              while True:
                  try:
                      s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                      s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_BINDTODEVICE", 25), b"oaitun_ue1")
                      s.sendto(b"keepalive", (dn, 9))
                      s.close()
                  except OSError:
                      pass
                  time.sleep(period)
            - {{ $lab.networks.n6.addresses.dn | quote }}
            - {{ $lab.defense.ueKeepaliveS | quote }}
          securityContext: {capabilities: {add: [NET_RAW], drop: [ALL]}}
          resources: {requests: {cpu: 5m, memory: 16Mi}, limits: {cpu: 50m, memory: 64Mi}}
        {{- end }}
        {{- if eq $nf "smf" }}
        - name: capture
          image: {{ $lab.toolsImage | quote }}
          command: [python3, /opt/lab/runtime.py, capture]
          securityContext: {capabilities: {add: [NET_RAW, NET_ADMIN, CHOWN, SETUID, SETGID], drop: [ALL]}}
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
        {{- if eq $nf "smf" }}
        - name: lab-ca
          secret: {secretName: oai-lab-ca, items: [{key: ca.crt, path: ca.crt}]}
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
