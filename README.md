# SpotFSM

SpotFSM is an Autonomous Infrastructure Guardrail for volatile infrastructure telemetry, starting with AWS Spot instance management.

The core `ByteStreamManifold` engine turns rolling metric windows into structural signatures and a hazard score (`lambda_hazard`). Instead of reacting to a hard threshold like "price > X", the system watches for structural rupture in the stream itself and raises migration pressure before the underlying market or cluster fully destabilizes.

## Status

- Phase 1 complete: the C++ manifold engine was isolated as `manifold_engine`, and the Python encoder was generalized from market candles to arbitrary telemetry.
- Phase 2 complete: SpotFSM can poll Prometheus and CloudWatch metrics through the bridge in [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge).
- Phase 3 implemented: SpotFSM now includes a real-data replay harness, a stateful migration policy, and a simulated operator in [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm).

## Phase 2 Bridge

The bridge lives under [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge) and does three things:

1. Pulls a fixed-step metric series from Prometheus `query_range` or CloudWatch `GetMetricData`.
2. Converts the series into `TelemetryPoint` windows using z-score and velocity bucketization.
3. Runs the latest window through `manifold_engine` and emits the current signature, hazard, and full encoded window payload as JSON.

Prometheus queries must resolve to a single time series. If a query returns multiple series, aggregate in PromQL first so the bridge is fed one metric stream per `metric_id`.

## Phase 3 Replay

Phase 3 adds four pieces under [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm):

1. `datasets.py`: loads real AWS Spot price history from public Zenodo `.tsv.zst` archives or AWS CLI `describe-spot-price-history` JSON.
2. `policy.py`: evaluates structural hazard, rupture, coherence, and adaptive deltas to decide `STABLE`, `OBSERVE`, or `MIGRATE`.
3. `operator.py`: simulates `drain_node` / `request_new_instance` behavior and persists replay state in memory or Redis/Valkey.
4. `replay.py`: runs a historical series through the encoder and policy, compares against a reactive price-only baseline, and writes CSV/JSON artifacts.

The replay event metric is explicit: this harness infers future `price_spike` events from public price history. It does not claim to observe actual AWS interruption notices.

## Quick Start

Install dependencies and build the extension:

```bash
make install
make build-manifold-engine
```

Run a bridge poll:

```bash
make bridge-once
```

List volatile public Spot series from a downloaded monthly archive:

```bash
make list-spot-series
```

Run the real-data replay using [config/telemetry_policy.example.yaml](/sep/SpotFSM/config/telemetry_policy.example.yaml):

```bash
make replay-real
```

The replay writes a decision trace CSV, a summary JSON report, and a simulated operator log under `output/replay/`.

## Current Real-Data Example

The example policy config targets the public January 2024 archive and replays:

- `aps1-az3`
- `inf2.8xlarge`
- `Linux/UNIX`

With the current example calibration, the structural policy is materially more selective than the reactive baseline on that stream while still catching most inferred spike events. The generated report lives at `output/replay/spot_aps1-az3_inf2.8xlarge_linux_unix_summary.json` after running the replay.

## Repo Layout

- [src/core](/sep/SpotFSM/src/core): C++ structural manifold engine and pybind bindings.
- [scripts/research/regime_manifold](/sep/SpotFSM/scripts/research/regime_manifold): generic telemetry encoder, decoder, analytics, and runtime loader.
- [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge): Phase 2 connectors, service layer, and polling CLI.
- [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm): Phase 3 loader, policy, replay harness, and operator.
- [tests/test_telemetry_bridge.py](/sep/SpotFSM/tests/test_telemetry_bridge.py): bridge regression tests.
- [tests/test_spotfsm_phase3.py](/sep/SpotFSM/tests/test_spotfsm_phase3.py): Phase 3 policy and dataset tests.

## Remaining Work

- Phase 3 extension: backtest against interruption labels if a labeled interruption dataset is added.
- Phase 4: live visualization and cluster demonstration path.
