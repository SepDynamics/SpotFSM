"""Bridge service that turns live telemetry into structural manifold windows."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from scripts.research.regime_manifold.encoder import TelemetryManifoldEncoder

from .connectors import (
    CloudWatchMetricConnector,
    LLMProbeConnector,
    PrometheusRangeConnector,
    TelemetrySource,
)
from .types import BridgeConfig, BridgeObservation, MetricDefinition


class BridgeService:
    """Polls telemetry sources and emits the latest structural view per metric."""

    def __init__(
        self,
        config: BridgeConfig,
        *,
        connectors: Dict[str, TelemetrySource],
        encoder: Optional[TelemetryManifoldEncoder] = None,
    ) -> None:
        self.config = config
        self.connectors = connectors
        self.encoder = encoder or TelemetryManifoldEncoder(
            window_points=config.encoder.window_points,
            stride_points=config.encoder.stride_points,
            baseline_period=config.encoder.baseline_period,
        )

    def poll_once(self, *, end_time: Optional[datetime] = None) -> List[BridgeObservation]:
        return [self.poll_metric(metric, end_time=end_time) for metric in self.config.metrics]

    def poll_metric(
        self, metric: MetricDefinition, *, end_time: Optional[datetime] = None
    ) -> BridgeObservation:
        connector = self.connectors[metric.provider]

        try:
            points = connector.fetch_points(metric, end_time=end_time)
        except Exception as exc:
            return BridgeObservation(
                metric_id=metric.metric_id,
                provider=metric.provider,
                sample_count=0,
                labels=dict(metric.labels),
                error=str(exc),
            )

        if not points:
            return BridgeObservation(
                metric_id=metric.metric_id,
                provider=metric.provider,
                sample_count=0,
                labels=dict(metric.labels),
                error="source returned no usable samples",
            )

        try:
            windows = self.encoder.encode(
                points,
                metric_id=metric.metric_id,
                return_only_latest=True,
                align_latest_to_stride=False,
            )
        except Exception as exc:
            return BridgeObservation(
                metric_id=metric.metric_id,
                provider=metric.provider,
                sample_count=len(points),
                labels=dict(metric.labels),
                first_timestamp_ms=points[0].timestamp_ms,
                last_timestamp_ms=points[-1].timestamp_ms,
                current_value=points[-1].value,
                error=str(exc),
            )

        latest_window = windows[-1] if windows else None
        return BridgeObservation(
            metric_id=metric.metric_id,
            provider=metric.provider,
            sample_count=len(points),
            labels=dict(metric.labels),
            first_timestamp_ms=points[0].timestamp_ms,
            last_timestamp_ms=points[-1].timestamp_ms,
            current_value=points[-1].value,
            latest_signature=latest_window.signature if latest_window else None,
            latest_hazard=(
                float(latest_window.metrics.get("hazard"))
                if latest_window and "hazard" in latest_window.metrics
                else None
            ),
            latest_window=latest_window,
            error=(
                None
                if latest_window is not None
                else (
                    "insufficient samples for one manifold window "
                    f"(need {self.encoder.window_points}, got {len(points)})"
                )
            ),
        )


def build_bridge_service(
    config: BridgeConfig,
    *,
    prometheus_connector: Optional[PrometheusRangeConnector] = None,
    cloudwatch_connector: Optional[CloudWatchMetricConnector] = None,
    llm_probe_connector: Optional[LLMProbeConnector] = None,
    encoder: Optional[TelemetryManifoldEncoder] = None,
) -> BridgeService:
    connectors: Dict[str, TelemetrySource] = {}
    providers = {metric.provider for metric in config.metrics}

    if "prometheus" in providers:
        if config.prometheus is None and prometheus_connector is None:
            raise ValueError("bridge config uses Prometheus metrics but no prometheus block is configured")
        connectors["prometheus"] = prometheus_connector or PrometheusRangeConnector(
            config.prometheus
        )

    if "cloudwatch" in providers:
        if config.cloudwatch is None and cloudwatch_connector is None:
            raise ValueError("bridge config uses CloudWatch metrics but no cloudwatch block is configured")
        connectors["cloudwatch"] = cloudwatch_connector or CloudWatchMetricConnector(
            config.cloudwatch
        )

    if "llm_probe" in providers:
        if config.llm_probe is None and llm_probe_connector is None:
            raise ValueError("bridge config uses llm_probe metrics but no llm_probe block is configured")
        connectors["llm_probe"] = llm_probe_connector or LLMProbeConnector(
            config.llm_probe
        )

    return BridgeService(config, connectors=connectors, encoder=encoder)
