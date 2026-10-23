#!/usr/bin/env python3
"""Build the v5 live model sidecar image and lock it (artifacts/k8s/state/sidecar-image.json).

  python3 scripts/k8s/classifier/build_sidecar.py [--load]

Tag = sha256 of the Dockerfile, the 3 Python files and the frozen models (16 hex). --load also puts the
image into minikube (staged.ensure_image; clean the tarballs afterwards, see the handoff).
"""
import argparse, hashlib, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/k8s"))
INPUTS = ["deploy/k8s/images/Dockerfile.sidecar", "scripts/ml/defence_engine_v4.py", "scripts/ml/prep_v4_windows.py",
          "scripts/k8s/classifier/sidecar_v4.py"] + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "artifacts/ml/v4/models").iterdir())


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
