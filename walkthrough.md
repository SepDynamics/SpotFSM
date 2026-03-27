# SpotFSM Walkthrough

This walkthrough reflects the current transition state of the repository.

The retained core is the byte-stream structural manifold engine plus the live
telemetry bridge. The active product direction is LLM API degradation detection
and smart provider routing.

## Retained Core

- The C++ manifold engine remains under [src/core](/sep/SpotFSM/src/core).
- The Python codec under
  [scripts/research/regime_manifold](/sep/SpotFSM/scripts/research/regime_manifold)
  still converts rolling telemetry windows into structural signatures.
- The bridge CLI under
  [scripts/telemetry_bridge/cli.py](/sep/SpotFSM/scripts/telemetry_bridge/cli.py)
  still emits one JSON record per configured metric.

## New LLM Probe Path

- [scripts/llm_probe](/sep/SpotFSM/scripts/llm_probe) polls provider APIs with a
  short fixed prompt and records raw JSONL probe results.
- [config/llm_routing.example.yaml](/sep/SpotFSM/config/llm_routing.example.yaml)
  is the shared config for both raw probe collection and bridge ingestion.
- The bridge now accepts `llm_probe` as a telemetry provider alongside
  Prometheus and CloudWatch.

## Legacy Replay Path

- [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm) remains as a legacy replay and
  operator reference.
- [config/telemetry_policy.example.yaml](/sep/SpotFSM/config/telemetry_policy.example.yaml)
  still drives the legacy Spot replay.
- That package is no longer the validated future thesis for the repo.

## Test Coverage

- [tests/test_telemetry_bridge.py](/sep/SpotFSM/tests/test_telemetry_bridge.py)
  covers bridge parsing and service behavior, including `llm_probe` ingestion.
- [tests/test_spotfsm_phase3.py](/sep/SpotFSM/tests/test_spotfsm_phase3.py)
  still covers the legacy Spot policy and dataset path.

## Next Step

The next milestone is not front-end work. It is validation:

- collect a real LLM probe corpus over days or weeks
- add routing policy on top of structural hazard
- replay against public incident windows from provider status pages
