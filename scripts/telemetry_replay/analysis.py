"""Generic analysis helpers for replaying actions against labeled events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Mapping, Protocol, Sequence, Tuple


class IndexedTelemetryEvent(Protocol):
    """Minimal event surface required for action attribution."""

    event_index: int
    event_timestamp_ms: int


@dataclass(frozen=True)
class EventAttribution:
    """Summary of how replay actions were matched to labeled events."""

    assigned_action_indices: FrozenSet[int]
    matched_event_count: int
    lead_times_s: Tuple[float, ...]


def attribute_action_indices_to_events(
    action_indices: Sequence[int],
    action_timestamps_ms: Mapping[int, int],
    events: Sequence[IndexedTelemetryEvent],
    *,
    lookback_points: int,
) -> EventAttribution:
    assigned_action_indices = set()
    lead_times_s = []
    matched_event_count = 0

    for event in events:
        candidates = [
            idx
            for idx in action_indices
            if event.event_index - lookback_points <= idx < event.event_index
        ]
        if not candidates:
            continue

        chosen = min(candidates)
        assigned_action_indices.add(chosen)
        matched_event_count += 1
        lead_times_s.append(
            (event.event_timestamp_ms - int(action_timestamps_ms[chosen])) / 1000.0
        )

    return EventAttribution(
        assigned_action_indices=frozenset(assigned_action_indices),
        matched_event_count=matched_event_count,
        lead_times_s=tuple(lead_times_s),
    )
