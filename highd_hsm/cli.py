"""Command line interface built with argparse (no external dependencies)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

from .config import HsmConfig, PipelineConfig
from .pipeline.run import RecordingProcessor, process_all

LOGGER = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate roadway structure, traffic flow and HSM crash predictions from HighD recordings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    all_parser = subparsers.add_parser("estimate-all", help="Process all recordings in a directory.")
    all_parser.add_argument("data_root", type=Path)
    all_parser.add_argument("out", type=Path)
    all_parser.add_argument("--area", default="urban")
    all_parser.add_argument("--facility", default="freeway")
    all_parser.add_argument("--calibration", type=float, default=1.0)
    all_parser.add_argument("--aadt-factors", type=Path, default=None)
    all_parser.add_argument("--coefficients", type=Path, default=None)
    all_parser.add_argument("--severity", type=Path, default=None)
    all_parser.add_argument("--no-report", action="store_true")
    all_parser.add_argument("-v", "--verbose", action="store_true")

    one_parser = subparsers.add_parser("estimate-one", help="Process a single recording directory.")
    one_parser.add_argument("recording_dir", type=Path)
    one_parser.add_argument("out", type=Path)
    one_parser.add_argument("--area", default="urban")
    one_parser.add_argument("--facility", default="freeway")
    one_parser.add_argument("--calibration", type=float, default=1.0)
    one_parser.add_argument("--aadt-factors", type=Path, default=None)
    one_parser.add_argument("--coefficients", type=Path, default=None)
    one_parser.add_argument("--severity", type=Path, default=None)
    one_parser.add_argument("--no-report", action="store_true")
    one_parser.add_argument("-v", "--verbose", action="store_true")

    return parser


def _create_processor(args: argparse.Namespace) -> RecordingProcessor:
    pipeline_cfg = PipelineConfig(
        area_type=args.area,
        facility=args.facility,
        aadt_factors_path=args.aadt_factors,
        hsm_coefficients_path=args.coefficients,
        severity_distribution_path=args.severity,
        output_reports=not args.no_report,
    )
    hsm_cfg = HsmConfig(calibration_factor=args.calibration)
    return RecordingProcessor.from_paths(pipeline_cfg, hsm_cfg, aadt_factors_path=args.aadt_factors)


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "estimate-all":
        processor = _create_processor(args)
        process_all(args.data_root, args.out, processor)
    elif args.command == "estimate-one":
        processor = _create_processor(args)
        processor.process(args.recording_dir, args.out)
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
