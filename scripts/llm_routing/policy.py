"""Structural and timeout-based routing policies for LLM providers."""

from __future__ import annotations

import statistics
from collections import deque
from typing import Deque, Dict, List, Optional

from scripts.llm_probe.types import ProbeResult
from scripts.research.regime_manifold.types import EncodedWindow

from .types import (
    RoutingAction,
    RoutingDecision,
    StructuralRoutingConfig,
    TimeoutRoutingConfig,
    metric_id_to_target,
)


def parse_signature(signature: str) -> Dict[str, float]:
    values: Dict[str, float] = {}
    for chunk in signature.split("_"):
        if not chunk:
            continue
        key = chunk[0]
        try:
            values[key] = float(chunk[1:])
        except ValueError:
            continue
    return values


class StructuralRoutingPolicy:
    """Convert structural windows into provider routing states."""

    def __init__(self, config: Optional[StructuralRoutingConfig] = None) -> None:
        self.config = config or StructuralRoutingConfig()
        self.hazard_history: Deque[float] = deque(maxlen=self.config.history_window)
        self.rupture_history: Deque[float] = deque(maxlen=self.config.history_window)
        self.consecutive_signals = 0
        self.cooldown_remaining = 0
        self.recovery_streak = 0
        self.on_fallback = False

    def evaluate(self, window: EncodedWindow) -> RoutingDecision:
        metrics = window.metrics
        hazard = float(metrics.get("hazard", 0.0))
        rupture = float(metrics.get("rupture", 0.0))
        coherence = float(metrics.get("coherence", 0.0))
        entropy = float(metrics.get("entropy", 0.0))
        current_target = metric_id_to_target(window.metric_id)
        primary_target = self.config.topology.primary_target or current_target
        fallback_target = self.config.topology.fallback_target_for(primary_target)

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

        signature_values = parse_signature(window.signature)
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
        if (
            signature_values.get("c", coherence)
            <= self.config.signature_coherence_ceiling
            and signature_values.get("e", entropy) >= self.config.signature_entropy_floor
        ):
            score += self.config.signature_bias
            reasons.append("signature_high_entropy_low_coherence")

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
            reasons.append("below_recovery_band")
        else:
            self.consecutive_signals = max(0, self.consecutive_signals - 1)

        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        emergency = (
            hazard >= self.config.emergency_hazard
            and rupture >= self.config.emergency_rupture
        )
        route_condition = (
            score >= self.config.score_route_threshold
            and self.consecutive_signals >= self.config.min_consecutive_signals
            and self.cooldown_remaining == 0
        )
        observe_condition = signal_detected or score >= self.config.score_observe_threshold

        if self.on_fallback:
            if hazard <= self.config.recovery_hazard and rupture <= self.config.recovery_rupture:
                self.recovery_streak += 1
                reasons.append("recovery_window")
            else:
                self.recovery_streak = 0

            if emergency:
                self.cooldown_remaining = self.config.cooldown_windows
                self.recovery_streak = 0
                reasons.append("emergency_threshold")
            elif route_condition:
                self.cooldown_remaining = self.config.cooldown_windows
                self.recovery_streak = 0
                reasons.append("route_threshold")

            if (
                self.recovery_streak >= self.config.recovery_windows
                and self.cooldown_remaining == 0
                and not observe_condition
            ):
                self.on_fallback = False
                action = RoutingAction.PRIMARY
                selected_target = primary_target
                reasons.append("recovered_to_primary")
            else:
                action = RoutingAction.ROUTE_FALLBACK
                selected_target = fallback_target or primary_target
                reasons.append("holding_fallback")
        else:
            if emergency:
                reasons.append("emergency_threshold")
                if fallback_target:
                    self.on_fallback = True
                    self.cooldown_remaining = self.config.cooldown_windows
                    self.recovery_streak = 0
                    action = RoutingAction.ROUTE_FALLBACK
                    selected_target = fallback_target
                else:
                    action = RoutingAction.OBSERVE
                    selected_target = primary_target
                    reasons.append("no_fallback_target")
            elif route_condition:
                reasons.append("route_threshold")
                if fallback_target:
                    self.on_fallback = True
                    self.cooldown_remaining = self.config.cooldown_windows
                    self.recovery_streak = 0
                    action = RoutingAction.ROUTE_FALLBACK
                    selected_target = fallback_target
                else:
                    action = RoutingAction.OBSERVE
                    selected_target = primary_target
                    reasons.append("no_fallback_target")
            elif observe_condition:
                action = RoutingAction.OBSERVE
                selected_target = primary_target
                reasons.append("observe_threshold")
            else:
                action = RoutingAction.PRIMARY
                selected_target = primary_target

        self.hazard_history.append(hazard)
        self.rupture_history.append(rupture)

        return RoutingDecision(
            policy_name="structural",
            action=action,
            timestamp_ms=window.end_ms,
            score=score,
            reasons=tuple(reasons),
            primary_target=primary_target,
            selected_target=selected_target,
            fallback_target=fallback_target,
            hazard=hazard,
            rupture=rupture,
            coherence=coherence,
            entropy=entropy,
            hazard_delta=hazard_delta,
            rupture_delta=rupture_delta,
            cooldown_remaining=self.cooldown_remaining,
            consecutive_signals=self.consecutive_signals,
            recovery_streak=self.recovery_streak,
            signature=window.signature,
            window=window,
        )


