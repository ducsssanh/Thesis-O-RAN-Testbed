# Helm Chart for OAI Next Generation Node B (OAI-gNB) Fronthaul 7.2

7.2 fronthaul helm-charts are a bit special than RFSIM or VRTSIM based 
helm-charts as it requires special configuration on the gNB host server. The gNB 
host server should have: 

1. [PTP Operator](https://github.com/openshift/ptp-operator) or PTP configured in leader or follower mode
2. [SRIOV Operator](https://github.com/k8snetworkplumbingwg/sriov-network-operator) or sriov interface configuration
3. Disable chrony or timedatectl ntp service
4. OS realtime configuration with isolated cpus for workload

Performance profile for **openshift**:

```yaml
  globallyDisableIrqLoadBalancing: true
  additionalKernelArgs:
   - nmi_watchdog=0
   - audit=0
   - idle=poll
   - mce=off
   - processor.max_cstate=1
   - idle=poll
   - vfio_pci.enable_sriov=1
   - vfio_pci.disable_idle_d3=11 #depends on intel or AMD
   - intel_idle.max_cstate=0 #depends on intel or AMD
   - intel_iommu=on  #depends on intel or AMD
  cpu:
    isolated: "$ISOLATED_CPUS"
    reserved: "$RESERVED_CPUS" # 4 should be enough
  hugepages:
    defaultHugepagesSize: "1G"
    pages:
    - size: "1G"
      count: 20
      node: 0
  net:
    userLevelNetworking: true  #optional
  numa:
    topologyPolicy: restricted
  workloadHints:
    realTime: true
    highPowerConsumption: true
    perPodPowerManagement: false
  realTimeKernel:
    enabled: true
```

Isolated cpus are for the workload and reserved are for the operating system. 

Make sure this profile configure `cpuManagerPolicy` to static. If it does not 
then the helm-charts will not work. In openshift you can check 
`kubeletconfigs.machineconfiguration.openshift.io` to confirm cpuManagerPolicy. 

For **Vanilla Kubernetes** based cluster, before making the cluster update your 
grub command line to below command line

```bash
isolcpus=managed_irq,$ISOLATED_CPU nohz_full=$ISOLATED_CPU nohz=on rcu_nocbs=$ISOLATED_CPUS irqaffinity=$RESERVED_CPUS rcu_nocb_poll selinux=0 enforcing=0 crashkernel=auto nosoftlockup hugepagesz=1G hugepages=20 hugepagesz=2M hugepages=0 default_hugepagesz=1G mitigations=off processor.max_cstate=1 idle=poll iommu=pt skew_tick=1 tsc=nowatchdog nmi_watchdog=0 softlockup_panic=0 audit=0 mce=off
```

For intel (x86) you can add:

```bash
intel_pstate=disable intel_iommu=on
```

For AMD (x86) you can add:

```bash
amd_iommu=on
#disabling amd_pstate only available in kernel +6.8
amd_pstate=disable
```

**NOTE**: Use either tuned-adm or update grub. But don't do both. 

Sample kubeadm configuration (only for reference) you can use:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: "$YOUR_CLUSTER_IP_ADDRESS"
  bindPort: 6443
nodeRegistration:
  criSocket: unix:///var/run/crio/crio.sock
---
kind: ClusterConfiguration
apiVersion: kubeadm.k8s.io/v1beta4
clusterName: "$YOUR_CLUSTER_NAME"
kubernetesVersion: "$K8S_VERSION"
networking:
  serviceSubnet: "10.96.0.0/16"
  podSubnet: "10.244.0.0/24"
  dnsDomain: "cluster.local"
---
kind: KubeletConfiguration
apiVersion: kubelet.config.k8s.io/v1beta1
cgroupDriver: systemd
cpuManagerPolicy: static
cpuManagerPolicyOptions:
   "full-pcpus-only": "true"
reservedSystemCPUs: $RESERVED_CPUS
memorySwap: {}
topologyManagerPolicy: "best-effort"
failSwapOn: false
containerLogMaxSize: 50Mi
featureGates:
   CPUManager: true
   CPUManagerPolicyOptions: true
   CPUManagerPolicyBetaOptions: true
---
apiVersion: kubeproxy.config.k8s.io/v1alpha1
kind: KubeProxyConfiguration
ipvs:
  strictARP: true
```

Make sure you are also restricing the cpu affinity of systemd in 
`/etc/systemd/system.conf`

Common configuration: 

Openshift or Vanilla K8s cluster might need (depending if one of your 
configuration automatically applies it)

```bash
sysctl kernel.sched_rt_runtime_us
sysctl kernel.timer_migration
# check the values if they are not -1 and 0 then update
echo -1 > /proc/sys/kernel/sched_rt_runtime_us
echo 0 > /proc/sys/kernel/timer_migration
```

## Introduction

To know more about the feature set of OpenAirInterface you can check it [here](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/FEATURE_SET.md#openairinterface-5g-nr-feature-set). 

The [codebase](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tree/develop) for gNB, CU, DU, CU-CP/CU-UP, NR-UE is the same. 

The configuration file used by the nf is in [config.yaml](./config.yaml). It is 
YAML based. You can refer to the sample configuration files in [Example configuration files](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tree/develop/targets/PROJECTS/GENERIC-NR-5GC/CONF). 

Not all are YAML based but you can use the same parameter names.

It is strongly recommended that you read about [OAI 7.2 implementation](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/ORAN_FHI7.2_Tutorial.md?ref_type=heads)

## Prerequisite

1. Configure the baremetal DU server as mentioned explained above  
2. Before using the helm-charts you have to create two dedicated `SriovNetworkNodePolicy` for C and U plane. 

Using below Kubernetes manifest

```yaml
apiVersion: sriovnetwork.openshift.io/v1
kind: SriovNetworkNodePolicy
metadata:      
  name: RESOURCE_NAME_U_PLANE
  # in vanilla k8s the namespace is sriov-network-operator
  namespace: openshift-sriov-network-operator
spec:
  resourceName: RESOURCE_NAME_U_PLANE
  nodeSelector:
    feature.node.kubernetes.io/network-sriov.capable: "true"
  priority: 11
  mtu: 9216
  deviceType: vfio-pci
  isRdma: false
  numVfs: 4
  linkType: eth
  nicSelector:
    pfNames:
      - 'PHYSICAL_INTERFACE#0-1'     # Same device specified by rootDevices
    rootDevices:
      - 'PCI_ADDRESS_OF_THE_PHYSICAL_INTERFACE' # PCI bus address
---
apiVersion: sriovnetwork.openshift.io/v1
kind: SriovNetworkNodePolicy
metadata:      
  name: RESOURCE_NAME_C_PLANE
  # in vanilla k8s the namespace is sriov-network-operator
namespace: openshift-sriov-network-operator
spec:
  resourceName: RESOURCE_NAME_C_PLANE
  nodeSelector:
    feature.node.kubernetes.io/network-sriov.capable: "true"
  priority: 12
  mtu: 9216
  deviceType: vfio-pci
  isRdma: false
  numVfs: 4
  linkType: eth
  nicSelector:
    pfNames:
      - 'PHYSICAL_INTERFACE#2-3'     # Same device specified by rootDevices
    rootDevices:
      - 'PCI_ADDRESS_OF_THE_PHYSICAL_INTERFACE' # PCI bus address
```

## 📁 Chart Structure

```
.
├── Chart.yaml
├── templates
│ ├── configmap.yaml
│ ├── deployment.yaml
│ ├── _helpers.tpl
│ ├── nad.yaml
│ ├── NOTES.txt
│ ├── rbac.yaml
│ ├── serviceaccount.yaml
│ └── service.yaml
└── values.yaml
```

The chart creates:

1. **Service**
2. **RBAC** (Role + RoleBinding)
3. **Deployment**
4. **ConfigMap** (mounts gNB configuration)
5. **ServiceAccount**
6. **NetworkAttachmentDefinition** *(optional — when Multus is enabled)*

## Parameters

All configurable parameters are defined in [values.yaml](./values.yaml).  
Below table summarizes key parameters.

### 🧱 Base Parameters

| Parameter | Allowed Values | Description |
|------------|----------------|--------------|
| **kubernetesDistribution** | `Vanilla` / `Openshift` | Select Kubernetes flavor |
| **nfimage.repository** | String | DU image name (default: `oaisoftwarealliance/oai-gnb`) |
| **nfimage.version** | String | Image tag (default: `develop`) |
| **nfimage.pullPolicy** | `IfNotPresent` / `Always` / `Never` | Container image pull policy |
| **imagePullSecrets** | List | Optional; for private registries (e.g., DockerHub credentials) |
| **serviceAccount.create** | `true` / `false` | Create a dedicated service account |
| **serviceAccount.annotations** | Map | Optional service account annotations |
| **podSecurityContext.runAsUser** | Integer | Usually `0` (root) |
| **podSecurityContext.runAsGroup** | Integer | Usually `0` (root) |

💡 Optional:
You can specify private registry credentials by un-commenting and editing:

```yaml
imagePullSecrets:
 - name: regcred
```
---

## 📦 Container Images

Our [Jenkins Platform](https://jenkins-oai.eurecom.fr/view/RAN/) publishes new ubuntu images weekly on Docker Hub:

| Image | Description |
|--------|--------------|
| [`oaisoftwarealliance/oai-gnb`](https://hub.docker.com/r/oaisoftwarealliance/oai-gnb) | Monolithic gNB, DU, CU, CU-CP |
| [`oaisoftwarealliance/oai-nr-cuup`](https://hub.docker.com/r/oaisoftwarealliance/oai-nr-cuup) | CU-UP component |

Tags available:
- `develop` → latest development image  
- `YYYY.wNN` → weekly tagged build (e.g., `2025.w44`)

> Only **Ubuntu 24.04** images are published.  
> For **Red Hat/UBI** systems, build locally following [this guide](../../../openshift/README.md).

---

### 🕸️ Multus Interface Configuration

| Parameter | Allowed Values | Description |
|------------|----------------|--------------|
| **multus.enabled** | `true` / `false` | Enable Multus (default: `false`) |
| **multus.interfaces[].name** | `f1c` / `f1u` / `ru` | Logical interface name inside the container |
| **multus.interfaces[].hostInterface** | String | Host network interface name |
| **multus.interfaces[].type** | String | macvlan, vlan, sriov |
| **multus.interfaces[].ipAdd** | IPv4 | Static IP assigned to the interface |
| **multus.interfaces[].netmask** | CIDR mask | Interface netmask |
| **multus.interfaces[].defaultRoute** | IPv4 | Default route (optional) |
| **multus.interfaces[].gateway** | IPv4 | Gateway for interface (optional) |
| **multus.interfaces[].mtu** | Integer | MTU for interface (optional) |
| **multus.interfaces[].enabled** | `true` / `false` | Enable or disable interface |

> 💡 **Tip:**  
> If you do not have a gateway for Multus interfaces, leave `gateway` and `defaultRoute` empty.  
> Incorrect gateway configuration can break pod networking and DNS resolution.

> ⚙️ **Usage Modes:**
> - **RF-SIM Mode:** only F1 interface needed (can reuse `eth0`)  
> - **Physical gNB:** separate `ru` interface required for RU/Radio connection  

---

### ⚙️ gNB Configuration

The main runtime configuration is mounted through `config.yaml`.  
You can adapt it by editing `config.yaml` or override certain parameters in the `config` section of `values.yaml`.

| Parameter | Description |
|------------|--------------|
| **config.timeZone** | Container timezone |
| **config.useAdditionalOptions** | CLI flags for `nr-softmodem` |
| **config.gnbName** | DU node name |
| **config.gdbstack** | `1` to enable GDB traces |
| **config.tac** | Tracking Area Code |
| **config.plmn_list** | PLMN and S-NSSAI configuration |

---

### 🧰 Debugging & Developer Options

| Parameter | Values | Description |
|------------|---------|-------------|
| **start.gnb** | `true` / `false` | If `false`, NF container sleeps (manual debug) |
| **start.tcpdump** | `true` / `false` | If `true`, tcpdump sidecar starts (sleep mode) |
| **includeTcpDumpContainer** | `true` / `false` | Include tcpdump sidecar |
| **tcpdumpimage.repository** | String | Tcpdump image name |
| **tcpdumpimage.version** | String | Tcpdump tag |
| **tcpdumpimage.pullPolicy** | String | Pull policy |
| **resources.define** | `true` / `false` | Enable explicit CPU/memory limits |
| **resources.limits.nf.cpu / memory** | String | NF resource limits |
| **resources.requests.nf.cpu / memory** | String | NF resource requests |
| **terminationGracePeriodSeconds** | Integer | Grace period before termination (default: 5 s) |

Depending on the distribution of your Kubernetes cluster 
`resources.limits.sriovClaims` and multus section needs to be updated will change. 

```yaml
- name: "uplane"
  enabled: true
  type: sriov
  mac: "00:11:22:33:44:66"
  #make sure the name is correct
  sriovNetworkNamespace: "openshift-sriov-network-operator"
  #make sure it exists
  sriovResourceName: "ruvfiou"
  vlan: "3"
- name: "cplane"
  enabled: true
  mac: "00:11:22:33:44:67"
  type: sriov
  #make sure the name is correct
  sriovNetworkNamespace: "openshift-sriov-network-operator"
  #make sure it exists
  sriovResourceName: "ruvfioc"
  vlan: "3"
.
.
.
resources:
  define: true
  limits:
    cpu: 14
    memory: 5Gi
    hugepages: 8Gi
    sriovClaims:
      - name: openshift.io/ruvfioc #make sure it exists
        quantity: 1
      - name: openshift.io/ruvfiou #make sure it exists
        quantity: 1
  requests:
    cpu: 14
    memory: 5Gi
    hugepages: 8Gi
    sriovClaims:
      - name: openshift.io/ruvfioc  #make sure it exists
        quantity: 1
      - name: openshift.io/ruvfiou  #make sure it exists
        quantity: 1
```

## 🚀 Deployment Examples

Before deploying the gNB, ensure the **Core Network** is operational:

- [OAI 5G Core Basic](../../oai-5g-basic/README.md)
- [OAI 5G Core Mini](../../oai-5g-mini/README.md)

### Deploy the gNB

```bash
# to set the distribution --set kubernetesDistribution="Vanilla/Openshift"
helm install oai-gnb .
```

## 📝 Notes & Recommendations

1. **Multus Setup**: Ensure Multus CNI is correctly configured before enabling it in the chart. Avoid invalid gateway settings, as they may break pod connectivity.
2. **Configuration Flexibility**: The default config block exposes limited options for simplicity. For advanced setups, copy your own configuration file into `./config.yaml`.
3. **Performance**:
- Make sure the system is configured as mentioned above
- Facultative: for 4x4 100MHz scenario you would need total 14 isolated CPUs
- facultative: for 2x2 100MHz scenario you would need total 8 isolated CPUs
