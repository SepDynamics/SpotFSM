from __future__ import annotations

import requests

from scripts.llm_probe.poller import LLMProbePoller
from scripts.llm_probe.types import LLMProbeConfig, ProbeTarget, parse_probe_metric_id


class DummyStreamingResponse:
    def __init__(self, status_code: int, lines):
        self.status_code = status_code
        self._lines = list(lines)

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


class DummySession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._responses.pop(0)


class FailingSession:
    def post(self, url, **kwargs):
        raise requests.RequestException("dial failed")


def test_parse_probe_metric_id_supports_dotted_models():
    provider, model, signal = parse_probe_metric_id("groq.llama-3.1-8b-instant.tps")
    assert provider == "groq"
    assert model == "llama-3.1-8b-instant"
    assert signal == "tps"


def test_openai_probe_parses_stream_usage_and_ttft():
    session = DummySession(
        [
            DummyStreamingResponse(
                200,
                [
                    'data: {"choices":[{"delta":{"role":"assistant"}}]}',
                    "",
                    'data: {"choices":[{"delta":{"content":"OK"}}]}',
                    "",
                    'data: {"choices":[],"usage":{"prompt_tokens":6,"completion_tokens":1}}',
                    "",
                    "data: [DONE]",
                    "",
                ],
            )
        ]
    )
    poller = LLMProbePoller(
        LLMProbeConfig(
            targets=(
                ProbeTarget(
                    provider="openai",
                    model="gpt-4o-mini",
                    api_key_env="OPENAI_API_KEY",
                ),
            )
        ),
        session=session,
        env={"OPENAI_API_KEY": "test-key"},
    )

    result = poller.probe_once()[0]

    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.http_status == 200
    assert result.prompt_tokens == 6
    assert result.completion_tokens == 1
    assert result.ttft_ms >= 0.0
    assert result.total_latency_ms >= result.ttft_ms
    assert result.error is False


def test_anthropic_probe_parses_message_events():
    session = DummySession(
        [
            DummyStreamingResponse(
                200,
                [
                    'event: message_start',
                    'data: {"message":{"usage":{"input_tokens":7,"output_tokens":0}}}',
                    "",
                    'event: content_block_delta',
                    'data: {"delta":{"text":"OK"}}',
                    "",
                    'event: message_delta',
                    'data: {"usage":{"output_tokens":2}}',
                    "",
                    'event: message_stop',
                    'data: {"type":"message_stop"}',
                    "",
                ],
            )
        ]
    )
    poller = LLMProbePoller(
        LLMProbeConfig(
            targets=(
                ProbeTarget(
                    provider="anthropic",
                    model="claude-3-5-haiku-latest",
                    api_key_env="ANTHROPIC_API_KEY",
                ),
            )
        ),
        session=session,
        env={"ANTHROPIC_API_KEY": "test-key"},
    )

    result = poller.probe_once()[0]

    assert result.provider == "anthropic"
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 2
    assert result.http_status == 200
    assert result.ttft_ms >= 0.0
    assert result.error is False


def test_probe_returns_error_record_on_http_failure():
    session = DummySession([DummyStreamingResponse(429, [])])
    poller = LLMProbePoller(
        LLMProbeConfig(
            targets=(
                ProbeTarget(
                    provider="groq",
                    model="llama-3.1-8b-instant",
                    api_key_env="GROQ_API_KEY",
                ),
            )
        ),
        session=session,
        env={"GROQ_API_KEY": "test-key"},
    )

    result = poller.probe_once()[0]

    assert result.provider == "groq"
    assert result.http_status == 429
    assert result.error is True
    assert result.tps == 0.0


def test_probe_returns_error_record_on_transport_failure():
    poller = LLMProbePoller(
        LLMProbeConfig(
            targets=(
                ProbeTarget(
                    provider="openai",
                    model="gpt-4o-mini",
                    api_key_env="OPENAI_API_KEY",
                ),
            )
        ),
        session=FailingSession(),
        env={"OPENAI_API_KEY": "test-key"},
    )

    result = poller.probe_once()[0]

    assert result.provider == "openai"
    assert result.http_status == 0
    assert result.error is True
