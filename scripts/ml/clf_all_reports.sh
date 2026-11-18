#!/usr/bin/env bash
# Out-of-fold reports for every finished configuration (selection only; no test numbers).
cd "$(dirname "$0")/../.."
for d in artifacts/clf/R0*/; do r=$(basename $d); n=$(ls $d/*/scores.pkl 2>/dev/null | wc -l); [ "$n" -eq 15 ] || continue
  .venv-ml/bin/python scripts/ml/report_clf.py "$r" "$d" --boot 200 --json research/clf/${r}_oof.json > research/clf/${r}_oof.txt 2>&1; done
