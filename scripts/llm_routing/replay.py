"""Replay raw LLM probe data through structural and timeout routing policies."""

from __future__ import annotations

import argparse
import csv
import json
from glob import glob
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import yaml

from scripts.llm_probe.types import LLMProbeConfig, ProbeResult, parse_probe_metric_id
from scripts.research.regime_manifold import TelemetryManifoldEncoder, TelemetryPoint
from scripts.telemetry_bridge.types import BridgeConfig, EncoderSettings

from .policy import StructuralRoutingPolicy, TimeoutRoutingPolicy
from .types import (
    ProbeSeries,
    ReplayConfig,
    RoutingAction,
    RoutingDecision,
    RoutingTopologyConfig,
    StructuralRoutingConfig,
    TimeoutRoutingConfig,
    metric_id_to_target,
)


def load_probe_series(
    source_glob: str,
    *,
    metric_id: str,
) -> ProbeSeries:
    provider, model, signal = parse_probe_metric_id(metric_id)
    samples: List[ProbeResult] = []

    for candidate in sorted(glob(source_glob)):
        path = Path(candidate)
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = ProbeResult.from_mapping(json.loads(line))
                except Exception as exc:
                    raise ValueError(
                        f"failed to parse probe record in {path}:{line_number}: {exc}"
                    ) from exc
                if record.provider == provider and record.model == model:
                    samples.append(record)

    samples.sort(key=lambda sample: sample.timestamp_ms)
    return ProbeSeries(
        metric_id=metric_id,
        provider=provider,
        model=model,
        signal=signal,
        source_glob=source_glob,
        samples=tuple(samples),
    )


