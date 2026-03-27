"""Migration policy and reactive baseline evaluators."""

from __future__ import annotations

import statistics
from collections import deque
from typing import Deque, Dict, List, Optional
import random

from scripts.research.regime_manifold.types import EncodedWindow, TelemetryPoint

from .types import (
    AlwaysMigrateConfig,
    DecisionAction,
    MigrationDecision,
    PolicyConfig,
    RandomConfig,
    ReactiveBaselineConfig,
    RollingZScoreConfig,
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


class MigrationPolicy:
    """Stateful policy that converts structural metrics into migration actions."""

    def __init__(self, config: Optional[PolicyConfig] = None) -> None:
        self.config = config or PolicyConfig()
        self.hazard_history: Deque[float] = deque(maxlen=self.config.history_window)
        self.rupture_history: Deque[float] = deque(maxlen=self.config.history_window)
        self.consecutive_signals = 0
        self.cooldown_remaining = 0
        self.state = DecisionAction.STABLE.value

    def evaluate(
        self,
        window: EncodedWindow,
        *,
        current_price: Optional[float] = None,
    ) -> MigrationDecision:
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

        action = DecisionAction.STABLE
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        emergency = hazard >= self.config.emergency_hazard and rupture >= self.config.emergency_rupture
        if emergency:
            action = DecisionAction.MIGRATE
            reasons.append("emergency_threshold")
        elif (
            score >= self.config.score_migrate_threshold
            and self.consecutive_signals >= self.config.min_consecutive_signals
            and self.cooldown_remaining == 0
        ):
            action = DecisionAction.MIGRATE
            reasons.append("score_above_migrate_threshold")
        elif signal_detected or score >= self.config.score_observe_threshold:
            action = DecisionAction.OBSERVE
            reasons.append("observe_threshold")
        elif hazard <= self.config.recovery_hazard and rupture <= self.config.recovery_rupture:
            action = DecisionAction.STABLE
        elif self.state in {DecisionAction.MIGRATE.value, DecisionAction.OBSERVE.value}:
            action = DecisionAction.OBSERVE
            reasons.append("sticky_hazard_state")

        if action == DecisionAction.MIGRATE:
            self.cooldown_remaining = self.config.cooldown_windows
            self.state = DecisionAction.MIGRATE.value
        elif action == DecisionAction.OBSERVE:
            self.state = DecisionAction.OBSERVE.value
        else:
            self.state = DecisionAction.STABLE.value

        self.hazard_history.append(hazard)
        self.rupture_history.append(rupture)

        return MigrationDecision(
            policy_name="spotfsm",
            action=action,
            timestamp_ms=window.end_ms,
            score=score,
            reasons=tuple(reasons),
            current_price=current_price if current_price is not None else 0.0,
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


class ReactivePricePolicy:
    """Price-only baseline for comparison against structural policy decisions."""

    def __init__(self, config: Optional[ReactiveBaselineConfig] = None) -> None:
        self.config = config or ReactiveBaselineConfig()
        self.price_history: Deque[float] = deque(maxlen=self.config.rolling_window_points)
        self.velocity_history: Deque[float] = deque(
            maxlen=max(2, self.config.rolling_window_points - 1)
        )
        self.cooldown_remaining = 0

    def evaluate(self, point: TelemetryPoint) -> MigrationDecision:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        reasons: List[str] = []
        action = DecisionAction.STABLE
        score = 0.0
        zscore = 0.0
        price_ratio = 1.0
        velocity_score = 0.0

        if self.price_history:
            velocity = point.value - self.price_history[-1]
            self.velocity_history.append(velocity)

        if len(self.price_history) >= self.config.rolling_window_points:
            prices = list(self.price_history)
            mean_price = statistics.fmean(prices)
            price_std = statistics.pstdev(prices) if len(prices) >= 2 else 0.0
            rolling_min = min(prices)
            zscore = (
                (point.value - mean_price) / price_std if price_std > 1e-9 else 0.0
            )
            price_ratio = point.value / rolling_min if rolling_min > 0 else 1.0

            if len(self.velocity_history) >= 2:
                velocity_std = statistics.pstdev(self.velocity_history)
                if velocity_std > 1e-9:
                    velocity_score = max(
                        0.0, self.velocity_history[-1] / velocity_std
                    )

            score = max(
                zscore / max(self.config.price_zscore_threshold, 1e-9),
                price_ratio / max(self.config.price_multiplier_threshold, 1e-9),
                velocity_score / max(self.config.velocity_std_multiplier, 1e-9),
            )

            if (
                zscore >= self.config.price_zscore_threshold
                or price_ratio >= self.config.price_multiplier_threshold
                or velocity_score >= self.config.velocity_std_multiplier
            ):
                if self.cooldown_remaining == 0:
                    action = DecisionAction.MIGRATE
                    self.cooldown_remaining = self.config.cooldown_points
                else:
                    action = DecisionAction.OBSERVE
                reasons.append("price_threshold_breach")
            elif zscore >= self.config.price_zscore_observe:
                action = DecisionAction.OBSERVE
                reasons.append("price_elevated")

        self.price_history.append(point.value)

        return MigrationDecision(
            policy_name="reactive",
            action=action,
            timestamp_ms=point.timestamp_ms,
            score=score,
            reasons=tuple(reasons),
            current_price=point.value,
            cooldown_remaining=self.cooldown_remaining,
        )


class AlwaysMigratePolicy:
    """Trivial baseline that triggers migration continuously according to cooldown."""

    def __init__(self, config: Optional[AlwaysMigrateConfig] = None) -> None:
        self.config = config or AlwaysMigrateConfig()
        self.cooldown_remaining = 0

    def evaluate(self, point: TelemetryPoint) -> MigrationDecision:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        action = DecisionAction.STABLE
        reasons: List[str] = []

        if self.cooldown_remaining == 0:
            action = DecisionAction.MIGRATE
            self.cooldown_remaining = self.config.cooldown_points
            reasons.append("always_migrate")
        else:
            action = DecisionAction.OBSERVE

        return MigrationDecision(
            policy_name="always_migrate",
            action=action,
            timestamp_ms=point.timestamp_ms,
            score=1.0,
            reasons=tuple(reasons),
            current_price=point.value,
            cooldown_remaining=self.cooldown_remaining,
        )


class RollingZScorePolicy:
    """Simple baseline using a standard rolling z-score with one tunable parameter."""

    def __init__(self, config: Optional[RollingZScoreConfig] = None) -> None:
        self.config = config or RollingZScoreConfig()
        self.price_history: Deque[float] = deque(maxlen=self.config.rolling_window_points)
        self.cooldown_remaining = 0

    def evaluate(self, point: TelemetryPoint) -> MigrationDecision:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        action = DecisionAction.STABLE
        reasons: List[str] = []
        zscore = 0.0

        if len(self.price_history) >= self.config.rolling_window_points:
            prices = list(self.price_history)
            mean_price = statistics.fmean(prices)
            price_std = statistics.pstdev(prices) if len(prices) >= 2 else 0.0
            
            zscore = (point.value - mean_price) / price_std if price_std > 1e-9 else 0.0

            if zscore >= self.config.zscore_threshold and self.cooldown_remaining == 0:
                action = DecisionAction.MIGRATE
                self.cooldown_remaining = self.config.cooldown_points
                reasons.append("zscore_threshold_breach")
            elif zscore >= self.config.zscore_threshold * 0.8:
                action = DecisionAction.OBSERVE
                reasons.append("zscore_elevated")

        self.price_history.append(point.value)

        return MigrationDecision(
            policy_name="rolling_zscore",
            action=action,
            timestamp_ms=point.timestamp_ms,
            score=zscore,
            reasons=tuple(reasons),
            current_price=point.value,
            cooldown_remaining=self.cooldown_remaining,
        )


class RandomPolicy:
    """Baseline that triggers migrations randomly based on a calibrated probability."""

    def __init__(self, config: Optional[RandomConfig] = None) -> None:
        self.config = config or RandomConfig()
        self.cooldown_remaining = 0
        # Initialize isolated random state to avoid interfering with global random
        self.rng = random.Random(42)  

    def evaluate(self, point: TelemetryPoint) -> MigrationDecision:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

        action = DecisionAction.STABLE
        reasons: List[str] = []

        if self.cooldown_remaining == 0 and self.rng.random() < self.config.firing_probability:
            action = DecisionAction.MIGRATE
            self.cooldown_remaining = self.config.cooldown_points
            reasons.append("random_trigger")

        return MigrationDecision(
            policy_name="random",
            action=action,
            timestamp_ms=point.timestamp_ms,
            score=0.0,
            reasons=tuple(reasons),
            current_price=point.value,
            cooldown_remaining=self.cooldown_remaining,
        )
