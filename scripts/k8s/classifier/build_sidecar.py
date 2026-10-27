#!/usr/bin/env python3
"""Build the xApp classifier sidecar image and lock it (artifacts/k8s/state/sidecar-image.json).
Since 2026-10-27 the image holds the stub classifier (placeholder until a DRL policy replaces it).

  python3 scripts/k8s/classifier/build_sidecar.py [--load]

Tag = sha256 of the Dockerfile and the sidecar source (16 hex). --load also puts the
image into minikube (staged.ensure_image; clean the tarballs afterwards, see the handoff).
"""
import argparse, hashlib, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/k8s"))
INPUTS = ["deploy/k8s/images/Dockerfile.sidecar", "scripts/k8s/classifier/stub_classifier.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true")
    a = ap.parse_args()
    files = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in INPUTS}
    digest = hashlib.sha256("".join(f + files[f] for f in INPUTS).encode()).hexdigest()[:16]
    image = "oai-lab-sidecar:" + digest
    subprocess.run(["docker", "build", "-f", str(ROOT / INPUTS[0]), "-t", image, str(ROOT)], check=True)
    info = json.loads(subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True, text=True).stdout)[0]
    lock = ROOT / "artifacts/k8s/state/sidecar-image.json"
    lock.write_text(json.dumps({"image": image, "id": info["Id"], "sourceHash": digest, "inputs": files}, indent=2) + "\n")
    print("Built " + image)
    if a.load:
        import staged
        staged.ensure_image(image)
        print("Loaded into minikube")


if __name__ == "__main__":
    main()
