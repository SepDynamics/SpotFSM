"""CLI entrypoint for polling infrastructure telemetry into manifold windows."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Iterable, Optional

import yaml

from .service import build_bridge_service
from .types import BridgeConfig, BridgeObservation


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Poll Prometheus/CloudWatch telemetry and emit manifold windows."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the bridge YAML config.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll each configured metric once and exit.",
    )
    parser.add_argument(
        "--output-path",
        help="Optional JSONL output path. Overrides output_path in the config.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout instead of compact JSONL.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = _load_config(Path(args.config))
    service = build_bridge_service(config)
    output_path = Path(args.output_path or config.output_path) if (args.output_path or config.output_path) else None

    while True:
        observations = service.poll_once()
        for observation in observations:
            _emit_observation(observation, pretty=args.pretty, output_path=output_path)

        if args.once:
            return 0
        time.sleep(config.poll_interval_seconds)


def _load_config(path: Path) -> BridgeConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return BridgeConfig.from_mapping(payload)


def _emit_observation(
    observation: BridgeObservation,
    *,
    pretty: bool,
    output_path: Optional[Path],
) -> None:
    payload = observation.to_json()
    line = json.dumps(payload, indent=2 if pretty else None, sort_keys=pretty)
    print(line, flush=True)

    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
