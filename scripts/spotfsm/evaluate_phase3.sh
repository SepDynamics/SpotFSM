#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "SpotFSM Phase 3: Held-out Evaluation & Honest Baselines"
echo "=========================================================="

TRAIN_MONTH="2024-01"
TEST_MONTH="2024-02"
CONFIG="config/telemetry_policy.example.yaml"
LABELS_CSV="data/raw/interruption_labels_test.csv" # Real labels to be dropped here

echo "[1/2] Simulating Optimization/Calibration on ${TRAIN_MONTH} (Train Set)"
# We run the replay on the train set (representing the in-sample tuning phase)
python -m scripts.spotfsm.replay \
    --config $CONFIG \
    --dataset-source zenodo_tsv_zst \
    --download-zenodo-month $TRAIN_MONTH \
    --output-dir output/phase3/train \
    --top-series-limit 5

echo "[2/2] Running Held-out Evaluation on ${TEST_MONTH} (Test Set) with Honest Baselines"
# Here we test the frozen parameters against a completely unseen month,
# comparing the structural policy continuously against RollingZScore, Random, and AlwaysMigrate.
#
# IMPORTANT: When the real EventBridge dataset is available, uncomment the --interruption-events-csv line.

python -m scripts.spotfsm.replay \
    --config $CONFIG \
    --dataset-source zenodo_tsv_zst \
    --download-zenodo-month $TEST_MONTH \
    --output-dir output/phase3/test \
    # --interruption-events-csv $LABELS_CSV

echo "Evaluation complete. Summaries comparing SpotFSM vs Random vs ZScore are in output/phase3/test/"
