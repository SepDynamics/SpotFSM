# Repo Transition Plan

This repository is transitioning away from AWS Spot and Kubernetes
workload-health framing as its primary product claim.

The retained core is the structural manifold engine plus the live telemetry
bridge. The active target is **LLM API health monitoring and preemptive traffic
routing**, because it matches the existing bridge architecture and offers public
incident labels for replay.

## Started In This Slice

- Removed the stale trading-era configs that no longer belong in the main tree.
- Added a shared LLM routing config and a new `scripts/llm_probe` package for
  raw probe collection.
- Extended the generic bridge to read `llm_probe` JSONL as a first-class
  telemetry source.
- Reframed top-level docs and Make targets around LLM API health.

## Decision

- Keep the generic telemetry engine, encoder, and bridge.
- Keep `scripts/spotfsm` only as a legacy replay/operator reference.
- Stop presenting Kubernetes workload health as the next repo thesis.
- Validate lead-time advantage against real provider incidents before any repo
  rename.

## What Stays

- `src/core`: structural byte-stream engine and pybind extension.
- `scripts/research/regime_manifold`: generic telemetry encoding and decoding.
- `scripts/telemetry_bridge`: live polling and manifold window generation.
- `scripts/telemetry_replay`: generic action-to-event attribution helpers.
- Existing bridge and legacy replay tests.

## What Becomes Legacy

- `scripts/spotfsm`: AWS Spot-specific loaders, replay harness, and policy
  framing.
- `config/telemetry_policy.example.yaml`: legacy replay example.
- Spot-specific docs, claims, and evaluation framing.

## What Must Be Added

- A provider-routing policy that converts structural hazard into primary/fallback
  routing actions.
- Replay ingestion for public incident windows from provider status pages.
- Baselines that match the new domain, such as timeout/error-only routing.
- Longer-running probe collection to build a real replay corpus.

## Transition Phases

### Phase 0: Repo Cleanup

- Remove dead trading configs and unrelated research leftovers.
- Mark `scripts/spotfsm` as legacy in docs instead of active scope.
- Replace the K8s forward plan with the LLM routing thesis.

Acceptance criteria:

- Top-level docs no longer point to Kubernetes as the next validation target.
- The tree does not carry the obviously stale trading configs in active scope.

### Phase 1: LLM API Probe Collection

- Poll each configured provider/model with a short deterministic prompt.
- Record `ttft_ms`, `total_latency_ms`, `tps`, `error`, and token usage as JSONL.
- Keep the raw probe output under `output/probes/` as the future replay corpus.

Acceptance criteria:

- `make probe-once` writes valid probe records for configured targets.
- Probe JSONL can be accumulated over time without schema changes.

### Phase 2: Bridge Integration

- Treat each `provider.model.signal` combination as one metric stream.
- Read raw probe JSONL through the existing `TelemetrySource` surface.
- Reuse the current encoder, manifold engine, and bridge service unchanged.

Acceptance criteria:

- `make bridge-once` can emit structural observations from probe history.
- No domain-specific changes are required in `src/core` or the encoder.

### Phase 3: Routing Policy

- Adapt the legacy migration policy into provider-routing semantics.
- Map `STABLE` to primary, `OBSERVE` to prepare fallback, and `MIGRATE` to route.
- Add cooldown and recovery logic so the router does not flap between providers.

Acceptance criteria:

- Structural routing decisions can be simulated against probe history.
- Recovery logic requires sustained stability before reverting to primary.

### Phase 4: Validation And Replay

- Ingest public provider incident windows from status pages or aggregators.
- Compare structural routing against timeout/error-only baselines.
- Measure lead time, recall, and false-positive burden.

Acceptance criteria:

- Results are grounded in real incident timestamps rather than proxy labels.
- The repo has a credible claim about preemptive detection or the pivot stops.

## Immediate Backlog

1. Run the new probe collector long enough to build a nontrivial JSONL corpus.
2. Add provider-routing policy and replay surfaces on top of the existing bridge output.
3. Ingest public incident windows from provider status pages.
4. Measure lead time against a simple reactive timeout/error baseline.
