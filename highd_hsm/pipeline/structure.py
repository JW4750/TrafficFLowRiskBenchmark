"""Derive roadway structure metrics from HighD recordings (stdlib implementation)."""

from __future__ import annotations

from statistics import mean
from typing import Dict, List

from ..io.highd import RecordingData, robust_segment_length


def _lane_width_stats(markings: List[float]) -> Dict[str, float]:
    if len(markings) < 2:
        return {"count": 0, "mean": 0.0, "std": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    widths = [abs(markings[i + 1] - markings[i]) for i in range(len(markings) - 1)]
    widths_sorted = sorted(widths)
    n = len(widths_sorted)
    avg = sum(widths_sorted) / n
    variance = sum((w - avg) ** 2 for w in widths_sorted) / n
    mid = widths_sorted[n // 2] if n % 2 else (widths_sorted[n // 2 - 1] + widths_sorted[n // 2]) / 2
    return {
        "count": n,
        "mean": float(avg),
        "std": float(variance ** 0.5),
        "median": float(mid),
        "min": float(widths_sorted[0]),
        "max": float(widths_sorted[-1]),
    }


def _lane_count_from_markings(markings: List[float]) -> int:
    return max(len(markings) - 1, 0)


def _lane_count_from_lane_ids(tracks_meta: List[Dict[str, object]], direction: int) -> int:
    lane_ids = set()
    for row in tracks_meta:
        try:
            if int(row.get("drivingDirection", 0)) != direction:
                continue
        except (TypeError, ValueError):
            continue
        lane_value = row.get("laneId")
        if lane_value in (None, ""):
            continue
        try:
            lane_ids.add(int(float(lane_value)))
        except (TypeError, ValueError):
            continue
    return len(lane_ids)


def analyze_structure(recording: RecordingData) -> Dict[str, object]:
    meta = recording.meta
    direction_markings = {
        1: meta.lower_lane_markings,
        2: meta.upper_lane_markings,
    }

    results: Dict[str, object] = {
        "recording_id": meta.recording_id,
        "speed_limit_kmh": meta.speed_limit_kmh,
        "duration_sec": meta.duration,
        "timestamp": meta.timestamp.isoformat() if meta.timestamp else None,
        "segment_length_m": robust_segment_length(recording.tracks),
        "directions": {},
    }

    for direction, markings in direction_markings.items():
        lane_count = _lane_count_from_markings(markings)
        fallback = _lane_count_from_lane_ids(recording.tracks_meta, direction)
        if lane_count == 0 and fallback > 0:
            lane_count = fallback
        lane_stats = _lane_width_stats(markings)
        results["directions"][direction] = {
            "lane_count": lane_count,
            "lane_widths": lane_stats,
        }

    lane_counts = [info["lane_count"] for info in results["directions"].values() if info["lane_count"] > 0]
    results["lane_count_total"] = int(sum(lane_counts))
    results["lane_count_mean"] = float(mean(lane_counts)) if lane_counts else 0.0
    return results
