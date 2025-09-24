"""Safety Performance Function utilities for freeway segments (stdlib)."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..config import HsmConfig


@dataclass
class SpfCoefficient:
    facility: str
    area_type: str
    collision_type: str
    intercept: float
    aadt_exponent: float
    length_exponent: float
    lanes_exponent: float

    def predict(self, aadt: float, length_miles: float, lanes: float) -> float:
        if aadt <= 0 or length_miles <= 0 or lanes <= 0:
            return 0.0
        ln_aadt = math.log(aadt)
        ln_length = math.log(length_miles)
        ln_lanes = math.log(lanes)
        estimate = self.intercept + self.aadt_exponent * ln_aadt + self.length_exponent * ln_length + self.lanes_exponent * ln_lanes
        return math.exp(estimate)


class FreewaySpf:
    def __init__(
        self,
        coefficients: Iterable[SpfCoefficient],
        severity_distribution: List[Dict[str, str]],
        config: Optional[HsmConfig] = None,
    ) -> None:
        self.coefficients = list(coefficients)
        self.config = config or HsmConfig()
        self.severity_distribution = severity_distribution

    @classmethod
    def from_files(
        cls,
        coefficients_path: Path,
        severity_path: Path,
        config: Optional[HsmConfig] = None,
    ) -> "FreewaySpf":
        coefficients: List[SpfCoefficient] = []
        with Path(coefficients_path).open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                coefficients.append(
                    SpfCoefficient(
                        facility=row["facility"].strip().lower(),
                        area_type=row["area_type"].strip().lower(),
                        collision_type=row["collision_type"].strip().lower(),
                        intercept=float(row["intercept"]),
                        aadt_exponent=float(row["aadt_exponent"]),
                        length_exponent=float(row["length_exponent"]),
                        lanes_exponent=float(row.get("lanes_exponent", 0.0) or 0.0),
                    )
                )
        severity: List[Dict[str, str]] = []
        with Path(severity_path).open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                row = {k: (v.strip().lower() if isinstance(v, str) else v) for k, v in row.items()}
                severity.append(row)
        return cls(coefficients, severity, config=config)

    def _select_coefficients(self, facility: str, area_type: str) -> Dict[str, SpfCoefficient]:
        matches = {
            coef.collision_type: coef
            for coef in self.coefficients
            if coef.facility == facility and coef.area_type == area_type
        }
        if not matches:
            raise KeyError(f"No SPF coefficients for facility={facility}, area={area_type}")
        return matches

    def _severity_shares(self, facility: str, area_type: str, collision_type: str) -> Dict[str, float]:
        for row in self.severity_distribution:
            if (
                row.get("facility") == facility
                and row.get("area_type") == area_type
                and row.get("collision_type") == collision_type
            ):
                fi = float(row.get("fi_share", 0.3))
                pdo = float(row.get("pdo_share", 0.7))
                total = fi + pdo
                if total <= 0:
                    return {"fi": 0.3, "pdo": 0.7}
                return {"fi": fi / total, "pdo": pdo / total}
        return {"fi": 0.3, "pdo": 0.7}

    def predict(
        self,
        *,
        facility: str,
        area_type: str,
        directional_inputs: Dict[int, Dict[str, float]],
    ) -> Dict[str, object]:
        facility = facility.lower()
        area_type = area_type.lower()
        selected = self._select_coefficients(facility, area_type)
        config = self.config

        totals = {collision: {"fi": 0.0, "pdo": 0.0} for collision in selected}

        lengths = [info.get("segment_length_miles", 0.0) for info in directional_inputs.values()]
        mean_length = sum(lengths) / len(lengths) if lengths else 0.0
        k_value = config.overdispersion.k_for_length(mean_length)

        for info in directional_inputs.values():
            lanes = info.get("lane_count", 0.0)
            length_miles = info.get("segment_length_miles", 0.0)
            aadt = info.get("aadt", 0.0)
            for collision, coef in selected.items():
                base = coef.predict(aadt, length_miles, lanes)
                cmf = config.cmf_for_key(collision)
                calibrated = base * config.calibration_factor * cmf
                shares = self._severity_shares(facility, area_type, collision)
                totals[collision]["fi"] += calibrated * shares["fi"]
                totals[collision]["pdo"] += calibrated * shares["pdo"]

        total_all = sum(totals[col]["fi"] + totals[col]["pdo"] for col in totals)
        return {
            "sv": totals.get("sv", {"fi": 0.0, "pdo": 0.0}),
            "mv": totals.get("mv", {"fi": 0.0, "pdo": 0.0}),
            "total_all_sev": total_all,
            "k_overdispersion": float(k_value),
            "calibration_C": config.calibration_factor,
        }
