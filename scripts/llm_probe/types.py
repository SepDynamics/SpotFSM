"""Datatypes shared by the LLM probe poller and bridge connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

PROBE_SIGNALS = frozenset(
    {
        "ttft_ms",
        "total_latency_ms",
        "tps",
        "error",
        "http_status",
        "prompt_tokens",
        "completion_tokens",
    }
)
SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic", "groq"})


def parse_probe_metric_id(metric_id: str) -> Tuple[str, str, str]:
    parts = [chunk.strip() for chunk in metric_id.split(".")]
    if len(parts) < 3:
        raise ValueError(
            f"llm_probe metric_id '{metric_id}' must be '<provider>.<model>.<signal>'"
        )

    provider = parts[0].lower()
    signal = parts[-1]
    model = ".".join(parts[1:-1]).strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"llm_probe metric_id '{metric_id}' uses unsupported provider '{provider}'"
        )
    if not model:
        raise ValueError(f"llm_probe metric_id '{metric_id}' is missing a model slug")
    if signal not in PROBE_SIGNALS:
        raise ValueError(
            f"llm_probe metric_id '{metric_id}' uses unsupported signal '{signal}'"
        )
    return provider, model, signal


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    model: str
    timestamp_ms: int
    ttft_ms: float
    total_latency_ms: float
    tps: float
    error: bool
    http_status: int
    prompt_tokens: int
    completion_tokens: int

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ProbeResult":
        total_latency_ms = float(payload.get("total_latency_ms", 0.0))
        completion_tokens = int(payload.get("completion_tokens", 0))
        computed_tps = (
            completion_tokens / (total_latency_ms / 1000.0)
            if total_latency_ms > 0.0
            else 0.0
        )
        return cls(
            provider=str(payload.get("provider", "")).strip().lower(),
            model=str(payload.get("model", "")).strip(),
            timestamp_ms=int(payload.get("timestamp_ms", 0)),
            ttft_ms=float(payload.get("ttft_ms", total_latency_ms)),
            total_latency_ms=total_latency_ms,
            tps=float(payload.get("tps", computed_tps)),
            error=bool(payload.get("error", False)),
            http_status=int(payload.get("http_status", 0)),
            prompt_tokens=int(payload.get("prompt_tokens", 0)),
            completion_tokens=completion_tokens,
        )

    def value_for_signal(self, signal: str) -> float:
        if signal == "ttft_ms":
            return self.ttft_ms
        if signal == "total_latency_ms":
            return self.total_latency_ms
        if signal == "tps":
            return self.tps
        if signal == "error":
            return 1.0 if self.error else 0.0
        if signal == "http_status":
            return float(self.http_status)
        if signal == "prompt_tokens":
            return float(self.prompt_tokens)
        if signal == "completion_tokens":
            return float(self.completion_tokens)
        raise ValueError(f"unsupported probe signal '{signal}'")

    def to_json(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "timestamp_ms": self.timestamp_ms,
            "ttft_ms": self.ttft_ms,
            "total_latency_ms": self.total_latency_ms,
            "tps": self.tps,
            "error": self.error,
            "http_status": self.http_status,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


@dataclass(frozen=True)
class ProbeTarget:
    provider: str
    model: str
    api_key_env: str
    base_url: Optional[str] = None
    max_completion_tokens: int = 8
    request_timeout_seconds: Optional[float] = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ProbeTarget":
        provider = str(payload.get("provider", "")).strip().lower()
        model = str(payload.get("model", "")).strip()
        api_key_env = str(payload.get("api_key_env", "")).strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"unsupported probe provider '{provider}'")
        if not model:
            raise ValueError("probe target requires model")
        if not api_key_env:
            raise ValueError("probe target requires api_key_env")
        request_timeout = payload.get("request_timeout_seconds")
        return cls(
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            base_url=(str(payload.get("base_url", "")).strip() or None),
            max_completion_tokens=int(payload.get("max_completion_tokens", 8)),
            request_timeout_seconds=(
                float(request_timeout) if request_timeout is not None else None
            ),
        )


@dataclass(frozen=True)
class LLMProbeConfig:
    poll_interval_seconds: int = 30
    prompt: str = "Reply with exactly: OK"
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 30.0
    output_path: str = "output/probes/llm_probe.jsonl"
    input_glob: str = "output/probes/*.jsonl"
    targets: Tuple[ProbeTarget, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LLMProbeConfig":
        llm_payload = payload.get("llm_probe", {}) or {}
        targets_payload = llm_payload.get("targets", [])
        return cls(
            poll_interval_seconds=int(payload.get("poll_interval_seconds", 30)),
            prompt=str(llm_payload.get("prompt", "Reply with exactly: OK")),
            connect_timeout_seconds=float(
                llm_payload.get("connect_timeout_seconds", 10.0)
            ),
            request_timeout_seconds=float(
                llm_payload.get("request_timeout_seconds", 30.0)
            ),
            output_path=str(
                llm_payload.get("output_path", "output/probes/llm_probe.jsonl")
            ),
            input_glob=str(llm_payload.get("input_glob", "output/probes/*.jsonl")),
            targets=tuple(ProbeTarget.from_mapping(item) for item in targets_payload),
        )
