"""Traffic flow analytics for HighD recordings using the Python standard library."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from ..io.highd import RecordingData


VEHICLE_CLASS_ALIASES = {
    "car": {"car", "Car", "CAR", "0", 0},
    "truck": {"truck", "Truck", "TRUCK", "1", 1},
}


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _classify_vehicle(value: object) -> str:
    for label, aliases in VEHICLE_CLASS_ALIASES.items():
        if value in aliases:
            return label
        if isinstance(value, str) and value.lower() == label:
            return label
    return "unknown"


def _directional_timeseries(subset: List[Dict[str, object]], frame_rate: float, duration: float) -> List[Dict[str, float]]:
    if not subset:
        return []
    bin_counts: Dict[int, int] = defaultdict(int)
    for row in subset:
        initial = _to_float(row.get("initialFrame"))
        bin_index = int(initial / frame_rate // 60)
        bin_counts[bin_index] += 1
    bins = sorted(bin_counts.keys())
    series: List[Dict[str, float]] = []
    for idx in bins:
        start = idx * 60.0
        end = min(start + 60.0, duration)
        series.append({
            "bin_start_sec": start,
            "bin_end_sec": end,
            "vehicles": int(bin_counts[idx]),
        })
    return series


def summarize_flow(recording: RecordingData) -> Dict[str, object]:
    meta = recording.meta
    duration = meta.duration
    results: Dict[str, object] = {
        "recording_id": meta.recording_id,
        "duration_sec": duration,
        "directions": {},
    }

    vehicles_by_direction: Dict[int, List[Dict[str, object]]] = defaultdict(list)
    for row in recording.tracks_meta:
        try:
            direction = int(row.get("drivingDirection", 0))
        except (TypeError, ValueError):
            continue
        row = dict(row)
        row["vehicle_class"] = _classify_vehicle(row.get("class"))
        vehicles_by_direction[direction].append(row)

    for direction, subset in sorted(vehicles_by_direction.items()):
        unique_ids = set()
        class_counts: Dict[str, int] = defaultdict(int)
        for row in subset:
            vehicle_id = row.get("id")
            if vehicle_id is None:
                continue
            unique_ids.add(str(vehicle_id))
            class_counts[row.get("vehicle_class", "unknown")] += 1
        vehicle_count = len(unique_ids)
        hourly_flow = vehicle_count / duration * 3600.0 if duration > 0 else 0.0

        timeseries = _directional_timeseries(subset, meta.frame_rate, duration)

        track_ids = unique_ids
        speeds = []
        for track_row in recording.tracks:
            if str(track_row.get("id")) in track_ids:
                speeds.append(_to_float(track_row.get("xVelocity")))
        avg_speed = sum(speeds) / len(speeds) if speeds else 0.0

        shares = {cls: count / vehicle_count if vehicle_count else 0.0 for cls, count in class_counts.items()}

        results["directions"][direction] = {
            "vehicle_count": vehicle_count,
            "hourly_flow_veh_per_h": float(hourly_flow),
            "class_shares": shares,
            "timeseries_1min": timeseries,
            "avg_speed_m_s": float(avg_speed),
        }

    total_hourly = sum(info["hourly_flow_veh_per_h"] for info in results["directions"].values())
    results["hourly_flow_total"] = float(total_hourly)
    return results
