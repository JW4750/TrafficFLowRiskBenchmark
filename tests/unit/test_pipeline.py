from pathlib import Path

import json

from highd_hsm.config import HsmConfig, PipelineConfig
from highd_hsm.io.highd import load_recording
from highd_hsm.pipeline.aadt import estimate_aadt
from highd_hsm.pipeline.flow import summarize_flow
from highd_hsm.pipeline.run import RecordingProcessor
from highd_hsm.pipeline.structure import analyze_structure


def _sample_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "highd_sample" / "01"


def test_structure_analysis_extracts_lanes():
    recording = load_recording(_sample_dir())
    structure = analyze_structure(recording)
    assert structure["lane_count_total"] == 4
    assert structure["directions"][1]["lane_count"] == 2
    assert structure["directions"][2]["lane_count"] == 2
    assert structure["segment_length_m"] > 150


def test_flow_summary_counts_directional_volume():
    recording = load_recording(_sample_dir())
    flow = summarize_flow(recording)
    assert set(flow["directions"].keys()) == {1, 2}
    dir1 = flow["directions"][1]
    assert dir1["vehicle_count"] == 5
    assert flow["hourly_flow_total"] > 30


def test_aadt_factoring_uses_config():
    recording = load_recording(_sample_dir())
    flow = summarize_flow(recording)
    factors_path = Path(__file__).resolve().parents[2] / "config" / "aadt_factors.json"
    from highd_hsm.config import load_aadt_config

    factors = load_aadt_config(factors_path)
    aadt = estimate_aadt(recording, flow, factors)
    dir1 = aadt["directions"][1]
    assert dir1["aadt"] > dir1["hourly_flow"] * 24


def test_end_to_end_pipeline(tmp_path):
    recording_dir = _sample_dir()
    pipeline_cfg = PipelineConfig(
        area_type="urban",
        facility="freeway",
        aadt_factors_path=Path(__file__).resolve().parents[2] / "config" / "aadt_factors.json",
        output_reports=False,
    )
    processor = RecordingProcessor.from_paths(pipeline_cfg, HsmConfig())
    outputs = processor.process(recording_dir, tmp_path)

    for name in ("structure.json", "flow.json", "aadt.json", "hsm_prediction.json"):
        assert (tmp_path / name).exists(), f"missing {name}"

    prediction = outputs["hsm_prediction"]
    assert prediction["total_all_sev"] >= 0
    assert "k_overdispersion" in prediction
