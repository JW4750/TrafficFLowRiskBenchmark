"""Orchestrates the end-to-end processing for a single HighD recording."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

from ..config import AadtFactorConfig, HsmConfig, PipelineConfig, ensure_output_directory, load_aadt_config
from ..io.highd import iter_recordings, load_recording
from ..hsm.spf import FreewaySpf
from .aadt import estimate_aadt
from .flow import summarize_flow
from .structure import analyze_structure

LOGGER = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COEFFICIENTS = PACKAGE_ROOT / "data" / "hsm_coefficients" / "freeway_spf.csv"
DEFAULT_SEVERITY = PACKAGE_ROOT / "data" / "hsm_coefficients" / "severity_distribution.csv"


def _default_spf(config: HsmConfig, coefficients_path: Optional[Path], severity_path: Optional[Path]) -> FreewaySpf:
    coef_path = Path(coefficients_path) if coefficients_path else DEFAULT_COEFFICIENTS
    sev_path = Path(severity_path) if severity_path else DEFAULT_SEVERITY
    return FreewaySpf.from_files(coef_path, sev_path, config=config)


def _write_json(path: Path, data: Dict[str, object]) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _generate_report(
    output_dir: Path,
    structure: Dict[str, object],
    flow: Dict[str, object],
    aadt: Dict[str, object],
    hsm: Dict[str, object],
) -> None:
    report_path = output_dir / "report.md"
    with Path(report_path).open("w", encoding="utf-8") as fh:
        fh.write(f"# HighD Recording {structure['recording_id']}\n\n")
        fh.write("## Roadway Structure\n")
        fh.write(json.dumps(structure, indent=2, ensure_ascii=False))
        fh.write("\n\n## Traffic Flow\n")
        fh.write(json.dumps(flow, indent=2, ensure_ascii=False))
        fh.write("\n\n## AADT Estimate\n")
        fh.write(json.dumps(aadt, indent=2, ensure_ascii=False))
        fh.write("\n\n## HSM Prediction\n")
        fh.write(json.dumps(hsm, indent=2, ensure_ascii=False))
        fh.write("\n\n*Report generated without external plotting libraries.*\n")


class RecordingProcessor:
    """Helper encapsulating configuration and reusable models."""

    def __init__(
        self,
        pipeline_config: PipelineConfig,
        hsm_config: Optional[HsmConfig] = None,
        aadt_config: Optional[AadtFactorConfig] = None,
        spf_model: Optional[FreewaySpf] = None,
    ) -> None:
        self.pipeline_config = pipeline_config
        self.hsm_config = hsm_config or HsmConfig()
        self.aadt_config = aadt_config
        self.spf_model = spf_model or _default_spf(
            self.hsm_config,
            pipeline_config.hsm_coefficients_path,
            pipeline_config.severity_distribution_path,
        )

    @classmethod
    def from_paths(
        cls,
        pipeline_config: PipelineConfig,
        hsm_config: Optional[HsmConfig] = None,
        aadt_factors_path: Optional[Path] = None,
    ) -> "RecordingProcessor":
        aadt_config = load_aadt_config(aadt_factors_path or pipeline_config.aadt_factors_path)
        return cls(pipeline_config, hsm_config, aadt_config)

    def process(self, recording_path: Path, output_dir: Path) -> Dict[str, Dict[str, object]]:
        recording = load_recording(recording_path)
        LOGGER.info("Processing recording %s", recording.meta.recording_id)

        ensure_output_directory(output_dir)

        structure = analyze_structure(recording)
        flow = summarize_flow(recording)
        aadt = estimate_aadt(recording, flow, self.aadt_config)

        length_m = structure.get("segment_length_m", 0.0)
        length_miles = length_m / 1609.344 if length_m else 0.0
        directional_inputs: Dict[int, Dict[str, float]] = {}
        for direction, struct_info in structure.get("directions", {}).items():
            lanes = max(struct_info.get("lane_count", 0), 1)
            aadt_dir = aadt.get("directions", {}).get(direction, {}).get("aadt", 0.0)
            directional_inputs[int(direction)] = {
                "lane_count": float(lanes),
                "segment_length_miles": float(length_miles),
                "aadt": float(aadt_dir),
            }

        hsm_predictions = self.spf_model.predict(
            facility=self.pipeline_config.facility,
            area_type=self.pipeline_config.area_type,
            directional_inputs=directional_inputs,
        )

        _write_json(output_dir / "structure.json", structure)
        _write_json(output_dir / "flow.json", flow)
        _write_json(output_dir / "aadt.json", aadt)
        _write_json(output_dir / "hsm_prediction.json", hsm_predictions)

        if self.pipeline_config.output_reports:
            _generate_report(output_dir, structure, flow, aadt, hsm_predictions)

        return {
            "structure": structure,
            "flow": flow,
            "aadt": aadt,
            "hsm_prediction": hsm_predictions,
        }


def process_all(
    data_root: Path,
    output_root: Path,
    processor: RecordingProcessor,
) -> Dict[str, Dict[str, Dict[str, object]]]:
    ensure_output_directory(output_root)
    results = {}
    for recording_dir in iter_recordings(data_root):
        target_dir = output_root / recording_dir.name
        results[recording_dir.name] = processor.process(recording_dir, target_dir)
    return results
