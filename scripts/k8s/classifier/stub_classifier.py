#!/usr/bin/env python3
"""Stand-in for the model sidecar of the xApp classifier (plan Phase X).

Speaks the classifier interface (design 5.6): POST /classify with
{"supi", "since_seq", "window": [feature vectors]} -> {"label", "score",
"layer", "kind", "reason"}. Runs on the xApp loopback; Gate X uses it to
check the external path and the fallback to the rules.
Since 2026-10-27 it is also the placeholder of the model sidecar in the xApp pod (the GBDT sidecar was removed;
a DRL policy will plug into the same interface). POST /mode and /reset (sent by the harness) are acknowledged;
GET /healthz and /state answer {"ok": true, "version": "stub"}.
Usage: stub_classifier.py [--port 8091] [--attack SUPI ...] [--mode answer|unknown|sleep]
  answer   attack for the SUPIs given, benign for the others
  unknown  always "unknown" (the xApp falls back to its rules)
  sleep    answer after 2 s (beyond the xApp timeout)
Every request is appended to /tmp/stub_classifier.jsonl.
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8091)
ap.add_argument("--attack", nargs="*", default=[])
ap.add_argument("--mode", choices=["answer", "unknown", "sleep"], default="answer")
args = ap.parse_args()


class Handler(BaseHTTPRequestHandler):
    def reply(self, ans):
        body = json.dumps(ans).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply({"ok": True, "version": "stub", "mode": args.mode})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path in ("/mode", "/reset"):
            return self.reply({"ok": True, "version": "stub"})
        with open("/tmp/stub_classifier.jsonl", "a") as f:
            f.write(json.dumps({"at": time.time(), "supi": req.get("supi"), "n": len(req.get("window", [])),
                                "since_seq": req.get("since_seq")}) + "\n")
        if args.mode == "sleep":
            time.sleep(2)
        if args.mode == "unknown":
            ans = {"label": "unknown"}
        elif req.get("supi") in args.attack:
            ans = {"label": "attack", "score": 0.99, "layer": "ran", "kind": "stub_attack", "reason": "stub: listed SUPI"}
        else:
            ans = {"label": "benign", "score": 0.01, "layer": "ran"}
        self.reply(ans)

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
