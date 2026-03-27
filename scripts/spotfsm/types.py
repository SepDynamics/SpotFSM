"""Shared datatypes for Phase 3 policy and replay flows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from scripts.research.regime_manifold.types import EncodedWindow, TelemetryPoint


class DecisionAction(str, Enum):
    STABLE = "STABLE"
    OBSERVE = "OBSERVE"
    MIGRATE = "MIGRATE"


@dataclass(frozen=True)
class SpotPriceSeriesSelector:
    availability_zone_id: str
    instance_type: str
    product_description: str = "Linux/UNIX"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SpotPriceSeriesSelector":
        availability_zone_id = str(payload.get("availability_zone_id", "")).strip()
        instance_type = str(payload.get("instance_type", "")).strip()
        product_description = str(
            payload.get("product_description", "Linux/UNIX")
        ).strip()
        if not availability_zone_id or not instance_type:
            raise ValueError(
                "dataset selector requires availability_zone_id and instance_type"
            )
        return cls(
            availability_zone_id=availability_zone_id,
            instance_type=instance_type,
            product_description=product_description,
        )

    def metric_id(self) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", self.product_description).strip("_")
        return (
            f"spot_{self.availability_zone_id}_{self.instance_type}_{slug}".lower()
        )


@dataclass(frozen=True)
class SpotPriceRecord:
    availability_zone_id: str
    instance_type: str
    product_description: str
    price: float
    timestamp_ms: int


@dataclass(frozen=True)
class SpotPriceSeries:
    metric_id: str
    selector: SpotPriceSeriesSelector
    source: str
    source_path: str
    points: Tuple[TelemetryPoint, ...]

    def to_json(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "selector": {
                "availability_zone_id": self.selector.availability_zone_id,
                "instance_type": self.selector.instance_type,
                "product_description": self.selector.product_description,
            },
            "source": self.source,
            "source_path": self.source_path,
            "point_count": len(self.points),
            "first_timestamp_ms": self.points[0].timestamp_ms if self.points else None,
            "last_timestamp_ms": self.points[-1].timestamp_ms if self.points else None,
        }


@dataclass(frozen=True)
class TopSeriesCandidate:
    selector: SpotPriceSeriesSelector
    sample_count: int
    min_price: float
    max_price: float
    relative_range: float

    def to_json(self) -> Dict[str, Any]:
        return {
            "availability_zone_id": self.selector.availability_zone_id,
            "instance_type": self.selector.instance_type,
            "product_description": self.selector.product_description,
            "sample_count": self.sample_count,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "relative_range": self.relative_range,
        }


@dataclass(frozen=True)
class PolicyConfig:
    hazard_floor: float = 0.82
    rupture_floor: float = 0.38
    coherence_ceiling: float = 0.48
    recovery_hazard: float = 0.8
    recovery_rupture: float = 0.3
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
    score_migrate_threshold: float = 1.08
    min_consecutive_signals: int = 1
    cooldown_windows: int = 4
    emergency_hazard: float = 0.92
    emergency_rupture: float = 0.52
    signature_coherence_ceiling: float = 0.45
    signature_entropy_floor: float = 0.93

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "PolicyConfig":
        payload = payload or {}
        return cls(
            hazard_floor=float(payload.get("hazard_floor", 0.82)),
            rupture_floor=float(payload.get("rupture_floor", 0.38)),
            coherence_ceiling=float(payload.get("coherence_ceiling", 0.48)),
            recovery_hazard=float(payload.get("recovery_hazard", 0.8)),
            recovery_rupture=float(payload.get("recovery_rupture", 0.3)),
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
            score_migrate_threshold=float(
                payload.get("score_migrate_threshold", 1.08)
            ),
            min_consecutive_signals=int(
                payload.get("min_consecutive_signals", 1)
            ),
            cooldown_windows=int(payload.get("cooldown_windows", 4)),
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
class ReactiveBaselineConfig:
    rolling_window_points: int = 12
    price_zscore_threshold: float = 1.75
    price_zscore_observe: float = 1.1
    price_multiplier_threshold: float = 1.12
    velocity_std_multiplier: float = 1.2
    cooldown_points: int = 4

    @classmethod
    def from_mapping(
        cls, payload: Optional[Mapping[str, Any]]
    ) -> "ReactiveBaselineConfig":
        payload = payload or {}
        return cls(
            rolling_window_points=int(payload.get("rolling_window_points", 12)),
            price_zscore_threshold=float(
                payload.get("price_zscore_threshold", 1.75)
            ),
            price_zscore_observe=float(payload.get("price_zscore_observe", 1.1)),
            price_multiplier_threshold=float(
                payload.get("price_multiplier_threshold", 1.12)
            ),
            velocity_std_multiplier=float(
                payload.get("velocity_std_multiplier", 1.2)
            ),
            cooldown_points=int(payload.get("cooldown_points", 4)),
        )


@dataclass(frozen=True)
class AlwaysMigrateConfig:
    cooldown_points: int = 4

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "AlwaysMigrateConfig":
        payload = payload or {}
        return cls(cooldown_points=int(payload.get("cooldown_points", 4)))


@dataclass(frozen=True)
class RollingZScoreConfig:
    rolling_window_points: int = 12
    zscore_threshold: float = 1.75
    cooldown_points: int = 4

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "RollingZScoreConfig":
        payload = payload or {}
        return cls(
            rolling_window_points=int(payload.get("rolling_window_points", 12)),
            zscore_threshold=float(payload.get("zscore_threshold", 1.75)),
            cooldown_points=int(payload.get("cooldown_points", 4)),
        )


@dataclass(frozen=True)
class RandomConfig:
    firing_probability: float = 0.01
    cooldown_points: int = 4

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "RandomConfig":
        payload = payload or {}
        return cls(
            firing_probability=float(payload.get("firing_probability", 0.01)),
            cooldown_points=int(payload.get("cooldown_points", 4)),
        )



@dataclass(frozen=True)
class ReplayConfig:
    event_lookahead_points: int = 8
    event_spike_multiplier: float = 1.12
    event_spike_absolute: float = 0.05
    event_attribution_lookback_points: int = 8
    output_dir: str = "output/replay"

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "ReplayConfig":
        payload = payload or {}
        return cls(
            event_lookahead_points=int(payload.get("event_lookahead_points", 8)),
            event_spike_multiplier=float(
                payload.get("event_spike_multiplier", 1.12)
            ),
            event_spike_absolute=float(payload.get("event_spike_absolute", 0.05)),
            event_attribution_lookback_points=int(
                payload.get("event_attribution_lookback_points", 8)
            ),
            output_dir=str(payload.get("output_dir", "output/replay")),
        )


@dataclass(frozen=True)
class OperatorConfig:
    workload_id: str = "spotfsm-replay"
    action_log_path: str = "output/replay/simulated_operator.jsonl"
    redis_url: Optional[str] = None
    redis_key_prefix: str = "spotfsm:replay"

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "OperatorConfig":
        payload = payload or {}
        redis_url = payload.get("redis_url")
        return cls(
            workload_id=str(payload.get("workload_id", "spotfsm-replay")),
            action_log_path=str(
                payload.get(
                    "action_log_path", "output/replay/simulated_operator.jsonl"
                )
            ),
            redis_url=str(redis_url) if redis_url else None,
            redis_key_prefix=str(payload.get("redis_key_prefix", "spotfsm:replay")),
        )


@dataclass(frozen=True)
class ReplayEvent:
    anchor_index: int
    event_index: int
    anchor_timestamp_ms: int
    event_timestamp_ms: int
    anchor_price: float
    event_price: float
    event_type: str = "price_spike"

    def to_json(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "anchor_index": self.anchor_index,
            "event_index": self.event_index,
            "anchor_timestamp_ms": self.anchor_timestamp_ms,
            "event_timestamp_ms": self.event_timestamp_ms,
            "anchor_price": self.anchor_price,
            "event_price": self.event_price,
            "price_ratio": (
                self.event_price / self.anchor_price if self.anchor_price else None
            ),
        }


@dataclass(frozen=True)
class MigrationDecision:
    policy_name: str
    action: DecisionAction
    timestamp_ms: int
    score: float
    reasons: Tuple[str, ...]
    current_price: float
    hazard: Optional[float] = None
    rupture: Optional[float] = None
    coherence: Optional[float] = None
    entropy: Optional[float] = None
    hazard_delta: Optional[float] = None
    rupture_delta: Optional[float] = None
    cooldown_remaining: int = 0
    consecutive_signals: int = 0
    signature: Optional[str] = None
    window: Optional[EncodedWindow] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "action": self.action.value,
            "timestamp_ms": self.timestamp_ms,
            "score": self.score,
            "reasons": list(self.reasons),
            "current_price": self.current_price,
            "hazard": self.hazard,
            "rupture": self.rupture,
            "coherence": self.coherence,
            "entropy": self.entropy,
            "hazard_delta": self.hazard_delta,
            "rupture_delta": self.rupture_delta,
            "cooldown_remaining": self.cooldown_remaining,
            "consecutive_signals": self.consecutive_signals,
            "signature": self.signature,
        }


@dataclass(frozen=True)
class OperatorActionRecord:
    workload_id: str
    timestamp_ms: int
    action: DecisionAction
    state: str
    status: str
    detail: str
    signature: Optional[str] = None
    hazard: Optional[float] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "timestamp_ms": self.timestamp_ms,
            "action": self.action.value,
            "state": self.state,
            "status": self.status,
            "detail": self.detail,
            "signature": self.signature,
            "hazard": self.hazard,
        }
