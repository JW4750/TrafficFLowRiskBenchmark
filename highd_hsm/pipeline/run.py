"""Orchestrates the end-to-end processing for a single HighD recording."""

from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path
from typing import Dict, Iterable, Optional

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


def _format_number(value: object, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    format_spec = f"{{:,.{decimals}f}}"
    return format_spec.format(number)


def _format_percentage(value: float) -> str:
    return _format_number(value * 100.0, decimals=1) + "%"


def _render_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    head_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_html = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_html.append(f"<tr>{cells}</tr>")
    return (
        "<table><thead><tr>"
        + head_html
        + "</tr></thead><tbody>"
        + "".join(body_html)
        + "</tbody></table>"
    )


def _render_severity_bars(breakdown: Dict[str, float], total: float) -> str:
    bars = []
    for level in ("k", "a", "b", "c", "o"):
        value = float(breakdown.get(level, 0.0))
        share = value / total if total > 0 else 0.0
        width_pct = max(0.0, min(share * 100.0, 100.0))
        bars.append(
            "<div class=\"severity-row\">"
            f"<span class=\"severity-label\">{level.upper()}</span>"
            "<div class=\"severity-bar\">"
            f"<div class=\"severity-bar-fill\" style=\"width:{width_pct:.1f}%\"></div>"
            "</div>"
            f"<span class=\"severity-value\">{_format_number(value)}</span>"
            "</div>"
        )
    return "".join(bars)


def _generate_html_report(
    output_dir: Path,
    structure: Dict[str, object],
    flow: Dict[str, object],
    aadt: Dict[str, object],
    hsm: Dict[str, object],
) -> None:
    recording_id = escape(str(structure.get("recording_id", "Unknown")))
    summary_cards = [
        ("Segment length (m)", _format_number(structure.get("segment_length_m", 0.0))),
        ("Total lanes", escape(str(structure.get("lane_count_total", "-")))),
        (
            "Total hourly flow (veh/h)",
            _format_number(flow.get("hourly_flow_total", 0.0)),
        ),
        (
            "Total AADT (veh/day)",
            _format_number(aadt.get("aadt_total", 0.0)),
        ),
        (
            "Predicted crashes (annual)",
            _format_number(hsm.get("total_all_sev", 0.0)),
        ),
        (
            "Economic loss (USD)",
            _format_number(hsm.get("economic_loss", {}).get("total", 0.0)),
        ),
    ]

    structure_rows = [
        ("Recording ID", recording_id),
        ("Speed limit (km/h)", _format_number(structure.get("speed_limit_kmh", 0.0))),
        ("Observation duration (s)", _format_number(structure.get("duration_sec", 0.0))),
        ("Average lanes per direction", _format_number(structure.get("lane_count_mean", 0.0))),
    ]

    direction_rows = []
    for direction, info in sorted(structure.get("directions", {}).items()):
        lane_widths = info.get("lane_widths", {})
        direction_rows.append(
            (
                escape(str(direction)),
                escape(str(info.get("lane_count", "-"))),
                _format_number(lane_widths.get("mean", 0.0)),
                _format_number(lane_widths.get("std", 0.0)),
                _format_number(lane_widths.get("min", 0.0)),
                _format_number(lane_widths.get("max", 0.0)),
            )
        )

    flow_rows = []
    for direction, info in sorted(flow.get("directions", {}).items()):
        shares = info.get("class_shares", {})
        share_text = ", ".join(
            f"{escape(str(cls))}: {_format_percentage(float(share))}"
            for cls, share in sorted(shares.items())
        )
        flow_rows.append(
            (
                escape(str(direction)),
                _format_number(info.get("vehicle_count", 0), decimals=0),
                _format_number(info.get("hourly_flow_veh_per_h", 0.0)),
                _format_number(info.get("avg_speed_m_s", 0.0)),
                escape(share_text or "–"),
            )
        )

    aadt_rows = []
    for direction, info in sorted(aadt.get("directions", {}).items()):
        components = info.get("scaling_components", {})
        component_text = ", ".join(
            f"{escape(str(key))}: {_format_number(val)}"
            for key, val in components.items()
        )
        aadt_rows.append(
            (
                escape(str(direction)),
                _format_number(info.get("hourly_flow", 0.0)),
                _format_number(info.get("aadt", 0.0)),
                escape(component_text or "–"),
            )
        )

    collision_rows = []
    severity_rows = []
    severity_total = float(hsm.get("total_all_sev", 0.0))
    severity_breakdown = hsm.get("severity_breakdown", {})
    severity_costs = hsm.get("economic_loss", {}).get("by_severity", {})

    for key, value in sorted(hsm.items()):
        if not isinstance(value, dict) or "kabco" not in value:
            continue
        collision_rows.append(
            (
                escape(key.upper()),
                _format_number(value.get("fi", 0.0)),
                _format_number(value.get("pdo", 0.0)),
                _format_number(value.get("total", 0.0)),
            )
        )

    for level in ("k", "a", "b", "c", "o"):
        crashes = float(severity_breakdown.get(level, 0.0))
        share = crashes / severity_total if severity_total > 0 else 0.0
        severity_rows.append(
            (
                escape(level.upper()),
                _format_number(crashes),
                _format_percentage(share),
                _format_number(severity_costs.get(level, 0.0)),
            )
        )

    severity_bars = _render_severity_bars(severity_breakdown, severity_total)

    timeseries_rows = []
    for direction, info in sorted(flow.get("directions", {}).items()):
        for entry in info.get("timeseries_1min", []):
            timeseries_rows.append(
                (
                    escape(str(direction)),
                    _format_number(entry.get("bin_start_sec", 0.0)),
                    _format_number(entry.get("bin_end_sec", 0.0)),
                    _format_number(entry.get("vehicles", 0), decimals=0),
                )
            )

    builder = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\" />",
        f"<title>HighD Safety Summary – {recording_id}</title>",
        "<style>",
        "body{font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:24px;background:#f7f9fc;color:#202124;}",
        "h1{margin-top:0;}",
        ".summary-grid{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:24px;}",
        ".summary-card{flex:1 1 240px;background:white;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(15,23,42,0.15);border:1px solid #e0e7ff;}",
        ".summary-card h3{margin:0;font-size:0.9rem;color:#5f6368;text-transform:uppercase;letter-spacing:0.08em;}",
        ".summary-card p{margin:8px 0 0;font-size:1.6rem;font-weight:600;color:#1a73e8;}",
        "table{border-collapse:collapse;width:100%;margin-bottom:24px;background:white;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(15,23,42,0.1);}th,td{border:1px solid #e0e7ff;padding:10px;text-align:left;font-size:0.95rem;}th{background:#eef2ff;font-weight:600;}",
        ".section{margin-bottom:40px;}",
        ".section h2{margin-bottom:12px;border-bottom:2px solid #1a73e8;padding-bottom:6px;}",
        ".severity-container{display:flex;flex-direction:column;gap:8px;background:white;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(15,23,42,0.1);border:1px solid #e0e7ff;margin-bottom:24px;}",
        ".severity-row{display:flex;align-items:center;gap:12px;}",
        ".severity-label{width:36px;font-weight:600;}",
        ".severity-bar{flex:1;height:12px;background:#e8f0fe;border-radius:8px;overflow:hidden;}",
        ".severity-bar-fill{height:100%;background:#1a73e8;}",
        ".severity-value{width:120px;text-align:right;font-variant-numeric:tabular-nums;}",
        "footer{margin-top:32px;color:#5f6368;font-size:0.85rem;}",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>HighD Safety Summary – {recording_id}</h1>",
        "<div class=\"summary-grid\">",
    ]

    for title, value in summary_cards:
        builder.append(
            f"<div class=\"summary-card\"><h3>{escape(title)}</h3><p>{value}</p></div>"
        )

    builder.append("</div>")

    builder.append("<div class=\"section\">")
    builder.append("<h2>Roadway Structure</h2>")
    builder.append(
        _render_table(
            ("Metric", "Value"),
            ((escape(label), value) for label, value in structure_rows),
        )
    )
    if direction_rows:
        builder.append("<h3>Directional Lane Geometry</h3>")
        builder.append(
            _render_table(
                (
                    "Direction",
                    "Lane count",
                    "Mean width (m)",
                    "Std dev (m)",
                    "Min width (m)",
                    "Max width (m)",
                ),
                direction_rows,
            )
        )
    builder.append("</div>")

    builder.append("<div class=\"section\">")
    builder.append("<h2>Traffic Flow</h2>")
    builder.append(
        _render_table(
            (
                "Direction",
                "Unique vehicles",
                "Hourly flow (veh/h)",
                "Avg speed (m/s)",
                "Vehicle class shares",
            ),
            flow_rows,
        )
    )
    if timeseries_rows:
        builder.append("<h3>1-minute Flow Timeseries</h3>")
        builder.append(
            _render_table(
                (
                    "Direction",
                    "Start (s)",
                    "End (s)",
                    "Vehicles",
                ),
                timeseries_rows,
            )
        )
    builder.append("</div>")

    builder.append("<div class=\"section\">")
    builder.append("<h2>AADT Estimation</h2>")
    builder.append(
        _render_table(
            ("Direction", "Hourly flow", "AADT", "Scaling components"),
            aadt_rows,
        )
    )
    builder.append("</div>")

    builder.append("<div class=\"section\">")
    builder.append("<h2>HSM Crash Prediction</h2>")
    if collision_rows:
        builder.append(
            _render_table(
                ("Collision type", "FI crashes", "PDO crashes", "Total"),
                collision_rows,
            )
        )
    builder.append("<div class=\"severity-container\">")
    builder.append("<h3>KABCO Severity Distribution</h3>")
    builder.append(severity_bars)
    builder.append("</div>")
    builder.append(
        _render_table(
            ("Severity", "Expected crashes", "Share", "Economic loss (USD)"),
            severity_rows,
        )
    )
    builder.append("</div>")

    builder.append(
        "<footer>Generated automatically from HighD observations using Highway Safety Manual methods.</footer>"
    )
    builder.append("</body></html>")

    html_path = output_dir / "report.html"
    with Path(html_path).open("w", encoding="utf-8") as fh:
        fh.write("\n".join(builder))


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
            _generate_html_report(output_dir, structure, flow, aadt, hsm_predictions)

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
