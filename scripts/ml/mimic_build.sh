#!/usr/bin/env bash
# Episodes with the "mimic" KPM scenario (benign KPM replay, donors from other runs on the same split side) and the run-level gate
# (option a), masked and unmasked (KPM-only baseline). Status per job in artifacts/clf/jobs/mimic_*.status.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; O=artifacts/clf/mimic; J=artifacts/clf/jobs; mkdir -p $O $J
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
export EP_MIMIC=1 EP_MIMIC_POOL=all EP_GATE=run
for v in m m_nomask; do
  NM=""; [ $v = m_nomask ] && NM="EP_NOMASK=1"
  job mimic_main_$v "$NM EP_SPLIT=artifacts/clf/split_final.json $P scripts/ml/clf_features.py research/datasets/oran_flooding_twin/rows.parquet $O/episodes31_$v.pkl" &
  job mimic_l2_$v "$NM EP_SPLIT=artifacts/clf/split_final.json $P scripts/ml/clf_features.py research/datasets/oran_flooding_twin_l2/rows.parquet $O/episodes31_l2_$v.pkl" &
  job mimic_live_$v "$NM EP_SPLIT=artifacts/clf/live/split_live.json $P scripts/ml/clf_features.py artifacts/clf/live/rows.parquet $O/episodes31_live_$v.pkl" &
done
wait
grep -H . $J/mimic_*.status
