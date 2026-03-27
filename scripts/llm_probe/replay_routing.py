"""Offline replay harness for LLM probe data to validate routing policies."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from scripts.research.regime_manifold.encoder import TelemetryManifoldEncoder, TelemetryPoint
from scripts.llm_probe.policy import LLMRoutingPolicy, LLMRoutingPolicyConfig, ReactiveRoutingPolicy, RoutingAction, RoutingDecision
from scripts.llm_probe.types import ProbeResult, LLMProbeConfig


def run_llm_replay(
    results: Sequence[ProbeResult],
    *,
    metric_id: str,
    encoder: TelemetryManifoldEncoder,
    structural_policy: LLMRoutingPolicy,
    reactive_policy: ReactiveRoutingPolicy,
    output_dir: Path,
) -> Dict[str, object]:
    points = [TelemetryPoint(timestamp_ms=r.timestamp_ms, value=r.total_latency_ms) for r in results]
    
    # Identify Ground Truth Events (Errors or Timeouts)
    events: List[int] = [] # Indices of points that are ground-truth failures
    for idx, r in enumerate(results):
        if r.error or r.http_status >= 400 or r.total_latency_ms >= reactive_policy.timeout_ms:
            events.append(idx)

    rows: List[Dict[str, object]] = []
    prefix: List[TelemetryPoint] = []
    
    structural_actions: List[int] = []
    reactive_actions: List[int] = []

    for idx, point in enumerate(points):
        prefix.append(point)
        result = results[idx]
        
        structural_decision: Optional[RoutingDecision] = None
        if len(prefix) >= encoder.window_points:
            windows = encoder.encode(
                prefix,
                metric_id=metric_id,
                return_only_latest=True,
                align_latest_to_stride=False,
            )
            latest_window = windows[-1] if windows else None
            if latest_window:
                structural_decision = structural_policy.evaluate(
                    latest_window, current_value=point.value
                )
        
        reactive_decision = reactive_policy.evaluate(point, is_error=result.error or result.http_status >= 400)
        
        if structural_decision and structural_decision.action == RoutingAction.ROUTE:
            structural_actions.append(idx)
        if reactive_decision.action == RoutingAction.ROUTE:
            reactive_actions.append(idx)

        rows.append({
            "index": idx,
            "timestamp_ms": point.timestamp_ms,
            "latency_ms": point.value,
            "error": result.error,
            "status": result.http_status,
            "struct_action": structural_decision.action.value if structural_decision else "warmup",
            "struct_hazard": structural_decision.hazard if structural_decision else 0.0,
            "react_action": reactive_decision.action.value,
            "is_event": idx in events,
        })

    # Lead Time Analysis
    struct_metrics = _analyze_lead_time(structural_actions, events, points)
    react_metrics = _analyze_lead_time(reactive_actions, events, points)

    summary = {
        "metric_id": metric_id,
        "total_points": len(points),
        "total_events": len(events),
        "structural": struct_metrics,
        "reactive": react_metrics,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{metric_id}_replay.json").write_text(json.dumps(summary, indent=2))
    
    return summary


def _analyze_lead_time(
    action_indices: List[int],
    event_indices: List[int],
    points: List[TelemetryPoint],
) -> Dict[str, object]:
    if not event_indices:
        return {"action_count": len(action_indices), "matched_events": 0, "avg_lead_time_s": 0.0}

    matched_events = 0
    lead_times: List[float] = []
    
    # Simple attribution: for each action, find the first event after it within a lookahead window (e.g. 10 mins)
    LOOKAHEAD_MS = 600_000 # 10 minutes
    
    used_events = set()
    for a_idx in action_indices:
        a_ts = points[a_idx].timestamp_ms
        for e_idx in event_indices:
            if e_idx <= a_idx or e_idx in used_events:
                continue
            e_ts = points[e_idx].timestamp_ms
            if e_ts - a_ts <= LOOKAHEAD_MS:
                matched_events += 1
                lead_times.append((e_ts - a_ts) / 1000.0)
                used_events.add(e_idx)
                break
                
    return {
        "action_count": len(action_indices),
        "matched_events": matched_events,
        "recall": matched_events / len(event_indices) if event_indices else 0.0,
        "precision": matched_events / len(action_indices) if action_indices else 0.0,
        "avg_lead_time_s": statistics.mean(lead_times) if lead_times else 0.0,
        "max_lead_time_s": max(lead_times) if lead_times else 0.0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/probes/llm_probe.jsonl")
    parser.add_argument("--output-dir", default="output/llm_routing_replay")
    parser.add_argument("--window-points", type=int, default=16) # Smaller window for probe data frequency
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input {input_path} not found")
        return

    results_by_model: Dict[str, List[ProbeResult]] = {}
    with input_path.open("r") as f:
        for line in f:
            if not line.strip(): continue
            res = ProbeResult.from_mapping(json.loads(line))
            key = f"{res.provider}.{res.model}"
            if key not in results_by_model:
                results_by_model[key] = []
            results_by_model[key].append(res)

    encoder = TelemetryManifoldEncoder(window_points=args.window_points, stride_points=1, baseline_period=100)
    struct_policy = LLMRoutingPolicy(LLMRoutingPolicyConfig(
        hazard_floor=0.1, 
        rupture_floor=0.1,
        min_consecutive_signals=1,
        score_route_threshold=0.8
    ))
    react_policy = ReactiveRoutingPolicy(timeout_ms=3000.0)

    for model_key, results in results_by_model.items():
        print(f"Replaying {model_key} ({len(results)} points)...")
        summary = run_llm_replay(
            results,
            metric_id=model_key,
            encoder=encoder,
            structural_policy=struct_policy,
            reactive_policy=react_policy,
            output_dir=Path(args.output_dir)
        )
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
