"""Data types for structural manifold encoding and decoding."""

import base64
from dataclasses import dataclass
from typing import Dict, Optional

BITS_PER_POINT = 8

MIN_WINDOW_POINTS = 8
MIN_STRIDE_POINTS = 1
EPSILON_ZSCORE = 1e-6

BIT_WIDTH_DIR = 1
BIT_WIDTH_VEL = 3
BIT_WIDTH_ZSCORE = 2
BIT_WIDTH_FLAGS = 2

MAX_VEL_BUCKET = (1 << BIT_WIDTH_VEL) - 1
MAX_ZSCORE_BUCKET = (1 << BIT_WIDTH_ZSCORE) - 1

@dataclass
class TelemetryPoint:
    """Minimal telemetry point representation used by the codec."""
    timestamp_ms: int
    value: float


@dataclass
class CanonicalFeatures:
    realized_vol: float
    mean_val: float
    autocorr: float
    trend_strength: float
    zscore_avg: float
    regime: str
    regime_confidence: float


@dataclass
class EncodedWindow:
    metric_id: str
    start_ms: int
    end_ms: int
    bits: bytes
    bit_length: int
    signature: str
    metrics: Dict[str, float]
    canonical: CanonicalFeatures
    codec_meta: Dict[str, float]

    def bits_b64(self) -> str:
        return base64.b64encode(self.bits).decode("ascii")

    def to_json(self) -> Dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "bits_b64": self.bits_b64(),
            "bit_length": self.bit_length,
            "signature": self.signature,
            "metrics": self.metrics,
            "canonical": self.canonical.__dict__,
            "codec_meta": self.codec_meta,
        }
