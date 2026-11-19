#!/usr/bin/env bash
# Run one configuration over 5 folds x 3 seeds. Usage: run_clf.sh <name> <parallel> <threads> <train_clf args...>
set -u
name=$1; par=$2; thr=$3; shift 3
out=artifacts/clf/$name; mkdir -p "$out"
for f in 0 1 2 3 4; do for s in 0 1 2; do echo "$f $s"; done; done | \
  xargs -P "$par" -L 1 bash -c '[ -f '"$out"'/fold$0_seed$1/scores.pkl ] || .venv-ml/bin/python scripts/ml/train_clf.py --fold $0 --seed $1 --threads '"$thr"' --out '"$out"'/fold$0_seed$1 '"$*"' >> '"$out"'/log.txt 2>&1'
echo "finished $name $(ls $out/*/scores.pkl 2>/dev/null | wc -l)/15" >> "$out/log.txt"
