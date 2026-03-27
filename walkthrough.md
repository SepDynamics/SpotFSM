# SpotFSM Walkthrough

This walkthrough reflects the current post-extraction state of the repository.

## Phase 1 Recap

- The C++ byte-stream manifold engine was isolated under [src/core](/sep/SpotFSM/src/core).
- The Python codec was generalized into `TelemetryManifoldEncoder`, replacing candle-specific ATR and delta logic with velocity and z-score bucketization.
- The runtime now loads the compiled `manifold_engine` extension from the local build tree when it is not already importable from the environment.
- The old decoder and analytics surfaces were repaired so they match the telemetry schema instead of the removed trading schema.

## Phase 2 Added

- A bridge package under [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge) supports:
  `Prometheus` range queries via `/api/v1/query_range`
  `CloudWatch` metric fetches via `GetMetricData`
- A polling CLI at [scripts/telemetry_bridge/cli.py](/sep/SpotFSM/scripts/telemetry_bridge/cli.py) emits one JSON record per configured metric.
- A sample bridge config lives at [config/telemetry_bridge.example.yaml](/sep/SpotFSM/config/telemetry_bridge.example.yaml).

## Phase 3 Added

- Real-data loaders in [scripts/spotfsm/datasets.py](/sep/SpotFSM/scripts/spotfsm/datasets.py) support:
  public Zenodo monthly `.tsv.zst` archives
  AWS CLI `describe-spot-price-history` JSON
- The stateful migration policy in [scripts/spotfsm/policy.py](/sep/SpotFSM/scripts/spotfsm/policy.py) uses hazard, rupture, coherence, entropy gap, and rolling deltas to avoid simple threshold flapping.
- The simulated operator in [scripts/spotfsm/operator.py](/sep/SpotFSM/scripts/spotfsm/operator.py) logs `MIGRATE` actions and persists replay state to memory or Redis.
- The replay harness in [scripts/spotfsm/replay.py](/sep/SpotFSM/scripts/spotfsm/replay.py) compares SpotFSM against a reactive price-only baseline and writes CSV/JSON artifacts.
- A sample replay config lives at [config/telemetry_policy.example.yaml](/sep/SpotFSM/config/telemetry_policy.example.yaml).

## Real-Data Verification

- A real public archive was downloaded locally: `data/raw/2024-01.tsv.zst`.
- The current example replay uses `aps1-az3 / inf2.8xlarge / Linux/UNIX`.
- The generated summary report is `output/replay/spot_aps1-az3_inf2.8xlarge_linux_unix_summary.json`.
- The generated decision trace is `output/replay/spot_aps1-az3_inf2.8xlarge_linux_unix_decisions.csv`.

## Test Coverage

- Bridge parsing and service behavior are covered by [tests/test_telemetry_bridge.py](/sep/SpotFSM/tests/test_telemetry_bridge.py).
- Policy behavior, AWS JSON loading, Zenodo `.tsv.zst` parsing, and spike-event detection are covered by [tests/test_spotfsm_phase3.py](/sep/SpotFSM/tests/test_spotfsm_phase3.py).

## Next Step

Phase 4 should visualize the replay and live bridge outputs together:

- expose hazard and operator state in a dashboard stream
- surface policy explanations alongside migration decisions
- attach real cluster actions once K8s and cloud credentials are available