def run_replay(
    series: ProbeSeries,
    *,
    encoder: TelemetryManifoldEncoder,
    structural_policy: StructuralRoutingPolicy,
    timeout_policy: TimeoutRoutingPolicy,
    output_dir: str,
) -> Dict[str, object]:
    rows: List[Dict[str, object]] = []
    prefix: List[TelemetryPoint] = []

    for idx, sample in enumerate(series.samples):
        point = TelemetryPoint(
            timestamp_ms=sample.timestamp_ms,
            value=sample.value_for_signal(series.signal),
        )
        prefix.append(point)

        if len(prefix) >= encoder.window_points:
            latest_windows = encoder.encode(
                prefix,
                metric_id=series.metric_id,
                return_only_latest=True,
                align_latest_to_stride=False,
            )
            latest_window = latest_windows[-1] if latest_windows else None
            if latest_window is not None:
                structural_decision = structural_policy.evaluate(latest_window)
            else:
                structural_decision = _warmup_decision(
                    "structural",
                    sample,
                    primary_target=metric_id_to_target(series.metric_id),
                    fallback_target=structural_policy.config.topology.fallback_target_for(
                        structural_policy.config.topology.primary_target
                        or metric_id_to_target(series.metric_id)
                    ),
                    observed_value=point.value,
                )
        else:
            structural_decision = _warmup_decision(
                "structural",
                sample,
                primary_target=metric_id_to_target(series.metric_id),
                fallback_target=structural_policy.config.topology.fallback_target_for(
                    structural_policy.config.topology.primary_target
                    or metric_id_to_target(series.metric_id)
                ),
                observed_value=point.value,
            )

        timeout_decision = timeout_policy.evaluate(sample)

        rows.append(
            {
                "point_index": idx,
                "timestamp_ms": sample.timestamp_ms,
                "provider": sample.provider,
                "model": sample.model,
                "signal": series.signal,
                "signal_value": point.value,
                "ttft_ms": sample.ttft_ms,
                "total_latency_ms": sample.total_latency_ms,
                "tps": sample.tps,
                "error": int(sample.error),
                "http_status": sample.http_status,
                "structural_action": structural_decision.action.value,
                "structural_selected_target": structural_decision.selected_target,
                "structural_score": structural_decision.score,
                "structural_hazard": structural_decision.hazard,
                "structural_rupture": structural_decision.rupture,
                "structural_signature": structural_decision.signature,
                "structural_reasons": "|".join(structural_decision.reasons),
                "timeout_action": timeout_decision.action.value,
                "timeout_selected_target": timeout_decision.selected_target,
                "timeout_score": timeout_decision.score,
                "timeout_reasons": "|".join(timeout_decision.reasons),
            }
        )

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    metric_slug = series.metric_id.replace("/", "_")
    decisions_path = output_root / f"{metric_slug}_decisions.csv"
    summary_path = output_root / f"{metric_slug}_summary.json"

    _write_rows_csv(decisions_path, rows)
    summary = {
        "dataset": series.to_json(),
        "structural": _summarize_policy(rows, "structural"),
        "timeout": _summarize_policy(rows, "timeout"),
        "comparison": _compare_policies(rows),
        "artifacts": {
            "decisions_csv": str(decisions_path),
            "summary_json": str(summary_path),
        },
        "notes": [
            "Replay compares structural routing against a hard timeout/error baseline.",
            "Status-page incident attribution is not wired in yet.",
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay raw LLM probe data through structural and timeout routing policies."
    )
    parser.add_argument("--config", required=True, help="Path to the shared LLM routing YAML config.")
    parser.add_argument(
        "--metric-id",
        help="Override replay.structural_metric_id from the config.",
    )
    parser.add_argument(
        "--output-dir",
        help="Override replay.output_dir from the config.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = _load_yaml(args.config)
    bridge_config = BridgeConfig.from_mapping(payload)
    llm_probe_config = LLMProbeConfig.from_mapping(payload)
    replay_config = ReplayConfig.from_mapping(
        payload.get("replay"),
        default_source_glob=llm_probe_config.input_glob,
    )

    metric_id = args.metric_id or replay_config.structural_metric_id or _default_metric_id(
        bridge_config
    )
    source_glob = replay_config.source_glob
    series = load_probe_series(source_glob, metric_id=metric_id)
    if not series.samples:
        raise SystemExit(
            f"no probe samples found for {metric_id!r} under {source_glob!r}"
        )

    encoder_settings = EncoderSettings.from_mapping(payload.get("encoder"))
    topology = RoutingTopologyConfig.from_mapping(
        payload.get("routing"),
        default_primary_target=metric_id_to_target(metric_id),
    )
    structural_config = StructuralRoutingConfig.from_mapping(
        (payload.get("routing") or {}).get("structural_policy"),
        topology=topology,
    )
    timeout_config = TimeoutRoutingConfig.from_mapping(
        (payload.get("routing") or {}).get("timeout_policy"),
        topology=topology,
    )

    encoder = TelemetryManifoldEncoder(
        window_points=encoder_settings.window_points,
        stride_points=encoder_settings.stride_points,
        baseline_period=encoder_settings.baseline_period,
    )
    summary = run_replay(
        series,
        encoder=encoder,
        structural_policy=StructuralRoutingPolicy(structural_config),
        timeout_policy=TimeoutRoutingPolicy(timeout_config),
        output_dir=args.output_dir or replay_config.output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _default_metric_id(config: BridgeConfig) -> str:
    for metric in config.metrics:
        if metric.provider != "llm_probe":
            continue
        _, _, signal = parse_probe_metric_id(metric.metric_id)
        if signal != "error":
            return metric.metric_id
    raise ValueError("config does not define a replayable llm_probe metric")


def _warmup_decision(
    policy_name: str,
    sample: ProbeResult,
    *,
    primary_target: str,
    fallback_target: Optional[str],
    observed_value: float,
) -> RoutingDecision:
    return RoutingDecision(
        policy_name=policy_name,
        action=RoutingAction.PRIMARY,
        timestamp_ms=sample.timestamp_ms,
        score=0.0,
        reasons=("warmup",),
        primary_target=primary_target,
        selected_target=primary_target,
        fallback_target=fallback_target,
        observed_value=observed_value,
        ttft_ms=sample.ttft_ms,
        error=sample.error,
    )


def _summarize_policy(rows: Sequence[Dict[str, object]], policy_key: str) -> Dict[str, object]:
    action_field = f"{policy_key}_action"
    route_rows = [row for row in rows if row[action_field] == RoutingAction.ROUTE_FALLBACK.value]
    observe_rows = [row for row in rows if row[action_field] == RoutingAction.OBSERVE.value]
    return {
        "route_count": len(route_rows),
        "observe_count": len(observe_rows),
        "primary_count": len(rows) - len(route_rows) - len(observe_rows),
        "first_route_timestamp_ms": (
            int(route_rows[0]["timestamp_ms"]) if route_rows else None
        ),
        "first_route_index": int(route_rows[0]["point_index"]) if route_rows else None,
        "last_selected_target": (
            str(rows[-1][f"{policy_key}_selected_target"]) if rows else None
        ),
    }


def _compare_policies(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    structural_first = next(
        (
            int(row["timestamp_ms"])
            for row in rows
            if row["structural_action"] == RoutingAction.ROUTE_FALLBACK.value
        ),
        None,
    )
    timeout_first = next(
        (
            int(row["timestamp_ms"])
            for row in rows
            if row["timeout_action"] == RoutingAction.ROUTE_FALLBACK.value
        ),
        None,
    )
    return {
        "structural_first_route_timestamp_ms": structural_first,
        "timeout_first_route_timestamp_ms": timeout_first,
        "structural_lead_over_timeout_s": (
            (timeout_first - structural_first) / 1000.0
            if structural_first is not None and timeout_first is not None
            else None
        ),
    }


def _write_rows_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_yaml(path: str) -> Dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return dict(yaml.safe_load(handle) or {})


if __name__ == "__main__":
    raise SystemExit(main())
