"""Data bridge for streaming telemetry into manifold windows."""

from .service import BridgeObservation, BridgeService, build_bridge_service
from .types import (
    BridgeConfig,
    CloudWatchConnectionConfig,
    EncoderSettings,
    LLMProbeConnectionConfig,
    MetricDefinition,
    PrometheusConnectionConfig,
)

__all__ = [
    "BridgeConfig",
    "BridgeObservation",
    "BridgeService",
    "CloudWatchConnectionConfig",
    "EncoderSettings",
    "LLMProbeConnectionConfig",
    "MetricDefinition",
    "PrometheusConnectionConfig",
    "build_bridge_service",
]
