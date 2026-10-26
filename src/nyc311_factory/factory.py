"""End-to-end orchestration and reproducibility manifest generation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .analytics import build_analysis_outputs, load_population
from .config import Settings
from .curation import curate_raw_pages
from .pipeline import RawDownloader


def run_factory(settings: Settings, *, offline: bool = False) -> dict[str, Any]:
    """Run ingestion, validation, population join, summaries, and manifest.

    Offline replay requires a complete local download checkpoint. It skips all
    source requests, including the live schema check, and records that choice.
    """
    # Record the start time; it goes into the manifest.
    started = datetime.now(UTC)
    # Validate the external dependency before spending time downloading source rows.
    population = load_population(settings.population_path)
    downloader = RawDownloader(settings)
    # Steps run in order: download raw pages, curate them, then join with population.
    download_result = downloader.run(offline=offline)
    output_dir = settings.output_dir or settings.raw_dir.parent.parent / "curated"
    manifest_path = output_dir / "run_manifest.json"
    curation_result = curate_raw_pages(settings, output_dir)
    analysis_result = build_analysis_outputs(
        settings,
        output_dir / "curated_records.csv",
        population,
        output_dir,
    )
    finished = datetime.now(UTC)

    # Every file this run produced. The manifest records a hash for each one.
    output_paths = [
        output_dir / "curated_records.csv",
        output_dir / "quarantine.jsonl",
        output_dir / "quality_report.json",
        output_dir / "analytical_records.csv",
        output_dir / "monthly_summary_wide.csv",
        *sorted(settings.raw_dir.glob("page_*.json")),  # the raw pages are included too
    ]
    # SHA-256 hashes let a second run prove its outputs are byte-identical.
    output_hashes = {
        _relative_path(path, settings): _sha256(path)
        for path in sorted(set(output_paths))
        if path.is_file()
    }
    # The manifest is a record of this run: timing, settings, row counts, and file hashes.
    manifest = {
        "run_started_at_utc": started.isoformat(),
        "run_finished_at_utc": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "code_version": __version__,
        "code_revision": _code_revision(settings),
        "selection_scope": settings.source_signature,
        "source_consistency": (
            "Offline replay of a previously downloaded checkpoint; no source requests "
            "were made during this run. The original offset download may not be a snapshot."
            if offline
            else "Socrata offset pagination is ordered by created_date and unique_key; "
            "the live source may change during a run, so this is not a snapshot."
        ),
        "source_schema_validation": (
            "skipped_offline"
            if offline
            else "validated"
            if downloader.source_schema is not None
            else "not_configured"
        ),
        "source_schema": downloader.source_schema,
        "request_count": getattr(downloader.client, "request_count", None),
        "raw_records": download_result["raw_count"],
        "accepted_records": curation_result["accepted_records"],
        "quarantined_records": curation_result["quarantined_records"],
        "quarantine_by_reason": curation_result["quarantine_by_reason"],
        "population_join": {
            "analytical_records": analysis_result["analytical_records"],
            "population_matched_records": analysis_result["population_matched_records"],
            "population_unmatched_records": analysis_result["population_unmatched_records"],
            "borough_disagreements": analysis_result["borough_disagreements"],
        },
        "outputs_sha256": output_hashes,
    }
    # The manifest is written last, after every output it describes exists.
    _write_json_atomic(manifest_path, manifest)
    return {
        "raw_records": download_result["raw_count"],
        "accepted_records": curation_result["accepted_records"],
        "quarantined_records": curation_result["quarantined_records"],
        "analytical_records": analysis_result["analytical_records"],
        "monthly_summary_rows": analysis_result["monthly_summary_rows"],
        "request_count": manifest["request_count"],
        "run_manifest": str(manifest_path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    # Read in 1 MB chunks, so large files never have to fit in memory all at once.
    with path.open("rb") as output_file:
        for chunk in iter(lambda: output_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_root(settings: Settings) -> Path:
    # checkpoint.json sits in data/raw/311/, so four .parent steps reach the project root.
    return settings.checkpoint_path.parent.parent.parent.parent


def _code_revision(settings: Settings) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_project_root(settings),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable (no Git commit found)"
    return result.stdout.strip()


def _relative_path(path: Path, settings: Settings) -> str:
    project_root = _project_root(settings)
    # Store paths relative to the project, so the manifest still makes sense on another machine.
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        # The file is outside the project, so only its name is stored.
        return path.name


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    # Same temp-file-then-rename pattern as the other writers, so the file is never half-written.
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
