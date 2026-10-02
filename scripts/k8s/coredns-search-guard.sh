#!/usr/bin/env bash
# Answer NXDOMAIN locally for search-path artifacts such as
# "oai-nrf.oai-core.svc.cluster.local.<host-search-domain>". Pods use ndots:5,
# so every FQDN lookup first tries the node's search domain; CoreDNS forwards
# that to the minikube node resolver, which can hang (~15 s) when Docker's
# embedded DNS cannot reach upstream. OAI NF HTTP clients then time out on NRF.
# Reverse (PTR) lookups of the lab secondary networks 172.30.0.0/16 are answered
# the same way: SMF resolves the UPF PFCP Node ID and otherwise waits ~38 s and
# gives up on the association.
# Idempotent; CoreDNS reloads the Corefile automatically.
set -Eeuo pipefail
K=(kubectl --context oai-lab -n kube-system)
corefile=$("${K[@]}" get cm coredns -o jsonpath='{.data.Corefile}')
if grep -q 'oai-lab ptr guard' <<<"$corefile"; then echo "guard already present"; exit 0; fi
# Drop an older guard revision (search-path only) before inserting the current one.
corefile=$(python3 - "$corefile" <<'PY'
import re, sys
print(re.sub(r"    # oai-lab search-path guard\n    template ANY ANY \{[^}]*\}\n", "", sys.argv[1]), end="")
PY
)
guard='    # oai-lab search-path guard
    template ANY ANY {
       match "\.cluster\.local\.[^.]+.*\.$"
       rcode NXDOMAIN
       fallthrough
    }
    # oai-lab ptr guard
    template ANY PTR 30.172.in-addr.arpa {
       rcode NXDOMAIN
    }'
new=$(python3 - "$corefile" "$guard" <<'PY'
import sys
c, g = sys.argv[1], sys.argv[2]
i = c.index("    kubernetes cluster.local")
print(c[:i] + g + "\n" + c[i:], end="")
PY
)
"${K[@]}" create cm coredns --from-literal=Corefile="$new" --dry-run=client -o yaml | "${K[@]}" apply -f -
echo "guard installed"
