"""Utilities for loading HighD dataset recordings without external dependencies."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

LOGGER = logging.getLogger(__name__)


@dataclass
class RecordingMeta:
    recording_id: str
    frame_rate: float
    duration: float
    num_vehicles: int
    num_cars: int
    num_trucks: int
    speed_limit_m_s: float
    upper_lane_markings: List[float]
    lower_lane_markings: List[float]
    timestamp: Optional[datetime] = None

    @property
    def duration_hours(self) -> float:
        return self.duration / 3600.0

    @property
    def speed_limit_kmh(self) -> float:
        return self.speed_limit_m_s * 3.6


@dataclass
class RecordingData:
    path: Path
    meta: RecordingMeta
    tracks_meta: List[Dict[str, object]]
    tracks: List[Dict[str, object]]


HIGH_D_META_FILE = "recordingMeta.csv"
HIGH_D_TRACKS_META_FILE = "tracksMeta.csv"
HIGH_D_TRACKS_FILE = "tracks.csv"


def _read_csv_dicts(path: Path) -> List[Dict[str, object]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def _parse_lane_markings(value: str) -> List[float]:
    if isinstance(value, list):
        return [float(v) for v in value]
    value = str(value).strip()
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            return [float(v) for v in parsed]
        except json.JSONDecodeError:
            pass
    parts = [p for p in value.replace(";", ",").split(",") if p]
    return [float(p) for p in parts]


def _parse_timestamp(row: Dict[str, object]) -> Optional[datetime]:
    for key in ("timeStamp", "timestamp", "date"):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            continue
    return None


def load_recording(path: Path) -> RecordingData:
    path = Path(path)
    meta_path = path / HIGH_D_META_FILE
    tracks_meta_path = path / HIGH_D_TRACKS_META_FILE
    tracks_path = path / HIGH_D_TRACKS_FILE
    if not meta_path.exists():
        raise FileNotFoundError(meta_path)
    if not tracks_meta_path.exists():
        raise FileNotFoundError(tracks_meta_path)
    if not tracks_path.exists():
        raise FileNotFoundError(tracks_path)

    meta_records = _read_csv_dicts(meta_path)
    if not meta_records:
        raise ValueError(f"Empty metadata in {meta_path}")
    row = meta_records[0]
    recording_meta = RecordingMeta(
        recording_id=str(row.get("id", path.name)),
        frame_rate=float(row.get("frameRate", row.get("frame_rate", 25.0))),
        duration=float(row.get("duration", row.get("durationSec", 0.0))),
        num_vehicles=int(float(row.get("numVehicles", row.get("numvehicles", 0)))),
        num_cars=int(float(row.get("numCars", row.get("numcars", 0)))),
        num_trucks=int(float(row.get("numTrucks", row.get("numtrucks", 0)))),
        speed_limit_m_s=float(row.get("speedLimit", row.get("speedlimit", 0.0))),
        upper_lane_markings=_parse_lane_markings(row.get("upperLaneMarkings", "[]")),
        lower_lane_markings=_parse_lane_markings(row.get("lowerLaneMarkings", "[]")),
        timestamp=_parse_timestamp(row),
    )

    tracks_meta = _read_csv_dicts(tracks_meta_path)
    tracks = _read_csv_dicts(tracks_path)

    if not tracks_meta:
        raise ValueError(f"tracksMeta.csv empty in {tracks_meta_path}")
    if not tracks:
        raise ValueError(f"tracks.csv empty in {tracks_path}")

    required_meta_cols = {"id", "drivingDirection"}
    if not required_meta_cols.issubset(tracks_meta[0].keys()):
        missing = required_meta_cols - set(tracks_meta[0].keys())
        raise ValueError(f"tracksMeta missing columns: {missing}")
    if "frame" not in tracks[0]:
        raise ValueError("tracks.csv must include a 'frame' column")

    return RecordingData(path=path, meta=recording_meta, tracks_meta=tracks_meta, tracks=tracks)


def iter_recordings(root: Path) -> Iterable[Path]:
    root = Path(root)
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        if (candidate / HIGH_D_META_FILE).exists():
            yield candidate
        else:
            LOGGER.debug("Skipping %s: missing %s", candidate, HIGH_D_META_FILE)


def _percentile(values: List[float], perc: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * perc / 100.0
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    if f == c:
        return values_sorted[f]
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return d0 + d1


def robust_segment_length(tracks: List[Dict[str, object]]) -> float:
    if not tracks:
        return 0.0
    xs: List[float] = []
    for row in tracks:
        value = row.get("x")
        if value in (None, ""):
            continue
        try:
            xs.append(float(value))
        except ValueError:
            continue
    if not xs:
        LOGGER.warning("tracks.csv missing usable x coordinate; cannot estimate segment length reliably")
        return 0.0
    low = _percentile(xs, 5)
    high = _percentile(xs, 95)
    return float(max(high - low, 0.0))
