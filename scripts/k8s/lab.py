#!/usr/bin/env python3
"""Isolated oai-lab orchestration. No legacy backend imports or commands."""
import argparse, base64, csv, datetime, hashlib, ipaddress, json, os, pathlib, re
import secrets, shutil, socket, subprocess, sys, tempfile, time
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/k8s"
STATE = ROOT / "artifacts/k8s"
PROFILE = "oai-lab"
NFS = ["nrf", "udr", "udm", "ausf", "amf", "smf", "upf", "flexric", "gnb", "nr-ue"]
K = [
    "minikube",
    "--profile",
    PROFILE,
    "kubectl",
    "--",
    "--context",
    PROFILE,
    "--namespace",
    PROFILE,
    "--request-timeout=30s",
]
H = ["helm", "--kube-context", PROFILE, "--namespace", PROFILE]


# Stable CLI inputs are separate from generated evidence and diagnostic logs.
ARTIFACT_GROUPS = {
    "state": ("images.json", "images.yaml", "current-run"),
    "build": (
        "images.partial.json",
        "source-provenance.json",
        "tools-build.log",
        "upf-build.log",
        "radio-build.log",
        "smf-build.log",
    ),
    "bootstrap": (
        "bootstrap.json",
        "bootstrap-bpf.json",
        "bootstrap-client.json",
        "bootstrap-server.json",
        "bootstrap-tun.json",
        "bootstrap-radio.json",
        "bootstrap-manifest.yaml",
        "bootstrap-pods.json",
        "bootstrap-values.yaml",
        "bootstrap-run.log",
        "node-images.json",
        "context-isolation.json",
    ),
    "checks": (
        "check.log",
        "preflight.json",
        "rendered.yaml",
        "rendered-all.yaml",
        "server-validation.log",
        "server-validation-first-failure.log",
        "unit-tests.log",
        "compose-profile-tests.log",
        "invalid-xdp.json",
        "invalid-xdp.log",
        "negative-bpf.json",
        "negative-subnet.json",
        "radio-smoke-host.log",
        "subscriber-secret-check.json",
    ),
    "diagnostics": ("last-failure.json", "status.txt"),
    "core": ("core-gate.json",),
}
ARTIFACT_LOCATIONS = {
    name: pathlib.Path(group) / name
    for group, names in ARTIFACT_GROUPS.items()
    for name in names
}


def artifact_path(name):
    """Resolve an artifact without silently creating new files at the root."""
    return STATE / ARTIFACT_LOCATIONS[name]


def prepare_artifact_dirs():
    for group in ARTIFACT_GROUPS:
        (STATE / group).mkdir(parents=True, exist_ok=True)


class GateError(RuntimeError):
    pass