class TimeoutRoutingPolicy:
    """Hard-threshold baseline based on errors and TTFT timeout breaches."""

    def __init__(self, config: Optional[TimeoutRoutingConfig] = None) -> None:
        self.config = config or TimeoutRoutingConfig()
        self.cooldown_remaining = 0
        self.recovery_streak = 0
        self.on_fallback = False

    def evaluate(self, result: ProbeResult) -> RoutingDecision:
        current_target = f"{result.provider}.{result.model}"
        primary_target = self.config.topology.primary_target or current_target
        fallback_target = self.config.topology.fallback_target_for(primary_target)
        trigger = result.error or result.ttft_ms >= self.config.ttft_timeout_ms
        recovered = (
            not result.error and result.ttft_ms <= self.config.recovery_ttft_ms
        )

        reasons: List[str] = []
        score = 0.0
        if self.config.ttft_timeout_ms > 0:
            score = result.ttft_ms / self.config.ttft_timeout_ms
        if result.error:
            score = max(score, 1.0)

        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        if self.on_fallback:
            if trigger:
                self.cooldown_remaining = self.config.cooldown_points
                self.recovery_streak = 0
                reasons.append("error_or_timeout")
                action = RoutingAction.ROUTE_FALLBACK
                selected_target = fallback_target or primary_target
            else:
                if recovered:
                    self.recovery_streak += 1
                    reasons.append("recovery_window")
                else:
                    self.recovery_streak = 0

                if (
                    self.recovery_streak >= self.config.recovery_windows
                    and self.cooldown_remaining == 0
                ):
                    self.on_fallback = False
                    action = RoutingAction.PRIMARY
                    selected_target = primary_target
                    reasons.append("recovered_to_primary")
                else:
                    action = RoutingAction.ROUTE_FALLBACK
                    selected_target = fallback_target or primary_target
                    reasons.append("holding_fallback")
        else:
            if trigger:
                reasons.append("error_or_timeout")
                if fallback_target:
                    self.on_fallback = True
                    self.cooldown_remaining = self.config.cooldown_points
                    action = RoutingAction.ROUTE_FALLBACK
                    selected_target = fallback_target
                else:
                    action = RoutingAction.PRIMARY
                    selected_target = primary_target
                    reasons.append("no_fallback_target")
            else:
                action = RoutingAction.PRIMARY
                selected_target = primary_target

        return RoutingDecision(
            policy_name="timeout",
            action=action,
            timestamp_ms=result.timestamp_ms,
            score=score,
            reasons=tuple(reasons),
            primary_target=primary_target,
            selected_target=selected_target,
            fallback_target=fallback_target,
            observed_value=result.ttft_ms,
            ttft_ms=result.ttft_ms,
            error=result.error,
            cooldown_remaining=self.cooldown_remaining,
            recovery_streak=self.recovery_streak,
        )
