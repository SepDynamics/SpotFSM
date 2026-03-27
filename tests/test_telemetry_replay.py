from __future__ import annotations

from dataclasses import dataclass

from scripts.telemetry_replay import attribute_action_indices_to_events


@dataclass(frozen=True)
class _Event:
    event_index: int
    event_timestamp_ms: int


def test_attribute_action_indices_to_events_matches_lead_times():
    attribution = attribute_action_indices_to_events(
        [2, 5, 9],
        {2: 2_000, 5: 5_000, 9: 9_000},
        [
            _Event(event_index=6, event_timestamp_ms=6_500),
            _Event(event_index=11, event_timestamp_ms=11_000),
        ],
        lookback_points=3,
    )

    assert attribution.assigned_action_indices == frozenset({5, 9})
    assert attribution.matched_event_count == 2
    assert attribution.lead_times_s == (1.5, 2.0)


def test_attribute_action_indices_to_events_ignores_unmatched_events():
    attribution = attribute_action_indices_to_events(
        [4],
        {4: 4_000},
        [_Event(event_index=10, event_timestamp_ms=10_000)],
        lookback_points=2,
    )

    assert attribution.assigned_action_indices == frozenset()
    assert attribution.matched_event_count == 0
    assert attribution.lead_times_s == ()
