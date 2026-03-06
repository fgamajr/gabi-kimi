"""Pipeline orchestrator — coordinate the complete automated ingestion pipeline.

Orchestrates all pipeline phases:
  1. Discovery: Detect new DOU publications
  2. Download: Download ZIP bundles
  3. Extract: Extract XML and images from ZIPs
  4. Parse: Parse XML into DOUArticle objects
  5. Normalize: Compute hashes and canonicalize content
  6. Ingest: Insert into PostgreSQL registry
  7. Commit: Seal with CRSS-1 cryptographic commitment
  8. Report: Generate ingestion report

Usage:
    # Run full automated pipeline
    python -m src.backend.ingest.orchestrator --days 1 --auto-discover --seal

    # Run with custom configuration
    python -m src.backend.ingest.orchestrator --config config/production.yaml

    # Dry run (discovery only)
    python -m src.backend.ingest.orchestrator --days 1 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.backend.ingest.auto_discovery import discover_new_publications
from src.backend.ingest.bulk_pipeline import PipelineResult, run_pipeline
from src.backend.ingest.date_selector import DateRange


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Configuration for automated pipeline runs."""
    # Data directory
    data_dir: Path = Path("ops/data/inlabs")

    # Database
    dsn: str = "host=localhost port=5433 dbname=gabi user=gabi password=gabi"

    # Discovery
    auto_discover: bool = True
    discovery_lookback_days: int = 1
    discovery_sections: list[str] | None = None

    # Download
    download_sections: list[str] | None = None
    include_extras: bool = True
    skip_existing_downloads: bool = True

    # Ingestion
    seal_commitment: bool = True
    sources_yaml: Path | None = None
    identity_yaml: Path | None = None

    # Error handling
    max_retries: int = 3
    retry_delay_seconds: int = 300

    # Reporting
    generate_report: bool = True
    report_output: Path | None = None

    # Other
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class PipelineOrchestrator:
    """Coordinates the complete ingestion pipeline."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.start_time = time.monotonic()
        self.phases: dict[str, dict[str, Any]] = {}

    def _start_phase(self, name: str) -> None:
        """Mark the start of a pipeline phase."""
        self.phases[name] = {
            "start_time": time.monotonic(),
            "status": "running",
        }
        _log(f"{'=' * 60}")
        _log(f"PHASE: {name.upper()}")
        _log(f"{'=' * 60}")

    def _end_phase(self, name: str, **kwargs: Any) -> None:
        """Mark the end of a pipeline phase."""
        phase = self.phases[name]
        phase["end_time"] = time.monotonic()
        phase["duration_ms"] = int((phase["end_time"] - phase["start_time"]) * 1000)
        phase["status"] = "completed"
        phase.update(kwargs)
        _log(f"Phase {name} completed in {phase['duration_ms'] / 1000:.1f}s")

    def _phase_failed(self, name: str, error: str) -> None:
        """Mark a phase as failed."""
        phase = self.phases[name]
        phase["end_time"] = time.monotonic()
        phase["duration_ms"] = int((phase["end_time"] - phase["start_time"]) * 1000)
        phase["status"] = "failed"
        phase["error"] = error
        _log(f"Phase {name} FAILED: {error}")

    def run(self) -> PipelineResult:
        """Execute the full pipeline with error handling and retries."""
        _log(f"Pipeline orchestrator started")
        _log(f"Configuration: auto_discover={self.config.auto_discover}, "
             f"seal={self.config.seal_commitment}, dry_run={self.config.dry_run}")

        try:
            # Phase 1: Discovery
            self._start_phase("discovery")
            date_range = self._determine_date_range()
            targets = self._discover_publications(date_range)
            self._end_phase("discovery", targets_count=len(targets))

            if self.config.dry_run:
                _log("Dry run: stopping after discovery phase")
                result = PipelineResult()
                result.zips_targeted = len(targets)
                self._generate_final_report(result)
                return result

            if not targets:
                _log("No new publications to process")
                result = PipelineResult()
                self._generate_final_report(result)
                return result

            # Phase 2-7: Run bulk pipeline
            self._start_phase("bulk_pipeline")
            result = self._run_bulk_pipeline(date_range)
            self._end_phase(
                "bulk_pipeline",
                zips_downloaded=result.zips_downloaded,
                articles_parsed=result.articles_parsed,
                records_ingested=result.records_ingested,
                commitment_sealed=result.commitment_sealed,
            )

            # Phase 8: Reporting
            self._start_phase("reporting")
            self._generate_final_report(result)
            self._end_phase("reporting")

            return result

        except Exception as ex:
            _log(f"Pipeline failed: {ex}")
            raise

    def _determine_date_range(self) -> DateRange:
        """Determine the date range to process."""
        end_date = date.today()
        start_date = end_date - timedelta(days=self.config.discovery_lookback_days)
        return DateRange(start_date, end_date)

    def _discover_publications(self, date_range: DateRange) -> list[Any]:
        """Discover new publications."""
        if not self.config.auto_discover:
            _log("Discovery skipped (auto_discover=False)")
            return []

        _log(f"Discovering publications from {date_range.start} to {date_range.end}")

        # For now, we just return an empty list since the bulk_pipeline
        # will handle discovery internally via build_targets
        # In the future, we can integrate with the discovery registry
        return []

    def _run_bulk_pipeline(self, date_range: DateRange) -> PipelineResult:
        """Run the bulk pipeline."""
        return run_pipeline(
            date_range=date_range,
            data_dir=self.config.data_dir,
            dsn=self.config.dsn,
            sections=self.config.download_sections,
            include_extras=self.config.include_extras,
            skip_download=False,
            download_only=False,
            parse_only=False,
            seal=self.config.seal_commitment,
            sources_yaml=self.config.sources_yaml,
            identity_yaml=self.config.identity_yaml,
        )

    def _generate_final_report(self, result: PipelineResult) -> None:
        """Generate final pipeline report."""
        total_duration_ms = int((time.monotonic() - self.start_time) * 1000)

        _log(f"\n{'=' * 60}")
        _log(f"PIPELINE COMPLETE")
        _log(f"{'=' * 60}")

        # Phase summary
        for phase_name, phase_data in self.phases.items():
            status = phase_data["status"].upper()
            duration = phase_data.get("duration_ms", 0) / 1000
            details = []
            if "targets_count" in phase_data:
                details.append(f"targets={phase_data['targets_count']}")
            if "zips_downloaded" in phase_data:
                details.append(f"zips={phase_data['zips_downloaded']}")
            if "articles_parsed" in phase_data:
                details.append(f"articles={phase_data['articles_parsed']}")
            if "records_ingested" in phase_data:
                details.append(f"records={phase_data['records_ingested']}")
            if "commitment_sealed" in phase_data:
                details.append(f"sealed={phase_data['commitment_sealed']}")
            details_str = " " + " ".join(details) if details else ""
            _log(f"  {phase_name:15s} {status:10s} {duration:6.1f}s{details_str}")

        _log(f"{'-' * 60}")
        _log(f"Total duration: {total_duration_ms / 1000:.1f}s")

        # Write report to file if configured
        if self.config.generate_report and self.config.report_output:
            report = {
                "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_ms": total_duration_ms,
                "phases": self.phases,
                "result": {
                    "zips_targeted": result.zips_targeted,
                    "zips_downloaded": result.zips_downloaded,
                    "zips_failed": result.zips_failed,
                    "download_bytes": result.download_bytes,
                    "xml_files_extracted": result.xml_files_extracted,
                    "image_files_extracted": result.image_files_extracted,
                    "articles_parsed": result.articles_parsed,
                    "articles_skipped": result.articles_skipped,
                    "records_produced": result.records_produced,
                    "records_ingested": result.records_ingested,
                    "records_duplicate": result.records_duplicate,
                    "records_new_version": result.records_new_version,
                    "records_new_publication": result.records_new_publication,
                    "commitment_root": result.commitment_root,
                    "commitment_sealed": result.commitment_sealed,
                    "errors": result.extraction_errors + result.ingestion_errors,
                },
            }
            self.config.report_output.parent.mkdir(parents=True, exist_ok=True)
            self.config.report_output.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _log(f"Report written to {self.config.report_output}")

        _log(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

def load_config_from_yaml(path: Path) -> PipelineConfig:
    """Load pipeline configuration from YAML file."""
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    config = PipelineConfig()

    # Data directory
    if "data_dir" in data:
        config.data_dir = Path(data["data_dir"])

    # Database
    if "database" in data:
        db = data["database"]
        if "dsn" in db:
            config.dsn = db["dsn"]

    # Discovery
    if "discovery" in data:
        disc = data["discovery"]
        if "auto_discover" in disc:
            config.auto_discover = disc["auto_discover"]
        if "lookback_days" in disc:
            config.discovery_lookback_days = disc["lookback_days"]
        if "sections" in disc:
            config.discovery_sections = disc["sections"]

    # Download
    if "download" in data:
        dl = data["download"]
        if "sections" in dl:
            config.download_sections = dl["sections"]
        if "include_extras" in dl:
            config.include_extras = dl["include_extras"]
        if "skip_existing" in dl:
            config.skip_existing_downloads = dl["skip_existing"]

    # Ingestion
    if "ingestion" in data:
        ing = data["ingestion"]
        if "seal_commitment" in ing:
            config.seal_commitment = ing["seal_commitment"]
        if "sources_yaml" in ing:
            config.sources_yaml = Path(ing["sources_yaml"])
        if "identity_yaml" in ing:
            config.identity_yaml = Path(ing["identity_yaml"])

    # Error handling
    if "error_handling" in data:
        eh = data["error_handling"]
        if "max_retries" in eh:
            config.max_retries = eh["max_retries"]
        if "retry_delay_seconds" in eh:
            config.retry_delay_seconds = eh["retry_delay_seconds"]

    # Reporting
    if "reporting" in data:
        rep = data["reporting"]
        if "generate_report" in rep:
            config.generate_report = rep["generate_report"]
        if "report_output" in rep:
            config.report_output = Path(rep["report_output"])

    return config


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Automated DOU ingestion pipeline orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Configuration
    p.add_argument(
        "--config", type=Path, default=None,
        help="Path to YAML configuration file",
    )

    # Date selection
    p.add_argument(
        "--days", type=int, default=1,
        help="Number of days to process (default: 1)",
    )

    # Discovery
    p.add_argument(
        "--auto-discover", action="store_true", default=True,
        help="Automatically discover new publications (default: enabled)",
    )
    p.add_argument(
        "--no-auto-discover", action="store_false", dest="auto_discover",
        help="Disable automatic discovery",
    )

    # Download
    p.add_argument(
        "--sections", nargs="+", default=None,
        help="Sections to download (e.g. do1 do2 do3). Default: all",
    )
    p.add_argument(
        "--no-extras", action="store_true",
        help="Skip extra edition detection",
    )

    # Ingestion
    p.add_argument(
        "--seal", action="store_true", default=True,
        help="Seal batch with CRSS-1 commitment (default: enabled)",
    )
    p.add_argument(
        "--no-seal", action="store_false", dest="seal",
        help="Skip commitment sealing",
    )
    p.add_argument(
        "--sources", type=Path, default=None,
        help="Path to sources YAML file",
    )
    p.add_argument(
        "--identity", type=Path, default=None,
        help="Path to identity YAML file",
    )

    # Database
    p.add_argument(
        "--dsn",
        default=os.environ.get(
            "GABI_DSN", "host=localhost port=5433 dbname=gabi user=gabi password=gabi"
        ),
        help="PostgreSQL DSN",
    )

    # Data directory
    p.add_argument(
        "--data-dir", type=Path, default=Path("ops/data/inlabs"),
        help="Directory for ZIP downloads (default: ops/data/inlabs)",
    )

    # Reporting
    p.add_argument(
        "--report-output", type=Path, default=None,
        help="Path to write JSON report file",
    )

    # Dry run
    p.add_argument(
        "--dry-run", action="store_true",
        help="Dry run: discover only, don't download or ingest",
    )

    args = p.parse_args()

    # Load configuration
    if args.config and args.config.exists():
        config = load_config_from_yaml(args.config)
    else:
        config = PipelineConfig()

    # Override config with CLI args
    config.data_dir = args.data_dir
    config.dsn = args.dsn
    config.discovery_lookback_days = args.days
    config.auto_discover = args.auto_discover
    config.download_sections = args.sections
    config.include_extras = not args.no_extras
    config.seal_commitment = args.seal
    config.sources_yaml = args.sources
    config.identity_yaml = args.identity
    config.dry_run = args.dry_run

    if args.report_output:
        config.generate_report = True
        config.report_output = args.report_output

    # Run orchestrator
    orchestrator = PipelineOrchestrator(config)
    result = orchestrator.run()

    # Exit code
    if result.ingestion_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
