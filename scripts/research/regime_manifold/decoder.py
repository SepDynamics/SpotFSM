"""Decoder for reconstructing telemetry-oriented buckets from encoded windows."""

from typing import Dict, List, Sequence

from .types import (
    BITS_PER_POINT,
    EPSILON_ZSCORE,
    EncodedWindow,
    MAX_VEL_BUCKET,
    MAX_ZSCORE_BUCKET,
)


class TelemetryManifoldDecoder:
    """Reconstruct bucket-level telemetry signals for inspection."""

    @staticmethod
    def decode_window_bits(window: EncodedWindow) -> List[Dict[str, float]]:
        bit_values = _bytes_to_bits(window.bits, window.bit_length)
        records: List[Dict[str, float]] = []
        idx = 0

        baseline_mean = float(window.codec_meta.get("baseline_mean", 0.0))
        baseline_std = max(
            EPSILON_ZSCORE,
            float(window.codec_meta.get("baseline_std", EPSILON_ZSCORE)),
        )

        while idx + BITS_PER_POINT <= len(bit_values):
            direction = bit_values[idx]
            velocity_bucket = _bits_to_int(bit_values[idx + 1 : idx + 4])
            zscore_bucket = _bits_to_int(bit_values[idx + 4 : idx + 6])
            flags = _bits_to_int(bit_values[idx + 6 : idx + 8])
            idx += BITS_PER_POINT

            velocity_ratio = velocity_bucket / MAX_VEL_BUCKET if MAX_VEL_BUCKET else 0.0
            zscore_ratio = zscore_bucket / MAX_ZSCORE_BUCKET if MAX_ZSCORE_BUCKET else 0.0

            velocity_est = velocity_ratio * baseline_std * 2.0
            if direction == 0:
                velocity_est *= -1.0
            if flags & 0b01:
                velocity_est = 0.0

            records.append(
                {
                    "direction": float(direction),
                    "velocity_bucket": float(velocity_bucket),
                    "velocity_est": velocity_est,
                    "zscore_bucket": float(zscore_bucket),
                    "zscore_est": zscore_ratio * 3.0,
                    "is_extreme": float(bool(flags & 0b10)),
                    "is_static": float(bool(flags & 0b01)),
                    "baseline_mean": baseline_mean,
                    "baseline_std": baseline_std,
                }
            )
        return records


class MarketManifoldDecoder(TelemetryManifoldDecoder):
    """Backward-compatible alias for the old decoder name."""


def _bits_to_int(bits: Sequence[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | (bit & 1)
    return value


def _bytes_to_bits(data: bytes, bit_length: int) -> List[int]:
    bits: List[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
            if len(bits) == bit_length:
                return bits
    return bits[:bit_length]