def run(args, *, data=None, capture=True, timeout=600, check=True):
    p = subprocess.run(
        [str(a) for a in args],
        input=data,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    if check and p.returncode:
        raise GateError(
            "Command failed: "
            + str(args[0])
            + " "
            + str(args[1:3])
            + "\n"
            + (p.stderr or "")[-2000:]
        )
    return p.stdout or ""


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def validate(v, routes=()):
    c = v["global"]["lab"]
    if c["profile"] != PROFILE or c["namespace"] != PROFILE:
        raise GateError("Only profile/namespace oai-lab is permitted")
    if c["xdpMode"] != "skb":
        raise GateError("Kubernetes lab requires xdpMode=skb")
    if not c["usageReporting"]:
        raise GateError("Usage reporting must be enabled")
    if c["radio"] != {
        "band": 78,
        "prbs": 106,
        "numerology": 1,
        "frequency": 3619200000,
    }:
        raise GateError(
            "This initial gNB radio template supports only the pinned RFsim profile"
        )
    nets = [ipaddress.ip_network(c["ueSubnet"])]
    for name, n in c["networks"].items():
        if name not in ["n2", "n3", "n4", "n6", "e2"]:
            raise GateError("Unexpected interface " + name)
        subnet = ipaddress.ip_network(n["subnet"])
        nets.append(subnet)
        if subnet.version != 4 or subnet.prefixlen != 24:
            raise GateError("Initial secondary topology requires IPv4 /24 networks")
        if any(
            ipaddress.ip_address(a)
            in [subnet.network_address + 250, subnet.network_address + 251]
            for a in n["addresses"].values()
        ):
            raise GateError("Addresses .250/.251 reserved for bootstrap probes")
        if len(set(n["addresses"].values())) != len(n["addresses"]):
            raise GateError("Duplicate secondary IP")
        for address in n["addresses"].values():
            if ipaddress.ip_address(address) not in subnet or address in [
                str(subnet.network_address),
                str(subnet.broadcast_address),
            ]:
                raise GateError("Invalid secondary IP")
    for i, n in enumerate(nets):
        if any(n.overlaps(o) for o in nets[i + 1 :]):
            raise GateError("Overlapping lab subnets")
        for route in routes:
            if n.version == route.version and n.overlaps(route):
                raise GateError("Subnet conflict: " + str(n) + " with " + str(route))
    for nf in ["nrf", "udr", "udm", "ausf", "amf", "smf"]:
        if c["workloads"][nf]["image"] != "oaisoftwarealliance/oai-" + nf + ":v2.2.0":
            raise GateError("CP image must remain pinned at v2.2.0")
    return c


def host_check(v, *, for_build=False):
    for exe in ["docker", "minikube", "kubectl", "helm", "ip", "tshark", "g++"]:
        if not shutil.which(exe):
            raise GateError("Missing command: " + exe)
    c = validate(v)
    if os.cpu_count() < c["cpus"]:
        raise GateError("Insufficient CPUs")
    mem = {
        l.split(":")[0]: int(l.split()[1])
        for l in pathlib.Path("/proc/meminfo").read_text().splitlines()
    }
    # An already running lab owns its reservation; do not require another 16 GiB.
    running = (
        run(
            ["docker", "ps", "--filter", "name=^/oai-lab$", "--format", "{{.Names}}"]
        ).strip()
        == PROFILE
    )
    required = 2048 if running else c["memoryMiB"] + 1024
    if for_build:
        required = max(required, 4096)
    # Swap is an explicit host capacity reserve for this single-node lab. Keep
    # its contribution visible in evidence instead of pretending it is RAM.
    swap_free = mem.get("SwapFree", 0)
    if mem["MemAvailable"] + swap_free < required * 1024:
        raise GateError(
            "Insufficient available RAM+swap; need " + str(required) + " MiB"
        )
    # A retained cluster with all required images already imported does not need
    # another full build/import disk reservation. New builds always do.
    retained_images = False
    if running and not for_build and (artifact_path("images.json")).exists():
        node_images = json.loads(
            run(
                ["minikube", "--profile", PROFILE, "image", "ls", "--format=json"],
                timeout=60,
            )
        )
        tags = {
            tag.removeprefix("docker.io/").removeprefix("library/")
            for item in node_images
            for tag in item.get("repoTags", [])
        }
        locked = json.loads((artifact_path("images.json")).read_text())
        expected = [i["image"] for i in locked["images"].values()] + [c["dbImage"]]
        expected += [c["workloads"][nf]["image"] for nf in NFS[:6]]
        retained_images = all(tag in tags for tag in expected)
    disk_required = (
        c.get("minRetainedDiskGiB", 5) if retained_images else c["minDiskGiB"]
    )
    if shutil.disk_usage(ROOT).free < disk_required * 1024**3:
        raise GateError(
            "Insufficient disk space; no cache will be deleted automatically"
        )
    routes = []
    for r in json.loads(run(["ip", "-j", "route", "show", "table", "all"])):
        dest = r.get("dst", "default")
        if dest != "default":
            routes.append(ipaddress.ip_network(dest, strict=False))
    ids = run(["docker", "network", "ls", "-q"]).split()
    if ids:
        for net in json.loads(run(["docker", "network", "inspect", *ids])):
            for block in net.get("IPAM", {}).get("Config") or []:
                if block.get("Subnet"):
                    routes.append(ipaddress.ip_network(block["Subnet"]))
    # Reserve minikube's pod/service ranges even before bootstrap.
    validate(
        v,
        [
            *routes,
            ipaddress.ip_network("10.244.0.0/16"),
            ipaddress.ip_network("10.96.0.0/12"),
        ],
    )
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_SCTP):
            pass
    except OSError as e:
        raise GateError("SCTP unavailable: " + str(e))
    config = pathlib.Path("/boot/config-" + os.uname().release)
    if config.exists() and "CONFIG_BPF_SYSCALL=y" not in config.read_text():
        raise GateError("Kernel lacks BPF syscall")
    return {
        "ramAvailableKiB": mem["MemAvailable"],
        "swapFreeKiB": swap_free,
        "diskFreeBytes": shutil.disk_usage(ROOT).free,
        "diskRequiredGiB": disk_required,
        "retainedImages": retained_images,
        "kernel": os.uname().release,
        "sctp": True,
        "bpf": "load/attach gate required inside UPF",
    }


