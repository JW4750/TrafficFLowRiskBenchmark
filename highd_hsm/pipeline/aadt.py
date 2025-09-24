"""Compute Annual Average Daily Traffic (AADT) estimates from HighD flows."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from ..config import AadtFactorConfig
from ..io.highd import RecordingData
from .flow import summarize_flow


def _weekday_key(ts: datetime) -> str:
    return ts.strftime("%a")


def estimate_aadt(
    recording: RecordingData,
    flow_summary: Dict[str, object],
    factors: Optional[AadtFactorConfig] = None,
) -> Dict[str, object]:
    """Convert observed hourly flow into AADT using optional adjustment factors."""

    meta = recording.meta
    timestamp = meta.timestamp
    results: Dict[str, object] = {
        "recording_id": meta.recording_id,
        "directions": {},
        "method": "factored" if factors and timestamp else "baseline",
    }

    total_aadt = 0.0
    for direction, info in flow_summary.get("directions", {}).items():
        hourly = float(info.get("hourly_flow_veh_per_h", 0.0))
        scaling = 24.0
        components = {"base_hours": 24.0}
        if factors and timestamp:
            weekday_factor = factors.factor_for_weekday(_weekday_key(timestamp))
            month_factor = factors.factor_for_month(timestamp.month)
            hour_share = factors.share_for_hour(timestamp.hour)
            if hour_share == 0:
                hour_share = 1.0
            scaling = 24.0 * weekday_factor * month_factor / hour_share
            components.update({
                "weekday_factor": weekday_factor,
                "month_factor": month_factor,
                "hour_share": hour_share,
            })
        aadt = hourly * scaling
        total_aadt += aadt
        results["directions"][direction] = {
            "hourly_flow": hourly,
            "scaling_components": components,
            "aadt": float(aadt),
        }

    results["aadt_total"] = float(total_aadt)
    return results
