# SpotFSM

This repository is now centered on an **LLM inference health monitor and smart router**.

The retained core is the `ByteStreamManifold` engine plus the telemetry bridge:
rolling windows are encoded into structural signatures and a hazard score so the
system can detect provider degradation before a plain timeout or error-rate
threshold fires.

## Current Thesis

- Probe multiple LLM providers with a fixed streaming prompt.
- Record `ttft_ms`, `total_latency_ms`, `tps`, and `error` as raw JSONL.
- Feed those signals into the existing manifold bridge without changing the
  encoder or C++ core.
- Use structural hazard to drive provider-routing policy and replay analysis.

The current transition plan lives in
[docs/transition_plan.md](/sep/SpotFSM/docs/transition_plan.md).

## Core Components

- [src/core](/sep/SpotFSM/src/core): C++ structural manifold engine and pybind bindings.
- [scripts/research/regime_manifold](/sep/SpotFSM/scripts/research/regime_manifold): generic telemetry encoder, decoder, analytics, and runtime loader.
- [scripts/llm_probe](/sep/SpotFSM/scripts/llm_probe): streaming probe poller for OpenAI, Anthropic, and Groq.
- [scripts/telemetry_bridge](/sep/SpotFSM/scripts/telemetry_bridge): generic bridge that now supports Prometheus, CloudWatch, and `llm_probe` JSONL inputs.
- [scripts/telemetry_replay](/sep/SpotFSM/scripts/telemetry_replay): generic action-to-event attribution helpers.
- [scripts/spotfsm](/sep/SpotFSM/scripts/spotfsm): legacy Spot replay and policy code retained as an operator/replay reference, not the active product thesis.

## Quick Start

Install dependencies and build the extension:

```bash
make install
make build-manifold-engine
```

Set provider API keys for whichever targets you want to probe:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GROQ_API_KEY=...
```

Run one raw probe pass using
[config/llm_routing.example.yaml](/sep/SpotFSM/config/llm_routing.example.yaml):

```bash
make probe-once
```

Run one bridge pass over the accumulated probe JSONL:

```bash
make bridge-once
```

Raw probe results append to `output/probes/*.jsonl`. Bridge observations append
to `output/llm_routing.jsonl`.

Run the routing replay against accumulated probe history:

```bash
make replay-llm
```

## Config Surface

The shared example config in
[config/llm_routing.example.yaml](/sep/SpotFSM/config/llm_routing.example.yaml)
contains two layers:

1. `llm_probe.targets`: provider/model/API-key settings for the polling step.
2. `metrics`: structural bridge inputs such as
   `openai.gpt-4o-mini.ttft_ms` or `groq.llama-3.1-8b-instant.tps`.

That keeps the raw probe collector and the structural bridge on one config
surface while preserving the generic `TelemetrySource` interface.

## Legacy Scope

The Spot replay remains in the tree because it still provides useful policy,
operator, and replay structure. It is legacy scope now:

- [config/telemetry_policy.example.yaml](/sep/SpotFSM/config/telemetry_policy.example.yaml)
  is a legacy replay example.
- [tests/test_spotfsm_phase3.py](/sep/SpotFSM/tests/test_spotfsm_phase3.py)
  still guards the old replay path.
- New product claims should not be built on Spot-price proxy events.

## Validation Direction

The next honest evaluation path is to replay real LLM probe history against
public status-page incidents from providers such as OpenAI, Anthropic, and
Groq, then measure how much lead time the structural detector provides before
those incidents are publicly posted.
