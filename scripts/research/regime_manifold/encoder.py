"""Encoder for converting infrastructure telemetry windows into structural manifolds."""

import json
import math
import statistics
from typing import Dict, List, Sequence, Tuple

from .runtime import load_manifold_engine
from .types import (
    BITS_PER_POINT,
    TelemetryPoint,
    CanonicalFeatures,
    EncodedWindow,
    MIN_WINDOW_POINTS,
    MIN_STRIDE_POINTS,
    EPSILON_ZSCORE,
    MAX_VEL_BUCKET,
    MAX_ZSCORE_BUCKET,
    BIT_WIDTH_DIR,
    BIT_WIDTH_VEL,
    BIT_WIDTH_ZSCORE,
    BIT_WIDTH_FLAGS,
)


class FeatureExtractor:
    """Extracts canonical mathematical features from telemetry windows."""

    @staticmethod
    def extract(
        subset: Sequence[TelemetryPoint],
        velocities: Sequence[float],
        baseline_mean: float,
        baseline_std: float,
    ) -> CanonicalFeatures:
        if len(subset) < 2:
            return CanonicalFeatures(0.0, 0.0, 0.0, 0.0, 0.0, "insufficient", 0.0)

        realized_vol = statistics.pstdev(velocities) if len(velocities) >= 2 else 0.0
        mean_val = statistics.fmean(p.value for p in subset)
        autocorr = _lag1_autocorr(velocities)

        xs = list(range(len(subset)))
        vals = [p.value for p in subset]
        slope = _ols_slope(xs, vals)
        trend_strength = (slope * len(subset)) / max(EPSILON_ZSCORE, realized_vol)

        zscore_avg = (mean_val - baseline_mean) / max(EPSILON_ZSCORE, baseline_std)

        regime, confidence = _classify_regime(
            trend_strength, autocorr, realized_vol, baseline_std
        )

        return CanonicalFeatures(
            realized_vol=realized_vol,
            mean_val=mean_val,
            autocorr=autocorr,
            trend_strength=trend_strength,
            zscore_avg=zscore_avg,
            regime=regime,
            regime_confidence=confidence,
        )


class WindowBitEncoder:
    """Encodes a sequence of telemetry points into a bitwise representation."""

    @staticmethod
    def encode_bits(
        subset: Sequence[TelemetryPoint],
        baseline_mean: float,
        baseline_std: float,
        *,
        prev_value: float,
    ) -> Tuple[List[int], Dict[str, float]]:
        bits: List[int] = []
        last_value = prev_value
        std_safe = max(baseline_std, EPSILON_ZSCORE)

        for point in subset:
            velocity = point.value - last_value
            direction = 1 if velocity >= 0 else 0
            
            # Map velocity magnitude to 0-7
            vel_ratio = min(1.0, abs(velocity) / (std_safe * 2.0))
            vel_bucket = min(MAX_VEL_BUCKET, int(round(vel_ratio * MAX_VEL_BUCKET)))
            
            # Map Z-score magnitude to 0-3
            zscore = abs(point.value - baseline_mean) / std_safe
            zscore_ratio = min(1.0, zscore / 3.0)
            zscore_bucket = min(MAX_ZSCORE_BUCKET, int(round(zscore_ratio * MAX_ZSCORE_BUCKET)))

            # Flags (2 bits)
            is_extreme = 1 if zscore >= 3.0 else 0
            is_static = 1 if velocity == 0.0 else 0
            flags = (is_extreme << 1) | is_static

            bits.extend(_int_to_bits(direction, BIT_WIDTH_DIR))
            bits.extend(_int_to_bits(vel_bucket, BIT_WIDTH_VEL))
            bits.extend(_int_to_bits(zscore_bucket, BIT_WIDTH_ZSCORE))
            bits.extend(_int_to_bits(flags, BIT_WIDTH_FLAGS))

            last_value = point.value

        meta = {
            "baseline_mean": float(baseline_mean),
            "baseline_std": float(baseline_std),
        }
        return bits, meta


class StructuralAnalyzer:
    """Interfaces with the Manifold Engine to analyze bitwise constraints."""

    @staticmethod
    def analyze(bit_bytes: bytes) -> Tuple[str, Dict[str, float]]:
        manifold_engine = load_manifold_engine()
        json_str = manifold_engine.analyze_bytes(
            bit_bytes, len(bit_bytes), len(bit_bytes), 3
        )
        parsed = json.loads(json_str)
        w = parsed.get("windows", [{}])[0]
        metrics = w.get("metrics", {})
        metrics["hazard"] = w.get("lambda_hazard", 0.0)
        metrics["rupture"] = metrics.get("rupture", 0.0)
        signature = w.get("signature", "")
        return signature, metrics


