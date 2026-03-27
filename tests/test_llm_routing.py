from __future__ import annotations

import json
from pathlib import Path

from scripts.llm_probe.types import ProbeResult
from scripts.llm_routing.policy import StructuralRoutingPolicy, TimeoutRoutingPolicy
from scripts.llm_routing.replay import load_probe_series, run_replay
from scripts.llm_routing.types import (
    RoutingTopologyConfig,
    StructuralRoutingConfig,
    TimeoutRoutingConfig,
)
from scripts.research.regime_manifold import TelemetryManifoldEncoder
from scripts.research.regime_manifold import encoder as manifold_encoder
from scripts.research.regime_manifold.types import CanonicalFeatures, EncodedWindow


def _window(
    *,
    metric_id: str,
    timestamp_ms: int,
    hazard: float,
    rupture: float,
    coherence: float,
    entropy: float,
    signature: str = "c0.440_s0.000_e0.950",
) -> EncodedWindow:
    return EncodedWindow(
        metric_id=metric_id,
        start_ms=timestamp_ms - 1_000,
        end_ms=timestamp_ms,
        bits=b"",
        bit_length=0,
        signature=signature,
        metrics={
            "hazard": hazard,
            "rupture": rupture,
            "coherence": coherence,
            "entropy": entropy,
            "stability": 0.0,
        },
        canonical=CanonicalFeatures(0.0, 0.0, 0.0, 0.0, 0.0, "neutral", 0.5),
        codec_meta={},
    )


def _probe_result(
    *,
    timestamp_ms: int,
    ttft_ms: float,
    error: bool = False,
) -> ProbeResult:
    return ProbeResult(
        provider="openai",
        model="gpt-4o-mini",
        timestamp_ms=timestamp_ms,
        ttft_ms=ttft_ms,
        total_latency_ms=ttft_ms + 100.0,
        tps=4.0,
        error=error,
        http_status=500 if error else 200,
        prompt_tokens=6,
        completion_tokens=1,
    )


def test_structural_routing_policy_resists_stationary_hazard():
    topology = RoutingTopologyConfig(
        primary_target="openai.gpt-4o-mini",
        provider_priority=(
            "openai.gpt-4o-mini",
            "anthropic.claude-3-5-haiku-latest",
        ),
    )
    policy = StructuralRoutingPolicy(
        StructuralRoutingConfig(
            topology=topology,
            hazard_floor=0.75,
            rupture_floor=0.35,
            min_hazard_delta=0.02,
            min_rupture_delta=0.03,
            score_route_threshold=1.1,
            min_consecutive_signals=2,
        )
    )

    actions = []
    for idx in range(10):
        decision = policy.evaluate(
            _window(
                metric_id="openai.gpt-4o-mini.ttft_ms",
                timestamp_ms=idx * 1_000,
                hazard=0.76,
                rupture=0.36,
                coherence=0.46,
                entropy=0.90,
            )
        )
        actions.append(decision.action.value)

    assert "ROUTE_FALLBACK" not in actions


def test_structural_routing_policy_routes_then_recovers_to_primary():
    topology = RoutingTopologyConfig(
        primary_target="openai.gpt-4o-mini",
        provider_priority=(
            "openai.gpt-4o-mini",
            "anthropic.claude-3-5-haiku-latest",
        ),
    )
    policy = StructuralRoutingPolicy(
        StructuralRoutingConfig(
            topology=topology,
            hazard_floor=0.75,
            rupture_floor=0.35,
            score_route_threshold=1.0,
            min_consecutive_signals=1,
            cooldown_windows=1,
            recovery_windows=3,
            recovery_hazard=0.5,
            recovery_rupture=0.2,
        )
    )

    for idx in range(3):
        policy.evaluate(
            _window(
                metric_id="openai.gpt-4o-mini.ttft_ms",
                timestamp_ms=idx * 1_000,
                hazard=0.4,
                rupture=0.1,
                coherence=0.5,
                entropy=0.7,
                signature="c0.500_s0.000_e0.700",
            )
        )

    routed = False
    for idx in range(3, 6):
        decision = policy.evaluate(
            _window(
                metric_id="openai.gpt-4o-mini.ttft_ms",
                timestamp_ms=idx * 1_000,
                hazard=0.93,
                rupture=0.56,
                coherence=0.42,
                entropy=0.97,
            )
        )
        routed = routed or decision.action.value == "ROUTE_FALLBACK"

    final_decision = None
    for idx in range(6, 11):
        final_decision = policy.evaluate(
            _window(
                metric_id="openai.gpt-4o-mini.ttft_ms",
                timestamp_ms=idx * 1_000,
                hazard=0.3,
                rupture=0.1,
                coherence=0.55,
                entropy=0.6,
                signature="c0.550_s0.000_e0.600",
            )
        )

    assert routed is True
    assert final_decision is not None
    assert final_decision.action.value == "PRIMARY"


