# Repo Transition Plan

This repository is transitioning away from "AWS Spot interruption prediction"
as its primary product claim.

The retained core is the byte-stream structural manifold engine plus the live
telemetry bridge. The next target problem is Kubernetes workload health and
failure-risk detection, because it offers better signals, clearer labels, and a
more honest evaluation path than public Spot price history.

## Started In This Slice

- Local `pytest` collection is pinned to this checkout instead of leaking to a
  sibling `scripts` package.
- Top-level docs now mark the Spot replay as legacy scope.
- A K8s workload-health bridge config exists for the next validation step.
- A new `scripts/telemetry_replay` module now holds generic action-to-event
  attribution logic extracted from the Spot replay path.

## Decision

- Keep the generic telemetry engine, encoder, and bridge.
- Treat `scripts/spotfsm` as a legacy replay package until a generic replay
  surface replaces it.
- Do not invest further in `price_spike` proxy events as the main evaluation
  story.
- Validate one labeled workload-health problem before renaming the repository.

## What Stays

- `src/core`: structural byte-stream engine and pybind extension.
- `scripts/research/regime_manifold`: generic telemetry encoding and decoding.
- `scripts/telemetry_bridge`: Prometheus and CloudWatch polling path.
- Existing tests around the bridge and encoder.

## What Becomes Legacy

- `scripts/spotfsm`: AWS Spot-specific loaders, replay harness, and policy
  framing.
- `config/telemetry_policy.example.yaml`: legacy replay example.
- Spot-focused README claims and replay conclusions.

## What Must Be Added

- A generic replay/event-ingestion surface that does not assume Spot prices.
- Kubernetes-oriented configs and docs for collecting candidate signals.
- Workload-health event loaders for real outcomes such as OOM kills, evictions,
  restart bursts, or incident windows.
- Baselines that match the new domain instead of price-only migration logic.

## Transition Phases

### Phase 0: Stabilize The Current Tree

- Add package boundaries so tests import from this repo reliably.
- Mark SpotFSM as a legacy/example module in top-level docs.
- Add K8s-oriented bridge configs and transition docs.

Acceptance criteria:

- `pytest` collects from this checkout without import leakage.
- README no longer presents AWS Spot replay as the future product thesis.

### Phase 1: K8s Signal Validation

- Use Prometheus to poll 3-5 candidate workload-health signals for one target
  namespace or workload.
- Verify each query aggregates to a single time series per metric.
- Record short historical windows and inspect manifold signatures around known
  bad periods.

Candidate signals:

- CPU throttle ratio
- Memory pressure ratio
- Restart velocity
- Pending pod pressure

Acceptance criteria:

- At least one workload has a reproducible signal set and a labeled failure
  class worth replaying.

### Phase 2: Generic Replay Surface

- Extract generic event/replay types from the Spot-specific package.
- Support telemetry streams plus labeled events without embedding domain names
  like `price` or `interruption`.
- Keep the operator/policy comparison structure, but rename it for generic
  workload actions.

Acceptance criteria:

- Replay code can run on non-Spot telemetry without adapter hacks.

### Phase 3: Honest K8s Evaluation

- Ingest real events such as `OOMKilled`, `Evicted`, restart cascades, or
  incident windows from cluster data.
- Compare structural policy against simple reactive baselines.
- Measure lead time, avoidance/recall, and false-positive burden.

Acceptance criteria:

- Results are based on real labels rather than proxy spikes.
- The new domain shows a credible lead-time advantage or the pivot is aborted.

### Phase 4: Repo Rename And Archive

- Rename the repository only after Phase 3 produces a credible result.
- Move `scripts/spotfsm` under a `legacy/` or `archive/` path if still needed.
- Remove or relocate stale trading configs that no longer belong in the main
  story.

Acceptance criteria:

- Top-level naming matches the validated problem, not the discarded thesis.

## Immediate Backlog

1. Choose one target namespace/workload and tune the K8s PromQL selectors for it.
2. Capture a first real telemetry sample with `make bridge-once-k8s`.
3. Extract generic replay/event types beyond attribution helpers.
4. Add a real K8s event loader for OOM, eviction, or restart-incident labels.
