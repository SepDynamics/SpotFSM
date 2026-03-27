"""Prometheus and CloudWatch telemetry connectors for the Phase 2 bridge."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Protocol

import requests

from scripts.research.regime_manifold.types import TelemetryPoint

from .types import (
    CloudWatchConnectionConfig,
    MetricDefinition,
    PrometheusConnectionConfig,
)


class ConnectorError(RuntimeError):
    """Raised when a telemetry connector cannot produce a usable series."""


class TelemetrySource(Protocol):
    def fetch_points(
        self, metric: MetricDefinition, *, end_time: Optional[datetime] = None
    ) -> List[TelemetryPoint]:
        ...


class PrometheusRangeConnector:
    """Fetch fixed-step telemetry series through Prometheus query_range."""

    def __init__(
        self,
        config: PrometheusConnectionConfig,
        *,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()

    def fetch_points(
        self, metric: MetricDefinition, *, end_time: Optional[datetime] = None
    ) -> List[TelemetryPoint]:
        if metric.provider != "prometheus":
            raise ConnectorError(
                f"metric '{metric.metric_id}' is not configured for Prometheus"
            )

        end_time = _ensure_utc(end_time or datetime.now(timezone.utc))
        start_time = end_time - timedelta(
            seconds=max(0, (metric.lookback_points - 1) * metric.period_seconds)
        )

        params: Dict[str, Any] = {
            "query": metric.query,
            "start": start_time.timestamp(),
            "end": end_time.timestamp(),
            "step": metric.period_seconds,
        }

        request_kwargs: Dict[str, Any] = {
            "params": params,
            "timeout": self.config.timeout_seconds,
            "verify": self.config.verify_tls,
        }
        if self.config.headers:
            request_kwargs["headers"] = self.config.headers

        response = self.session.get(
            f"{self.config.base_url.rstrip('/')}/api/v1/query_range", **request_kwargs
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("status") != "success":
            raise ConnectorError(
                f"Prometheus query_range failed for metric '{metric.metric_id}'"
            )

        results = payload.get("data", {}).get("result", [])
        if not results:
            return []
        if len(results) > 1:
            raise ConnectorError(
                f"Prometheus query for '{metric.metric_id}' returned multiple series; "
                "aggregate to a single series in PromQL before ingesting it."
            )

        return _parse_prometheus_values(results[0].get("values", []))


class CloudWatchMetricConnector:
    """Fetch fixed-period metric series through CloudWatch GetMetricData."""

    def __init__(
        self,
        config: CloudWatchConnectionConfig,
        *,
        client: Optional[Any] = None,
    ) -> None:
        self.config = config
        self._static_client = client
        self._clients: Dict[str, Any] = {}

    def fetch_points(
        self, metric: MetricDefinition, *, end_time: Optional[datetime] = None
    ) -> List[TelemetryPoint]:
        if metric.provider != "cloudwatch":
            raise ConnectorError(
                f"metric '{metric.metric_id}' is not configured for CloudWatch"
            )

        region = metric.region or self.config.region
        if not region:
            raise ConnectorError(
                f"metric '{metric.metric_id}' requires a CloudWatch region"
            )

        end_time = _ensure_utc(end_time or datetime.now(timezone.utc))
        start_time = end_time - timedelta(
            seconds=max(0, (metric.lookback_points - 1) * metric.period_seconds)
        )

        client = self._get_client(region)
        response = client.get_metric_data(
            MetricDataQueries=[
                {
                    "Id": "spotfsm",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": metric.namespace,
                            "MetricName": metric.metric_name,
                            "Dimensions": [
                                {"Name": name, "Value": value}
                                for name, value in sorted(metric.dimensions.items())
                            ],
                        },
                        "Period": metric.period_seconds,
                        "Stat": metric.statistic,
                        **({"Unit": metric.unit} if metric.unit else {}),
                    },
                    "ReturnData": True,
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
            ScanBy="TimestampAscending",
        )

        results = response.get("MetricDataResults", [])
        if not results:
            return []
        return _parse_cloudwatch_values(results[0])

    def _get_client(self, region: str) -> Any:
        if self._static_client is not None:
            return self._static_client
        if region in self._clients:
            return self._clients[region]

        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise ConnectorError(
                "CloudWatch support requires boto3. Install dependencies from requirements.txt."
            ) from exc

        session_kwargs: Dict[str, Any] = {"region_name": region}
        if self.config.profile:
            session_kwargs["profile_name"] = self.config.profile
        session = boto3.session.Session(**session_kwargs)
        client = session.client("cloudwatch", region_name=region)
        self._clients[region] = client
        return client


def _parse_prometheus_values(values: Iterable[Iterable[Any]]) -> List[TelemetryPoint]:
    points: List[TelemetryPoint] = []
    for item in values:
        timestamp_s, value_raw = item
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        points.append(
            TelemetryPoint(timestamp_ms=int(float(timestamp_s) * 1000), value=value)
        )
    return points


def _parse_cloudwatch_values(result: Dict[str, Any]) -> List[TelemetryPoint]:
    timestamps = result.get("Timestamps", [])
    values = result.get("Values", [])
    points: List[TelemetryPoint] = []

    pairs = sorted(zip(timestamps, values), key=lambda item: item[0])
    for timestamp, value_raw in pairs:
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue

        ts = _ensure_utc(timestamp)
        points.append(TelemetryPoint(timestamp_ms=int(ts.timestamp() * 1000), value=value))
    return points


def _ensure_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
