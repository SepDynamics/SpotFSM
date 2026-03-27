# SpotFSM

This repository is in transition from an AWS Spot-specific experiment into a
generic telemetry regime and failure-risk workbench.

The retained core is the `ByteStreamManifold` engine plus the telemetry bridge:
rolling windows are encoded into structural signatures and a hazard score
(`lambda_hazard`) so the system can detect regime shifts before a simple raw
threshold would fire.

## Transition Status

- The generic engine and bridge are retained.
- The AWS Spot replay in [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm) is now a
  legacy/example package, not the long-term repo thesis.
- The next validation target is Kubernetes workload health using real workload
  signals and real failure labels.
- The transition plan lives in
  [docs/transition_plan.md](/sep/SpotFSM/docs/transition_plan.md).

## Core Bridge

The bridge lives under [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge) and does three things:

1. Pulls a fixed-step metric series from Prometheus `query_range` or CloudWatch `GetMetricData`.
2. Converts the series into `TelemetryPoint` windows using z-score and velocity bucketization.
3. Runs the latest window through `manifold_engine` and emits the current signature, hazard, and full encoded window payload as JSON.

Prometheus queries must resolve to a single time series. If a query returns multiple series, aggregate in PromQL first so the bridge is fed one metric stream per `metric_id`.

## Legacy Spot Replay

The legacy replay package under [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm)
still contains four useful building blocks:

1. `datasets.py`: loads AWS Spot price history from public Zenodo `.tsv.zst`
   archives or AWS CLI `describe-spot-price-history` JSON.
2. `policy.py`: evaluates structural hazard, rupture, coherence, and adaptive deltas to decide `STABLE`, `OBSERVE`, or `MIGRATE`.
3. `operator.py`: simulates `drain_node` / `request_new_instance` behavior and persists replay state in memory or Redis/Valkey.
4. `replay.py`: runs a historical series through the encoder and policy,
   compares against a reactive price-only baseline, and writes CSV/JSON
   artifacts.

That replay remains explicit about its limitation: it infers future
`price_spike` events from public price history. It does not claim to observe
actual AWS interruption notices, and it is no longer the recommended direction
for the repo.

## Next Target

The current pivot target is Kubernetes workload health. The bridge already
supports the data path needed to start validating that problem against real
Prometheus metrics.

An initial K8s bridge config lives at
[config/k8s_workload_health_bridge.example.yaml](/sep/SpotFSM/config/k8s_workload_health_bridge.example.yaml).
It focuses on:

- CPU throttle ratio
- Memory pressure ratio
- Restart velocity
- Pending pod pressure

The config intentionally aggregates each query to a single series, because the
current bridge expects one stream per `metric_id`.

## Quick Start

Install dependencies and build the extension:

```bash
make install
make build-manifold-engine
```

Run a generic bridge poll:

```bash
make bridge-once
```

Run the K8s-oriented bridge example:

```bash
make bridge-once-k8s
```

The example queries are placeholders for a target namespace/workload. Adjust
the label selectors before using them against a real cluster.

## Legacy Replay Example

Run the legacy Spot replay using
[config/telemetry_policy.example.yaml](/sep/SpotFSM/config/telemetry_policy.example.yaml):

```bash
make replay-real
```

The legacy replay writes a decision trace CSV, a summary JSON report, and a
simulated operator log under `output/replay/`.

## Repo Layout

- [src/core](/sep/SpotFSM/src/core): C++ structural manifold engine and pybind bindings.
- [scripts/research/regime_manifold](/sep/SpotFSM/scripts/research/regime_manifold): generic telemetry encoder, decoder, analytics, and runtime loader.
- [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge): generic connectors, service layer, and polling CLI.
- [scripts/telemetry_replay](/sep/SpotFSM/scripts/telemetry_replay): generic replay analysis helpers extracted from the legacy Spot path.
- [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm): legacy Spot-specific replay and policy package retained during transition.
- [docs/transition_plan.md](/sep/SpotFSM/docs/transition_plan.md): phased repo transition plan.
- [config/k8s_workload_health_bridge.example.yaml](/sep/SpotFSM/config/k8s_workload_health_bridge.example.yaml): initial K8s workload-health bridge config.
- [tests/test_telemetry_bridge.py](/sep/SpotFSM/tests/test_telemetry_bridge.py): bridge regression tests.
- [tests/test_spotfsm_phase3.py](/sep/SpotFSM/tests/test_spotfsm_phase3.py): Phase 3 policy and dataset tests.

## Remaining Work

- Extract a generic replay/event-ingestion layer out of the Spot-specific
  package.
- Expand the new generic replay module beyond action-to-event attribution.
- Validate one labeled K8s workload-health problem before renaming the repo.
- Archive or relocate stale trading-era configs once the new direction is
  proven.
