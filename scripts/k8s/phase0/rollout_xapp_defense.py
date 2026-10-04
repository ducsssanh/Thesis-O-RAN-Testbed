#!/usr/bin/env python3
"""Roll out the locked xApp build together with global.lab.defense.xapp.

`lab.sh rollout xapp` keeps --reuse-values, so a defense setting changed in
deploy/k8s/values/minikube.yaml would not reach the pod; this passes it
explicitly. Usage: rollout_xapp_defense.py   (image from xapp-image.json)
"""
import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import staged as s  # noqa: E402

image = json.loads((s.STATE / "state/xapp-image.json").read_text())["image"]
cfg = yaml.safe_load((s.DEPLOY / "values/minikube.yaml").read_text())["global"]["lab"]["defense"]["xapp"]
s.ensure_image(image)
s.helm("near-rt-ric", "upgrade", "near-rt-ric", s.DEPLOY / "charts/near-rt-ric", "--reuse-values",
       "--set", "xappImage=" + image, "--set-json", "global.lab.defense.xapp=" + json.dumps(cfg),
       "--timeout", "5m", timeout=360)
s.ready("near-rt-ric", "deployment", "oai-lab-xapp")
print("xApp " + image + " with defense config " + json.dumps(cfg))
