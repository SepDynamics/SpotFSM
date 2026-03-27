"""Offline replay harness for real Spot price data."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from scripts.research.regime_manifold import TelemetryManifoldEncoder, TelemetryPoint
from scripts.telemetry_bridge.types import EncoderSettings

from .datasets import (
    DEFAULT_ZENODO_RECORD_ID,
    download_zenodo_file,
    load_aws_cli_spot_series,
    load_zenodo_spot_series,
    scan_zenodo_top_series,
)
from .operator import InMemoryStateStore, RedisStateStore, SimulatedOperator
from .policy import MigrationPolicy, ReactivePricePolicy
from .types import (
    DecisionAction,
    MigrationDecision,
    OperatorConfig,
    PolicyConfig,
    ReactiveBaselineConfig,
    ReplayConfig,
    ReplayEvent,
    SpotPriceSeries,
    SpotPriceSeriesSelector,
)


def detect_price_spike_events(
    points: Sequence[TelemetryPoint],
    config: ReplayConfig,
) -> List[ReplayEvent]:
    events: List[ReplayEvent] = []
    idx = 0
    while idx < len(points) - 1:
        anchor = points[idx]
        target_price = max(
            anchor.value * config.event_spike_multiplier,
            anchor.value + config.event_spike_absolute,
        )
        found_index = None
        max_index = min(len(points), idx + 1 + config.event_lookahead_points)
        for future_idx in range(idx + 1, max_index):
            if points[future_idx].value >= target_price:
                found_index = future_idx
                break
        if found_index is None:
            idx += 1
            continue
        event_point = points[found_index]
        events.append(
            ReplayEvent(
                anchor_index=idx,
                event_index=found_index,
                anchor_timestamp_ms=anchor.timestamp_ms,
                event_timestamp_ms=event_point.timestamp_ms,
                anchor_price=anchor.value,
                event_price=event_point.value,
            )
        )
        idx = found_index + 1
    return events


def run_replay(
    series: SpotPriceSeries,
    *,
    encoder: TelemetryManifoldEncoder,
    structural_policy: MigrationPolicy,
    reactive_policy: ReactivePricePolicy,
    replay_config: ReplayConfig,
    operator: SimulatedOperator,
    output_dir: str,
) -> Dict[str, object]:
    points = list(series.points)
    events = detect_price_spike_events(points, replay_config)
    rows: List[Dict[str, object]] = []
    prefix: List[TelemetryPoint] = []

    for idx, point in enumerate(points):
        prefix.append(point)
        structural_decision = None
        latest_window = None
        if len(prefix) >= encoder.window_points:
            latest_windows = encoder.encode(
                prefix,
                metric_id=series.metric_id,
                return_only_latest=True,
                align_latest_to_stride=False,
            )
            latest_window = latest_windows[-1] if latest_windows else None
            if latest_window is not None:
                structural_decision = structural_policy.evaluate(
                    latest_window, current_price=point.value
                )

        if structural_decision is None:
            structural_decision = _warmup_decision(
                "spotfsm", point, len(prefix), encoder.window_points
            )

        reactive_decision = reactive_policy.evaluate(point)
        operator_record = operator.execute(structural_decision)
        event_here = next(
            (event for event in events if event.event_index == idx),
            None,
        )

        rows.append(
            {
                "point_index": idx,
                "timestamp_ms": point.timestamp_ms,
                "price": point.value,
                "spotfsm_action": structural_decision.action.value,
                "spotfsm_score": structural_decision.score,
                "spotfsm_hazard": structural_decision.hazard,
                "spotfsm_rupture": structural_decision.rupture,
                "spotfsm_coherence": structural_decision.coherence,
                "spotfsm_entropy": structural_decision.entropy,
                "spotfsm_signature": structural_decision.signature,
                "spotfsm_reasons": "|".join(structural_decision.reasons),
                "reactive_action": reactive_decision.action.value,
                "reactive_score": reactive_decision.score,
                "reactive_reasons": "|".join(reactive_decision.reasons),
                "operator_state": operator_record.state,
                "event_here": bool(event_here),
                "event_type": event_here.event_type if event_here else "",
            }
        )

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    decisions_path = output_root / f"{series.metric_id}_decisions.csv"
    summary_path = output_root / f"{series.metric_id}_summary.json"

    _write_rows_csv(decisions_path, rows)
    summary = {
        "dataset": series.to_json(),
        "events": [event.to_json() for event in events],
        "spotfsm": _summarize_policy(rows, events, policy_key="spotfsm", replay_config=replay_config),
        "reactive": _summarize_policy(rows, events, policy_key="reactive", replay_config=replay_config),
        "artifacts": {
            "decisions_csv": str(decisions_path),
            "summary_json": str(summary_path),
            "operator_log": str(operator.action_log_path),
        },
        "notes": [
            "Replay events are inferred from future spot-price spikes in the public archive.",
            "They are not actual AWS interruption notices.",
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay real AWS Spot price history through SpotFSM migration policy."
    )
    parser.add_argument("--config", help="Path to replay YAML config.")
    parser.add_argument(
        "--dataset-source",
        choices=("zenodo_tsv_zst", "aws_cli_json"),
        help="Override the dataset source declared in the config.",
    )
    parser.add_argument("--dataset-path", help="Path to a local dataset file.")
    parser.add_argument(
        "--download-zenodo-month",
        help="Download a real monthly .tsv.zst archive such as 2024-01 or 2025-07.",
    )
    parser.add_argument(
        "--zenodo-record-id",
        type=int,
        default=DEFAULT_ZENODO_RECORD_ID,
        help="Zenodo record ID that stores public monthly .tsv.zst files.",
    )
    parser.add_argument("--availability-zone-id")
    parser.add_argument("--instance-type")
    parser.add_argument("--product-description", default="Linux/UNIX")
    parser.add_argument(
        "--list-top-series",
        action="store_true",
        help="Scan a Zenodo archive and print high-variance candidate series.",
    )
    parser.add_argument("--top-series-limit", type=int, default=20)
    parser.add_argument("--output-dir", help="Override replay.output_dir from config.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    config_payload = _load_yaml(args.config) if args.config else {}
    dataset_payload = dict(config_payload.get("dataset", {}))
    encoder_settings = EncoderSettings.from_mapping(config_payload.get("encoder"))
    policy_config = PolicyConfig.from_mapping(config_payload.get("policy"))
    baseline_config = ReactiveBaselineConfig.from_mapping(config_payload.get("baseline"))
    replay_config = ReplayConfig.from_mapping(config_payload.get("replay"))
    operator_config = OperatorConfig.from_mapping(config_payload.get("operator"))

    dataset_source = args.dataset_source or dataset_payload.get("source", "zenodo_tsv_zst")
    dataset_path = args.dataset_path or dataset_payload.get("path")

    if args.download_zenodo_month:
        filename = args.download_zenodo_month
        if not filename.endswith(".tsv.zst"):
            filename = f"{filename}.tsv.zst"
        dataset_path = str(
            download_zenodo_file(
                record_id=args.zenodo_record_id,
                filename=filename,
            )
        )

    if not dataset_path:
        raise SystemExit("dataset path is required; pass --dataset-path or --download-zenodo-month")

    if args.list_top_series:
        candidates = scan_zenodo_top_series(
            dataset_path,
            product_description=args.product_description,
            top_n=args.top_series_limit,
        )
        for candidate in candidates:
            print(json.dumps(candidate.to_json(), sort_keys=True))
        return 0

    selector = SpotPriceSeriesSelector.from_mapping(
        {
            "availability_zone_id": args.availability_zone_id
            or dataset_payload.get("availability_zone_id"),
            "instance_type": args.instance_type or dataset_payload.get("instance_type"),
            "product_description": args.product_description
            or dataset_payload.get("product_description", "Linux/UNIX"),
        }
    )

    if dataset_source == "zenodo_tsv_zst":
        series = load_zenodo_spot_series(dataset_path, selector)
    elif dataset_source == "aws_cli_json":
        series = load_aws_cli_spot_series(dataset_path, selector)
    else:
        raise SystemExit(f"unsupported dataset source: {dataset_source}")

    encoder = TelemetryManifoldEncoder(
        window_points=encoder_settings.window_points,
        stride_points=encoder_settings.stride_points,
        baseline_period=encoder_settings.baseline_period,
    )
    structural_policy = MigrationPolicy(policy_config)
    reactive_policy = ReactivePricePolicy(baseline_config)

    if operator_config.redis_url:
        state_store = RedisStateStore(
            operator_config.redis_url,
            key_prefix=operator_config.redis_key_prefix,
        )
    else:
        state_store = InMemoryStateStore()
    operator = SimulatedOperator(operator_config, state_store=state_store)

    summary = run_replay(
        series,
        encoder=encoder,
        structural_policy=structural_policy,
        reactive_policy=reactive_policy,
        replay_config=replay_config,
        operator=operator,
        output_dir=args.output_dir or replay_config.output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _summarize_policy(
    rows: Sequence[Dict[str, object]],
    events: Sequence[ReplayEvent],
    *,
    policy_key: str,
    replay_config: ReplayConfig,
) -> Dict[str, object]:
    action_field = f"{policy_key}_action"
    migration_indices = [
        int(row["point_index"])
        for row in rows
        if row[action_field] == DecisionAction.MIGRATE.value
    ]
    assigned_migrations = set()
    avoided = 0
    lead_times_s: List[float] = []

    for event in events:
        candidates = [
            idx
            for idx in migration_indices
            if event.event_index - replay_config.event_attribution_lookback_points
            <= idx
            < event.event_index
        ]
        if not candidates:
            continue
        chosen = min(candidates)
        assigned_migrations.add(chosen)
        avoided += 1
        lead_times_s.append(
            (event.event_timestamp_ms - int(rows[chosen]["timestamp_ms"])) / 1000.0
        )

    false_positive_count = sum(
        1 for idx in migration_indices if idx not in assigned_migrations
    )
    return {
        "migration_count": len(migration_indices),
        "event_count": len(events),
        "avoided_event_count": avoided,
        "interruption_avoidance_rate": avoided / len(events) if events else 0.0,
        "avg_lead_time_seconds": statistics.fmean(lead_times_s) if lead_times_s else 0.0,
        "median_lead_time_seconds": statistics.median(lead_times_s) if lead_times_s else 0.0,
        "false_positive_count": false_positive_count,
        "precision": avoided / len(migration_indices) if migration_indices else 0.0,
    }


def _write_rows_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _warmup_decision(
    policy_name: str,
    point: TelemetryPoint,
    prefix_count: int,
    required_points: int,
) -> MigrationDecision:
    return MigrationDecision(
        policy_name=policy_name,
        action=DecisionAction.STABLE,
        timestamp_ms=point.timestamp_ms,
        score=0.0,
        reasons=(f"warmup_{prefix_count}_of_{required_points}",),
        current_price=point.value,
    )


def _load_yaml(path: str) -> Dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


if __name__ == "__main__":
    raise SystemExit(main())
