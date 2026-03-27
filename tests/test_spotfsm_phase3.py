from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.research.regime_manifold.types import CanonicalFeatures, EncodedWindow, TelemetryPoint
from scripts.spotfsm.datasets import load_aws_cli_spot_series, load_zenodo_spot_series
from scripts.spotfsm.policy import MigrationPolicy, ReactivePricePolicy
from scripts.spotfsm.replay import detect_price_spike_events
from scripts.spotfsm.types import PolicyConfig, ReactiveBaselineConfig, ReplayConfig, SpotPriceSeriesSelector


def _window(
    *,
    timestamp_ms: int,
    hazard: float,
    rupture: float,
    coherence: float,
    entropy: float,
    signature: str = "c0.440_s0.000_e0.950",
) -> EncodedWindow:
    return EncodedWindow(
        metric_id="spot",
        start_ms=timestamp_ms - 1_000,
        end_ms=timestamp_ms,
        bits=b"",
        bit_length=0,
        signature=signature,
        metrics={
            "hazard": hazard,
            "rupture": rupture,
            "coherence": coherence,
            "entropy": entropy,
            "stability": 0.0,
        },
        canonical=CanonicalFeatures(0.0, 0.0, 0.0, 0.0, 0.0, "neutral", 0.5),
        codec_meta={},
    )


def test_migration_policy_resists_stationary_high_hazard():
    policy = MigrationPolicy(
        PolicyConfig(
            hazard_floor=0.84,
            rupture_floor=0.42,
            min_hazard_delta=0.015,
            min_rupture_delta=0.035,
            score_migrate_threshold=1.1,
            min_consecutive_signals=2,
        )
    )
    actions = []
    for idx in range(10):
        decision = policy.evaluate(
            _window(
                timestamp_ms=idx * 1_000,
                hazard=0.85,
                rupture=0.43,
                coherence=0.46,
                entropy=0.90,
            ),
            current_price=1.0,
        )
        actions.append(decision.action.value)

    assert "MIGRATE" not in actions


def test_migration_policy_triggers_on_structural_shift():
    policy = MigrationPolicy(
        PolicyConfig(
            hazard_floor=0.84,
            rupture_floor=0.42,
            min_hazard_delta=0.01,
            min_rupture_delta=0.02,
            score_migrate_threshold=1.0,
            min_consecutive_signals=2,
        )
    )

    for idx in range(4):
        policy.evaluate(
            _window(
                timestamp_ms=idx * 1_000,
                hazard=0.84,
                rupture=0.40,
                coherence=0.48,
                entropy=0.88,
                signature="c0.480_s0.000_e0.880",
            ),
            current_price=1.0,
        )

    decision = None
    for idx in range(4, 7):
        decision = policy.evaluate(
            _window(
                timestamp_ms=idx * 1_000,
                hazard=0.93,
                rupture=0.56,
                coherence=0.42,
                entropy=0.97,
            ),
            current_price=1.2,
        )
    assert decision is not None
    assert decision.action.value == "MIGRATE"


def test_reactive_policy_waits_for_price_jump():
    policy = ReactivePricePolicy(
        ReactiveBaselineConfig(
            rolling_window_points=4,
            price_zscore_threshold=1.0,
            price_multiplier_threshold=1.05,
            velocity_std_multiplier=0.8,
            cooldown_points=1,
        )
    )
    points = [
        TelemetryPoint(timestamp_ms=1_000 * idx, value=value)
        for idx, value in enumerate([1.0, 1.01, 1.02, 1.03, 1.12])
    ]
    actions = [policy.evaluate(point).action.value for point in points]
    assert actions[-1] == "MIGRATE"
    assert actions[:-1].count("MIGRATE") == 0


def test_detect_price_spike_events_dedupes_overlap():
    points = [
        TelemetryPoint(timestamp_ms=1_000 * idx, value=value)
        for idx, value in enumerate([1.0, 1.01, 1.15, 1.16, 1.17, 1.18])
    ]
    events = detect_price_spike_events(
        points,
        ReplayConfig(
            event_lookahead_points=3,
            event_spike_multiplier=1.12,
            event_spike_absolute=0.05,
            event_attribution_lookback_points=3,
            output_dir="output/replay",
        ),
    )
    assert len(events) == 1
    assert events[0].event_index == 2


def test_load_aws_cli_spot_series(tmp_path: Path):
    path = tmp_path / "spot.json"
    path.write_text(
        json.dumps(
            {
                "SpotPriceHistory": [
                    {
                        "AvailabilityZoneId": "use1-az4",
                        "InstanceType": "m6idn.12xlarge",
                        "ProductDescription": "Linux/UNIX",
                        "SpotPrice": "1.45",
                        "Timestamp": "2024-01-01T00:00:00+00:00",
                    },
                    {
                        "AvailabilityZoneId": "use1-az4",
                        "InstanceType": "m6idn.12xlarge",
                        "ProductDescription": "Linux/UNIX",
                        "SpotPrice": "1.46",
                        "Timestamp": "2024-01-01T01:00:00+00:00",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    series = load_aws_cli_spot_series(
        str(path),
        SpotPriceSeriesSelector(
            availability_zone_id="use1-az4",
            instance_type="m6idn.12xlarge",
            product_description="Linux/UNIX",
        ),
    )
    assert len(series.points) == 2
    assert series.points[0].value == 1.45


def test_load_zenodo_spot_series_from_real_tsv_zst(tmp_path: Path):
    raw_path = tmp_path / "sample.tsv"
    raw_path.write_text(
        "\n".join(
            [
                "aps1-az3\tinf2.8xlarge\tLinux/UNIX\t0.310800\t2024-01-01T00:00:00+00:00",
                "aps1-az3\tinf2.8xlarge\tLinux/UNIX\t0.311400\t2024-01-01T04:47:22+00:00",
                "aps1-az1\tm5.large\tLinux/UNIX\t0.020000\t2024-01-01T00:00:00+00:00",
            ]
        ),
        encoding="utf-8",
    )
    compressed_path = tmp_path / "sample.tsv.zst"
    subprocess.run(
        ["zstd", "-q", "-f", str(raw_path), "-o", str(compressed_path)],
        check=True,
    )

    series = load_zenodo_spot_series(
        str(compressed_path),
        SpotPriceSeriesSelector(
            availability_zone_id="aps1-az3",
            instance_type="inf2.8xlarge",
            product_description="Linux/UNIX",
        ),
    )
    assert len(series.points) == 2
    assert series.points[1].value == 0.3114