def fingerprint(paths):
    h = hashlib.sha256()
    skip = {".git", "build", "ran_build", "__pycache__", "CMakeFiles", "log", "logs"}
    for base in paths:
        for here, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in skip)
            for name in sorted(files):
                p = pathlib.Path(here) / name
                # .previous / compile_commands.json: local editor/patch leftovers,
                # not produced by scripts/verify-oai-upstream.sh --into.
                if (
                    p.is_symlink()
                    or name.endswith((".o", ".a", ".pyc"))
                    or ".previous" in name
                    or name == "compile_commands.json"
                ):
                    continue
                h.update(str(p.relative_to(ROOT)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()


class Lab:
    def __init__(self, args):
        prepare_artifact_dirs()
        self.args = args
        self.values = yaml.safe_load(args.values.read_text())
        self.c = validate(self.values)
        self.runid = (
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-k8s"
        )
        self.out = ROOT / "artifacts/experiments" / self.runid
        self.enabled = []
        self.seed = False
        self.xapp = False
        self.bootstrap = False

    def render(self):
        flags = [f"oai-{n}.enabled=true" for n in NFS] + [
            "seedEnabled=true",
            "xappEnabled=true",
        ]
        rendered = run(
            H
            + [
                "template",
                PROFILE,
                DEPLOY / "chart",
                "-f",
                self.args.values,
                "--set",
                ",".join(flags),
            ]
        )
        docs = list(yaml.safe_load_all(rendered))
        cm = next(
            d
            for d in docs
            if d
            and d["kind"] == "ConfigMap"
            and d["metadata"]["name"] == "oai-lab-config"
        )
        cfg = yaml.safe_load(cm["data"]["config.yaml"])
        assert cfg["upf"]["support_features"]["xdp_mode"] == "skb"
        assert len(cfg["smf"]["upfs"]) == 1 and len(cfg["snssais"]) == 1
        STATE.mkdir(parents=True, exist_ok=True)
        (artifact_path("rendered.yaml")).write_text(rendered)
        run(
            H
            + [
                "lint",
                DEPLOY / "chart",
                "-f",
                self.args.values,
                "--set",
                ",".join(flags),
            ],
            capture=False,
        )

    def check(self):
        self.render()
        write_json(artifact_path("preflight.json"), host_check(self.values))
        print("Preflight passed; runtime BPF attachment will be checked during up.", flush=True)

    def build(self):
        self.render()
        write_json(
            artifact_path("preflight.json"), host_check(self.values, for_build=True)
        )
        print("Build preflight passed.")
        lock = {}
        tag = fingerprint(
            [
                ROOT / "src/oai-upf",
                ROOT / "src/oai-ran",
                ROOT / "src/flexric",
                DEPLOY / "images",
            ]
        )[:16]
        jobs = [
            ("tools", DEPLOY / "images/Dockerfile.tools", ROOT, None, tag),
            (
                "upf",
                ROOT / "src/oai-upf/docker/Dockerfile.upf.ubuntu",
                ROOT / "src/oai-upf",
                "oai-upf",
                tag,
            ),
            ("radio", DEPLOY / "images/Dockerfile.radio", ROOT, None, tag),
        ]
        # SMF patches and the tree each one applies to. The tag hashes all of
        # them so a rebuilt image is never labelled with a subset of its fixes.
        smf_patches = [
            (
                ROOT / "src/oai-smf/src/oai-cn5g-common-src",
                ROOT / "patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch",
            ),
            (
                ROOT / "src/oai-smf",
                ROOT / "patches/oai-smf-v2.2.0-stale-session-release.patch",
            ),
            (
                ROOT / "src/oai-smf/src/oai-cn5g-common-src",
                ROOT / "patches/oai-smf-v2.2.0-common-src-user-id-length.patch",
            ),
            (
                ROOT / "src/oai-smf",
                ROOT / "patches/oai-smf-v2.2.0-user-id-urr-config-ttl.patch",
            ),
            (
                ROOT / "src/oai-smf",
                ROOT / "patches/oai-smf-v2.2.0-reassociation-up-features.patch",
            ),
            (
                ROOT / "src/oai-smf/src/oai-cn5g-common-src",
                ROOT / "patches/oai-smf-v2.2.0-common-src-usage-report-times.patch",
            ),
            (
                ROOT / "src/oai-smf",
                ROOT / "patches/oai-smf-v2.2.0-usage-report-times.patch",
            ),
        ]
        if (ROOT / "src/oai-smf").is_dir() and all(p.exists() for _, p in smf_patches):
            smf_patch_hashes = {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for _, p in smf_patches
            }
            smf_tag_hash = hashlib.sha256(
                "".join(smf_patch_hashes[p.name] for _, p in smf_patches).encode()
            ).hexdigest()
            smf_commit = run(
                ["git", "-C", ROOT / "src/oai-smf", "rev-parse", "HEAD"]
            ).strip()
            # Refuse to label an unpatched binary as the compatibility build.
            # The patches overlap, so unapply them newest first on a copy.
            src = ROOT / "src/oai-smf"
            with tempfile.TemporaryDirectory() as tmp:
                copy = pathlib.Path(tmp) / "smf"
                shutil.copytree(
                    src, copy, ignore=shutil.ignore_patterns(".git", "build")
                )
                for tree, patch in reversed(smf_patches):
                    run(
                        ["patch", "-d", copy / tree.relative_to(src),
                         "-R", "-p1", "-s", "-f", "-i", patch]
                    )
            jobs.append(
                (
                    "smf",
                    ROOT / "src/oai-smf/docker/Dockerfile.smf.ubuntu",
                    ROOT / "src/oai-smf",
                    "oai-smf",
                    "v2.2.0-lab-" + smf_tag_hash[:8],
                )
            )
        for name, dockerfile, context, target, image_tag in jobs:
            image = "oai-lab-" + name + ":" + image_tag
            cmd = ["docker", "build", "-f", dockerfile, "-t", image]
            if target:
                commit = smf_commit if name == "smf" else tag
                cmd += ["--target", target, "--build-arg", "GIT_COMMIT=" + commit]
            print("Building " + image, flush=True)
            with (artifact_path(name + "-build.log")).open("w") as log:
                p = subprocess.run(
                    [str(x) for x in cmd + [context]],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            if p.returncode:
                raise GateError(
                    "Image build failed: "
                    + name
                    + "; see artifacts/k8s/build/"
                    + name
                    + "-build.log"
                )
            info = json.loads(run(["docker", "image", "inspect", image]))[0]
            lock[name] = {
                "image": image,
                "id": info["Id"],
                "repoDigests": info.get("RepoDigests", []),
            }
            if name == "smf":
                lock[name].update(
                    sourceCommit=smf_commit,
                    patchSha256=smf_patch_hashes,
                )
            write_json(artifact_path("images.partial.json"), lock)
        overlay = {
            "global": {
                "lab": {
                    "toolsImage": lock["tools"]["image"],
                    "workloads": {
                        n: {
                            "image": lock[
                                "smf"
                                if n == "smf"
                                else "upf"
                                if n == "upf"
                                else "radio"
                            ]["image"]
                        }
                        for n in ["smf", "upf", "gnb", "nr-ue", "flexric"]
                    },
                }
            }
        }
        (artifact_path("images.yaml")).write_text(yaml.safe_dump(overlay))
        write_json(artifact_path("images.json"), {"sourceHash": tag, "images": lock})

    def k(self, *args, **kw):
        # Watch/exec streams may legitimately outlive the default HTTP timeout.
        # Their process timeouts and Kubernetes wait deadlines remain bounded.
        streaming = args and args[0] in ("exec", "wait", "rollout")
        return run(
            K + (["--request-timeout=0"] if streaming else []) + list(args), **kw
        )

    def exec(self, nf, *args, **kw):
        deployment = "oai-" + nf if nf in NFS else "oai-lab-" + nf
        return self.k("exec", "deployment/" + deployment, "-c", nf, "--", *args, **kw)

    def helm(self):
        flags = [f"oai-{n}.enabled={str(n in self.enabled).lower()}" for n in NFS] + [
            "seedEnabled=" + str(self.seed).lower(),
            "xappEnabled=" + str(self.xapp).lower(),
            "bootstrapTestEnabled=" + str(self.bootstrap).lower(),
        ]
        run(
            H
            + [
                "upgrade",
                "--install",
                PROFILE,
                DEPLOY / "chart",
                "-f",
                self.args.values,
                "-f",
                artifact_path("images.yaml"),
                "--set",
                ",".join(flags),
                "--timeout",
                "5m",
            ],
            capture=False,
        )

    def ready(self, nf):
        obj = (
            "statefulset/oai-lab-db"
            if nf == "db"
            else "deployment/" + ("oai-" + nf if nf in NFS else "oai-lab-" + nf)
        )
        self.k("rollout", "status", obj, "--timeout=180s", capture=False, timeout=200)

    def wait(self, description, fn, timeout=180):
        start = time.monotonic()
        last = ""
        while time.monotonic() - start < timeout:
            try:
                val = fn()
                if val:
                    return val
            except (GateError, ValueError, KeyError) as e:
                last = str(e)
            time.sleep(3)
        raise GateError(description + " timed out. " + last[-500:])

    def credentials(self):
        # Reuse credentials when PVCs survive down/up. Never log secret data.
        got = self.k(
            "get", "secret", self.c["secretName"], "--ignore-not-found", "-o", "name"
        )
        if got:
            return
        raw = (ROOT / "configs/ue/ue1.conf").read_text()
        fields = {}
        for k, p in [("IMSI", "imsi"), ("KEY", "key"), ("OPC", "opc")]:
            m = re.search(r"\b" + p + r'\s*=\s*"([a-fA-F0-9]+)"', raw, re.I)
            if not m:
                raise GateError(
                    "Cannot read UE1 " + k + "; create lab Secret explicitly"
                )
            fields[k] = m.group(1)
        fields.update(
            DB_PASSWORD=secrets.token_hex(24), DB_ROOT_PASSWORD=secrets.token_hex(24)
        )
        self.k(
            "apply",
            "-f",
            "-",
            data=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": self.c["secretName"], "namespace": PROFILE},
                    "type": "Opaque",
                    "stringData": fields,
                }
            ),
        )

    def up(self):
        self.check()
        if not all(
            (artifact_path(name)).exists() for name in ("images.yaml", "images.json")
        ):
            raise GateError("Run build successfully before up")
        lock = json.loads((artifact_path("images.json")).read_text())
        current = fingerprint(
            [
                ROOT / "src/oai-upf",
                ROOT / "src/oai-ran",
                ROOT / "src/flexric",
                DEPLOY / "images",
            ]
        )[:16]
        if current != lock["sourceHash"]:
            raise GateError("Source changed since build; rebuild images")
        for item in lock["images"].values():
            if (
                json.loads(run(["docker", "image", "inspect", item["image"]]))[0]["Id"]
                != item["id"]
            ):
                raise GateError("Image ID changed; rebuild")
        run(
            [
                "minikube",
                "start",
                "--profile",
                PROFILE,
                "--keep-context",
                "--driver=docker",
                "--container-runtime=containerd",
                "--kubernetes-version=" + self.c["kubernetesVersion"],
                "--cni=bridge",
                "--cpus=" + str(self.c["cpus"]),
                "--memory=" + str(self.c["memoryMiB"]),
                "--interactive=false",
            ],
            capture=False,
            timeout=900,
        )
        self.k(
            "apply",
            "-f",
            "-",
            data=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": PROFILE,
                        "labels": {"pod-security.kubernetes.io/enforce": "privileged"},
                    },
                }
            ),
        )
        run(
            K[:]
            + [
                "--namespace",
                "kube-system",
                "apply",
                "-f",
                DEPLOY / "vendor/multus.yaml",
            ],
            capture=False,
        )
        run(
            K[:]
            + [
                "--namespace",
                "kube-system",
                "rollout",
                "status",
                "daemonset/kube-multus-ds",
                "--timeout=180s",
            ],
            capture=False,
        )
        run(
            [
                "minikube",
                "--profile",
                PROFILE,
                "ssh",
                "--",
                "test -x /opt/cni/bin/bridge && test -x /opt/cni/bin/static && test -e /dev/net/tun",
            ],
            capture=False,
        )
        node_tags = {
            tag.removeprefix("docker.io/").removeprefix("library/")
            for tag in run(
                ["minikube", "--profile", PROFILE, "image", "ls"], timeout=60
            ).splitlines()
        }
        for item in lock["images"].values():
            if item["image"] not in node_tags:
                run(
                    [
                        "minikube",
                        "--profile",
                        PROFILE,
                        "image",
                        "load",
                        item["image"],
                    ],
                    capture=False,
                    timeout=600,
                )
                node_tags.add(item["image"])
        for image in [self.c["dbImage"]] + [
            self.c["workloads"][nf]["image"] for nf in NFS[:6]
        ]:
            local = (
                subprocess.run(
                    ["docker", "image", "inspect", image],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            )
            if image not in node_tags:
                run(
                    [
                        "minikube",
                        "--profile",
                        PROFILE,
                        "image",
                        "load" if local else "pull",
                        image,
                    ],
                    capture=False,
                    timeout=600,
                )
                node_tags.add(image)
        runtime_images = json.loads(
            run(
                [
                    "minikube",
                    "--profile",
                    PROFILE,
                    "ssh",
                    "--",
                    "sudo crictl images -o json",
                ]
            )
        )
        write_json(artifact_path("node-images.json"), runtime_images)
        actual = {
            tag.removeprefix("docker.io/").removeprefix("library/")
            for item in runtime_images["images"]
            for tag in item.get("repoTags", [])
        }
        expected = (
            [i["image"] for i in lock["images"].values()]
            + [self.c["dbImage"]]
            + [self.c["workloads"][nf]["image"] for nf in NFS[:6]]
        )
        if any(tag not in actual for tag in expected):
            raise GateError("Required image missing in node runtime")
        self.credentials()
        self.helm()
        self.ready("db")
        self.ready("dn")
        for side in ["server", "client", "upf-bpf", "ue-tun", "radio"]:
            self.k("delete", "job", "oai-lab-bootstrap-" + side, "--ignore-not-found")
        self.bootstrap = True
        self.helm()
        for side in ["server", "client"]:
            self.k(
                "wait",
                "--for=condition=complete",
                "job/oai-lab-bootstrap-" + side,
                "--timeout=180s",
                capture=False,
            )
            (artifact_path("bootstrap-" + side + ".json")).write_text(
                self.k("logs", "job/oai-lab-bootstrap-" + side)
            )
        self.k(
            "wait",
            "--for=condition=complete",
            "job/oai-lab-bootstrap-upf-bpf",
            "--timeout=120s",
            capture=False,
        )
        bpf = json.loads(self.k("logs", "job/oai-lab-bootstrap-upf-bpf"))
        write_json(artifact_path("bootstrap-bpf.json"), bpf)
        if not bpf.get("program_types", {}).get("have_xdp_prog_type"):
            raise GateError("Kernel cannot load XDP programs from UPF privileged pod")
        self.k(
            "wait",
            "--for=condition=complete",
            "job/oai-lab-bootstrap-ue-tun",
            "--timeout=60s",
            capture=False,
        )
        tun = json.loads(self.k("logs", "job/oai-lab-bootstrap-ue-tun"))
        if not tun.get("tun"):
            raise GateError("UE cannot create TUN without privileged mode")
        write_json(artifact_path("bootstrap-tun.json"), tun)
        self.k(
            "wait",
            "--for=condition=complete",
            "job/oai-lab-bootstrap-radio",
            "--timeout=60s",
            capture=False,
        )
        radio = json.loads(self.k("logs", "job/oai-lab-bootstrap-radio"))
        if radio.get("status") != "PASS":
            raise GateError("Radio image has unresolved binaries/libraries")
        write_json(artifact_path("bootstrap-radio.json"), radio)
        write_json(
            artifact_path("source-provenance.json"),
            {
                "commits": {
                    p.stem: p.read_text().strip()
                    for p in (ROOT / "manifests").glob("*.commit")
                },
                "patchSha256": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (ROOT / "patches").glob("*.patch")
                },
                "chart": json.loads((DEPLOY / "vendor/PROVENANCE.json").read_text()),
            },
        )
        write_json(
            artifact_path("bootstrap.json"),
            {
                "status": "PASS",
                "scope": "milestone 1, not end-to-end acceptance",
                "images": lock,
            },
        )
        (artifact_path("bootstrap-pods.json")).write_text(
            self.k("get", "pods", "-o", "json")
        )
        (artifact_path("bootstrap-values.yaml")).write_text(
            run(H + ["get", "values", PROFILE, "-o", "yaml"])
        )
        if self.args.stage == "bootstrap":
            return
        self.k("delete", "job", "oai-lab-subscriber", "--ignore-not-found")
        self.seed = True
        self.helm()
        self.k(
            "wait",
            "--for=condition=complete",
            "job/oai-lab-subscriber",
            "--timeout=180s",
            capture=False,
        )
        for nf in NFS[:7]:
            self.enabled.append(nf)
            self.helm()
            self.ready(nf)
            if nf == "smf":
                self.capture_start()
        self.wait(
            "PFCP accepted association",
            lambda: self.k(
                "exec",
                "deployment/oai-smf",
                "-c",
                "capture",
                "--",
                "tshark",
                "-r",
                "/artifacts/runs/" + self.runid + "/pfcp.pcap",
                "-Y",
                "pfcp.msg_type == 6 && pfcp.cause == 1",
                "-T",
                "fields",
                "-e",
                "pfcp.seqno",
                check=False,
            ).strip(),
        )
        self.core_gate()
        if self.args.stage == "core":
            return
        for nf in ["flexric", "gnb"]:
            self.enabled.append(nf)
            self.helm()
            self.ready(nf)
        self.start_session()
        self.complete_milestone3()

    def capture_start(self):
        self.exec("dn", "mkdir", "-p", "/artifacts/runs/" + self.runid)
        self.exec(
            "dn",
            "python3",
            "-c",
            'import pathlib,json; p=pathlib.Path("/artifacts"); (p/"current-run").write_text('
            + repr(self.runid)
            + '); (p/"request.tmp").write_text(json.dumps({"run_id":'
            + repr(self.runid)
            + '})); (p/"request.tmp").replace(p/"capture-request.json")',
        )
        self.wait(
            "PFCP capture ready",
            lambda: self.exec(
                "dn", "test", "-f", "/artifacts/runs/" + self.runid + "/capture.ready"
            )
            == "",
        )

    def start_session(self):
        self.capture_start()
        self.enabled = NFS[:9]
        self.xapp = False
        self.helm()
        self.k(
            "wait",
            "--for=delete",
            "pod",
            "-l",
            "oai-lab/component=nr-ue",
            "--timeout=90s",
        )
        self.k(
            "wait",
            "--for=delete",
            "pod",
            "-l",
            "oai-lab/component=xapp",
            "--timeout=90s",
        )
        self.enabled = NFS[:]
        self.xapp = True
        self.helm()
        self.ready("nr-ue")
        self.ready("xapp")
        ue_ip = self.wait("UE registration/PDU interface", self.ue_ip)
        self.ensure_ue_route(ue_ip)
        self.wait(
            "E2 setup",
            lambda: re.search(
                r"(?i)E2.*setup.*(response|success)",
                # The gNB/FlexRIC connection survives UE-only session restarts.
                # Read the current gNB pod's complete log so steady-state radio
                # statistics cannot push the valid setup response out of a
                # fixed tail window before an experiment starts.
                self.k("logs", "deployment/oai-gnb", "-c", "gnb", "--tail=-1"),
            ),
        )
        self.xdp_gate()
        self.wait(
            "KPM samples",
            lambda: int(
                self.exec(
                    "dn",
                    "sh",
                    "-c",
                    "test -f /artifacts/runs/"
                    + self.runid
                    + "/KPI_Metrics.csv && wc -l < /artifacts/runs/"
                    + self.runid
                    + "/KPI_Metrics.csv",
                )
            )
            > 1,
        )
        self.out.mkdir(parents=True, exist_ok=True)
        self.metadata()
        (artifact_path("current-run")).write_text(self.runid)

    def ensure_ue_route(self, ue_ip):
        # The pod default route belongs to Kubernetes.  Route only the lab N6
        # subnet through the PDU TUN so DN traffic uses the UE address and does
        # not escape through eth0.  A UE pod restart drops this route; without
        # it UL leaves via eth0 and iperf2's connected DL socket binds the pod
        # address, so both directions look broken although GTP-U is fine.
        dn = self.c["networks"]["n6"]["addresses"]["dn"]

        def via_tun():
            routes = json.loads(self.exec("nr-ue", "ip", "-j", "route", "get", dn))
            return bool(routes) and (
                routes[0].get("dev") == "oaitun_ue1"
                and routes[0].get("prefsrc") == ue_ip
            )

        if via_tun():
            return
        self.exec(
            "nr-ue",
            "ip",
            "route",
            "replace",
            self.c["networks"]["n6"]["subnet"],
            "dev",
            "oaitun_ue1",
            "src",
            ue_ip,
        )
        if not via_tun():
            raise GateError("UE route to DN " + dn + " does not use oaitun_ue1/" + ue_ip)

    def ue_ip(self):
        for interface in json.loads(self.exec("nr-ue", "ip", "-j", "address")):
            for addr in interface.get("addr_info", []):
                if addr["family"] == "inet" and ipaddress.ip_address(
                    addr["local"]
                ) in ipaddress.ip_network(self.c["ueSubnet"]):
                    return addr["local"]
        return None

    def xdp_gate(self):
        info = json.loads(self.exec("upf", "/openair-upf/bin/bpftool", "-j", "net"))
        records = info if isinstance(info, list) else [info]
        xdp = [e for r in records for e in r.get("xdp", [])]
        for interface in ["n3", "n6"]:
            if not any(
                e.get("devname") == interface
                and e.get("mode") == "generic"
                and e.get("id", 0) > 0
                for e in xdp
            ):
                raise GateError("XDP-SKB not attached to " + interface)
        self.out.mkdir(parents=True, exist_ok=True)
        write_json(self.out / "xdp.json", info)
        return info

    def core_gate(self):
        """Prove core readiness beyond Kubernetes rollout state."""
        smf_log = self.k("logs", "deployment/oai-smf", "-c", "smf", "--tail=-1")
        decoder_errors = re.findall(
            r"PFCP IE TLV 43|bad length|pfcp_tlv_bad_length|terminate called|uncaught",
            smf_log,
            re.I,
        )
        if decoder_errors:
            raise GateError("SMF PFCP decoder error after association")

        profiles = {}
        for nf in ["UDR", "UDM", "AUSF", "AMF", "SMF", "UPF"]:
            response = json.loads(
                self.exec(
                    "dn",
                    "curl",
                    "-fsS",
                    "http://oai-nrf/nnrf-disc/v1/nf-instances"
                    + "?target-nf-type="
                    + nf
                    + "&requester-nf-type=SMF",
                )
            )
            profiles[nf] = [
                {
                    "name": item.get("nfInstanceName"),
                    "status": item.get("nfStatus"),
                }
                for item in response.get("nfInstances", [])
            ]
            if not any(item["status"] == "REGISTERED" for item in profiles[nf]):
                raise GateError(nf + " is not REGISTERED in NRF")

        pcap = "/artifacts/runs/" + self.runid + "/pfcp.pcap"
        def pfcp_state():
            fields = self.k(
                "exec",
                "deployment/oai-smf",
                "-c",
                "capture",
                "--",
                "tshark",
                "-r",
                pcap,
                "-Y",
                "pfcp",
                "-T",
                "fields",
                "-e",
                "pfcp.msg_type",
                "-e",
                "pfcp.seqno",
                "-e",
                "pfcp.cause",
            )
            messages = []
            for line in fields.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    messages.append(
                        (
                            int(parts[0]),
                            int(parts[1]),
                            int(parts[2])
                            if len(parts) > 2 and parts[2].isdigit()
                            else None,
                        )
                    )
            associations = [m for m in messages if m[0] == 6 and m[2] == 1]
            heartbeat_requests = {m[1] for m in messages if m[0] == 1}
            heartbeat_responses = {m[1] for m in messages if m[0] == 2}
            heartbeat_pairs = len(heartbeat_requests & heartbeat_responses)
            if associations and heartbeat_pairs >= 2:
                return associations, heartbeat_pairs
            return None

        associations, heartbeat_pairs = self.wait(
            "PFCP association and two matched heartbeat responses",
            pfcp_state,
            timeout=60,
        )

        verbose = self.k(
            "exec",
            "deployment/oai-smf",
            "-c",
            "capture",
            "--",
            "tshark",
            "-r",
            pcap,
            "-Y",
            "pfcp.msg_type == 6",
            "-V",
        )
        ie43_length8 = bool(
            re.search(
                r"IE Type: UP Function Features \(43\).*?IE Length: 8",
                verbose,
                re.S,
            )
        )
        if not ie43_length8:
            raise GateError("Captured PFCP response does not contain IE 43 length 8")

        xdp = self.xdp_gate()
        dn_routes = json.loads(self.exec("dn", "ip", "-j", "route", "show"))
        expected_route = self.c["ueSubnet"]
        n6_upf = self.c["networks"]["n6"]["addresses"]["upf"]
        if not any(
            route.get("dst") == expected_route and route.get("gateway") == n6_upf
            for route in dn_routes
        ):
            raise GateError("DN return route through UPF N6 is missing")

        write_json(
            artifact_path("core-gate.json"),
            {
                "status": "PASS",
                "runId": self.runid,
                "nrfProfiles": profiles,
                "pfcp": {
                    "associationSequence": associations[-1][1],
                    "heartbeatPairs": heartbeat_pairs,
                    "ie43Length8": ie43_length8,
                },
                "smfDecoderErrorCount": len(decoder_errors),
                "dnReturnRoute": {"destination": expected_route, "via": n6_upf},
                "xdp": xdp,
            },
        )

    def metadata(self):
        write_json(
            self.out / "metadata.json",
            {
                "backend": "kubernetes",
                "context": PROFILE,
                "xdpMode": "skb",
                "valuesHash": hashlib.sha256(self.args.values.read_bytes()).hexdigest(),
                "chartHash": fingerprint([DEPLOY / "chart", DEPLOY / "vendor"]),
                "images": json.loads((artifact_path("images.json")).read_text()),
                "chartProvenance": json.loads(
                    (DEPLOY / "vendor/PROVENANCE.json").read_text()
                ),
            },
        )
        (self.out / "pod-images.json").write_text(self.k("get", "pods", "-o", "json"))

    def complete_milestone3(self):
        """Persist the radio/session/KPM gate without running milestone-4 traffic."""
        self.collect()
        kpm = self.out / "KPI_Metrics.csv"
        if not kpm.is_file():
            raise GateError("KPM CSV was not exported from the artifact volume")
        with kpm.open(newline="") as f:
            kpm_samples = max(sum(1 for _ in csv.reader(f)) - 1, 0)
        if kpm_samples < 1:
            raise GateError("Exported KPM CSV has no data samples")

        pods = json.loads(self.k("get", "pods", "-o", "json"))["items"]
        xapp_restarts = sum(
            status.get("restartCount", 0)
            for pod in pods
            if pod["metadata"].get("labels", {}).get("oai-lab/component") == "xapp"
            for status in pod.get("status", {}).get("containerStatuses", [])
        )
        xdp = json.loads((self.out / "xdp.json").read_text())
        xdp_ids = {
            entry["devname"]: entry["id"]
            for record in xdp
            for entry in record.get("xdp", [])
            if entry.get("devname") in {"n3", "n6"}
        }

        milestones_path = STATE / "milestones.json"
        milestones = (
            json.loads(milestones_path.read_text()) if milestones_path.exists() else {}
        )
        milestones["updatedAt"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        milestones["milestone3"] = {
            "status": "COMPLETE",
            "runId": self.runid,
            "ueRegistration": "PASS",
            "pduSession": "PASS",
            "ueIPv4": self.ue_ip(),
            "e2Setup": "PASS",
            "kpmCollection": "PASS",
            "kpmSamples": kpm_samples,
            "xappRestarts": xapp_restarts,
            "xdpSkbAttachAfterSession": "PASS",
            "xdpProgramIds": xdp_ids,
            "radioImage": json.loads((artifact_path("images.json")).read_text())["images"]["radio"],
            "evidence": [
                "experiments/" + self.runid + "/metadata.json",
                "experiments/" + self.runid + "/KPI_Metrics.csv",
                "experiments/" + self.runid + "/KPI_Metrics_Cells.csv",
                "experiments/" + self.runid + "/pfcp.pcap",
                "experiments/" + self.runid + "/xdp.json",
                "diagnostics/m3-full-up-final.log",
            ],
        }
        milestones.setdefault("milestone4", {"status": "NOT_RUN"})
        milestones["migrationComplete"] = False
        write_json(milestones_path, milestones)
        print(
            f"Milestone 3 PASS: UE {milestones['milestone3']['ueIPv4']}, "
            f"{kpm_samples} KPM sample(s).",
            flush=True,
        )

    def collect(self):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "events.txt").write_text(
            self.k("get", "events", "--sort-by=.lastTimestamp")
        )
        # Redact SIM and database secrets from application log output.
        vals = []
        try:
            vals = [
                base64.b64decode(v).decode()
                for v in json.loads(
                    self.k("get", "secret", self.c["secretName"], "-o", "json")
                )
                .get("data", {})
                .values()
            ]
        except GateError:
            pass
        pods = json.loads(self.k("get", "pods", "-o", "json"))["items"]
        for pod in pods:
            for cont in pod["spec"]["containers"]:
                log = self.k(
                    "logs",
                    pod["metadata"]["name"],
                    "-c",
                    cont["name"],
                    "--tail=5000",
                    check=False,
                )
                for value in vals:
                    log = log.replace(value, "[REDACTED]")
                (
                    self.out / (pod["metadata"]["name"] + "-" + cont["name"] + ".log")
                ).write_text(log)
        try:
            self.exec("dn", "touch", "/artifacts/runs/" + self.runid + "/capture.stop")
            self.wait(
                "capture flush",
                lambda: self.exec(
                    "dn",
                    "test",
                    "-f",
                    "/artifacts/runs/" + self.runid + "/capture.done",
                )
                == "",
                30,
            )
            with (self.out / "pod-artifacts.tar").open("wb") as f:
                subprocess.run(
                    K
                    + [
                        "exec",
                        "deployment/oai-lab-dn",
                        "-c",
                        "dn",
                        "--",
                        "tar",
                        "-C",
                        "/artifacts/runs/" + self.runid,
                        "-cf",
                        "-",
                        ".",
                    ],
                    stdout=f,
                    check=True,
                )
            import tarfile

            with tarfile.open(self.out / "pod-artifacts.tar") as t:
                t.extractall(self.out, filter="data")
        except (GateError, subprocess.CalledProcessError):
            pass

    def experiment(self):
        self.enabled = NFS[:]
        self.seed = True
        self.start_session()
        duration = self.c["experiment"]["duration"]
        rate = self.c["experiment"]["rate"]
        ue = self.ue_ip()
        dn = self.c["networks"]["n6"]["addresses"]["dn"]
        rows = []
        for direction, sender, receiver, dest, port in [
            ("ul", "nr-ue", "dn", dn, 5001),
            ("dl", "dn", "nr-ue", ue, 5002),
        ]:
            # Re-check per direction: the session may have aged since start_session.
            if self.ue_ip() != ue:
                raise GateError("UE address changed during experiment")
            self.ensure_ue_route(ue)
            log = "/tmp/oai-lab-iperf-" + direction + ".csv"
            # Bound receiver lifetime. Parse the receiver report, never the client exit code alone.
            self.exec(
                receiver,
                "sh",
                "-c",
                f"timeout {duration+20} iperf -s -u -p {port} -y C > {log} 2>&1 < /dev/null &",
            )
            time.sleep(2)
            start = int(time.time() * 1000)
            client = self.exec(
                sender,
                "iperf",
                "-c",
                dest,
                "-u",
                "-b",
                str(rate),
                "-l",
                "1200",
                "-t",
                str(duration),
                "-p",
                str(port),
                "-y",
                "C",
                timeout=duration + 30,
            )
            time.sleep(3)
            server = self.exec(receiver, "cat", log)
            (self.out / (direction + "-sender.csv")).write_text(client)
            (self.out / (direction + "-receiver.csv")).write_text(server)
            samples = [
                r
                for r in csv.reader(server.splitlines())
                if len(r) >= 13 and r[7].isdigit() and int(r[7]) > 0
            ]
            if not samples:
                raise GateError(direction + " has no positive receiver traffic report")
            row = max(samples, key=lambda r: int(r[7]))
            loss = float(row[12])
            write_json(
                self.out / (direction + "-summary.json"),
                {"bytes": int(row[7]), "lostPercent": loss},
            )
            if loss >= 100:
                raise GateError(direction + " packet loss is 100%")
            rows.append(
                [
                    direction,
                    direction,
                    rate,
                    duration,
                    start,
                    int(time.time() * 1000),
                    "ok",
                ]
            )
        with (self.out / "phases.csv").open("w") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "phase",
                    "direction",
                    "offered_rate",
                    "duration_seconds",
                    "start_unix_ms",
                    "end_unix_ms",
                    "status",
                ]
            )
            w.writerows(rows)
        time.sleep(5)
        self.collect()
        run([sys.executable, ROOT / "scripts/k8s/analyze.py", self.out], capture=False)

    def status(self):
        self.k("get", "pods,svc,pvc,jobs", "-o", "wide", capture=False)

    def down(self):
        run(
            H
            + [
                "uninstall",
                PROFILE,
                "--ignore-not-found",
                "--wait",
                "--timeout",
                "180s",
            ],
            capture=False,
        )
        print(
            "Release removed. Cluster, Secret, database PVC and artifact PVC retained."
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["check", "build", "up", "status", "experiment", "down"]
    )
    parser.add_argument(
        "--values", type=pathlib.Path, default=DEPLOY / "values/minikube.yaml"
    )
    parser.add_argument(
        "--stage", choices=["bootstrap", "core", "full"], default="full"
    )
    args = parser.parse_args()
    lab = None
    try:
        lab = Lab(args)
        getattr(lab, args.command)()
    except (GateError, subprocess.TimeoutExpired, ValueError, OSError) as e:
        print("FAIL: " + str(e), file=sys.stderr)
        STATE.mkdir(parents=True, exist_ok=True)
        write_json(
            artifact_path("last-failure.json"),
            {
                "command": args.command,
                "error": str(e),
                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        )
        if lab and args.command in ["up", "experiment"]:
            try:
                lab.collect()
            except Exception:
                pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
