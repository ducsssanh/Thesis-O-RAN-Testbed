import copy, importlib.util, ipaddress, json, pathlib, subprocess, tempfile, unittest
from unittest.mock import patch
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


def module(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


lab = module("lab", ROOT / "scripts/k8s/lab.py")
analyze = module("analyze", ROOT / "scripts/k8s/analyze.py")


class Tests(unittest.TestCase):
    def setUp(self):
        self.v = yaml.safe_load((ROOT / "deploy/k8s/values/minikube.yaml").read_text())

    def test_topology(self):
        lab.validate(self.v)

    def test_overlapping_network(self):
        self.v["global"]["lab"]["networks"]["n3"] = copy.deepcopy(
            self.v["global"]["lab"]["networks"]["n2"]
        )
        with self.assertRaisesRegex(lab.GateError, "Overlapping"):
            lab.validate(self.v)

    def test_host_overlap(self):
        with self.assertRaisesRegex(lab.GateError, "conflict"):
            lab.validate(self.v, [ipaddress.ip_network("172.30.0.0/16")])

    def test_invalid_mode(self):
        self.v["global"]["lab"]["xdpMode"] = "magic"
        with self.assertRaises(lab.GateError):
            lab.validate(self.v)

    def test_wrong_context(self):
        self.v["global"]["lab"]["profile"] = "kubernetes-admin@kubernetes"
        with self.assertRaises(lab.GateError):
            lab.validate(self.v)

    def test_artifact_paths_separate_state_and_evidence(self):
        with tempfile.TemporaryDirectory() as d, patch.object(
            lab, "STATE", pathlib.Path(d)
        ):
            lab.prepare_artifact_dirs()
            self.assertEqual(
                lab.artifact_path("images.json"), pathlib.Path(d) / "state/images.json"
            )
            self.assertEqual(
                lab.artifact_path("bootstrap-server.json"),
                pathlib.Path(d) / "bootstrap/bootstrap-server.json",
            )
            self.assertEqual(
                lab.artifact_path("radio-build.log"),
                pathlib.Path(d) / "build/radio-build.log",
            )
            with self.assertRaises(KeyError):
                lab.artifact_path("unclassified.json")

    def test_helm_reads_overlay_from_state_directory(self):
        args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
        with tempfile.TemporaryDirectory() as d, patch.object(
            lab, "STATE", pathlib.Path(d)
        ), patch.object(lab, "run") as run:
            lab.Lab(args).helm()
            self.assertIn(pathlib.Path(d) / "state/images.yaml", run.call_args.args[0])
            self.assertNotIn(pathlib.Path(d) / "images.yaml", run.call_args.args[0])

    def test_missing_image_does_not_bootstrap(self):
        args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
        with tempfile.TemporaryDirectory() as d, patch.object(
            lab, "STATE", pathlib.Path(d)
        ), patch.object(lab.Lab, "check"), patch.object(lab, "run") as run:
            with self.assertRaisesRegex(lab.GateError, "build"):
                lab.Lab(args).up()
            run.assert_not_called()

    def test_bpf_permission_failure_is_fatal(self):
        args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
        with patch.object(
            lab.Lab, "exec", side_effect=lab.GateError("Operation not permitted")
        ):
            with self.assertRaises(lab.GateError):
                lab.Lab(args).xdp_gate()

    def test_native_is_not_skb(self):
        args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
        with patch.object(
            lab.Lab,
            "exec",
            return_value='[{"xdp":[{"devname":"n3","mode":"driver","id":4}]}]',
        ):
            with self.assertRaises(lab.GateError):
                lab.Lab(args).xdp_gate()

    def test_smf_not_ready_stops(self):
        args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
        with patch.object(lab.Lab, "k", side_effect=lab.GateError("rollout timeout")):
            with self.assertRaises(lab.GateError):
                lab.Lab(args).ready("smf")

    def ue_route_lab(self, routes):
        """Lab whose UE pod answers `ip route get` from `routes` (one per call)."""
        args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
        l = lab.Lab(args)
        calls = []

        def fake(nf, *a, **kw):
            calls.append(a)
            return json.dumps(routes.pop(0)) if a[:3] == ("ip", "-j", "route") else ""

        return l, calls, fake

    def test_ue_route_present_is_untouched(self):
        l, calls, fake = self.ue_route_lab(
            [[{"dev": "oaitun_ue1", "prefsrc": "10.1.0.3"}]]
        )
        with patch.object(lab.Lab, "exec", side_effect=fake):
            l.ensure_ue_route("10.1.0.3")
        self.assertFalse(any("replace" in c for c in calls))

    def test_ue_route_lost_is_reinstalled(self):
        l, calls, fake = self.ue_route_lab(
            [
                [{"dev": "eth0", "prefsrc": "10.244.1.82"}],
                [{"dev": "oaitun_ue1", "prefsrc": "10.1.0.3"}],
            ]
        )
        with patch.object(lab.Lab, "exec", side_effect=fake):
            l.ensure_ue_route("10.1.0.3")
        replace = [c for c in calls if "replace" in c]
        self.assertEqual(len(replace), 1)
        self.assertIn(l.c["networks"]["n6"]["subnet"], replace[0])

    def test_ue_route_unfixable_fails(self):
        l, _, fake = self.ue_route_lab(
            [[{"dev": "eth0", "prefsrc": "10.244.1.82"}]] * 2
        )
        with patch.object(lab.Lab, "exec", side_effect=fake):
            with self.assertRaisesRegex(lab.GateError, "oaitun_ue1"):
                l.ensure_ue_route("10.1.0.3")

    def test_xapp_no_samples(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "kpm.csv"
            p.write_text("E2 Node ID,UE ID\n")
            with self.assertRaisesRegex(ValueError, "No KPM"):
                analyze.kpm_gate(p)

    def test_report_missing_or_rejected(self):
        cfg = [["iso", "1", "50", "12", "1", "1", "1", "1000", "", ""]]
        with self.assertRaisesRegex(ValueError, "threshold"):
            analyze.pfcp_gate(cfg, [], [])
        report = [
            ["1", "", "", "a", "b", "56", "1", "1", "200", "100", "100", "", "", ""]
        ]
        with self.assertRaisesRegex(ValueError, "accepted"):
            analyze.pfcp_gate(
                cfg,
                report,
                [["1", "a", "b", "56", "99", ""], ["2", "b", "a", "57", "99", "64"]],
            )

    def test_periodic_only_urr_config(self):
        # smf.upfs[].config.urr with only PERIO (no volume threshold)
        cfg = [["iso", "1", "50", "12", "1", "1", "0", "", "", "", "1"]]
        with self.assertRaisesRegex(ValueError, "period"):
            analyze.pfcp_gate(cfg, [], [])
        with self.assertRaisesRegex(ValueError, "threshold or measurement"):
            analyze.pfcp_gate([["iso", "1", "50", "12", "1", "1", "0", "", "", "", ""]], [], [])

    def test_response_transaction_matching(self):
        cfg = [["iso", "1", "50", "12", "1", "1", "1", "1000", "", ""]]
        report = [
            ["1", "", "", "a", "b", "56", "1", "1", "200", "100", "100", "", "", ""]
        ]
        with self.assertRaises(ValueError):
            analyze.pfcp_gate(
                cfg,
                report,
                [["1", "a", "b", "56", "99", ""], ["2", "b", "a", "57", "98", "1"]],
            )

    def test_render_security_and_interfaces(self):
        args = [
            "helm",
            "template",
            "oai-lab",
            str(ROOT / "deploy/k8s/chart"),
            "-f",
            str(ROOT / "deploy/k8s/values/minikube.yaml"),
            "--set",
            ",".join("oai-" + n + ".enabled=true" for n in lab.NFS)
            + ",seedEnabled=true,xappEnabled=true",
        ]
        docs = list(yaml.safe_load_all(subprocess.check_output(args, text=True)))
        cm = next(
            d
            for d in docs
            if d
            and d["kind"] == "ConfigMap"
            and d["metadata"]["name"] == "oai-lab-config"
        )
        c = yaml.safe_load(cm["data"]["config.yaml"])
        self.assertEqual(c["upf"]["support_features"]["xdp_mode"], "skb")
        self.assertFalse(c["amf"]["support_features_options"]["enable_simple_scenario"])
        self.assertTrue(c["register_nf"]["general"])
        self.assertEqual(len(c["smf"]["upfs"]), 1)
        self.assertNotIn("DROP DATABASE", cm["data"]["schema.sql"])
        self.assertNotIn("INSERT INTO", cm["data"]["schema.sql"])
        for d in docs:
            if d and d["kind"] == "Deployment":
                p = d["spec"]["template"]["spec"]
                self.assertFalse(p.get("hostNetwork", False))
                self.assertEqual(d["spec"]["strategy"]["type"], "Recreate")
                for cont in p.get("initContainers", []) + p["containers"]:
                    if cont.get("securityContext", {}).get("privileged"):
                        self.assertEqual(d["metadata"]["name"], "oai-upf")
                if d["metadata"]["name"] == "oai-upf":
                    nets = json.loads(
                        d["spec"]["template"]["metadata"]["annotations"][
                            "k8s.v1.cni.cncf.io/networks"
                        ]
                    )
                    self.assertEqual({n["interface"] for n in nets}, {"n3", "n4", "n6"})
            if d and d["kind"] == "NetworkAttachmentDefinition":
                n = json.loads(d["spec"]["config"])
                self.assertEqual(n["type"], "bridge")
                self.assertNotIn("gateway", n["ipam"])


if __name__ == "__main__":
    unittest.main()