class TelemetryManifoldEncoder:
    """Convert rolling telemetry windows into reversible structural manifolds."""

    def __init__(
        self,
        *,
        window_points: int = 64,
        stride_points: int = 16,
        baseline_period: int = 60,
    ) -> None:
        if window_points < MIN_WINDOW_POINTS:
            raise ValueError(f"window_points must be >= {MIN_WINDOW_POINTS}")
        if stride_points < MIN_STRIDE_POINTS:
            raise ValueError(f"stride_points must be >= {MIN_STRIDE_POINTS}")
        self.window_points = window_points
        self.stride_points = stride_points
        self.baseline_period = baseline_period

    def encode(
        self,
        points: Sequence[TelemetryPoint],
        *,
        metric_id: str,
        return_only_latest: bool = False,
        align_latest_to_stride: bool = True,
    ) -> List[EncodedWindow]:
        if len(points) < self.window_points:
            return []

        # Simple moving baseline
        vals = [p.value for p in points]
        
        windows: List[EncodedWindow] = []

        start = 0
        if return_only_latest:
            max_start = len(points) - self.window_points
            if max_start >= 0:
                if align_latest_to_stride:
                    start = (max_start // self.stride_points) * self.stride_points
                else:
                    start = max_start

        while start + self.window_points <= len(points):
            end = start + self.window_points
            subset = points[start:end]
            
            # Use rolling baseline for this window based on history
            hist_start = max(0, start - self.baseline_period)
            hist_vals = vals[hist_start:start] if start > 0 else vals[0:end]
            baseline_mean = statistics.fmean(hist_vals) if hist_vals else vals[0]
            baseline_std = statistics.pstdev(hist_vals) if len(hist_vals) > 1 else max(EPSILON_ZSCORE, baseline_mean * 0.05)

            subset_velocities = _calculate_velocities(points[max(0, start - 1):end])
            if start == 0 and len(subset_velocities) > 0:
                subset_velocities = subset_velocities[1:] # strip the dummy first if needed

            bits, meta = WindowBitEncoder.encode_bits(
                subset,
                baseline_mean,
                baseline_std,
                prev_value=points[start - 1].value if start > 0 else subset[0].value,
            )

            bit_bytes = _bits_to_bytes(bits)
            signature, metrics = StructuralAnalyzer.analyze(bit_bytes)

            canonical = FeatureExtractor.extract(
                subset, subset_velocities, baseline_mean, baseline_std
            )

            windows.append(
                EncodedWindow(
                    metric_id=metric_id,
                    start_ms=subset[0].timestamp_ms,
                    end_ms=subset[-1].timestamp_ms,
                    bits=bit_bytes,
                    bit_length=len(bits),
                    signature=signature,
                    metrics=metrics,
                    canonical=canonical,
                    codec_meta=meta,
                )
            )
            start += self.stride_points
        return windows


def _calculate_velocities(points: Sequence[TelemetryPoint]) -> List[float]:
    vels: List[float] = [0.0]
    for idx in range(1, len(points)):
        vels.append(points[idx].value - points[idx - 1].value)
    return vels


def _int_to_bits(value: int, width: int) -> List[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def _bits_to_bytes(bits: Sequence[int]) -> bytes:
    buf = bytearray()
    for idx in range(0, len(bits), 8):
        chunk = bits[idx : idx + 8]
        value = 0
        for bit in chunk:
            value = (value << 1) | (bit & 1)
        value <<= max(0, 8 - len(chunk))
        buf.append(value & 0xFF)
    return bytes(buf)


def _lag1_autocorr(series: Sequence[float]) -> float:
    if len(series) < 2:
        return 0.0
    mean = statistics.fmean(series)
    num = 0.0
    denom = 0.0
    for idx in range(1, len(series)):
        x0 = series[idx - 1] - mean
        x1 = series[idx] - mean
        num += x0 * x1
        denom += x0 * x0
    return num / denom if denom else 0.0


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom = sum((x - mean_x) ** 2 for x in xs)
    return num / denom if denom else 0.0


def _classify_regime(
    trend_strength: float,
    autocorr: float,
    realized_vol: float,
    baseline_std: float,
) -> Tuple[str, float]:
    std_safe = max(1e-6, baseline_std)
    vol_ratio = realized_vol / std_safe

    if trend_strength >= 1.5 and autocorr >= 0.1:
        return "trend_up", min(1.0, trend_strength / 3.0)
    if trend_strength <= -1.5 and autocorr >= 0.1:
        return "trend_down", min(1.0, abs(trend_strength) / 3.0)
    if vol_ratio < 0.75 and abs(autocorr) < 0.25:
        return "stable", 1.0 - vol_ratio
    if vol_ratio >= 1.5 and abs(autocorr) < 0.1:
        return "chaotic", min(1.0, vol_ratio / 3.0)
    return "neutral", 0.5
