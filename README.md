# SpotFSM

SpotFSM is an Autonomous Infrastructure Guardrail (FinOps/DevOps) specifically designed for **AWS Spot Instance Management**.

This system solves a multi-billion dollar problem: balancing the 90% cost savings of Spot instances against the risk of sudden interruption or price spikes. At its core, SpotFSM relies on the **ByteStreamManifold Engine**, a non-von Neumann symbolic chaos proxy that detects "Structural Rupture" (hazard) in volatile streams before they fully collapse.

## The Problem
Standard spot-management tools use reactive thresholds (e.g., "kill if price > $X"). SpotFSM allows for **Bias-Optimized Trailing**: 
It "trails" the maximum stability of a compute cluster. When the entropy of the price or availability stream reaches a critical threshold (**Hazard $\lambda$**), the system triggers a proactive migration to a different region or instance type *before* the AWS 2-minute termination notice.

This prevents "State Collapse" in non-checkpointed workloads (like CI/CD runners or real-time ML inference) by predicting volatility rather than reacting to it.

## The Proof
SpotFSM computes a unique `signature` based on coherence and stability, distinguishing between **benign noise** (random price fluctuations) and **structural shifts** (liquidity drying up or demand spikes). By calculating a "damping score" derived from structural options, SpotFSM claims predictive reliability over reactive thresholds.

## Roadmap to Prototype

### Phase 1: The "Surgery" (Extraction) - *Complete*
- Isolate the C++ engine (`libmanifold`).
- Discard the legacy trading FX Wrapper.
- Generalize the Python Encoder to accept generic numeric telemetry (e.g., CPU load, Error Rates, Spot Price) using Z-score and Velocity bit-mapping.

### Phase 2: The "Bridge" (Data Integration)
- Build a Prometheus/CloudWatch Connector service.
- Integrate the generic bit-mapping into the live ingestion pipeline.

### Phase 3: The "Action" (Operator)
- Replace legacy execution with the `spot_operator.py` infrastructure operator.
- Implement the `TRIGGER_MIGRATE` logic based on the **Hazard $\lambda$**.
- Backtest using historical AWS Spot Price records to generate a "Savings vs. Interruption" simulator report.

### Phase 4: The Demonstration
- Set up a Kubernetes (K8s) mock cluster using Spot nodes.
- Simulate a demand spike (price increase).
- Visualize the **Hazard $\lambda$** climbing via `LiveConsole.tsx` before nodes terminate and trigger automated migration.
