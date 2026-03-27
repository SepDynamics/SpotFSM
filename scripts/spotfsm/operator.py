"""Simulated operator and simple state stores for replay work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Protocol

import redis

from .types import DecisionAction, MigrationDecision, OperatorActionRecord, OperatorConfig


class StateStore(Protocol):
    def get(self, workload_id: str) -> Optional[Dict[str, object]]:
        ...

    def set(self, workload_id: str, payload: Dict[str, object]) -> None:
        ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self.data: Dict[str, Dict[str, object]] = {}

    def get(self, workload_id: str) -> Optional[Dict[str, object]]:
        return self.data.get(workload_id)

    def set(self, workload_id: str, payload: Dict[str, object]) -> None:
        self.data[workload_id] = dict(payload)


class RedisStateStore:
    def __init__(self, redis_url: str, *, key_prefix: str = "spotfsm:replay") -> None:
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix

    def get(self, workload_id: str) -> Optional[Dict[str, object]]:
        raw = self.client.get(self._key(workload_id))
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, workload_id: str, payload: Dict[str, object]) -> None:
        self.client.set(self._key(workload_id), json.dumps(payload, sort_keys=True))

    def _key(self, workload_id: str) -> str:
        return f"{self.key_prefix}:{workload_id}"


class SimulatedOperator:
    """Logs the action that would have been executed against a workload."""

    def __init__(
        self,
        config: Optional[OperatorConfig] = None,
        *,
        state_store: Optional[StateStore] = None,
    ) -> None:
        self.config = config or OperatorConfig()
        self.state_store = state_store or InMemoryStateStore()
        self.action_log_path = Path(self.config.action_log_path)
        self.action_log_path.parent.mkdir(parents=True, exist_ok=True)

    def execute(self, decision: MigrationDecision) -> OperatorActionRecord:
        if decision.action == DecisionAction.MIGRATE:
            state = "MIGRATING"
            detail = "drain_node -> request_new_instance"
            status = "simulated_success"
        elif decision.action == DecisionAction.OBSERVE:
            state = "HAZARD_DETECTED"
            detail = "monitoring hazard and holding workload placement"
            status = "tracked"
        else:
            state = "STABLE"
            detail = "no action"
            status = "idle"

        payload = {
            "state": state,
            "timestamp_ms": decision.timestamp_ms,
            "last_action": decision.action.value,
            "signature": decision.signature,
            "hazard": decision.hazard,
        }
        self.state_store.set(self.config.workload_id, payload)

        record = OperatorActionRecord(
            workload_id=self.config.workload_id,
            timestamp_ms=decision.timestamp_ms,
            action=decision.action,
            state=state,
            status=status,
            detail=detail,
            signature=decision.signature,
            hazard=decision.hazard,
        )
        with self.action_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_json(), sort_keys=True))
            handle.write("\n")
        return record
