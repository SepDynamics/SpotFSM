"""Data bridge for streaming infrastructure telemetry into manifold windows."""

from .service import BridgeObservation, BridgeService, build_bridge_service
from .types import (
    BridgeConfig,
    CloudWatchConnectionConfig,
    EncoderSettings,
    MetricDefinition,
    PrometheusConnectionConfig,
)

__all__ = [
    "BridgeConfig",
    "BridgeObservation",
    "BridgeService",
    "CloudWatchConnectionConfig",
    "EncoderSettings",
    "MetricDefinition",
    "PrometheusConnectionConfig",
    "build_bridge_service",
]
