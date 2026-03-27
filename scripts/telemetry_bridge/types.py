"""Configuration and bridge datatypes for live telemetry ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from scripts.llm_probe.types import parse_probe_metric_id
from scripts.research.regime_manifold.types import EncodedWindow


@dataclass(frozen=True)
class EncoderSettings:
    window_points: int = 64
    stride_points: int = 16
    baseline_period: int = 60

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "EncoderSettings":
        payload = payload or {}
        return cls(
            window_points=int(payload.get("window_points", 64)),
            stride_points=int(payload.get("stride_points", 16)),
            baseline_period=int(payload.get("baseline_period", 60)),
        )


@dataclass(frozen=True)
class PrometheusConnectionConfig:
    base_url: str
    timeout_seconds: float = 10.0
    verify_tls: bool = True
    headers: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls, payload: Optional[Mapping[str, Any]]
    ) -> Optional["PrometheusConnectionConfig"]:
        if not payload:
            return None
        base_url = str(payload.get("base_url", "")).strip()
        if not base_url:
            raise ValueError("prometheus.base_url is required when using Prometheus metrics")
        headers = {str(k): str(v) for k, v in dict(payload.get("headers", {})).items()}
        return cls(
            base_url=base_url,
            timeout_seconds=float(payload.get("timeout_seconds", 10.0)),
            verify_tls=bool(payload.get("verify_tls", True)),
            headers=headers,
        )


@dataclass(frozen=True)
class CloudWatchConnectionConfig:
    region: Optional[str] = None
    profile: Optional[str] = None

    @classmethod
    def from_mapping(
        cls, payload: Optional[Mapping[str, Any]]
    ) -> Optional["CloudWatchConnectionConfig"]:
        if not payload:
            return None
        region = payload.get("region")
        profile = payload.get("profile")
        return cls(
            region=str(region) if region else None,
            profile=str(profile) if profile else None,
        )


@dataclass(frozen=True)
class LLMProbeConnectionConfig:
    input_glob: str = "output/probes/*.jsonl"

    @classmethod
    def from_mapping(
        cls, payload: Optional[Mapping[str, Any]]
    ) -> Optional["LLMProbeConnectionConfig"]:
        if not payload:
            return None
        input_glob = (
            str(payload.get("input_glob", "")).strip()
            or str(payload.get("output_path", "")).strip()
            or "output/probes/*.jsonl"
        )
        return cls(input_glob=input_glob)


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    provider: str
    period_seconds: int = 60
    lookback_points: int = 96
    labels: Dict[str, str] = field(default_factory=dict)
    query: Optional[str] = None
    namespace: Optional[str] = None
    metric_name: Optional[str] = None
    dimensions: Dict[str, str] = field(default_factory=dict)
    statistic: str = "Average"
    region: Optional[str] = None
    unit: Optional[str] = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MetricDefinition":
        metric_id = str(payload.get("metric_id", "")).strip()
        provider = str(payload.get("provider", "")).strip().lower()
        if not metric_id:
            raise ValueError("each metric requires metric_id")
        if provider not in {"prometheus", "cloudwatch", "llm_probe"}:
            raise ValueError(
                f"metric '{metric_id}' must declare provider 'prometheus', 'cloudwatch', or 'llm_probe'"
            )

        labels = {str(k): str(v) for k, v in dict(payload.get("labels", {})).items()}
        dimensions = {
            str(k): str(v) for k, v in dict(payload.get("dimensions", {})).items()
        }

        metric = cls(
            metric_id=metric_id,
            provider=provider,
            period_seconds=int(payload.get("period_seconds", 60)),
            lookback_points=int(payload.get("lookback_points", 96)),
            labels=labels,
            query=str(payload["query"]).strip() if payload.get("query") else None,
            namespace=(
                str(payload["namespace"]).strip() if payload.get("namespace") else None
            ),
            metric_name=(
                str(payload["metric_name"]).strip()
                if payload.get("metric_name")
                else None
            ),
            dimensions=dimensions,
            statistic=str(payload.get("statistic", "Average")).strip(),
            region=str(payload["region"]).strip() if payload.get("region") else None,
            unit=str(payload["unit"]).strip() if payload.get("unit") else None,
        )
        metric.validate()
        return metric

    def validate(self) -> None:
        if self.period_seconds <= 0:
            raise ValueError(f"metric '{self.metric_id}' must use period_seconds > 0")
        if self.lookback_points <= 0:
            raise ValueError(f"metric '{self.metric_id}' must use lookback_points > 0")
        if self.provider == "prometheus" and not self.query:
            raise ValueError(f"metric '{self.metric_id}' requires query for Prometheus")
        if self.provider == "cloudwatch":
            if not self.namespace or not self.metric_name:
                raise ValueError(
                    f"metric '{self.metric_id}' requires namespace and metric_name for CloudWatch"
                )
        if self.provider == "llm_probe":
            parse_probe_metric_id(self.metric_id)


@dataclass(frozen=True)
class BridgeConfig:
    metrics: Tuple[MetricDefinition, ...]
    encoder: EncoderSettings = field(default_factory=EncoderSettings)
    poll_interval_seconds: int = 30
    output_path: Optional[str] = None
    prometheus: Optional[PrometheusConnectionConfig] = None
    cloudwatch: Optional[CloudWatchConnectionConfig] = None
    llm_probe: Optional[LLMProbeConnectionConfig] = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BridgeConfig":
        metrics_payload = payload.get("metrics", [])
        metrics = tuple(MetricDefinition.from_mapping(item) for item in metrics_payload)
        if not metrics:
            raise ValueError("bridge config must define at least one metric")
        return cls(
            metrics=metrics,
            encoder=EncoderSettings.from_mapping(payload.get("encoder")),
            poll_interval_seconds=int(payload.get("poll_interval_seconds", 30)),
            output_path=(
                str(payload["output_path"]).strip()
                if payload.get("output_path")
                else None
            ),
            prometheus=PrometheusConnectionConfig.from_mapping(payload.get("prometheus")),
            cloudwatch=CloudWatchConnectionConfig.from_mapping(payload.get("cloudwatch")),
            llm_probe=LLMProbeConnectionConfig.from_mapping(payload.get("llm_probe")),
        )


@dataclass
class BridgeObservation:
    metric_id: str
    provider: str
    sample_count: int
    labels: Dict[str, str]
    first_timestamp_ms: Optional[int] = None
    last_timestamp_ms: Optional[int] = None
    current_value: Optional[float] = None
    latest_signature: Optional[str] = None
    latest_hazard: Optional[float] = None
    latest_window: Optional[EncodedWindow] = None
    error: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "provider": self.provider,
            "labels": self.labels,
            "sample_count": self.sample_count,
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "current_value": self.current_value,
            "window_ready": self.latest_window is not None,
            "latest_signature": self.latest_signature,
            "latest_hazard": self.latest_hazard,
            "error": self.error,
            "window": self.latest_window.to_json() if self.latest_window else None,
        }
