"""Poll provider APIs with a fixed prompt and persist raw LLM health signals."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import requests
import yaml

from .types import LLMProbeConfig, ProbeResult, ProbeTarget

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


class ProbeConfigurationError(RuntimeError):
    """Raised when a probe target cannot be configured correctly."""


class LLMProbePoller:
    """Execute one streaming probe per configured provider/model target."""

    def __init__(
        self,
        config: LLMProbeConfig,
        *,
        session: Optional[requests.Session] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.env = env if env is not None else os.environ

    def probe_once(self) -> List[ProbeResult]:
        results: List[ProbeResult] = []
        for target in self.config.targets:
            try:
                results.append(self.probe_target(target))
            except ProbeConfigurationError as exc:
                print(str(exc), file=sys.stderr, flush=True)
        return results

    def probe_target(self, target: ProbeTarget) -> ProbeResult:
        api_key = self.env.get(target.api_key_env, "").strip()
        if not api_key:
            raise ProbeConfigurationError(
                f"missing API key env var '{target.api_key_env}' for {target.provider}:{target.model}"
            )

        if target.provider in {"openai", "groq"}:
            return self._probe_openai_compatible(target, api_key=api_key)
        if target.provider == "anthropic":
            return self._probe_anthropic(target, api_key=api_key)
        raise ProbeConfigurationError(f"unsupported probe provider '{target.provider}'")

    def _probe_openai_compatible(
        self,
        target: ProbeTarget,
        *,
        api_key: str,
    ) -> ProbeResult:
        request_started_ms = int(time.time() * 1000)
        started = time.perf_counter()
        ttft_ms: Optional[float] = None
        prompt_tokens = 0
        completion_tokens = 0
        error = False

        url = (
            target.base_url
            or (
                OPENAI_CHAT_COMPLETIONS_URL
                if target.provider == "openai"
                else GROQ_CHAT_COMPLETIONS_URL
            )
        )
        try:
            response = self.session.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": target.model,
                    "messages": [{"role": "user", "content": self.config.prompt}],
                    "temperature": 0,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "max_completion_tokens": target.max_completion_tokens,
                },
                stream=True,
                timeout=(
                    self.config.connect_timeout_seconds,
                    target.request_timeout_seconds
                    or self.config.request_timeout_seconds,
                ),
            )
        except requests.RequestException:
            total_latency_ms = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                provider=target.provider,
                model=target.model,
                timestamp_ms=request_started_ms,
                ttft_ms=total_latency_ms,
                total_latency_ms=total_latency_ms,
                tps=0.0,
                error=True,
                http_status=0,
                prompt_tokens=0,
                completion_tokens=0,
            )

        if response.status_code >= 400:
            total_latency_ms = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                provider=target.provider,
                model=target.model,
                timestamp_ms=request_started_ms,
                ttft_ms=total_latency_ms,
                total_latency_ms=total_latency_ms,
                tps=0.0,
                error=True,
                http_status=response.status_code,
                prompt_tokens=0,
                completion_tokens=0,
            )

        try:
            for _, data in _iter_sse_events(response.iter_lines(decode_unicode=True)):
                if data == "[DONE]":
                    break
                if not data:
                    continue
                payload = json.loads(data)
                usage = payload.get("usage") or {}
                prompt_tokens = int(
                    usage.get("prompt_tokens", prompt_tokens) or prompt_tokens
                )
                completion_tokens = int(
                    usage.get("completion_tokens", completion_tokens)
                    or completion_tokens
                )
                for choice in payload.get("choices", []):
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if isinstance(content, str) and content and ttft_ms is None:
                        ttft_ms = (time.perf_counter() - started) * 1000.0
        except Exception:
            error = True

        total_latency_ms = (time.perf_counter() - started) * 1000.0
        if ttft_ms is None:
            ttft_ms = total_latency_ms

        return ProbeResult(
            provider=target.provider,
            model=target.model,
            timestamp_ms=request_started_ms,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tps=_compute_tps(completion_tokens, total_latency_ms),
            error=error,
            http_status=response.status_code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _probe_anthropic(
        self,
        target: ProbeTarget,
        *,
        api_key: str,
    ) -> ProbeResult:
        request_started_ms = int(time.time() * 1000)
        started = time.perf_counter()
        ttft_ms: Optional[float] = None
        prompt_tokens = 0
        completion_tokens = 0
        error = False

        try:
            response = self.session.post(
                target.base_url or ANTHROPIC_MESSAGES_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": target.model,
                    "max_tokens": target.max_completion_tokens,
                    "temperature": 0,
                    "stream": True,
                    "messages": [{"role": "user", "content": self.config.prompt}],
                },
                stream=True,
                timeout=(
                    self.config.connect_timeout_seconds,
                    target.request_timeout_seconds
                    or self.config.request_timeout_seconds,
                ),
            )
        except requests.RequestException:
            total_latency_ms = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                provider=target.provider,
                model=target.model,
                timestamp_ms=request_started_ms,
                ttft_ms=total_latency_ms,
                total_latency_ms=total_latency_ms,
                tps=0.0,
                error=True,
                http_status=0,
                prompt_tokens=0,
                completion_tokens=0,
            )

        if response.status_code >= 400:
            total_latency_ms = (time.perf_counter() - started) * 1000.0
            return ProbeResult(
                provider=target.provider,
                model=target.model,
                timestamp_ms=request_started_ms,
                ttft_ms=total_latency_ms,
                total_latency_ms=total_latency_ms,
                tps=0.0,
                error=True,
                http_status=response.status_code,
                prompt_tokens=0,
                completion_tokens=0,
            )

        try:
            for event_name, data in _iter_sse_events(
                response.iter_lines(decode_unicode=True)
            ):
                if not data:
                    continue
                payload = json.loads(data)
                if event_name == "message_start":
                    usage = (payload.get("message") or {}).get("usage") or {}
                    prompt_tokens = int(
                        usage.get("input_tokens", prompt_tokens) or prompt_tokens
                    )
                    completion_tokens = int(
                        usage.get("output_tokens", completion_tokens)
                        or completion_tokens
                    )
                elif event_name == "content_block_delta":
                    delta = payload.get("delta") or {}
                    text = delta.get("text") or delta.get("partial_json")
                    if isinstance(text, str) and text and ttft_ms is None:
                        ttft_ms = (time.perf_counter() - started) * 1000.0
                elif event_name == "message_delta":
                    usage = payload.get("usage") or {}
                    prompt_tokens = int(
                        usage.get("input_tokens", prompt_tokens) or prompt_tokens
                    )
                    completion_tokens = int(
                        usage.get("output_tokens", completion_tokens)
                        or completion_tokens
                    )
                elif event_name == "error":
                    error = True
        except Exception:
            error = True

        total_latency_ms = (time.perf_counter() - started) * 1000.0
        if ttft_ms is None:
            ttft_ms = total_latency_ms

        return ProbeResult(
            provider=target.provider,
            model=target.model,
            timestamp_ms=request_started_ms,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tps=_compute_tps(completion_tokens, total_latency_ms),
            error=error,
            http_status=response.status_code,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def _iter_sse_events(lines: Iterable[str]) -> Iterator[Tuple[str, str]]:
    event_name = ""
    data_lines: List[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r")
        if not line:
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = ""
            data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())

    if data_lines:
        yield event_name, "\n".join(data_lines)


def _compute_tps(completion_tokens: int, total_latency_ms: float) -> float:
    if completion_tokens <= 0 or total_latency_ms <= 0.0:
        return 0.0
    return completion_tokens / (total_latency_ms / 1000.0)


def _load_config(path: Path) -> LLMProbeConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return LLMProbeConfig.from_mapping(payload)


def _emit_result(
    result: ProbeResult,
    *,
    pretty: bool,
    output_path: Optional[Path],
) -> None:
    payload = result.to_json()
    line = json.dumps(payload, indent=2 if pretty else None, sort_keys=pretty)
    print(line, flush=True)

    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
        handle.write("\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Poll LLM providers with a fixed prompt and write raw probe JSONL."
    )
    parser.add_argument(
        "--config", required=True, help="Path to the shared LLM routing YAML config."
    )
    parser.add_argument("--once", action="store_true", help="Run one probe per target and exit.")
    parser.add_argument(
        "--output-path",
        help="Optional raw probe JSONL output path. Overrides llm_probe.output_path in the config.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout instead of compact JSONL.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = _load_config(Path(args.config))
    poller = LLMProbePoller(config)
    output_path = (
        Path(args.output_path or config.output_path)
        if (args.output_path or config.output_path)
        else None
    )

    while True:
        for result in poller.probe_once():
            _emit_result(result, pretty=args.pretty, output_path=output_path)
        if args.once:
            return 0
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