def test_timeout_routing_policy_routes_on_timeout_and_recovers():
    topology = RoutingTopologyConfig(
        primary_target="openai.gpt-4o-mini",
        provider_priority=(
            "openai.gpt-4o-mini",
            "anthropic.claude-3-5-haiku-latest",
        ),
    )
    policy = TimeoutRoutingPolicy(
        TimeoutRoutingConfig(
            topology=topology,
            ttft_timeout_ms=10_000.0,
            recovery_ttft_ms=1_000.0,
            cooldown_points=1,
            recovery_windows=2,
        )
    )

    decisions = [
        policy.evaluate(_probe_result(timestamp_ms=0, ttft_ms=500.0)),
        policy.evaluate(_probe_result(timestamp_ms=1_000, ttft_ms=11_000.0)),
        policy.evaluate(_probe_result(timestamp_ms=2_000, ttft_ms=900.0)),
        policy.evaluate(_probe_result(timestamp_ms=3_000, ttft_ms=800.0)),
    ]

    assert decisions[0].action.value == "PRIMARY"
    assert decisions[1].action.value == "ROUTE_FALLBACK"
    assert decisions[-1].action.value == "PRIMARY"


def test_llm_routing_replay_outputs_structural_lead(tmp_path: Path, monkeypatch):
    probe_path = tmp_path / "probe.jsonl"
    samples = []
    for idx in range(12):
        ttft_ms = 400.0 if idx < 10 else 12_000.0
        samples.append(
            _probe_result(timestamp_ms=idx * 30_000, ttft_ms=ttft_ms).to_json()
        )
    probe_path.write_text(
        "\n".join(json.dumps(sample, sort_keys=True) for sample in samples) + "\n",
        encoding="utf-8",
    )

    call_count = {"value": 0}

    def fake_analyze(_):
        call_count["value"] += 1
        if call_count["value"] < 3:
            return (
                "c0.500_s0.000_e0.700",
                {
                    "coherence": 0.5,
                    "stability": 0.0,
                    "entropy": 0.7,
                    "hazard": 0.4,
                    "rupture": 0.1,
                },
            )
        return (
            "c0.420_s0.000_e0.970",
            {
                "coherence": 0.42,
                "stability": 0.0,
                "entropy": 0.97,
                "hazard": 0.93,
                "rupture": 0.56,
            },
        )

    monkeypatch.setattr(
        manifold_encoder.StructuralAnalyzer,
        "analyze",
        staticmethod(fake_analyze),
    )

    series = load_probe_series(
        str(probe_path),
        metric_id="openai.gpt-4o-mini.ttft_ms",
    )
    topology = RoutingTopologyConfig(
        primary_target="openai.gpt-4o-mini",
        provider_priority=(
            "openai.gpt-4o-mini",
            "anthropic.claude-3-5-haiku-latest",
        ),
    )
    summary = run_replay(
        series,
        encoder=TelemetryManifoldEncoder(
            window_points=8,
            stride_points=4,
            baseline_period=4,
        ),
        structural_policy=StructuralRoutingPolicy(
            StructuralRoutingConfig(
                topology=topology,
                hazard_floor=0.75,
                rupture_floor=0.35,
                score_route_threshold=1.0,
                min_consecutive_signals=1,
                cooldown_windows=1,
                recovery_windows=2,
            )
        ),
        timeout_policy=TimeoutRoutingPolicy(
            TimeoutRoutingConfig(
                topology=topology,
                ttft_timeout_ms=10_000.0,
                recovery_ttft_ms=1_000.0,
                cooldown_points=1,
                recovery_windows=2,
            )
        ),
        output_dir=str(tmp_path / "replay"),
    )

    assert summary["structural"]["route_count"] >= 1
    assert summary["timeout"]["route_count"] >= 1
    assert summary["comparison"]["structural_lead_over_timeout_s"] > 0
    assert Path(summary["artifacts"]["decisions_csv"]).exists()
    assert Path(summary["artifacts"]["summary_json"]).exists()
