"""Safety Performance Function utilities for freeway segments (stdlib)."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
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
        estimate = (
            self.intercept
            + self.aadt_exponent * ln_aadt
            + self.length_exponent * ln_length
            + self.lanes_exponent * ln_lanes
        )
        return math.exp(estimate)


KABCO_LEVELS = ("k", "a", "b", "c", "o")


DEFAULT_KABCO_SHARES: Dict[str, float] = {"k": 0.02, "a": 0.06, "b": 0.12, "c": 0.20, "o": 0.60}

DEFAULT_SEVERITY_COSTS: Dict[str, float] = {
    "k": 11_000_000.0,
    "a": 1_500_000.0,
    "b": 450_000.0,
    "c": 120_000.0,
    "o": 10_000.0,
}


@dataclass
class SeverityProfile:
    facility: str
    area_type: str
    collision_type: str
    kabco_shares: Dict[str, float] = field(default_factory=dict)
    fi_share: float = 0.0
    pdo_share: float = 0.0
    severity_costs: Dict[str, float] = field(default_factory=dict)

    @staticmethod
    def _coerce_float(value: Optional[str], default: float) -> float:
        if value in (None, "", "nan", "NaN"):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "SeverityProfile":
        facility = row.get("facility", "").strip().lower()
        area = row.get("area_type", "").strip().lower()
        collision = row.get("collision_type", "").strip().lower()

        shares = {}
        total = 0.0
        for level in KABCO_LEVELS:
            share = cls._coerce_float(row.get(f"{level}_share"), DEFAULT_KABCO_SHARES[level])
            shares[level] = share
            total += share
        if total <= 0:
            shares = dict(DEFAULT_KABCO_SHARES)
            total = sum(shares.values())
        shares = {level: share / total for level, share in shares.items()}

        fi_override = cls._coerce_float(row.get("fi_share"), -1.0)
        pdo_override = cls._coerce_float(row.get("pdo_share"), -1.0)
        if fi_override >= 0 and pdo_override >= 0:
            total_override = fi_override + pdo_override
            if total_override > 0:
                fi_target = fi_override / total_override
                pdo_target = pdo_override / total_override
                current_fi = shares["k"] + shares["a"] + shares["b"] + shares["c"]
                current_pdo = shares["o"]
                if current_fi > 0:
                    scale_fi = fi_target / current_fi
                    for level in ("k", "a", "b", "c"):
                        shares[level] *= scale_fi
                else:
                    equal_fi = fi_target / 4 if fi_target > 0 else 0.0
                    for level in ("k", "a", "b", "c"):
                        shares[level] = equal_fi
                if current_pdo > 0:
                    shares["o"] *= pdo_target / current_pdo
                else:
                    shares["o"] = pdo_target
                total_scaled = sum(shares.values())
                if total_scaled > 0:
                    shares = {level: value / total_scaled for level, value in shares.items()}

        fi_share = shares["k"] + shares["a"] + shares["b"] + shares["c"]
        pdo_share = shares["o"]

        costs = {
            level: cls._coerce_float(row.get(f"{level}_cost"), DEFAULT_SEVERITY_COSTS[level])
            for level in KABCO_LEVELS
        }

        return cls(facility, area, collision, shares, fi_share, pdo_share, costs)

    @classmethod
    def fallback(cls, facility: str, area_type: str, collision_type: str) -> "SeverityProfile":
        shares = dict(DEFAULT_KABCO_SHARES)
        total = sum(shares.values())
        normalized = {level: value / total for level, value in shares.items()}
        fi_share = normalized["k"] + normalized["a"] + normalized["b"] + normalized["c"]
        pdo_share = normalized["o"]
        costs = dict(DEFAULT_SEVERITY_COSTS)
        return cls(facility, area_type, collision_type, normalized, fi_share, pdo_share, costs)


class FreewaySpf:
    def __init__(
        self,
        coefficients: Iterable[SpfCoefficient],
        severity_distribution: Iterable[SeverityProfile],
        config: Optional[HsmConfig] = None,
    ) -> None:
        self.coefficients = list(coefficients)
        self.config = config or HsmConfig()
        self.severity_profiles = list(severity_distribution)

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
        severity: List[SeverityProfile] = []
        with Path(severity_path).open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                severity.append(SeverityProfile.from_row(row))
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

    def _severity_profile(
        self, facility: str, area_type: str, collision_type: str
    ) -> SeverityProfile:
        for profile in self.severity_profiles:
            if (
                profile.facility == facility
                and profile.area_type == area_type
                and profile.collision_type == collision_type
            ):
                return profile
        return SeverityProfile.fallback(facility, area_type, collision_type)

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

        def _empty_summary() -> Dict[str, object]:
            return {
                "fi": 0.0,
                "pdo": 0.0,
                "total": 0.0,
                "kabco": {level: 0.0 for level in KABCO_LEVELS},
                "economic_loss": {
                    "total": 0.0,
                    "by_severity": {level: 0.0 for level in KABCO_LEVELS},
                },
            }

        collision_totals: Dict[str, Dict[str, object]] = {}
        severity_totals = {level: 0.0 for level in KABCO_LEVELS}
        severity_cost_totals = {level: 0.0 for level in KABCO_LEVELS}

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
                profile = self._severity_profile(facility, area_type, collision)
                if collision not in collision_totals:
                    collision_totals[collision] = _empty_summary()
                collision_result = collision_totals[collision]

                collision_result["fi"] += calibrated * profile.fi_share
                collision_result["pdo"] += calibrated * profile.pdo_share
                collision_result["total"] += calibrated

                severity_cost_total = 0.0
                for level in KABCO_LEVELS:
                    share = profile.kabco_shares[level]
                    expected = calibrated * share
                    cost = expected * profile.severity_costs[level]
                    collision_result["kabco"][level] += expected
                    collision_result["economic_loss"]["by_severity"][level] += cost
                    severity_totals[level] += expected
                    severity_cost_totals[level] += cost
                    severity_cost_total += cost

                collision_result["economic_loss"]["total"] += severity_cost_total

        for collision in selected:
            if collision not in collision_totals:
                collision_totals[collision] = _empty_summary()

        total_all = sum(result["total"] for result in collision_totals.values())
        total_fi = sum(severity_totals[level] for level in ("k", "a", "b", "c"))
        total_pdo = severity_totals["o"]

        combined_loss = sum(severity_cost_totals.values())

        prediction: Dict[str, object] = {collision: data for collision, data in collision_totals.items()}
        prediction.update(
            {
                "total_all_sev": total_all,
                "total_fi": total_fi,
                "total_pdo": total_pdo,
                "severity_breakdown": severity_totals,
                "economic_loss": {
                    "total": combined_loss,
                    "by_severity": severity_cost_totals,
                },
                "k_overdispersion": float(k_value),
                "calibration_C": config.calibration_factor,
            }
        )
        return prediction
