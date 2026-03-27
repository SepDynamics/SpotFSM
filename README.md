# SpotFSM

SpotFSM is an Autonomous Infrastructure Guardrail for volatile infrastructure telemetry, starting with AWS Spot instance management.

The core `ByteStreamManifold` engine turns rolling metric windows into structural signatures and a hazard score (`lambda_hazard`). Instead of reacting to a hard threshold like "price > X", the system watches for structural rupture in the stream itself and raises migration pressure before the underlying market or cluster fully destabilizes.

## Status

- Phase 1 complete: the C++ manifold engine was isolated as `manifold_engine`, and the Python encoder was generalized from market candles to arbitrary telemetry.
- Phase 2 implemented in-repo: SpotFSM now has a pluggable telemetry bridge for `Prometheus` and `CloudWatch`, plus a polling CLI that emits the latest encoded window per metric as JSON.
- Phase 3 and 4 remain: operator actions, historical backtesting against spot records, and a live demonstration layer.

## Phase 2 Bridge

The bridge lives under [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge) and does three things:

1. Pulls a fixed-step metric series from Prometheus `query_range` or CloudWatch `GetMetricData`.
2. Converts the series into `TelemetryPoint` windows using z-score and velocity bucketization.
3. Runs the latest window through `manifold_engine` and emits a JSON record containing the current signature, hazard, and full encoded window payload.

Prometheus queries must resolve to a single time series. If a query returns multiple series, aggregate in PromQL first so the bridge is fed one metric stream per `metric_id`.

## Quick Start

Install dependencies and build the extension:

```bash
make install
make build-manifold-engine
```

Copy or edit [config/telemetry_bridge.example.yaml](/sep/SpotFSM/config/telemetry_bridge.example.yaml) so the metrics reflect your environment, then run a single bridge poll:

```bash
make bridge-once
```

Or run it continuously:

```bash
make bridge-poll
```

The CLI entrypoint is [scripts/telemetry_bridge/cli.py](/sep/SpotFSM/scripts/telemetry_bridge/cli.py) and prints JSONL to stdout. If `output_path` is set in the config, the same records are appended to disk for later analysis.

## Example Output

Each poll emits one record per configured metric:

```json
{
  "metric_id": "spot_price_estimate",
  "provider": "prometheus",
  "sample_count": 96,
  "current_value": 0.274,
  "window_ready": true,
  "latest_signature": "c0.603_s0.000_e0.579",
  "latest_hazard": 0.5726,
  "error": null
}
```

If a source returns too few samples to fill one manifold window, the record is still emitted with `window_ready: false` and a descriptive error.

## Repo Layout

- [src/core](/sep/SpotFSM/src/core): C++ structural manifold engine and pybind bindings.
- [scripts/research/regime_manifold](/sep/SpotFSM/scripts/research/regime_manifold): generic telemetry encoder, decoder, analytics, and runtime loader.
- [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge): Phase 2 connectors, service layer, and polling CLI.
- [tests/test_telemetry_bridge.py](/sep/SpotFSM/tests/test_telemetry_bridge.py): bridge and codec regression tests.

## Remaining Work

- Phase 3: operator policy that translates hazard into `TRIGGER_MIGRATE` or equivalent workload action.
- Phase 3: historical backtester against AWS spot price and interruption datasets.
- Phase 4: live visualization and cluster demonstration path.
