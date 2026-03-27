"""Routing policy and reactive baseline evaluators for LLM providers."""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

from scripts.research.regime_manifold.types import EncodedWindow, TelemetryPoint


class RoutingAction(Enum):
    STABLE = "stable"   # Use primary provider
    OBSERVE = "observe" # Potential degradation; prepare fallback
    ROUTE = "route"     # Active degradation; route to fallback


@dataclass(frozen=True)
class RoutingDecision:
    policy_name: str
    action: RoutingAction
    timestamp_ms: int
    score: float
    reasons: Tuple[str, ...]
    current_value: float
    hazard: float = 0.0
    rupture: float = 0.0
    coherence: float = 0.0
    entropy: float = 0.0
    hazard_delta: float = 0.0
    rupture_delta: float = 0.0
    cooldown_remaining: int = 0
    consecutive_signals: int = 0
    signature: Optional[str] = None
    window: Optional[EncodedWindow] = None

    def to_json(self) -> Dict[str, object]:
        return {
            "policy_name": self.policy_name,
            "action": self.action.value,
            "timestamp_ms": self.timestamp_ms,
            "score": self.score,
            "reasons": list(self.reasons),
            "current_value": self.current_value,
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
class LLMRoutingPolicyConfig:
    history_window: int = 20
    hazard_weight: float = 1.0
    rupture_weight: float = 1.0
    hazard_delta_weight: float = 2.0
    rupture_delta_weight: float = 2.0
    
    # Thresholds ported from SpotFSM but calibrated for LLM signals
    hazard_floor: float = 0.08
    rupture_floor: float = 0.08
    min_hazard_delta: float = 0.05
    min_rupture_delta: float = 0.05
    emergency_hazard: float = 0.6
    emergency_rupture: float = 0.6
    recovery_hazard: float = 0.05
    recovery_rupture: float = 0.05
    
    score_observe_threshold: float = 0.3
    score_route_threshold: float = 0.7
    
    min_consecutive_signals: int = 2
    cooldown_windows: int = 10
    
    coherence_ceiling: float = 0.3
    low_coherence_bias: float = 0.2
    min_entropy_gap: float = 0.4
    entropy_gap_bias: float = 0.3

    @classmethod
    def from_mapping(cls, payload: Optional[Dict[str, float]]) -> LLMRoutingPolicyConfig:
        if not payload:
            return cls()
        import dataclasses
        valid_keys = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in valid_keys})


