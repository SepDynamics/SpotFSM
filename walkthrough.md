# SpotFSM Walkthrough

This walkthrough reflects the current post-extraction state of the repository.

## Phase 1 Recap

- The C++ byte-stream manifold engine was isolated under [src/core](/sep/SpotFSM/src/core).
- The Python codec was generalized into `TelemetryManifoldEncoder`, replacing candle-specific ATR and delta logic with velocity and z-score bucketization.
- The runtime now loads the compiled `manifold_engine` extension from the local build tree when it is not already importable from the environment.
- The old decoder and analytics surfaces were repaired so they match the telemetry schema instead of the removed trading schema.

## Phase 2 Added

- A new bridge package under [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge) supports:
  `Prometheus` range queries via `/api/v1/query_range`
  `CloudWatch` metric fetches via `GetMetricData`
- A polling CLI at [scripts/telemetry_bridge/cli.py](/sep/SpotFSM/scripts/telemetry_bridge/cli.py) emits one JSON record per configured metric.
- A sample config at [config/telemetry_bridge.example.yaml](/sep/SpotFSM/config/telemetry_bridge.example.yaml) shows one Prometheus spot-price stream and one CloudWatch workload-pressure stream.
- The root [Makefile](/sep/SpotFSM/Makefile) now exposes `build-manifold-engine`, `bridge-once`, `bridge-poll`, and `test`.

## Verification Scope

- Connector parsing is covered by [tests/test_telemetry_bridge.py](/sep/SpotFSM/tests/test_telemetry_bridge.py).
- Bridge service behavior is covered for both successful encoding and insufficient-window cases.
- Decoder import and bucket reconstruction are covered so the generalized schema does not regress back to the removed candle format.

## Next Step

Phase 3 should attach an operator policy to the bridge output:

- Define hazard thresholds and dwell logic for `TRIGGER_MIGRATE`.
- Feed the bridge with historical spot price / interruption data for offline replay.
- Compare hazard-led migrations against a naive threshold baseline on uptime and cost retention.
