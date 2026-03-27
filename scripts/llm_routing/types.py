"""Shared datatypes for LLM routing policies and replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from scripts.llm_probe.types import ProbeResult, parse_probe_metric_id
from scripts.research.regime_manifold.types import EncodedWindow


class RoutingAction(str, Enum):
    PRIMARY = "PRIMARY"
    OBSERVE = "OBSERVE"
    ROUTE_FALLBACK = "ROUTE_FALLBACK"


def metric_id_to_target(metric_id: str) -> str:
    provider, model, _ = parse_probe_metric_id(metric_id)
    return f"{provider}.{model}"


@dataclass(frozen=True)
class RoutingTopologyConfig:
    primary_target: str = ""
    provider_priority: Tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        payload: Optional[Mapping[str, Any]],
        *,
        default_primary_target: Optional[str] = None,
    ) -> "RoutingTopologyConfig":
        payload = payload or {}
        provider_priority = tuple(
            str(item).strip()
            for item in payload.get("provider_priority", ())
            if str(item).strip()
        )
        primary_target = (
            str(payload.get("primary_target", "")).strip()
            or default_primary_target
            or (provider_priority[0] if provider_priority else "")
        )
        if primary_target and primary_target not in provider_priority:
            provider_priority = (primary_target, *provider_priority)
        return cls(
            primary_target=primary_target,
            provider_priority=provider_priority,
        )

    def fallback_target_for(self, current_target: str) -> Optional[str]:
        if len(self.provider_priority) < 2:
            return None

        if current_target in self.provider_priority:
            start_index = self.provider_priority.index(current_target)
        elif self.primary_target in self.provider_priority:
            start_index = self.provider_priority.index(self.primary_target)
        else:
            start_index = 0

        for offset in range(1, len(self.provider_priority)):
            candidate = self.provider_priority[
                (start_index + offset) % len(self.provider_priority)
            ]
            if candidate != current_target:
                return candidate
        return None


@dataclass(frozen=True)
class StructuralRoutingConfig:
    topology: RoutingTopologyConfig = field(default_factory=RoutingTopologyConfig)
    hazard_floor: float = 0.75
    rupture_floor: float = 0.35
    coherence_ceiling: float = 0.48
    recovery_hazard: float = 0.72
    recovery_rupture: float = 0.25
    history_window: int = 8
    min_hazard_delta: float = 0.005
    min_rupture_delta: float = 0.01
    hazard_weight: float = 0.6
    rupture_weight: float = 0.9
    hazard_delta_weight: float = 3.0
    rupture_delta_weight: float = 2.5
    low_coherence_bias: float = 0.08
    entropy_gap_bias: float = 0.08
    signature_bias: float = 0.1
    min_entropy_gap: float = 0.42
    score_observe_threshold: float = 0.95
    score_route_threshold: float = 1.05
    min_consecutive_signals: int = 1
    cooldown_windows: int = 4
    recovery_windows: int = 8
    emergency_hazard: float = 0.92
    emergency_rupture: float = 0.52
    signature_coherence_ceiling: float = 0.45
    signature_entropy_floor: float = 0.93

    @classmethod
    def from_mapping(
        cls,
        payload: Optional[Mapping[str, Any]],
        *,
        topology: RoutingTopologyConfig,
    ) -> "StructuralRoutingConfig":
        payload = payload or {}
        return cls(
            topology=topology,
            hazard_floor=float(payload.get("hazard_floor", 0.75)),
            rupture_floor=float(payload.get("rupture_floor", 0.35)),
            coherence_ceiling=float(payload.get("coherence_ceiling", 0.48)),
            recovery_hazard=float(payload.get("recovery_hazard", 0.72)),
            recovery_rupture=float(payload.get("recovery_rupture", 0.25)),
            history_window=int(payload.get("history_window", 8)),
            min_hazard_delta=float(payload.get("min_hazard_delta", 0.005)),
            min_rupture_delta=float(payload.get("min_rupture_delta", 0.01)),
            hazard_weight=float(payload.get("hazard_weight", 0.6)),
            rupture_weight=float(payload.get("rupture_weight", 0.9)),
            hazard_delta_weight=float(payload.get("hazard_delta_weight", 3.0)),
            rupture_delta_weight=float(payload.get("rupture_delta_weight", 2.5)),
            low_coherence_bias=float(payload.get("low_coherence_bias", 0.08)),
            entropy_gap_bias=float(payload.get("entropy_gap_bias", 0.08)),
            signature_bias=float(payload.get("signature_bias", 0.1)),
            min_entropy_gap=float(payload.get("min_entropy_gap", 0.42)),
            score_observe_threshold=float(
                payload.get("score_observe_threshold", 0.95)
            ),
            score_route_threshold=float(payload.get("score_route_threshold", 1.05)),
            min_consecutive_signals=int(
                payload.get("min_consecutive_signals", 1)
            ),
            cooldown_windows=int(payload.get("cooldown_windows", 4)),
            recovery_windows=int(payload.get("recovery_windows", 8)),
            emergency_hazard=float(payload.get("emergency_hazard", 0.92)),
            emergency_rupture=float(payload.get("emergency_rupture", 0.52)),
            signature_coherence_ceiling=float(
                payload.get("signature_coherence_ceiling", 0.45)
            ),
            signature_entropy_floor=float(
                payload.get("signature_entropy_floor", 0.93)
            ),
        )


@dataclass(frozen=True)
class TimeoutRoutingConfig:
    topology: RoutingTopologyConfig = field(default_factory=RoutingTopologyConfig)
    ttft_timeout_ms: float = 10_000.0
    recovery_ttft_ms: float = 2_500.0
    cooldown_points: int = 1
    recovery_windows: int = 4

    @classmethod
    def from_mapping(
        cls,
        payload: Optional[Mapping[str, Any]],
        *,
        topology: RoutingTopologyConfig,
    ) -> "TimeoutRoutingConfig":
        payload = payload or {}
        return cls(
            topology=topology,
            ttft_timeout_ms=float(payload.get("ttft_timeout_ms", 10_000.0)),
            recovery_ttft_ms=float(payload.get("recovery_ttft_ms", 2_500.0)),
            cooldown_points=int(payload.get("cooldown_points", 1)),
            recovery_windows=int(payload.get("recovery_windows", 4)),
        )


@dataclass(frozen=True)
class ReplayConfig:
    structural_metric_id: Optional[str] = None
    source_glob: str = "output/probes/*.jsonl"
    output_dir: str = "output/llm_replay"

    @classmethod
    def from_mapping(
        cls,
        payload: Optional[Mapping[str, Any]],
        *,
        default_source_glob: str,
    ) -> "ReplayConfig":
        payload = payload or {}
        structural_metric_id = payload.get("structural_metric_id")
        return cls(
            structural_metric_id=(
                str(structural_metric_id).strip() if structural_metric_id else None
            ),
            source_glob=str(payload.get("source_glob", default_source_glob)),
            output_dir=str(payload.get("output_dir", "output/llm_replay")),
        )


@dataclass(frozen=True)
class ProbeSeries:
    metric_id: str
    provider: str
    model: str
    signal: str
    source_glob: str
    samples: Tuple[ProbeResult, ...]

    def to_json(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "provider": self.provider,
            "model": self.model,
            "signal": self.signal,
            "source_glob": self.source_glob,
            "sample_count": len(self.samples),
            "first_timestamp_ms": self.samples[0].timestamp_ms if self.samples else None,
            "last_timestamp_ms": self.samples[-1].timestamp_ms if self.samples else None,
        }


@dataclass(frozen=True)
class RoutingDecision:
    policy_name: str
    action: RoutingAction
    timestamp_ms: int
    score: float
    reasons: Tuple[str, ...]
    primary_target: str
    selected_target: str
    fallback_target: Optional[str] = None
    observed_value: Optional[float] = None
    ttft_ms: Optional[float] = None
    error: Optional[bool] = None
    hazard: Optional[float] = None
    rupture: Optional[float] = None
    coherence: Optional[float] = None
    entropy: Optional[float] = None
    hazard_delta: Optional[float] = None
    rupture_delta: Optional[float] = None
    cooldown_remaining: int = 0
    consecutive_signals: int = 0
    recovery_streak: int = 0
    signature: Optional[str] = None
    window: Optional[EncodedWindow] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "action": self.action.value,
            "timestamp_ms": self.timestamp_ms,
            "score": self.score,
            "reasons": list(self.reasons),
            "primary_target": self.primary_target,
            "selected_target": self.selected_target,
            "fallback_target": self.fallback_target,
            "observed_value": self.observed_value,
            "ttft_ms": self.ttft_ms,
            "error": self.error,
            "hazard": self.hazard,
            "rupture": self.rupture,
            "coherence": self.coherence,
            "entropy": self.entropy,
            "hazard_delta": self.hazard_delta,
            "rupture_delta": self.rupture_delta,
            "cooldown_remaining": self.cooldown_remaining,
            "consecutive_signals": self.consecutive_signals,
            "recovery_streak": self.recovery_streak,
            "signature": self.signature,
        }
