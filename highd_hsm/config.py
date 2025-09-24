"""Configuration models for the HighD HSM toolkit (pure stdlib version)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class AadtFactorConfig:
    weekday_factors: Dict[str, float] = field(default_factory=dict)
    month_factors: Dict[str, float] = field(default_factory=dict)
    hour_shares: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> "AadtFactorConfig":
        with Path(path).open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls(
            weekday_factors=data.get("F_DOW", {}),
            month_factors=data.get("F_MOY", {}),
            hour_shares=data.get("HOD_share", {}),
        )

    def factor_for_weekday(self, weekday: str) -> float:
        return float(self.weekday_factors.get(weekday, 1.0))

    def factor_for_month(self, month: int) -> float:
        return float(self.month_factors.get(str(month), 1.0))

    def share_for_hour(self, hour: int) -> float:
        return float(self.hour_shares.get(str(hour), 1.0))


@dataclass
class SpfOverdispersionConfig:
    alpha: float = 0.4
    beta: float = -0.5

    def k_for_length(self, length_miles: float) -> float:
        length = max(length_miles, 1e-3)
        return self.alpha * (length ** self.beta)


@dataclass
class HsmConfig:
    calibration_factor: float = 1.0
    default_cmf: float = 1.0
    cmf_overrides: Dict[str, float] = field(default_factory=dict)
    overdispersion: SpfOverdispersionConfig = field(default_factory=SpfOverdispersionConfig)

    def cmf_for_key(self, key: str) -> float:
        return float(self.cmf_overrides.get(key, self.default_cmf))


@dataclass
class PipelineConfig:
    area_type: str = "urban"
    facility: str = "freeway"
    aadt_factors_path: Optional[Path] = None
    hsm_coefficients_path: Optional[Path] = None
    severity_distribution_path: Optional[Path] = None
    output_reports: bool = True

    def __post_init__(self) -> None:
        self.area_type = self.area_type.lower()
        self.facility = self.facility.lower()


def load_aadt_config(path: Optional[Path]) -> Optional[AadtFactorConfig]:
    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return AadtFactorConfig.from_file(path)


def ensure_output_directory(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
