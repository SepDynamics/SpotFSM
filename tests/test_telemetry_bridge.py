from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.research.regime_manifold import encoder as manifold_encoder
from scripts.research.regime_manifold.decoder import TelemetryManifoldDecoder
from scripts.research.regime_manifold.types import CanonicalFeatures, EncodedWindow, TelemetryPoint
from scripts.telemetry_bridge.connectors import (
    CloudWatchMetricConnector,
    ConnectorError,
    PrometheusRangeConnector,
)
from scripts.telemetry_bridge.service import BridgeService
from scripts.telemetry_bridge.types import (
    BridgeConfig,
    CloudWatchConnectionConfig,
    EncoderSettings,
    MetricDefinition,
    PrometheusConnectionConfig,
)


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class DummySession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return DummyResponse(self.payload)


class DummyCloudWatchClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def test_prometheus_connector_parses_query_range_series():
    session = DummySession(
        {
            "status": "success",
            "data": {
                "result": [
                    {
                        "values": [
                            [1767225600, "0.12"],
                            [1767225660, "0.19"],
                            [1767225720, "0.27"],
                        ]
                    }
                ]
            },
        }
    )
    connector = PrometheusRangeConnector(
        PrometheusConnectionConfig(base_url="http://prometheus:9090"),
        session=session,
    )
    metric = MetricDefinition(
        metric_id="spot_price",
        provider="prometheus",
        query="max(aws_spot_price_usd)",
        period_seconds=60,
        lookback_points=3,
    )

    end_time = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    points = connector.fetch_points(metric, end_time=end_time)

    assert [point.value for point in points] == [0.12, 0.19, 0.27]
    assert session.calls[0][0] == "http://prometheus:9090/api/v1/query_range"
    params = session.calls[0][1]["params"]
    assert params["query"] == "max(aws_spot_price_usd)"
    assert params["end"] - params["start"] == 120


def test_prometheus_connector_rejects_multiple_series():
    session = DummySession(
        {
            "status": "success",
            "data": {"result": [{"values": [[1, "1.0"]]}, {"values": [[1, "2.0"]]}]},
        }
    )
    connector = PrometheusRangeConnector(
        PrometheusConnectionConfig(base_url="http://prometheus:9090"),
        session=session,
    )
    metric = MetricDefinition(
        metric_id="spot_price",
        provider="prometheus",
        query="aws_spot_price_usd",
    )

    with pytest.raises(ConnectorError):
        connector.fetch_points(metric, end_time=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_cloudwatch_connector_parses_and_sorts_metric_data():
    client = DummyCloudWatchClient(
        {
            "MetricDataResults": [
                {
                    "Timestamps": [
                        datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
                        datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
                    ],
                    "Values": [72.0, 65.0],
                }
            ]
        }
    )
    connector = CloudWatchMetricConnector(
        CloudWatchConnectionConfig(region="us-east-1"),
        client=client,
    )
    metric = MetricDefinition(
        metric_id="cpu",
        provider="cloudwatch",
        namespace="AWS/EC2",
        metric_name="CPUUtilization",
        statistic="Average",
        period_seconds=60,
        lookback_points=2,
        dimensions={"AutoScalingGroupName": "ci-runner-spot"},
    )

    points = connector.fetch_points(metric, end_time=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc))

    assert [point.value for point in points] == [65.0, 72.0]
    request = client.calls[0]["MetricDataQueries"][0]["MetricStat"]["Metric"]
    assert request["Namespace"] == "AWS/EC2"
    assert request["MetricName"] == "CPUUtilization"


def test_bridge_service_emits_latest_window(monkeypatch):
    monkeypatch.setattr(
        manifold_encoder.StructuralAnalyzer,
        "analyze",
        staticmethod(
            lambda _: (
                "c0.500_s0.400_e0.600",
                {
                    "coherence": 0.5,
                    "stability": 0.4,
                    "entropy": 0.6,
                    "hazard": 0.7,
                    "rupture": 0.2,
                },
            )
        ),
    )

    class FakeConnector:
        def fetch_points(self, metric, *, end_time=None):
            return [
                TelemetryPoint(timestamp_ms=1_000 * idx, value=10.0 + idx)
                for idx in range(12)
            ]

    config = BridgeConfig(
        metrics=(
            MetricDefinition(
                metric_id="spot_price",
                provider="prometheus",
                query="max(aws_spot_price_usd)",
                lookback_points=12,
            ),
        ),
        encoder=EncoderSettings(window_points=8, stride_points=4, baseline_period=4),
    )
    service = BridgeService(config, connectors={"prometheus": FakeConnector()})

    observation = service.poll_metric(config.metrics[0])

    assert observation.latest_hazard == 0.7
    assert observation.latest_signature == "c0.500_s0.400_e0.600"
    assert observation.latest_window is not None
    assert observation.sample_count == 12
    assert observation.error is None


def test_bridge_service_reports_insufficient_samples():
    class FakeConnector:
        def fetch_points(self, metric, *, end_time=None):
            return [
                TelemetryPoint(timestamp_ms=1_000 * idx, value=10.0 + idx)
                for idx in range(4)
            ]

    config = BridgeConfig(
        metrics=(
            MetricDefinition(
                metric_id="spot_price",
                provider="prometheus",
                query="max(aws_spot_price_usd)",
                lookback_points=4,
            ),
        ),
        encoder=EncoderSettings(window_points=8, stride_points=4, baseline_period=4),
    )
    service = BridgeService(config, connectors={"prometheus": FakeConnector()})

    observation = service.poll_metric(config.metrics[0])

    assert observation.latest_window is None
    assert "insufficient samples" in observation.error


def test_decoder_reconstructs_telemetry_buckets():
    window = EncodedWindow(
        metric_id="spot_price",
        start_ms=0,
        end_ms=7_000,
        bits=bytes([0b11101101]),
        bit_length=8,
        signature="c0.600_s0.400_e0.500",
        metrics={"hazard": 0.3},
        canonical=CanonicalFeatures(0.1, 100.0, 0.0, 0.0, 0.0, "neutral", 0.5),
        codec_meta={"baseline_mean": 100.0, "baseline_std": 10.0},
    )

    decoded = TelemetryManifoldDecoder.decode_window_bits(window)

    assert len(decoded) == 1
    assert decoded[0]["direction"] == 1.0
    assert decoded[0]["velocity_bucket"] == 6.0
    assert decoded[0]["zscore_bucket"] == 3.0
    assert decoded[0]["is_static"] == 1.0
