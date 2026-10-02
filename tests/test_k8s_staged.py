#!/usr/bin/env python3
"""Contract checks for the four namespace chart split; no cluster mutation."""
import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(role, *sets):
    chart = ROOT / "deploy/k8s/charts" / role
    cmd = ["helm", "template", role, str(chart), "-f", str(ROOT / "deploy/k8s/values/minikube.yaml"), "-f", str(ROOT / "artifacts/k8s/state/images.yaml")]
    for setting in sets:
        cmd += ["--set", setting]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [x for x in yaml.safe_load_all(p.stdout) if x]


class SplitChartTests(unittest.TestCase):
    def test_network_attachments_are_namespaced_by_role(self):
        want = {
            "core": {"oai-amf-n2", "oai-smf-n4", "oai-upf-n3", "oai-upf-n4", "oai-upf-n6", "oai-dn-n6"},
            "ran": {"oai-gnb-n2", "oai-gnb-n3", "oai-gnb-e2"},
            "near-rt-ric": {"oai-flexric-e2", "oai-xapp-e2"},
            "non-rt-ric": set(),
        }
        for role, expected in want.items():
            docs = render(role)
            actual = {x["metadata"]["name"] for x in docs if x["kind"] == "NetworkAttachmentDefinition"}
            self.assertEqual(actual, expected, role)

    def test_core_disabled_then_single_nf_enabled(self):
        docs = render("core", "oai-upf.enabled=true", "global.lab.replicas=1", "replicas=1")
        workloads = [x for x in docs if x["kind"] == "Deployment"]
        self.assertEqual({x["metadata"]["name"] for x in workloads}, {"oai-upf", "oai-lab-dn"})
        upf = next(x for x in workloads if x["metadata"]["name"] == "oai-upf")
        self.assertEqual(upf["spec"]["replicas"], 1)
        self.assertTrue(upf["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"])
        cm = next(x for x in docs if x["kind"] == "ConfigMap")
        cfg = yaml.safe_load(cm["data"]["config.yaml"])
        self.assertEqual(cfg["upf"]["support_features"]["xdp_mode"], "skb")
        self.assertEqual(cfg["database"]["host"], "oai-lab-db.oai-core.svc.cluster.local")

    def test_https_services_and_zero_replicas_before_cutover(self):
        for role, workloads in [("non-rt-ric", {"informationservice", "urr-ei-producer"}), ("near-rt-ric", {"a1-ei-adapter"})]:
            docs = render(role)
            found = {x["metadata"]["name"]: x for x in docs if x["kind"] in ("Deployment", "StatefulSet")}
            for name in workloads:
                self.assertEqual(found[name]["spec"]["replicas"], 0)
            services = {x["metadata"]["name"]: x for x in docs if x["kind"] == "Service"}
            for name in workloads:
                self.assertEqual(services[name]["spec"]["ports"][0]["name"], "https")



class UeRouteTests(unittest.TestCase):
    """ensure_ue_route repairs a lost UE→DN route and fails if it cannot."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("staged", ROOT / "scripts/k8s/staged.py")
        self.staged = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.staged)

    def drive(self, answers):
        calls = []
        def fake(ns, deployment, container, *command, timeout=180):
            calls.append(command)
            return json.dumps(answers.pop(0)) if command[:3] == ("ip", "-j", "route") else ""
        self.staged.exec_pod = fake
        return calls

    def test_present_route_untouched(self):
        calls = self.drive([[{"dev": "oaitun_ue1", "prefsrc": "10.1.0.3"}]])
        self.staged.ensure_ue_route("10.1.0.3")
        self.assertFalse(any("replace" in c for c in calls))

    def test_lost_route_reinstalled(self):
        calls = self.drive([[{"dev": "eth0", "prefsrc": "10.244.1.82"}], [{"dev": "oaitun_ue1", "prefsrc": "10.1.0.3"}]])
        self.staged.ensure_ue_route("10.1.0.3")
        self.assertEqual(sum("replace" in c for c in calls), 1)

    def test_unfixable_route_fails(self):
        self.drive([[{"dev": "eth0", "prefsrc": "10.244.1.82"}]] * 2)
        with self.assertRaises(self.staged.Failure):
            self.staged.ensure_ue_route("10.1.0.3")

if __name__ == "__main__":
    unittest.main()
