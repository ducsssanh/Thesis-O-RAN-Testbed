#!/usr/bin/env python3
"""Incremental four-release deployment. All Kubernetes writes target oai-lab."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import select
import secrets
import socket
import tarfile
import subprocess
import sys
import tempfile
import threading
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/k8s"
STATE = ROOT / "artifacts/k8s"
CTX = "oai-lab"
OLD = "oai-lab"
ROLES = {"core": "oai-core", "ran": "oai-ran", "near-rt": "near-rt-ric", "nonrt": "non-rt-ric"}
CORE_NFS = ["nrf", "udr", "udm", "ausf", "amf", "smf", "upf"]
OLD_WORKLOADS = ["oai-nrf", "oai-udr", "oai-udm", "oai-ausf", "oai-amf", "oai-smf", "oai-upf", "oai-lab-dn", "oai-flexric", "oai-gnb", "oai-nr-ue", "oai-lab-xapp"]


class Failure(RuntimeError):
    pass


def run(args, *, input=None, timeout=180, check=True, env=None):
    p = subprocess.run([str(a) for a in args], input=input, text=True, errors="replace", capture_output=True, timeout=timeout, env=env)
    if check and p.returncode:
        raise Failure(f"{args[0]} failed: {(p.stderr or p.stdout)[-1200:]}")
    return p.stdout


def kub(ns, *args, **kw):
    return run(["kubectl", "--context=" + CTX, "-n", ns, *args], **kw)


def helm(ns, *args, **kw):
    return run(["helm", "--kube-context", CTX, "-n", ns, *args], **kw)


def values():
    c = yaml.safe_load((DEPLOY / "values/minikube.yaml").read_text())["global"]["lab"]
    if c["profile"] != CTX or c["xdpMode"] != "skb":
        raise Failure("Unexpected profile or XDP mode")
    return c


def cluster():
    try:
        return bool(kub("default", "get", "namespace", "kube-system", "-o", "name", timeout=8).strip())
    except Exception:
        return False


def resume():
    if not cluster():
        run(["minikube", "start", "-p", CTX, "--keep-context"], timeout=900)
    if not cluster():
        raise Failure("oai-lab Kubernetes API unavailable")
    print("oai-lab API ready; no Helm upgrade or bootstrap was run")


def check():
    import lab
    base=yaml.safe_load((DEPLOY/"values/minikube.yaml").read_text())
    lab.validate(base)
    lab.host_check(base)
    image_values=STATE/"state/images.yaml"
    for role,ns in ROLES.items():
        chart=DEPLOY/"charts"/(role if role in ("core","ran") else ns)
        args=["-f",DEPLOY/"values/minikube.yaml"]
        if image_values.exists():args += ["-f",image_values]
        run(["helm","lint",chart,*args],timeout=60)
        rendered=run(["helm","template",ns,chart,*args],timeout=60)
        docs=[x for x in yaml.safe_load_all(rendered) if x]
        if not docs:raise Failure("Empty chart: "+role)
        if cluster():
            kub(ns,"apply","--dry-run=server","-f","-",input=rendered,timeout=60)
        print(role+": "+str(len(docs))+" resources render/validate")


def namespace(name):
    label = {"pod-security.kubernetes.io/enforce": "privileged"} if name == "oai-core" else {}
    manifest = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name, "labels": label}}
    run(["kubectl", "--context=" + CTX, "apply", "-f", "-"], input=json.dumps(manifest))


def secret(ns, name, fields):
    manifest = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": ns}, "type": "Opaque", "data": {k: base64.b64encode(v if isinstance(v, bytes) else v.encode()).decode() for k, v in fields.items()}}
    kub(ns, "apply", "-f", "-", input=json.dumps(manifest))


def raw_secret(ns, name):
    data = json.loads(kub(ns, "get", "secret", name, "-o", "json"))["data"]
    return {k: base64.b64decode(v) for k, v in data.items()}


def credentials():
    c = values()
    old = raw_secret(OLD, c["secretName"])
    for key in ("IMSI", "KEY", "OPC"):
        if key not in old:
            raise Failure("Legacy UE secret is missing " + key)
    for ns in ROLES.values():
        namespace(ns)
    existing = kub("oai-core", "get", "secret", c["secretName"], "--ignore-not-found", "-o", "name")
    passwords = {k: v.decode() for k, v in raw_secret("oai-core", c["secretName"]).items() if k in ("DB_PASSWORD", "DB_ROOT_PASSWORD")} if existing else {"DB_PASSWORD": secrets.token_hex(24), "DB_ROOT_PASSWORD": secrets.token_hex(24)}
    imsi = old["IMSI"].decode()
    for ns in ROLES.values():
        fields = {"SUPI": "imsi-" + imsi}
        if ns in ("oai-core", "oai-ran"):
            fields.update({k: old[k].decode() for k in ("IMSI", "KEY", "OPC")})
        if ns == "oai-core":
            fields.update(passwords)
        secret(ns, c["secretName"], fields)


def prepare():
    resume()
    credentials()
    for role,ns in ROLES.items():
        if helm(ns,"status",ns,"-o","json",check=False).strip():
            continue
        release(role, ["replicas=0"] if role in ("core","ran","near-rt") else [])
    print("Four new releases installed at zero replicas; legacy pods remain running")


def openssl(*args, env=None):
    p = subprocess.run(["openssl", *map(str, args)], capture_output=True, text=True, env=env)
    if p.returncode:
        raise Failure("openssl failed: " + p.stderr[-600:])


def certs():
    resume()
    for ns in ROLES.values():
        namespace(ns)
    with tempfile.TemporaryDirectory(prefix="oai-lab-certs-") as temp:
        d = Path(temp)
        ca = d / "ca.crt"
        ca_key = d / "ca.key"
        old = kub("oai-core", "get", "secret", "oai-lab-ca-private", "--ignore-not-found", "-o", "name")
        if old:
            data = raw_secret("oai-core", "oai-lab-ca-private")
            ca.write_bytes(data["ca.crt"])
            ca_key.write_bytes(data["ca.key"])
        else:
            openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-subj", "/CN=OAI Lab CA", "-keyout", ca_key, "-out", ca)
            secret("oai-core", "oai-lab-ca-private", {"ca.crt": ca.read_bytes(), "ca.key": ca_key.read_bytes()})
        for ns in ROLES.values():
            secret(ns, "oai-lab-ca", {"ca.crt": ca.read_bytes()})
        for ns, service, name in [("non-rt-ric", "informationservice", "informationservice-tls"), ("non-rt-ric", "urr-ei-producer", "urr-ei-producer-tls"), ("near-rt-ric", "a1-ei-adapter", "a1-ei-adapter-tls"), ("near-rt-ric", "oai-lab-xapp", "oai-lab-xapp-tls")]:
            existing = kub(ns, "get", "secret", name, "--ignore-not-found", "-o", "name")
            if existing:
                continue
            hostname = f"{service}.{ns}.svc.cluster.local"
            key, csr, crt = d / (service + ".key"), d / (service + ".csr"), d / (service + ".crt")
            ext = d / (service + ".ext")
            ext.write_text(f"subjectAltName=DNS:{hostname},DNS:{service}.{ns}.svc,DNS:{service}\nextendedKeyUsage=serverAuth\n")
            openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=" + hostname, "-keyout", key, "-out", csr)
            openssl("x509", "-req", "-in", csr, "-CA", ca, "-CAkey", ca_key, "-CAcreateserial", "-days", "365", "-extfile", ext, "-out", crt)
            fields = {"tls.crt": crt.read_bytes(), "tls.key": key.read_bytes()}
            if service == "informationservice":
                password = secrets.token_urlsafe(24)
                env = {**os.environ, "LAB_STORE_PASS": password}
                p12 = d / "ics.p12"
                openssl("pkcs12", "-export", "-in", crt, "-inkey", key, "-certfile", ca, "-name", service, "-out", p12, "-passout", "env:LAB_STORE_PASS", env=env)
                jks = d / "keystore.jks"
                run(["keytool", "-importkeystore", "-noprompt", "-srckeystore", p12, "-srcstoretype", "PKCS12", "-srcstorepass:env", "LAB_STORE_PASS", "-destkeystore", jks, "-deststoretype", "JKS", "-deststorepass:env", "LAB_STORE_PASS"], timeout=60, env=env)
                trust = d / "truststore.jks"
                run(["keytool", "-importcert", "-noprompt", "-alias", "oai-lab-ca", "-file", ca, "-keystore", trust, "-storepass:env", "LAB_STORE_PASS"], timeout=60, env=env)
                fields.update({"keystore.jks": jks.read_bytes(), "truststore.jks": trust.read_bytes(), "store-password": password})
            secret(ns, name, fields)
    print("Lab CA and HTTPS Secrets are ready")


def old_active():
    pods = json.loads(kub(OLD, "get", "pods", "-o", "json"))["items"]
    return [p["metadata"]["name"] for p in pods if p["metadata"].get("labels", {}).get("oai-lab/component") in {"nrf", "udr", "udm", "ausf", "amf", "smf", "upf", "dn", "flexric", "gnb", "nr-ue", "xapp"} and p.get("status", {}).get("phase") not in ("Succeeded", "Failed")]


def guard():
    active = old_active()
    if active:
        raise Failure("Legacy pods still hold lab network/IPs: " + ", ".join(active[:8]) + "; run cutover first")


def snapshot():
    target = STATE / "state/pre-cutover.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    d = json.loads(kub(OLD, "get", "deployments,statefulsets,pods,pvc", "-o", "json"))
    selected = [{"kind": x["kind"], "name": x["metadata"]["name"], "replicas": x.get("spec", {}).get("replicas"), "image": [c["image"] for c in x.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])]} for x in d["items"]]
    target.write_text(json.dumps({"capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "resources": selected}, indent=2) + "\n")
    (STATE / "state/legacy-helm-values.yaml").write_text(helm(OLD, "get", "values", OLD, "-o", "yaml"))


def cutover():
    prepare()
    snapshot()
    live = {x["metadata"]["name"] for x in json.loads(kub(OLD, "get", "deployments", "-o", "json"))["items"]}
    for name in OLD_WORKLOADS:
        if name in live:
            kub(OLD, "scale", "deployment/" + name, "--replicas=0")
    kub(OLD, "scale", "statefulset/oai-lab-db", "--replicas=0")
    deadline = time.monotonic() + 180
    while old_active():
        if time.monotonic() > deadline:
            raise Failure("Legacy pods did not exit; cutover stopped")
        time.sleep(3)
    print("Legacy telecom pods stopped; Helm release, Secrets and PVCs retained")


def release(role, sets=()):
    ns = ROLES[role]
    chart = DEPLOY / "charts" / (role if role in ("core", "ran") else ns)
    args = ["upgrade", "--install", ns, chart, "-f", DEPLOY / "values/minikube.yaml"]
    images = STATE / "state/images.yaml"
    if images.exists():
        args.extend(["-f", images])
    for setting in sets:
        args.extend(["--set", setting])
        if setting.startswith("replicas="):
            args.extend(["--set", "global.lab." + setting])
    args.extend(["--timeout", "5m"])
    helm(ns, *args, timeout=360)


def ready(ns, kind, name, timeout=180):
    kub(ns, "rollout", "status", kind + "/" + name, "--timeout=" + str(timeout) + "s", timeout=timeout+20)


def is_ready(ns,kind,name):
    try:
        obj=json.loads(kub(ns,"get",kind+"/"+name,"-o","json",timeout=12))
        return obj["spec"].get("replicas",0)==1 and obj.get("status",{}).get("readyReplicas",0)>=1
    except Failure:return False


def release_values(ns):
    raw=helm(ns,"get","values",ns,"-o","json",check=False)
    try:return json.loads(raw)
    except ValueError:return {}


def current_pod_uid(ns,component):
    pods=json.loads(kub(ns,"get","pods","-l","oai-lab/component="+component,"-o","json"))["items"]
    return next((p["metadata"]["uid"] for p in pods if p.get("status",{}).get("phase")=="Running"),None)


def require_secrets(ns, names):
    for name in names:
        kub(ns, "get", "secret", name, "-o", "name")


def core():
    resume(); guard(); require_secrets("oai-core", [values()["secretName"], "oai-lab-ca"])
    gate_path=STATE/"core/staged-core-gate.json"
    prior=json.loads(gate_path.read_text()) if gate_path.exists() else {}
    if prior.get("runId")==run_id() and prior.get("podUIDs")=={"smf":current_pod_uid("oai-core","smf"),"upf":current_pod_uid("oai-core","upf")} and all(is_ready("oai-core","deployment","oai-"+nf) for nf in CORE_NFS):
        print("Core already passed and all NFs remain Ready; no Helm upgrade")
        return
    for name in ("smf","upf","tools"):
        lock=STATE/"state/images.json"
        if lock.exists():
            image=json.loads(lock.read_text())["images"][name]["image"]
            ensure_image(image)
    current=release_values("oai-core")
    enabled=[nf for nf in CORE_NFS if current.get("oai-"+nf,{}).get("enabled")]
    base=["replicas=1", "seedEnabled="+str(bool(current.get("seedEnabled"))).lower(), *["oai-"+n+".enabled=true" for n in enabled]]
    if not is_ready("oai-core","statefulset","oai-lab-db") or not is_ready("oai-core","deployment","oai-lab-dn"):
        release("core", base)
    ready("oai-core", "statefulset", "oai-lab-db"); ready("oai-core", "deployment", "oai-lab-dn")
    if not current.get("seedEnabled"):
        release("core", ["replicas=1", "seedEnabled=true", *["oai-"+n+".enabled=true" for n in enabled]])
    kub("oai-core", "wait", "--for=condition=complete", "job/oai-lab-subscriber", "--timeout=180s", timeout=200)
    for nf in CORE_NFS:
        if nf not in enabled:
            enabled.append(nf)
            release("core", ["replicas=1", "seedEnabled=true", *["oai-"+n+".enabled=true" for n in enabled]])
        ready("oai-core", "deployment", "oai-"+nf)
        if nf=="smf":start_capture()
    if prior.get("podUIDs")!={"smf":current_pod_uid("oai-core","smf"),"upf":current_pod_uid("oai-core","upf")}:
        # If UPF was already running before capture, reattach it once so the
        # new PCAP contains an Association Response for the current run.
        current_pcap="/artifacts/runs/"+run_id()+"/pfcp.pcap"
        assoc=exec_pod("oai-core","oai-smf","capture","tshark","-r",current_pcap,"-Y","pfcp.msg_type == 6 && pfcp.cause == 1","-T","fields","-e","pfcp.seqno",timeout=30)
        if not assoc.strip():
            restart_upf()
    core_gate()
    print("Core integration gate PASS")


def run_id():
    target=STATE/"state/current-staged-run"
    if target.exists():return target.read_text().strip()
    value=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-m35"
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(value+"\n")
    return value


def new_run():
    resume()
    if is_ready("oai-ran","deployment","oai-nr-ue"):
        raise Failure("Stop the UE before starting a new capture run")
    state=STATE/"state/current-staged-run"
    if state.exists():
        previous=state.read_text().strip()
        if previous:
            old="/artifacts/runs/"+previous
            exec_pod("oai-core","oai-lab-dn","dn","touch",old+"/capture.stop")
            poll("previous PFCP capture flush",lambda:exec_pod("oai-core","oai-lab-dn","dn","test","-f",old+"/capture.done",timeout=10)=="",30)
    new=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-m35"
    if state.exists() and state.read_text().strip()==new:
        raise Failure("Run ID already exists; retry after one second")
    state.parent.mkdir(parents=True,exist_ok=True)
    state.write_text(new+"\n")
    print("New staged run: "+new)


def exec_pod(ns,deployment,container,*command,timeout=180):
    return kub(ns,"exec","deployment/"+deployment,"-c",container,"--",*command,timeout=timeout)


def poll(description,fn,seconds=120):
    deadline=time.monotonic()+seconds;last=""
    while time.monotonic()<deadline:
        try:
            result=fn()
            if result:return result
        except (Failure,ValueError,KeyError) as err:last=str(err)
        time.sleep(3)
    raise Failure(description+" timed out. "+last[-300:])


def capture_closed(current):
    stopped="/artifacts/runs/"+current+"/capture.stop"
    return exec_pod("oai-core","oai-lab-dn","dn","sh","-c","if test -e \"$1\"; then echo yes; else echo no; fi","sh",stopped,timeout=10).strip()=="yes"


def start_capture():
    current=run_id()
    if capture_closed(current):
        raise Failure("PFCP capture for run "+current+" is already closed. Stop UE, run 'scripts/k8s/lab.sh new-run', then 'scripts/k8s/lab.sh up --stage ran' before experiment")
    code="import json,pathlib; p=pathlib.Path('/artifacts'); (p/'runs'/"+repr(current)+").mkdir(parents=True,exist_ok=True); (p/'request.tmp').write_text(json.dumps({'run_id':"+repr(current)+"})); (p/'request.tmp').replace(p/'capture-request.json')"
    exec_pod("oai-core","oai-lab-dn","dn","python3","-c",code)
    readyfile="/artifacts/runs/"+current+"/capture.ready"
    poll("PFCP capture ready",lambda:exec_pod("oai-core","oai-lab-dn","dn","test","-f",readyfile,timeout=10)=="",60)


def core_gate():
    current=run_id();pcap="/artifacts/runs/"+current+"/pfcp.pcap"
    def pfcp():
        raw=exec_pod("oai-core","oai-smf","capture","tshark","-r",pcap,"-Y","pfcp","-T","fields","-e","pfcp.msg_type","-e","pfcp.seqno","-e","pfcp.cause","-e","ip.src",timeout=30)
        rows=[]
        for line in raw.splitlines():
            parts=line.split("\t")
            if len(parts)>3 and parts[0].isdigit() and parts[1].isdigit():rows.append((int(parts[0]),int(parts[1]),int(parts[2]) if parts[2].isdigit() else None,parts[3]))
        assoc=[r for r in rows if r[0]==6 and r[2]==1]
        hb=len({r[1] for r in rows if r[0]==1}&{r[1] for r in rows if r[0]==2})
        upf_ip=values()["networks"]["n4"]["addresses"]["upf"]
        upf_hb=len({r[1] for r in rows if r[0]==1 and r[3]==upf_ip}&{r[1] for r in rows if r[0]==2 and r[3]!=upf_ip})
        return {"association":assoc[-1][1],"heartbeats":hb,"upfInitiatedHeartbeats":upf_hb} if assoc and hb>=2 and upf_hb>=1 else None
    pfcp_state=poll("PFCP association, two heartbeats and one UPF-initiated heartbeat",pfcp,120)
    nrf={}
    for nf in ("UDR","UDM","AUSF","AMF","SMF","UPF"):
        def registered():
            response=json.loads(exec_pod("oai-core","oai-lab-dn","dn","curl","-fsS","http://oai-nrf/nnrf-disc/v1/nf-instances?target-nf-type="+nf+"&requester-nf-type=SMF",timeout=15))
            return [x for x in response.get("nfInstances",[]) if x.get("nfStatus")=="REGISTERED"] or None
        nrf[nf]=len(poll(nf+" NRF registration",registered,90))
    raw=exec_pod("oai-core","oai-upf","upf","/openair-upf/bin/bpftool","-j","net")
    data=json.loads(raw);records=data if isinstance(data,list) else [data]
    xdp=[x for group in records for x in group.get("xdp",[])]
    ids={iface:next((x.get("id") for x in xdp if x.get("devname")==iface and x.get("mode")=="generic" and x.get("id",0)>0),None) for iface in ("n3","n6")}
    if any(x is None for x in ids.values()):raise Failure("XDP-SKB is missing from N3/N6")
    log=kub("oai-core","logs","deployment/oai-smf","-c","smf","--tail=2000")
    if re.search(r"PFCP IE TLV 43|pfcp_tlv_bad_length|uncaught",log,re.I):raise Failure("SMF PFCP decoder error")
    route=json.loads(exec_pod("oai-core","oai-lab-dn","dn","ip","-j","route","show"))
    c=values();if_route=any(x.get("dst")==c["ueSubnet"] and x.get("gateway")==c["networks"]["n6"]["addresses"]["upf"] for x in route)
    if not if_route:raise Failure("DN route to UE via UPF N6 missing")
    evidence={"status":"PASS","runId":current,"pfcp":pfcp_state,"nrf":nrf,"xdpProgramIds":ids,"dnReturnRoute":True,"podUIDs":{"smf":current_pod_uid("oai-core","smf"),"upf":current_pod_uid("oai-core","upf")}}
    target=STATE/"core/staged-core-gate.json";target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(evidence,indent=2)+"\n")


def ensure_image(image):
    if image.endswith(":unbuilt"):
        raise Failure("Image has not been built: " + image)
    tags = run(["minikube", "-p", CTX, "image", "ls"], timeout=60)
    if image in tags:
        return
    local = run(["docker", "image", "inspect", image], check=False)
    if not local:
        if "@sha256:" in image:
            run(["minikube", "-p", CTX, "image", "pull", image], timeout=900)
            return
        raise Failure("Image missing from both host Docker and minikube: " + image)
    run(["minikube", "-p", CTX, "image", "load", image], timeout=600)


def nonrt():
    resume(); require_secrets("non-rt-ric", [values()["secretName"], "oai-lab-ca", "informationservice-tls", "urr-ei-producer-tls"])
    if is_ready("non-rt-ric","statefulset","informationservice") and is_ready("non-rt-ric","deployment","urr-ei-producer"):
        print("Non-RT RIC already Ready; no Helm upgrade")
        return
    v = yaml.safe_load((DEPLOY / "charts/non-rt-ric/values.yaml").read_text())
    image = v["ics"]["image"]
    if not is_ready("non-rt-ric", "statefulset", "informationservice"):
        ensure_image(image)
    lock = STATE / "state/ei-images.json"
    if not lock.exists(): raise Failure("Run build-ei first")
    producer = json.loads(lock.read_text())["producer"]["image"]
    if not is_ready("non-rt-ric","statefulset","informationservice"):
        release("nonrt", ["ics.replicas=1", "producer.replicas="+str(release_values("non-rt-ric").get("producer",{}).get("replicas",0)), "producer.image="+producer])
    ready("non-rt-ric", "statefulset", "informationservice", 240)
    ensure_image(producer)
    release("nonrt", ["ics.replicas=1", "producer.replicas=1", "producer.image="+producer])
    ready("non-rt-ric", "deployment", "urr-ei-producer")


def near_rt():
    resume(); guard(); require_secrets("near-rt-ric", [values()["secretName"], "oai-lab-ca", "a1-ei-adapter-tls", "oai-lab-xapp-tls"])
    if is_ready("near-rt-ric","deployment","oai-flexric") and is_ready("near-rt-ric","deployment","a1-ei-adapter"):
        print("Near-RT RIC already Ready; no Helm upgrade")
        return
    lock = STATE / "state/ei-images.json"
    if not lock.exists(): raise Failure("Run build-ei first")
    adapter = json.loads(lock.read_text())["adapter"]["image"]
    image_lock = STATE / "state/images.json"
    if image_lock.exists():
        ensure_image(json.loads(image_lock.read_text())["images"]["radio"]["image"])
    ensure_image(adapter)
    previous=release_values("near-rt-ric")
    if not is_ready("near-rt-ric","deployment","oai-flexric"):
        release("near-rt", ["replicas=1", "oai-flexric.enabled=true", "adapter.replicas="+str(previous.get("adapter",{}).get("replicas",0)), "adapter.image="+adapter, "adapter.xappPushEnabled="+str(bool(previous.get("adapter",{}).get("xappPushEnabled"))).lower(), "xappEnabled="+str(bool(previous.get("xappEnabled"))).lower(), "xappImage="+str(previous.get("xappImage", "")), "global.lab.currentRun="+str(previous.get("global",{}).get("lab",{}).get("currentRun","bootstrap"))])
    ready("near-rt-ric", "deployment", "oai-flexric")
    release("near-rt", ["replicas=1", "oai-flexric.enabled=true", "adapter.replicas=1", "adapter.image="+adapter, "adapter.xappPushEnabled="+str(bool(previous.get("adapter",{}).get("xappPushEnabled"))).lower(), "xappEnabled="+str(bool(previous.get("xappEnabled"))).lower(), "xappImage="+str(previous.get("xappImage", "")), "global.lab.currentRun="+str(previous.get("global",{}).get("lab",{}).get("currentRun","bootstrap"))])
    ready("near-rt-ric", "deployment", "a1-ei-adapter")


class Forward:
    def __init__(self, ns, service, remote):
        self.ns, self.service, self.remote = ns, service, remote
        self.process = None
        self.local = None

    def __enter__(self):
        self.process = subprocess.Popen(
            ["kubectl", "--context="+CTX, "-n", self.ns, "port-forward", "--address", "127.0.0.1", "service/"+self.service, ":"+str(self.remote)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            readable,_,_=select.select([self.process.stdout],[],[],1)
            if readable:
                line=self.process.stdout.readline()
                match=re.search(r"Forwarding from 127\.0\.0\.1:(\d+)",line)
                if match:
                    self.local=int(match.group(1));return self
            if self.process.poll() is not None:
                break
        self.__exit__(None,None,None)
        raise Failure("port-forward failed for "+self.ns+"/"+self.service)

    def __exit__(self,*_):
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:self.process.kill()


def https_json(forward, path, ca, method="GET", body=None):
    host=f"{forward.service}.{forward.ns}.svc.cluster.local"
    cmd=["curl","--silent","--show-error","--fail-with-body","--noproxy","*","--max-time","15","--cacert",str(ca),"--connect-to",f"{host}:{forward.remote}:127.0.0.1:{forward.local}","-X",method]
    if body is not None:
        cmd += ["-H","Content-Type: application/json","--data-binary","@-"]
    cmd += [f"https://{host}:{forward.remote}{path}"]
    raw=run(cmd,input=json.dumps(body) if body is not None else None,timeout=20)
    return json.loads(raw) if raw.strip() else {}


def urr_key(report):
    """(SEID, session epoch, UR-SEQN); the epoch is empty for producer schema 1.0.0."""
    return (int(report["seid"]),str(report.get("session_epoch","")),int(report["ur_seqn"]))


def fresh_real_urr(reports, now=None, max_age_seconds=300):
    now=now or dt.datetime.now(dt.timezone.utc)
    fresh=[]
    for report in reports if isinstance(reports,list) else []:
        try:
            if int(report.get("ur_seqn",-1))==999999999:continue
            if int(report.get("ul_bytes",0) or 0)+int(report.get("dl_bytes",0) or 0)<=0:continue
            observed=dt.datetime.fromisoformat(str(report["observed_at"]).replace("Z","+00:00"))
            if observed.tzinfo is None:observed=observed.replace(tzinfo=dt.timezone.utc)
        except (AttributeError,KeyError,TypeError,ValueError):
            continue
        age=(now-observed.astimezone(dt.timezone.utc)).total_seconds()
        if -60<=age<=max_age_seconds:fresh.append((observed,report))
    return max(fresh,key=lambda item:item[0])[1] if fresh else None


def gate_ei(real=False):
    resume()
    with tempfile.TemporaryDirectory(prefix="oai-lab-ca-") as d:
        ca=Path(d)/"ca.crt";ca.write_bytes(raw_secret("oai-core","oai-lab-ca")["ca.crt"])
        with Forward("non-rt-ric","informationservice",9083) as ics, Forward("non-rt-ric","urr-ei-producer",8443) as producer, Forward("near-rt-ric","a1-ei-adapter",8443) as adapter:
            status=https_json(ics,"/status",ca)
            if status.get("status") is None:raise Failure("ICS /status lacks status")
            https_json(ics,"/data-producer/v1/info-types/oai-urr_1.0.0",ca)
            operational=https_json(ics,"/data-producer/v1/info-producers/oai-urr-producer/status",ca)
            if operational.get("operational_state")!="ENABLED":raise Failure("Producer is not ENABLED")
            job=https_json(ics,"/A1-EI/v1/eijobs/oai-urr-nearrt-ue1/status",ca)
            if job.get("eiJobStatus")!="ENABLED":raise Failure("A1-EI job is not ENABLED")
            https_json(producer,"/readyz",ca)
            https_json(adapter,"/readyz",ca)
            if real:
                reports=https_json(adapter,"/v1/urr",ca)
                if not isinstance(reports,list):raise Failure("Adapter /v1/urr did not return a report list")
                latest=fresh_real_urr(reports)
                if latest is None:raise Failure("No real usage report with UL/DL bytes received by the adapter in the last 5 minutes")
                evidence={"mode":"real","status":"PASS","report":latest,"job":job}
            else:
                supi=raw_secret("oai-core",values()["secretName"])["SUPI"].decode()
                seid=10**15+int(time.time())
                fixture={"notifId":"oai-urr-producer","eventNotifs":[{"event":"QOS_MON","timeStamp":str(int(time.time())+2208988800),"supi":supi,"pduSeId":1,"customized_data":{"event":"QOS_MON","Usage Report":{"SEID":seid,"UR-SEQN":999999999,"Trigger":"Volume Threshold","Duration":120,"NoP":{"Total":2,"Uplink":1,"Downlink":1},"Volume":{"Total":200,"Uplink":100,"Downlink":100}}}}]}
                https_json(producer,"/callbacks/smf",ca,"POST",fixture)
                https_json(producer,"/callbacks/smf",ca,"POST",fixture)
                deadline=time.monotonic()+30
                while True:
                    try:
                        latest=https_json(adapter,"/v1/urr/latest",ca)
                        if latest.get("seid")==seid:break
                    except Failure:pass
                    if time.monotonic()>deadline:raise Failure("Fixture not delivered to adapter")
                    time.sleep(2)
                evidence={"mode":"fixture","status":"PASS","report":latest,"job":job}
            target=STATE/"core/ei-gate.json";target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(evidence,indent=2)+"\n")
            print("A1-EI gate PASS ("+evidence["mode"]+")")


def gate_xapp(real=False):
    resume()
    if not real: gate_ei(False)
    with tempfile.TemporaryDirectory(prefix="oai-lab-ca-") as d:
        ca=Path(d)/"ca.crt";ca.write_bytes(raw_secret("oai-core","oai-lab-ca")["ca.crt"])
        with Forward("near-rt-ric","oai-lab-xapp",8443) as xapp, Forward("near-rt-ric","a1-ei-adapter",8443) as adapter:
            https_json(xapp,"/readyz",ca)
            target=(STATE/"core/ei-gate.json")
            if not real and not target.exists():raise Failure("Missing EI fixture evidence")
            if real:
                reports=https_json(adapter,"/v1/urr",ca)
                report=fresh_real_urr(reports)
                if report is None:raise Failure("No fresh real URR at adapter")
            else:report=json.loads(target.read_text())["report"]
            pair=urr_key(report)
            def delivered():
                status=https_json(adapter,"/v1/delivery/status",ca)
                if status.get("dead_letter",0):raise Failure("xApp delivery dead-letter is nonempty")
                path="/artifacts/runs/"+run_id()+"/urr-received.jsonl"
                raw=exec_pod("near-rt-ric","oai-lab-xapp","xapp","cat",path,timeout=10)
                matching=[]
                for line in raw.splitlines():
                    row=json.loads(line); x=row["report"]
                    if urr_key(x)==pair:
                        if any(int(x[k])!=int(report[k]) for k in ("ul_bytes","dl_bytes","total_bytes")):raise Failure("URR counters differ at xApp")
                        matching.append(row)
                if len(matching)>1:raise Failure("Duplicate URR persisted at xApp")
                return matching[0] if matching else None
            row=poll("xApp URR delivery",delivered,60)
            evidence={"status":"PASS","mode":"real" if real else "fixture","eventId":row["event_id"],"xappReceivedAt":row["received_at"],"report":row["report"]}
            out=STATE/"core/xapp-gate.json";out.write_text(json.dumps(evidence,indent=2)+"\n")
            print("xApp URR gate PASS ("+evidence["mode"]+")",flush=True)


def pfcp_peer_ready():
    """Require association and heartbeats for this UPF pod, not a prior pod."""
    pods=json.loads(kub("oai-core","get","pods","-l","oai-lab/component=upf","-o","json",timeout=10))["items"]
    live=[p for p in pods if p.get("status",{}).get("phase")=="Running" and not p["metadata"].get("deletionTimestamp")]
    if len(live)!=1:return False
    upf_started=live[0]["metadata"]["creationTimestamp"]
    upf_mac=exec_pod("oai-core","oai-upf","upf","cat","/sys/class/net/n4/address",timeout=10).strip().lower()
    arp=exec_pod("oai-core","oai-smf","smf","cat","/proc/net/arp",timeout=10)
    neighbor=next((line.split()[3].lower() for line in arp.splitlines()[1:] if line.split()[0]==values()["networks"]["n4"]["addresses"]["upf"] and line.split()[-1]=="n4"),None)
    if neighbor!=upf_mac:return False
    age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(upf_started.replace("Z","+00:00"))).total_seconds()
    recent=age>600
    log_window=["--since=60s","--tail=1200"] if recent else ["--since-time="+upf_started,"--tail=5000"]
    log=kub("oai-core","logs","deployment/oai-smf","-c","smf",*log_window,timeout=20)
    last_failure=max(log.rfind("UPF graph is empty"),log.rfind("HEARTBEAT PROCEDURE FAILED"))
    recovered=log[last_failure+1:]
    # A UPF restarted while the SMF runs re-associates on the existing graph
    # node (no "graph edge" line), so an Association Setup Response counts too
    associated=("Successfully added UPF graph edge for " in recovered) or ("ASSOCIATION SETUP RESPONSE" in recovered)
    return (recent or associated) and len(re.findall("handle_receive_pfcp_msg msg type 2",recovered))>=2


def restart_upf():
    """Restart the UPF with a cleared SMF N4 neighbor before a new UE session."""
    resume();guard()
    if is_ready("oai-ran","deployment","oai-nr-ue"):
        raise Failure("Stop the UE and wait for its pod to exit before restart-upf")
    ready("oai-core","deployment","oai-smf",30)
    exec_pod("oai-core","oai-smf","capture","ip","-V",timeout=10)
    old_uid=current_pod_uid("oai-core","upf")
    print("Stopping old UPF pod before replacing its static N4 address",flush=True)
    kub("oai-core","scale","deployment/oai-upf","--replicas=0")
    kub("oai-core","wait","--for=delete","pod","-l","oai-lab/component=upf","--timeout=120s",timeout=130)
    kub("oai-core","exec","deployment/oai-smf","-c","capture","--","ip","neigh","flush","to",values()["networks"]["n4"]["addresses"]["upf"],"dev","n4")
    print("SMF N4 neighbor cleared; starting UPF",flush=True)
    kub("oai-core","scale","deployment/oai-upf","--replicas=1")
    ready("oai-core","deployment","oai-upf",180)
    if current_pod_uid("oai-core","upf")==old_uid:raise Failure("UPF pod UID did not change")
    poll("SMF-UPF PFCP association and heartbeat",pfcp_peer_ready,90)
    print("UPF restart/PFCP gate PASS; create a new run before starting UE",flush=True)


def ran():
    resume(); guard(); require_secrets("oai-ran", [values()["secretName"]])
    require_secrets("near-rt-ric", ["oai-lab-xapp-tls"])
    current=run_id()
    if capture_closed(current):
        if is_ready("oai-ran","deployment","oai-nr-ue"):
            raise Failure("Run "+current+" has a closed PFCP capture. Scale UE to 0, run 'scripts/k8s/lab.sh new-run', then rerun this stage so capture starts before UE")
        new_run()
    try:poll("SMF-UPF PFCP association/heartbeat before UE",pfcp_peer_ready,45)
    except Failure as e:raise Failure(str(e)+". SMF may retain a stale N4 neighbor after UPF restart; stop UE and run 'scripts/k8s/lab.sh restart-upf' before this stage") from e
    def kpm():
        output=exec_pod("near-rt-ric","oai-lab-xapp","xapp","sh","-c","test -f /artifacts/runs/"+run_id()+"/KPI_Metrics.csv && wc -l < /artifacts/runs/"+run_id()+"/KPI_Metrics.csv",timeout=10)
        return int(output.strip())>1
    def e2_nodes():
        # The ss build in the pinned FlexRIC image segfaults while rendering
        # SCTP associations. Read the kernel SCTP table directly instead.
        sockets=exec_pod("near-rt-ric","oai-flexric","flexric","cat","/proc/net/sctp/assocs",timeout=15)
        address=values()["networks"]["e2"]["addresses"]
        for line in sockets.splitlines()[1:]:
            fields=line.split()
            if len(fields)>12 and fields[4]=="3" and fields[11]=="36421" and address["flexric"] in line and address["gnb"] in line:
                return True
        return False
    if all(is_ready(ns,"deployment",name) for ns,name in [("near-rt-ric","oai-flexric"),("oai-ran","oai-gnb"),("oai-ran","oai-nr-ue"),("near-rt-ric","oai-lab-xapp")]) and e2_nodes():
        try:
            if kpm():
                print("RAN/E2/KPM already passed for this run; no Helm upgrade")
                return
        except (Failure,ValueError):pass
    gate_ei()
    start_capture()
    image_lock = STATE / "state/images.json"
    if image_lock.exists():
        ensure_image(json.loads(image_lock.read_text())["images"]["radio"]["image"])
    ready("near-rt-ric","deployment","oai-flexric",120)
    if ric_wedged():
        # Restarting the RIC drops every E2 association; the gNB is restarted
        # below because e2_nodes() is then empty.
        print("FlexRIC is stuck on a pending subscription delete; restarting it",flush=True)
        kub("near-rt-ric","rollout","restart","deployment/oai-flexric")
        ready("near-rt-ric","deployment","oai-flexric",180)
    # Enabling the xApp can change the Helm release. Finish that upgrade
    # before starting gNB, so an E2 connection cannot land on an old RIC pod.
    helm("near-rt-ric","upgrade","near-rt-ric",DEPLOY/"charts/near-rt-ric","--reuse-values","--set","xappEnabled=true","--set","global.lab.currentRun="+run_id(),"--timeout","5m",timeout=360)
    ready("near-rt-ric","deployment","oai-flexric",120)
    ready("near-rt-ric","deployment","oai-lab-xapp",240)
    if not is_ready("oai-ran","deployment","oai-gnb"):
        release("ran", ["replicas=1", "oai-gnb.enabled=true", "oai-nr-ue.enabled=false"])
    elif not e2_nodes():
        kub("oai-ran","rollout","restart","deployment/oai-gnb")
    ready("oai-ran", "deployment", "oai-gnb", 240)
    poll("gNB-to-FlexRIC E2 SCTP association",e2_nodes,120)
    release("ran", ["replicas=1", "oai-gnb.enabled=true", "oai-nr-ue.enabled=true"])
    ready("oai-ran", "deployment", "oai-nr-ue", 240)
    c=values()
    def ue_ip():
        interfaces=json.loads(exec_pod("oai-ran","oai-nr-ue","nr-ue","ip","-j","address",timeout=15))
        return next((a["local"] for x in interfaces for a in x.get("addr_info",[]) if a.get("family")=="inet" and a["local"].startswith("10.1.")),None)
    ip=poll("UE PDU interface",ue_ip,180)
    ensure_ue_route(ip)
    # The KPM xApp snapshots available UEs when it subscribes. Reconnect it
    # after the UE has a PDU session to obtain per-UE samples as well as cells.
    kub("near-rt-ric","rollout","restart","deployment/oai-lab-xapp")
    ready("near-rt-ric","deployment","oai-lab-xapp",240)
    poll("E2 setup",lambda:re.search(r"(?i)E2.*setup.*(response|success)",kub("oai-ran","logs","deployment/oai-gnb","-c","gnb","--tail=-1",timeout=30)),120)
    poll("KPM samples",kpm,120)
    print("RAN/E2/KPM gate PASS; UE IP: "+ip)


def ric_wedged(log=None):
    """FlexRIC can loop forever on a subscription delete towards an E2 node
    that died (gNB restart): it logs MSG ALREADY PENDING / Pending event
    timeout repeatedly and stops serving xApps until it is restarted."""
    if log is None:
        log=kub("near-rt-ric","logs","deployment/oai-flexric","-c","flexric","--tail=200",timeout=30)
    return log.count("MSG ALREADY PENDING")>=2


def kpm_age_seconds():
    """Age of the newest KPM cell sample of the current run (None if none)."""
    path="/artifacts/runs/"+run_id()+"/KPI_Metrics_Cells.csv"
    last=exec_pod("near-rt-ric","oai-lab-xapp","xapp","sh","-c","tail -1 "+path+" 2>/dev/null | cut -d, -f2",timeout=10).strip()
    try:return time.time()-int(last)/1000
    except ValueError:return None


def ensure_ue_route(ip):
    # A UE pod restart drops this route: UL then leaves via eth0 and iperf2's
    # connected DL socket binds the pod address, so both directions look broken
    # although GTP-U reaches the UE TUN. Verify the effective route, not the table.
    c=values();dn=c["networks"]["n6"]["addresses"]["dn"]
    def via_tun():
        r=json.loads(exec_pod("oai-ran","oai-nr-ue","nr-ue","ip","-j","route","get",dn,timeout=15))
        return bool(r) and r[0].get("dev")=="oaitun_ue1" and r[0].get("prefsrc")==ip
    if via_tun():return
    exec_pod("oai-ran","oai-nr-ue","nr-ue","ip","route","replace",c["networks"]["n6"]["subnet"],"dev","oaitun_ue1","src",ip)
    if not via_tun():raise Failure("UE route to DN "+dn+" does not use oaitun_ue1/"+ip)


def export_tar(ns,deployment,container,source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    command=["kubectl","--context="+CTX,"-n",ns,"exec","deployment/"+deployment,"-c",container,"--","tar","-C",source,"-cf","-","."]
    with tempfile.TemporaryFile() as stream:
        proc=subprocess.run(command,stdout=stream,stderr=subprocess.PIPE,timeout=60)
        if proc.returncode:raise Failure("Artifact export failed: "+proc.stderr.decode(errors="replace")[-500:])
        stream.seek(0)
        with tarfile.open(fileobj=stream,mode="r:") as archive:archive.extractall(target,filter="data")


def correlate_ei(out):
    def jsonl(path):
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    import csv
    with (out/"phases.csv").open() as f:phases=list(csv.DictReader(f))
    start=min(int(x["start_unix_ms"]) for x in phases)/1000
    end=max(int(x["end_unix_ms"]) for x in phases)/1000
    def in_window(epoch):return start-15<=epoch<=end+15
    producer=jsonl(out/"producer/normalized.jsonl")
    adapter=jsonl(out/"adapter/urr.jsonl")
    raw=jsonl(out/"producer/smf-raw.jsonl")
    pcap=run(["tshark","-r",out/"pfcp.pcap","-Y","pfcp.msg_type == 56 && pfcp.ur_seqn","-T","fields","-e","frame.time_epoch","-e","pfcp.seid","-e","pfcp.ur_seqn"],timeout=45)
    pairs=set()
    for line in pcap.splitlines():
        parts=line.split("\t")
        if len(parts)<3:continue
        try:
            if in_window(float(parts[0])):pairs.add((int(parts[1],0),int(parts[2],0)))
        except ValueError:continue
    raw_pairs=set()
    for message in raw:
        for event in message.get("eventNotifs",[]):
            usage=event.get("customized_data",{}).get("Usage Report",{})
            if usage.get("SEID") is not None and usage.get("UR-SEQN") is not None:
                try:
                    if in_window(float(event["timeStamp"])-2208988800):raw_pairs.add((int(usage["SEID"]),int(usage["UR-SEQN"])))
                except (KeyError,TypeError,ValueError):continue
    def real(records):
        found={}
        for x in records:
            try:
                if int(x["ur_seqn"])==999999999:continue
                at=dt.datetime.fromisoformat(x["observed_at"].replace("Z","+00:00")).timestamp()
                if in_window(at):found[(int(x["seid"]),int(x["ur_seqn"]))]=x
            except (KeyError,TypeError,ValueError):continue
        return found
    xapp_records=jsonl(out/"urr-received.jsonl")
    xapp=real([x["report"] for x in xapp_records if x.get("xapp_run_id")==out.name])
    p,a=real(producer),real(adapter)
    matches=set(p)&set(a)&set(xapp)&raw_pairs&pairs
    counters=("ul_bytes","dl_bytes","total_bytes","ul_packets","dl_packets","total_packets")
    matches={key for key in matches if all(int(p[key][field])==int(a[key][field])==int(xapp[key][field]) for field in counters)}
    if not matches:raise Failure("No real (SEID, UR-SEQN) shared in this experiment: PFCP="+str(len(pairs))+", SMF="+str(len(raw_pairs))+", producer="+str(len(p))+", adapter="+str(len(a)))
    with (out/"KPI_Metrics.csv").open() as f:kpm=list(csv.DictReader(f))
    samples=[]
    for row in kpm:
        try:samples.append(dt.datetime.fromisoformat(row["Time (ISO 8601)"]))
        except (ValueError,KeyError):pass
    if not samples:raise Failure("KPM timestamps missing")
    overlapping=[]
    for key in matches:
        at=dt.datetime.fromisoformat(a[key]["observed_at"])
        if min(samples)<=at<=max(samples):overlapping.append(key)
    if not overlapping:raise Failure("No KPM timestamp overlaps a delivered URR")
    key=overlapping[0]
    evidence={"status":"PASS","seid":key[0],"urSeqn":key[1],"pfcp":True,"smfCallback":True,"producer":True,"a1EiAdapter":True,"xappReceived":True,"kpmWindow":{"first":min(samples).isoformat(),"last":max(samples).isoformat()},"urrObservedAt":a[key]["observed_at"]}
    (out/"ei-correlation.json").write_text(json.dumps(evidence,indent=2)+"\n")


def experiment():
    resume();guard()
    runname=run_id();out=ROOT/"artifacts/experiments"/runname;out.mkdir(parents=True,exist_ok=True)
    c=values();duration=c["experiment"]["duration"];rate=c["experiment"]["rate"];length=c["experiment"].get("length",1200)
    # Calibration sweeps (A.7) override the traffic profile per run
    rate=os.environ.get("LAB_EXPERIMENT_RATE",rate);length=int(os.environ.get("LAB_EXPERIMENT_LENGTH",length));duration=int(os.environ.get("LAB_EXPERIMENT_DURATION",duration))
    (out/"profile.json").write_text(json.dumps({"rate":rate,"udpPayloadBytes":length,"durationSeconds":duration})+"\n")
    print("Experiment "+runname+": checking workloads and PFCP capture",flush=True)
    for ns,depl in [("oai-core","oai-upf"),("oai-ran","oai-nr-ue"),("near-rt-ric","a1-ei-adapter"),("near-rt-ric","oai-lab-xapp")]:ready(ns,"deployment",depl,30)
    age=kpm_age_seconds()
    if age is None or age>30:
        raise Failure("KPM is stale ("+("no samples" if age is None else str(int(age))+" s old")+") for run "+runname+"; FlexRIC may be stuck after a gNB restart. Scale UE to 0, run 'scripts/k8s/lab.sh new-run' and 'up --stage ran' (it restarts a stuck RIC)")
    start_capture()
    print("PFCP capture ready; UE and DN traffic will run at "+rate+" for "+str(duration)+" s per direction",flush=True)
    interfaces=json.loads(exec_pod("oai-ran","oai-nr-ue","nr-ue","ip","-j","address"))
    ue=next((a["local"] for x in interfaces for a in x.get("addr_info",[]) if a.get("family")=="inet" and a["local"].startswith("10.1.")),None)
    if not ue:raise Failure("UE PDU address missing")
    dn=c["networks"]["n6"]["addresses"]["dn"]
    def link_stats(ns,deployment,container,iface):
        raw=exec_pod(ns,deployment,container,"ip","-j","-s","link","show","dev",iface)
        items=json.loads(raw)
        if not items:raise Failure("No link statistics for "+iface)
        item=items[0]
        return {"interface":iface,"ifindex":item.get("ifindex"),"rx":item.get("stats64",{}).get("rx",item.get("stats",{}).get("rx",{})),"tx":item.get("stats64",{}).get("tx",item.get("stats",{}).get("tx",{}))}
    counters_before={
        "ueTun":link_stats("oai-ran","oai-nr-ue","nr-ue","oaitun_ue1"),
        "upfN3":link_stats("oai-core","oai-upf","upf","n3"),
    }
    (out/"dataplane-counters-before.json").write_text(json.dumps(counters_before,indent=2)+"\n")
    phases=[]
    for direction,source,target,destination,port in [("ul",("oai-ran","oai-nr-ue","nr-ue"),("oai-core","oai-lab-dn","dn"),dn,5001),("dl",("oai-core","oai-lab-dn","dn"),("oai-ran","oai-nr-ue","nr-ue"),ue,5002)]:
        ensure_ue_route(ue)
        print(direction.upper()+" started: "+source[1]+" → "+target[1]+" (receiver result pending)",flush=True)
        # iperf2's UDP -1 server can print its final CSV row yet stay alive.
        # Bound the receiver and accept timeout(1)'s 124 only when a positive
        # receiver CSV row was actually captured.
        receiver_cmd=["kubectl","--context="+CTX,"-n",target[0],"exec","deployment/"+target[1],"-c",target[2],"--","timeout",str(duration+10),"iperf","-s","-u","-1","-p",str(port),"-y","C"]
        receiver=subprocess.Popen(receiver_cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        time.sleep(1)
        if receiver.poll() is not None:
            output=receiver.communicate()[0]
            raise Failure(direction+" iperf receiver exited before traffic: "+output[-600:])
        start=int(time.time()*1000)
        try:
            # Keep inner IPv4/UDP plus N3 GTP-U encapsulation below MTU 1500.
            finished=threading.Event()
            def progress():
                elapsed=0
                while not finished.wait(15):
                    elapsed+=15
                    print(direction.upper()+" client running: "+str(elapsed)+" s elapsed; receiver not yet validated",flush=True)
            ticker=threading.Thread(target=progress,daemon=True);ticker.start()
            try:client=exec_pod(*source,"iperf","-c",destination,"-u","-b",rate,"-l",str(length),"-t",str(duration),"-p",str(port),"-y","C",timeout=duration+40)
            finally:finished.set();ticker.join(timeout=1)
            try:
                server,_=receiver.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                receiver.terminate()
                try:server,_=receiver.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    receiver.kill();server,_=receiver.communicate()
                raise Failure(direction+" iperf receiver got no completed report within 25s; output: "+server[-600:])
        except Exception:
            if receiver.poll() is None:
                receiver.terminate()
                try:receiver.wait(timeout=5)
                except subprocess.TimeoutExpired:receiver.kill();receiver.wait()
            raise
        if receiver.returncode not in (0,124):
            raise Failure(direction+" iperf receiver failed (exit "+str(receiver.returncode)+"): "+server[-600:])
        import csv
        rows=[r for r in csv.reader(server.splitlines()) if len(r)>=13 and r[7].isdigit() and int(r[7])>0]
        if not rows:raise Failure("No positive "+direction+" receiver report")
        (out/(direction+"-sender.csv")).write_text(client)
        with (out/(direction+"-receiver.csv")).open("w",newline="") as f:csv.writer(f).writerows(rows)
        row=max(rows,key=lambda r:int(r[7]));summary={"bytes":int(row[7]),"lostPercent":float(row[12])}
        (out/(direction+"-summary.json")).write_text(json.dumps(summary,indent=2)+"\n")
        if summary["lostPercent"]>=100:raise Failure(direction+" packet loss is 100%")
        print(direction.upper()+" receiver: "+str(summary["bytes"])+" bytes, "+str(summary["lostPercent"])+"% loss",flush=True)
        phases.append([direction,direction,rate,duration,start,int(time.time()*1000),"ok"])
    counters_after={
        "ueTun":link_stats("oai-ran","oai-nr-ue","nr-ue","oaitun_ue1"),
        "upfN3":link_stats("oai-core","oai-upf","upf","n3"),
    }
    (out/"dataplane-counters-after.json").write_text(json.dumps(counters_after,indent=2)+"\n")
    import csv
    with (out/"phases.csv").open("w",newline="") as f:
        writer=csv.writer(f);writer.writerow(["phase","direction","offered_rate","duration_seconds","start_unix_ms","end_unix_ms","status"]);writer.writerows(phases)
    time.sleep(5)
    print("UL/DL complete; flushing PFCP capture and exporting artifacts",flush=True)
    exec_pod("oai-core","oai-lab-dn","dn","touch","/artifacts/runs/"+runname+"/capture.stop")
    poll("PFCP capture flush",lambda:exec_pod("oai-core","oai-lab-dn","dn","test","-f","/artifacts/runs/"+runname+"/capture.done",timeout=10)=="",30)
    export_tar("oai-core","oai-lab-dn","dn","/artifacts/runs/"+runname,out)
    export_tar("near-rt-ric","oai-lab-xapp","xapp","/artifacts/runs/"+runname,out)
    export_tar("non-rt-ric","urr-ei-producer","artifacts","/var/lib/urr-ei",out/"producer")
    export_tar("near-rt-ric","a1-ei-adapter","artifacts","/var/lib/a1-ei",out/"adapter")
    xdp=json.loads(exec_pod("oai-core","oai-upf","upf","/openair-upf/bin/bpftool","-j","net"))
    (out/"xdp.json").write_text(json.dumps(xdp,indent=2)+"\n")
    xapp_lock=STATE/"state/xapp-image.json"
    metadata={"backend":"kubernetes-staged","context":CTX,"runId":runname,"xdpMode":"skb","valuesSha256":hashlib.sha256((DEPLOY/"values/minikube.yaml").read_bytes()).hexdigest(),"images":json.loads((STATE/"state/images.json").read_text()),"eiImages":json.loads((STATE/"state/ei-images.json").read_text()),"xappImage":json.loads(xapp_lock.read_text()) if xapp_lock.exists() else None}
    (out/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
    print("Artifacts exported; checking PFCP, XDP and KPM",flush=True)
    run([sys.executable,ROOT/"scripts/k8s/analyze.py",out],timeout=90)
    print("PFCP/XDP/KPM gate PASS; checking real A1-EI delivery and correlation",flush=True)
    gate_ei(real=True)
    gate_xapp(real=True)
    correlate_ei(out)
    print("One traffic run PASS; UPF restart and lifecycle rerun remain separate acceptance gates")


def build_ei():
    lock={}
    for name,folder in [("producer","urr-producer"),("adapter","a1-ei-adapter")]:
        path=ROOT/"src"/folder
        digest=hashlib.sha256(b"".join(p.read_bytes() for p in sorted(path.rglob("*.go")))).hexdigest()[:16]
        image="oai-lab-"+("urr-ei-producer" if name=="producer" else "a1-ei-adapter")+":"+digest
        run(["docker","build","-t",image,path],timeout=1800)
        info=json.loads(run(["docker","image","inspect",image]))[0]
        lock[name]={"image":image,"id":info["Id"]}
        target=STATE/"state/ei-images.json";target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(lock,indent=2)+"\n")
        print("Built "+image)


def build_xapp():
    sources=[p for p in sorted((ROOT/"src/flexric").rglob("*")) if p.is_file() and not any(x in p.parts for x in ("build",".git"))]
    sources.append(DEPLOY/"images/Dockerfile.radio")
    digest=hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest()[:16]
    image="oai-lab-xapp:"+digest
    cmd=["docker","build","--progress=plain","-f",str(DEPLOY/"images/Dockerfile.radio"),"--target","xapp","-t",image,str(ROOT)]
    with subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as process:
        for line in process.stdout:print(line,end="",flush=True)
        if process.wait()!=0:raise Failure("xApp Docker build failed")
    info=json.loads(run(["docker","image","inspect",image]))[0]
    target=STATE/"state/xapp-image.json";target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({"image":image,"id":info["Id"],"sourceHash":digest},indent=2)+"\n")
    print("Built "+image)


def rollout(component, image):
    mapping={"upf":("core","oai-upf","global.lab.workloads.upf.image"),"smf":("core","oai-smf","global.lab.workloads.smf.image"),"producer":("nonrt","urr-ei-producer","producer.image"),"adapter":("near-rt","a1-ei-adapter","adapter.image"),"xapp":("near-rt","oai-lab-xapp","xappImage")}
    if component not in mapping: raise Failure("Component must be upf, smf, producer, adapter or xapp")
    role,deployment,key=mapping[component];ns=ROLES[role]
    if component=="xapp":
        require_secrets(ns,["oai-lab-xapp-tls"])
        lock=STATE/"state/xapp-image.json"
        if not lock.exists() or json.loads(lock.read_text())["image"]!=image:raise Failure("Image is not the locked build-xapp result")
    if component=="adapter" and not is_ready("near-rt-ric","deployment","oai-lab-xapp"):
        raise Failure("Roll out the xApp receiver before enabling adapter push")
    ensure_image(image)
    if component=="upf":
        if is_ready("oai-ran","deployment","oai-nr-ue"):
            raise Failure("Stop UE and wait for its pod to exit before rolling out UPF; the N4 static IP will move to a new MAC")
        ready("oai-core","deployment","oai-smf",30)
        exec_pod("oai-core","oai-smf","capture","ip","-V",timeout=10)
        print("Stopping old UPF and clearing the SMF N4 neighbor before image rollout",flush=True)
        kub("oai-core","scale","deployment/oai-upf","--replicas=0")
        kub("oai-core","wait","--for=delete","pod","-l","oai-lab/component=upf","--timeout=120s",timeout=130)
        kub("oai-core","exec","deployment/oai-smf","-c","capture","--","ip","neigh","flush","to",values()["networks"]["n4"]["addresses"]["upf"],"dev","n4")
    upgrade=["upgrade",ns,DEPLOY/"charts"/(role if role in ("core", "ran") else ns),"--reuse-values","--set",key+"="+image]
    if component=="adapter": upgrade.extend(["--set","adapter.xappPushEnabled=true"])
    helm(ns,*upgrade,"--timeout","5m",timeout=360)
    if component=="upf":
        kub("oai-core","scale","deployment/oai-upf","--replicas=1")
    ready(ns,"deployment",deployment)
    if component=="xapp":
        print("xApp receiver image rolled out; rollout adapter after rebuilding it, then run gate-xapp",flush=True)
    if component=="upf":
        poll("SMF-UPF PFCP association and heartbeat after image rollout",pfcp_peer_ready,90)
    # Keep subsequent staged upgrades from restoring a previous image.
    if component in ("upf", "smf"):
        lock_path=STATE/"state/images.json"
        overlay_path=STATE/"state/images.yaml"
        if not lock_path.exists() or not overlay_path.exists():
            raise Failure("Missing image lock/overlay after successful rollout")
        lock=json.loads(lock_path.read_text())
        overlay=yaml.safe_load(overlay_path.read_text())
        info=json.loads(run(["docker","image","inspect",image]))[0]
        lock["images"][component]={"image":image,"id":info["Id"],"repoDigests":info.get("RepoDigests",[])}
        overlay["global"]["lab"]["workloads"][component]["image"]=image
        lock_path.write_text(json.dumps(lock,indent=2)+"\n")
        overlay_path.write_text(yaml.safe_dump(overlay,sort_keys=False))


def status():
    if not cluster():
        print("oai-lab API is offline; no start attempted")
        return
    for ns in [OLD,*ROLES.values()]:
        print("["+ns+"]")
        print(kub(ns,"get","pods,svc,pvc","--ignore-not-found","-o","wide",check=False))


def rollback():
    for ns in ROLES.values():
        for item in json.loads(kub(ns,"get","deployments,statefulsets","-o","json"))["items"]:
            kub(ns,"scale",item["kind"].lower()+"/"+item["metadata"]["name"],"--replicas=0")
    deadline=time.monotonic()+180
    while True:
        active=[]
        for ns in ROLES.values():
            active.extend((ns,p["metadata"]["name"]) for p in json.loads(kub(ns,"get","pods","-o","json"))["items"] if p.get("status",{}).get("phase") not in ("Succeeded","Failed"))
        if not active:break
        if time.monotonic()>deadline:raise Failure("New pods still hold IPs: "+str(active[:5]))
        time.sleep(3)
    snapshot_path=STATE/"state/pre-cutover.json"
    if not snapshot_path.exists(): raise Failure("Missing pre-cutover snapshot")
    state=json.loads(snapshot_path.read_text())
    for item in state["resources"]:
        if item["kind"] in ("Deployment","StatefulSet") and item["replicas"] is not None:
            kub(OLD,"scale",item["kind"].lower()+"/"+item["name"],"--replicas="+str(item["replicas"]))
    print("Legacy replicas restored from pre-cutover snapshot")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["check","resume","certs","prepare","cutover","rollback","up","rollout","restart-upf","build-ei","build-xapp","status","gate-ei","gate-xapp","experiment","new-run"])
    parser.add_argument("component",nargs="?")
    parser.add_argument("image",nargs="?")
    parser.add_argument("--stage",choices=["core","nonrt","near-rt","ran"])
    parser.add_argument("--real",action="store_true")
    parser.add_argument("--fixture",action="store_true")
    a=parser.parse_args()
    try:
        if a.command=="up":
            if not a.stage:raise Failure("up requires --stage")
            {"core":core,"nonrt":nonrt,"near-rt":near_rt,"ran":ran}[a.stage]()
        elif a.command=="rollout":
            if not a.component or not a.image: raise Failure("rollout requires COMPONENT IMAGE")
            rollout(a.component,a.image)
        elif a.command=="gate-ei":gate_ei(a.real)
        elif a.command=="gate-xapp":
            if a.real and a.fixture:raise Failure("Use either --real or --fixture")
            gate_xapp(a.real)
        else: globals()[a.command.replace("-","_")]()
    except (Failure,subprocess.TimeoutExpired,ValueError,KeyError) as e:
        print("FAIL: "+str(e),file=sys.stderr)
        return 1
    return 0


if __name__=="__main__": sys.exit(main())
