"""Real-data loaders for AWS Spot replay work."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

import requests

from scripts.research.regime_manifold.types import TelemetryPoint

from .types import (
    ReplayEvent,
    SpotPriceRecord,
    SpotPriceSeries,
    SpotPriceSeriesSelector,
    TopSeriesCandidate,
)

DEFAULT_ZENODO_RECORD_ID = 16671865


def download_zenodo_file(
    *,
    record_id: int = DEFAULT_ZENODO_RECORD_ID,
    filename: str,
    output_dir: str = "data/raw",
    overwrite: bool = False,
) -> Path:
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        return output_path

    url = f"https://zenodo.org/api/records/{record_id}/files/{filename}/content"
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with output_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return output_path


def load_zenodo_spot_series(
    path: str,
    selector: SpotPriceSeriesSelector,
    *,
    metric_id: Optional[str] = None,
    limit_points: Optional[int] = None,
) -> SpotPriceSeries:
    points: List[TelemetryPoint] = []
    for row in _iter_zenodo_rows(path):
        if (
            row.availability_zone_id == selector.availability_zone_id
            and row.instance_type == selector.instance_type
            and row.product_description == selector.product_description
        ):
            points.append(
                TelemetryPoint(timestamp_ms=row.timestamp_ms, value=row.price)
            )
            if limit_points is not None and len(points) >= limit_points:
                break

    if not points:
        raise ValueError(
            "no rows matched selector "
            f"{selector.availability_zone_id}/{selector.instance_type}/"
            f"{selector.product_description}"
        )

    return SpotPriceSeries(
        metric_id=metric_id or selector.metric_id(),
        selector=selector,
        source="zenodo_tsv_zst",
        source_path=path,
        points=tuple(points),
    )


def scan_zenodo_top_series(
    path: str,
    *,
    product_description: str = "Linux/UNIX",
    min_points: int = 64,
    top_n: int = 20,
) -> List[TopSeriesCandidate]:
    stats: Dict[tuple[str, str, str], List[float]] = {}
    for row in _iter_zenodo_rows(path):
        if row.product_description != product_description:
            continue
        key = (
            row.availability_zone_id,
            row.instance_type,
            row.product_description,
        )
        record = stats.get(key)
        if record is None:
            stats[key] = [1.0, row.price, row.price]
        else:
            record[0] += 1.0
            record[1] = min(record[1], row.price)
            record[2] = max(record[2], row.price)

    candidates: List[TopSeriesCandidate] = []
    for (availability_zone_id, instance_type, product), values in stats.items():
        sample_count = int(values[0])
        min_price = float(values[1])
        max_price = float(values[2])
        if sample_count < min_points or min_price <= 0:
            continue
        candidates.append(
            TopSeriesCandidate(
                selector=SpotPriceSeriesSelector(
                    availability_zone_id=availability_zone_id,
                    instance_type=instance_type,
                    product_description=product,
                ),
                sample_count=sample_count,
                min_price=min_price,
                max_price=max_price,
                relative_range=(max_price - min_price) / min_price,
            )
        )

    candidates.sort(
        key=lambda row: (row.relative_range, row.sample_count, row.max_price),
        reverse=True,
    )
    return candidates[:top_n]


def load_aws_cli_spot_series(
    path: str,
    selector: SpotPriceSeriesSelector,
    *,
    metric_id: Optional[str] = None,
    limit_points: Optional[int] = None,
) -> SpotPriceSeries:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    history = payload.get("SpotPriceHistory") or payload.get("spotPriceHistory") or []
    points: List[TelemetryPoint] = []
    for row in history:
        availability_zone_id = row.get("AvailabilityZoneId")
        if not availability_zone_id and row.get("AvailabilityZone"):
            availability_zone_id = str(row["AvailabilityZone"])

        if (
            availability_zone_id != selector.availability_zone_id
            or str(row.get("InstanceType")) != selector.instance_type
            or str(row.get("ProductDescription")) != selector.product_description
        ):
            continue

        timestamp = _parse_timestamp_ms(str(row["Timestamp"]))
        price = float(row["SpotPrice"])
        points.append(TelemetryPoint(timestamp_ms=timestamp, value=price))
        if limit_points is not None and len(points) >= limit_points:
            break

    if not points:
        raise ValueError(
            "no AWS CLI price history rows matched selector "
            f"{selector.availability_zone_id}/{selector.instance_type}/"
            f"{selector.product_description}"
        )

    points.sort(key=lambda point: point.timestamp_ms)
    return SpotPriceSeries(
        metric_id=metric_id or selector.metric_id(),
        selector=selector,
        source="aws_cli_json",
        source_path=path,
        points=tuple(points),
    )


def _iter_zenodo_rows(path: str) -> Iterator[SpotPriceRecord]:
    zstd_path = shutil.which("zstd")
    if zstd_path is None:
        raise RuntimeError("zstd is required to read .tsv.zst spot archives")

    proc = subprocess.Popen(
        [zstd_path, "-dc", "--long=31", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None

    try:
        for line in proc.stdout:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 5:
                continue
            yield SpotPriceRecord(
                availability_zone_id=parts[0],
                instance_type=parts[1],
                product_description=parts[2],
                price=float(parts[3]),
                timestamp_ms=_parse_timestamp_ms(parts[4]),
            )
    finally:
        proc.stdout.close()
        stderr = ""
        if proc.stderr is not None:
            stderr = proc.stderr.read()
            proc.stderr.close()
        return_code = proc.wait()
        if return_code not in {0, -15}:
            raise RuntimeError(f"zstd failed while reading {path}: {stderr.strip()}")


def _parse_timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def load_interruption_labels_csv(path: str) -> List[ReplayEvent]:
    """Loads actual AWS interruption notices from a CSV file.
    
    Expected columns: timestamp_ms, price, event_type
    The anchor_index and event_index will be mapped by replay.py later.
    """
    events = []
    with Path(path).open("r", encoding="utf-8") as handle:
        import csv
        reader = csv.DictReader(handle)
        for row in reader:
            events.append(
                ReplayEvent(
                    anchor_index=-1, # Mapped later
                    event_index=-1, # Mapped later
                    anchor_timestamp_ms=int(row["timestamp_ms"]),
                    event_timestamp_ms=int(row["timestamp_ms"]),
                    anchor_price=float(row.get("price", 0.0)),
                    event_price=float(row.get("price", 0.0)),
                    event_type=row.get("event_type", "aws_interruption"),
                )
            )
    events.sort(key=lambda e: e.event_timestamp_ms)
    return events
