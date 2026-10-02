# Helm Chart for OAI New Radio User Equipment (OAI-NR-UE)

This Helm chart deploys the **OpenAirInterface 5G New Radio User Equipment (OAI-NR-UE)** component.  
It supports both **RF-Simulated (RFsim)** and **physical (USRP-based)** operation modes.

This chart is tested with:
- [RF Simulated oai-gnb](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/radio/rfsimulator/README.md)
- Supported USRP devices:
  - USRP B2XX  
  - USRP N3XX  
  - USRP X3XX  

---

## ⚠️ Notes

- Tested on:
  - [Minikube](https://minikube.sigs.k8s.io/docs/)
  - [Red Hat OpenShift](https://www.redhat.com/en/technologies/cloud-computing/openshift) **versions 4.16–4.20**

- Minimum recommended resources for **RFSim NR-UE**:  
  **2 vCPUs** and **2 GiB RAM**


---

## 🧩 Introduction

The [OAI NR-UE](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tree/develop) implements the 5G New Radio User Equipment stack.  
It shares the same codebase as the **gNB**, **CU/DU**, and **CU-UP** components.

To learn more about features and configuration:
- [OAI 5G NR Feature Set](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/FEATURE_SET.md#openairinterface-5g-nr-feature-set)
- [nr-softmodem user guide](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/RUNMODEM.md)

---

## 📦 Container Images

Official OAI Docker images are published weekly on Docker Hub:

| Image | Description |
|--------|--------------|
| [`oaisoftwarealliance/oai-nr-ue`](https://hub.docker.com/r/oaisoftwarealliance/oai-nr-ue) | 5G NR User Equipment |

Tags:
- `develop` → latest development image  
- `YYYY.wNN` → weekly tagged release (e.g. `2025.w44`)

> Images are built on **Ubuntu 24.04**.  
> For OpenShift/UBI builds, follow this [tutorial](../../../openshift/README.md).

---

## 📁 Chart Structure

```
├── Chart.yaml
├── templates/
│ ├── configmap.yaml
│ ├── deployment.yaml
│ ├── _helpers.tpl
│ ├── NOTES.txt
│ ├── rbac.yaml
│ ├── serviceaccount.yaml
└── values.yaml
```

The chart creates the following Kubernetes resources:
1. **RBAC** (Role + RoleBinding)
2. **Deployment**
3. **ConfigMap**
4. **ServiceAccount**

---

## ⚙️ Configuration Parameters

All parameters are defined in [`values.yaml`](./values.yaml).

### 🧱 Base Parameters

| Parameter | Allowed Values | Description |
|------------|----------------|-------------|
| **kubernetesDistribution** | `Vanilla` / `Openshift` | Kubernetes flavor |
| **nfimage.repository** | String | Image name (default: `oaisoftwarealliance/oai-gnb`) |
| **nfimage.version** | String | Image tag (default: `develop`) |
| **nfimage.pullPolicy** | `IfNotPresent` / `Always` / `Never` | Kubernetes image pull policy |
| **imagePullSecrets.name** |String | Image pull secret |
| **serviceAccount.create** | `true` / `false` | Whether to create a new service account |
| **serviceAccount.annotations** | Map | Optional annotations |
| **podSecurityContext.runAsUser** | Integer | Must be `0` (root) |
| **podSecurityContext.runAsGroup** | Integer | Must be `0` (root) |

💡 Optional:
You can specify private registry credentials by un-commenting and editing:

```yaml
imagePullSecrets:
 - name: regcred
```
---

### ⚙️ NR-UE Configuration

The NR-UE configuration is applied via a ConfigMap.  
You can customize runtime behavior by editing the following parameters:

| Parameter | Example | Description |
|------------|----------|-------------|
| **config.timeZone** | `"Europe/Paris"` | Timezone for the container |
| **config.rfSimServer** | `"oai-ran"` | gNB hostname or IP (used in RFsim mode) |
| **config.fullImsi** | `"001010000000100"` | IMSI — must match entry in subscriber DB |
| **config.fullKey** | `"fec86ba6eb707ed08905757b1bb44b8f"` | Subscriber key (K) |
| **config.opc** | `"C42449363BBAD02B66D16BC975D77CC1"` | Operator Code (OPC) |
| **config.gdbstack** | `0` / `1` | Enable (1) or disable (0) GDB traces |
| **config.dnn** | `"oai"` | Data network name |
| **config.sst** | `"1"` | Slice/Service Type (must match AMF/SMF/UPF) |
| **config.sd** | `"16777215"` | Slice Differentiator |
| **config.radio** | `"rfsim"`, `"b2xx"`, `"n3xx"`, `"x3xx"` | Select radio hardware |
| **config.useAdditionalOptions** | `"-E --rfsim -r 106 --numerology 1 -C 3319680000 --log_config.global_log_options level,nocolor,time"` | Extra parameters for `nr-softmodem` |

> 💡 **Tip:**  
> If you are using `rfsim`, the NR-UE and gNB must reference each other’s hostnames correctly (e.g., `oai-ran`, `oai-gnb`).

---

### 🧰 Debugging and Sidecar Options

| Parameter | Values | Description |
|------------|---------|-------------|
| **start.nrue** | `true` / `false` | If `false`, container sleeps (manual debug mode) |
| **start.tcpdump** | `true` / `false` | If `true`, tcpdump sidecar runs |
| **includeTcpDumpContainer** | `true` / `false` | Add tcpdump sidecar container |
| **tcpdumpimage.repository** | String | Tcpdump image name |
| **tcpdumpimage.version** | String | Tcpdump tag |
| **tcpdumpimage.pullPolicy** | String | Image pull policy |

---

### 💾 Resource Configuration

| Parameter | Type | Description |
|------------|------|-------------|
| **resources.define** | `true` / `false` | Enable custom resource limits |
| **resources.limits.nf.cpu / memory** | String | CPU/memory limits for NR-UE container |
| **resources.requests.nf.cpu / memory** | String | CPU/memory requests for NR-UE container |
| **resources.limits.tcpdump.cpu / memory** | String | Limits for tcpdump sidecar (if enabled) |
| **resources.requests.tcpdump.cpu / memory** | String | Requests for tcpdump sidecar (if enabled) |
| **terminationGracePeriodSeconds** | Integer | Grace period before termination (default: 5 s) |

---

### ⚙️ Security Context

| Capability | Purpose |
|-------------|----------|
| `NET_ADMIN` | Required for interface configuration |
| `NET_RAW` | Required for packet capture (tcpdump) |
| `SYS_NICE` | Allows priority control of real-time threads |

> All other capabilities are dropped for security.

---

### 🧭 Scheduling and Placement

| Parameter | Type | Description |
|------------|------|-------------|
| **tolerations** | List | Node tolerations |
| **affinity** | Map | Pod affinity/anti-affinity |
| **nodeSelector** | Map | Node label selector |
| **nodeName** | String | Explicit node name binding |

---

## 🚀 Deployment Guide

### 0️⃣ Prerequisites

Ensure the **OAI 5G Core** and **gNB** are already running.

- [OAI 5G Core Basic](../../oai-5g-basic/README.md)
- [OAI 5G Core Mini](../../oai-5g-mini/README.md)

The NR-UE connects via:
- RF Simulator → using `config.rfSimServer`
- Physical setup → via Ethernet or USB-attached USRP

---

### 1️⃣ Configure and Deploy NR-UE

Edit `values.yaml` as needed (mainly `config.rfSimServer` and subscriber details), then deploy:

```bash
helm install oai-nr-ue .
```

### 2️⃣ Verify Connection

Once deployed, check logs to confirm UE attachment to the gNB and AMF.

To verify IP connectivity:

```bash
kubectl exec -it <oai-nr-ue-pod> -- bash
# Ping UPF or external target
ping -I oaitun_ue1 12.1.1.1
ping -I oaitun_ue1 8.8.8.8
```

## 📝 Notes and Recommendations

1. **Subscriber Database**: Ensure fullImsi, fullKey, and opc match the AMF/UDR subscriber entries.

2. **RF Simulation Mode**: In rfsim mode, NR-UE and gNB must resolve each other’s hostnames (usually via Kubernetes service names).

3. **Hardware Mode**: For physical USRPs (B2xx/N3xx/X3xx), ensure the host provides correct USB or network pass through.