class LLMRoutingPolicy:
    """Stateful policy that converts structural LLM health metrics into routing actions."""

    def __init__(self, config: Optional[LLMRoutingPolicyConfig] = None) -> None:
        self.config = config or LLMRoutingPolicyConfig()
        self.hazard_history: Deque[float] = deque(maxlen=self.config.history_window)
        self.rupture_history: Deque[float] = deque(maxlen=self.config.history_window)
        self.consecutive_signals = 0
        self.cooldown_remaining = 0
        self.state = RoutingAction.STABLE

    def evaluate(
        self,
        window: EncodedWindow,
        *,
        current_value: Optional[float] = None,
    ) -> RoutingDecision:
        metrics = window.metrics
        hazard = float(metrics.get("hazard", 0.0))
        rupture = float(metrics.get("rupture", 0.0))
        coherence = float(metrics.get("coherence", 0.0))
        entropy = float(metrics.get("entropy", 0.0))

        hazard_baseline = (
            statistics.median(self.hazard_history) if self.hazard_history else hazard
        )
        rupture_baseline = (
            statistics.median(self.rupture_history)
            if self.rupture_history
            else rupture
        )
        hazard_delta = hazard - hazard_baseline
        rupture_delta = rupture - rupture_baseline
        entropy_gap = entropy - coherence

        score = (
            hazard * self.config.hazard_weight
            + rupture * self.config.rupture_weight
            + max(0.0, hazard_delta) * self.config.hazard_delta_weight
            + max(0.0, rupture_delta) * self.config.rupture_delta_weight
        )
        reasons: List[str] = []

        if coherence <= self.config.coherence_ceiling:
            score += self.config.low_coherence_bias
            reasons.append("coherence_below_ceiling")
        if entropy_gap >= self.config.min_entropy_gap:
            score += self.config.entropy_gap_bias
            reasons.append("entropy_gap_high")

        signal_detected = (
            hazard >= self.config.hazard_floor
            and rupture >= self.config.rupture_floor
            and (
                hazard_delta >= self.config.min_hazard_delta
                or rupture_delta >= self.config.min_rupture_delta
                or hazard >= self.config.emergency_hazard
                or rupture >= self.config.emergency_rupture
            )
        )
        if signal_detected:
            self.consecutive_signals += 1
            reasons.append("structural_signal")
        elif hazard <= self.config.recovery_hazard and rupture <= self.config.recovery_rupture:
            self.consecutive_signals = 0
            # reasons.append("below_recovery_band")
        else:
            self.consecutive_signals = max(0, self.consecutive_signals - 1)

        action = RoutingAction.STABLE
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        emergency = hazard >= self.config.emergency_hazard and rupture >= self.config.emergency_rupture
        if emergency:
            action = RoutingAction.ROUTE
            reasons.append("emergency_threshold")
        elif (
            score >= self.config.score_route_threshold
            and self.consecutive_signals >= self.config.min_consecutive_signals
            and self.cooldown_remaining == 0
        ):
            action = RoutingAction.ROUTE
            reasons.append("score_above_route_threshold")
        elif signal_detected or score >= self.config.score_observe_threshold:
            action = RoutingAction.OBSERVE
            reasons.append("observe_threshold")
        elif hazard <= self.config.recovery_hazard and rupture <= self.config.recovery_rupture:
            action = RoutingAction.STABLE
        elif self.state in {RoutingAction.ROUTE, RoutingAction.OBSERVE}:
            action = RoutingAction.OBSERVE
            reasons.append("sticky_hazard_state")

        if action == RoutingAction.ROUTE:
            self.cooldown_remaining = self.config.cooldown_windows
            self.state = RoutingAction.ROUTE
        elif action == RoutingAction.OBSERVE:
            self.state = RoutingAction.OBSERVE
        else:
            self.state = RoutingAction.STABLE

        self.hazard_history.append(hazard)
        self.rupture_history.append(rupture)

        return RoutingDecision(
            policy_name="structural_router",
            action=action,
            timestamp_ms=window.end_ms,
            score=score,
            reasons=tuple(reasons),
            current_value=current_value if current_value is not None else 0.0,
            hazard=hazard,
            rupture=rupture,
            coherence=coherence,
            entropy=entropy,
            hazard_delta=hazard_delta,
            rupture_delta=rupture_delta,
            cooldown_remaining=self.cooldown_remaining,
            consecutive_signals=self.consecutive_signals,
            signature=window.signature,
            window=window,
        )


class ReactiveRoutingPolicy:
    """Reactive baseline that routes based on immediate errors or timeout thresholds."""

    def __init__(
        self,
        *,
        timeout_ms: float = 5000.0,
        error_rate_threshold: float = 0.1,
        window_size: int = 5,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.error_rate_threshold = error_rate_threshold
        self.history: Deque[Tuple[bool, float]] = deque(maxlen=window_size)
        self.cooldown_remaining = 0

    def evaluate(self, point: TelemetryPoint, *, is_error: bool = False) -> RoutingDecision:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        self.history.append((is_error, point.value))
        
        reasons: List[str] = []
        action = RoutingAction.STABLE
        
        # Immediate error or timeout
        if is_error or point.value >= self.timeout_ms:
            action = RoutingAction.ROUTE
            reasons.append("immediate_failure" if is_error else "timeout")
        else:
            # Check windowed error rate
            errors = sum(1 for e, _ in self.history if e)
            error_rate = errors / len(self.history)
            if error_rate >= self.error_rate_threshold:
                action = RoutingAction.ROUTE
                reasons.append(f"error_rate_high_{error_rate:.2f}")

        if action == RoutingAction.ROUTE:
            self.cooldown_remaining = 10 # Calibrated cooldown

        return RoutingDecision(
            policy_name="reactive_baseline",
            action=action,
            timestamp_ms=point.timestamp_ms,
            score=1.0 if action == RoutingAction.ROUTE else 0.0,
            reasons=tuple(reasons),
            current_value=point.value,
            cooldown_remaining=self.cooldown_remaining,
        )
